"""Testy pobierania read-only snapshotu scannera przez UI (Faza 8
Etap C). Zero prawdziwej sieci -- `httpx.MockTransport` symuluje
serwer GitHub Release, ten sam mechanizm, jaki httpx dostarcza
specjalnie do tego celu."""

from __future__ import annotations

import hashlib
import json

import httpx
import pytest

from buffett_scanner.ui.scanner_snapshot import (
    SnapshotUnavailableError,
    download_snapshot,
    ensure_local_snapshot,
    fetch_pointer,
)

OWNER = "AnastazjaBK"
REPO = "Tajfun_Lab"
FAKE_DB_CONTENT = b"fake-sqlite-bytes-for-test-only"
FAKE_SHA256 = hashlib.sha256(FAKE_DB_CONTENT).hexdigest()

VALID_POINTER = {
    "run_id": "live-scan-2026-10-07T120000000000Z",
    "run_date": "2026-10-07",
    "release_tag": "scanner-snapshot-live-scan-2026-10-07T120000000000Z",
    "asset_name": "live_scan_result.db",
    "sha256": FAKE_SHA256,
    "shortlist_size": 5,
    "published_at": "2026-10-07T12:05:00Z",
}


def _pointer_url():
    return (
        f"https://github.com/{OWNER}/{REPO}/releases/download/"
        "scanner-snapshot-latest/pointer.json"
    )


def _asset_url(pointer=VALID_POINTER):
    return (
        f"https://github.com/{OWNER}/{REPO}/releases/download/"
        f"{pointer['release_tag']}/{pointer['asset_name']}"
    )


def _client_for(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)


def test_fetch_pointer_parses_valid_json():
    def handler(request):
        assert str(request.url) == _pointer_url()
        return httpx.Response(200, json=VALID_POINTER)

    pointer = fetch_pointer(OWNER, REPO, client=_client_for(handler))
    assert pointer == VALID_POINTER


def test_fetch_pointer_raises_on_404():
    def handler(request):
        return httpx.Response(404, text="Not Found")

    with pytest.raises(SnapshotUnavailableError, match="404"):
        fetch_pointer(OWNER, REPO, client=_client_for(handler))


def test_fetch_pointer_raises_on_malformed_json():
    def handler(request):
        return httpx.Response(200, text="to nie jest json {{{")

    with pytest.raises(SnapshotUnavailableError, match="niepoprawny format"):
        fetch_pointer(OWNER, REPO, client=_client_for(handler))


def test_fetch_pointer_raises_on_missing_required_fields():
    def handler(request):
        return httpx.Response(200, json={"run_id": "live-scan-x"})  # brak reszty pól

    with pytest.raises(SnapshotUnavailableError, match="wymaganych pól"):
        fetch_pointer(OWNER, REPO, client=_client_for(handler))


def test_download_snapshot_writes_file_and_verifies_checksum(tmp_path):
    def handler(request):
        assert str(request.url) == _asset_url()
        return httpx.Response(200, content=FAKE_DB_CONTENT)

    dest = tmp_path / "snapshot.db"
    download_snapshot(VALID_POINTER, OWNER, REPO, dest_path=dest, client=_client_for(handler))
    assert dest.read_bytes() == FAKE_DB_CONTENT


def test_download_snapshot_rejects_corrupted_download_and_removes_file(tmp_path):
    """Test KLUCZOWY (sekcja 'możliwy do zweryfikowania przed
    użyciem'): serwer zwraca INNĄ zawartość niż oczekiwane SHA256 w
    pointerze (ucięty/uszkodzony download) -- plik musi zostać
    usunięty, nigdy pozostawiony tak, jakby był poprawny."""
    def handler(request):
        return httpx.Response(200, content=b"cos zupelnie innego niz oczekiwano")

    dest = tmp_path / "snapshot.db"
    with pytest.raises(SnapshotUnavailableError, match="SHA256"):
        download_snapshot(VALID_POINTER, OWNER, REPO, dest_path=dest, client=_client_for(handler))
    assert not dest.exists()


def test_download_snapshot_raises_on_non_200_without_leaving_file(tmp_path):
    def handler(request):
        return httpx.Response(500, text="Internal Server Error")

    dest = tmp_path / "snapshot.db"
    with pytest.raises(SnapshotUnavailableError, match="status 500"):
        download_snapshot(VALID_POINTER, OWNER, REPO, dest_path=dest, client=_client_for(handler))
    assert not dest.exists()


def test_ensure_local_snapshot_downloads_fresh_and_returns_pointer(tmp_path):
    calls = []

    def handler(request):
        calls.append(str(request.url))
        if request.url.path.endswith("pointer.json"):
            return httpx.Response(200, json=VALID_POINTER)
        return httpx.Response(200, content=FAKE_DB_CONTENT)

    path, pointer = ensure_local_snapshot(OWNER, REPO, cache_dir=tmp_path, client=_client_for(handler))
    assert pointer == VALID_POINTER
    assert path.exists()
    assert path.read_bytes() == FAKE_DB_CONTENT
    assert pointer["run_id"] in path.name  # test "jednoznacznie powiązany z run_id"
    assert len(calls) == 2  # pointer + asset


def test_ensure_local_snapshot_reuses_cache_without_redownloading_asset(tmp_path):
    """Test KLUCZOWY (sekcja 'cache\'owany lokalnie tylko jako
    odtwarzalna kopia'): drugie wywołanie z tym samym run_id NIE
    pobiera pliku .db ponownie -- tylko pointer.json (lekki)."""
    asset_requests = []

    def handler(request):
        if request.url.path.endswith("pointer.json"):
            return httpx.Response(200, json=VALID_POINTER)
        asset_requests.append(str(request.url))
        return httpx.Response(200, content=FAKE_DB_CONTENT)

    path1, _ = ensure_local_snapshot(OWNER, REPO, cache_dir=tmp_path, client=_client_for(handler))
    path2, _ = ensure_local_snapshot(OWNER, REPO, cache_dir=tmp_path, client=_client_for(handler))
    assert path1 == path2
    assert len(asset_requests) == 1  # tylko pierwsze wywołanie faktycznie pobrało .db


def test_ensure_local_snapshot_downloads_new_file_when_run_id_changes(tmp_path):
    """Nowy run_id (nowy live-scan) -> nowa nazwa pliku, świeże
    pobranie -- nigdy cicha reużycie danych z poprzedniego runu."""
    pointer_v2 = {**VALID_POINTER, "run_id": "live-scan-2026-10-08T000000000000Z",
                  "release_tag": "scanner-snapshot-live-scan-2026-10-08T000000000000Z"}
    state = {"pointer": VALID_POINTER}
    asset_requests = []

    def handler(request):
        if request.url.path.endswith("pointer.json"):
            return httpx.Response(200, json=state["pointer"])
        asset_requests.append(str(request.url))
        return httpx.Response(200, content=FAKE_DB_CONTENT)

    path1, pointer1 = ensure_local_snapshot(OWNER, REPO, cache_dir=tmp_path, client=_client_for(handler))
    state["pointer"] = pointer_v2
    path2, pointer2 = ensure_local_snapshot(OWNER, REPO, cache_dir=tmp_path, client=_client_for(handler))

    assert path1 != path2
    assert pointer1["run_id"] != pointer2["run_id"]
    assert len(asset_requests) == 2  # oba pobrania faktycznie wykonane, nic nie zreużyte błędnie


def test_ensure_local_snapshot_raises_when_pointer_unavailable(tmp_path):
    def handler(request):
        return httpx.Response(404)

    with pytest.raises(SnapshotUnavailableError):
        ensure_local_snapshot(OWNER, REPO, cache_dir=tmp_path, client=_client_for(handler))

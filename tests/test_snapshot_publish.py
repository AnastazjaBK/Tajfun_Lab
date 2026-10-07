"""Testy publikacji snapshotu scannera jako GitHub Release (Faza 8
Etap B). Zero sieci, zero prawdziwego `gh`/repo -- `GhReleaseClient`
dostaje fejkową funkcję `run` zamiast `subprocess.run`, ten sam wzorzec
co `monkeypatch.setattr(cli, "FMPClient", _FakeFMPClient)` w
`test_cli.py`."""

from __future__ import annotations

import json
import sqlite3

import pytest

from buffett_scanner.db import SCHEMA, insert_live_scan_run
from buffett_scanner.snapshot_publish import (
    POINTER_ASSET_NAME,
    RELEASE_TAG_PREFIX,
    SNAPSHOT_POINTER_TAG,
    GhReleaseClient,
    SnapshotPublishError,
    build_pointer_payload,
    build_release_notes,
    compute_sha256,
    publish_snapshot,
    read_latest_run_summary,
    should_publish_as_live_scan,
)


class _FakeCompletedProcess:
    def __init__(self, returncode: int, stderr: str = ""):
        self.returncode = returncode
        self.stderr = stderr


class _FakeGhCli:
    """Zapamiętuje każde wywołanie `gh ...` i śledzi, które release'y
    "istnieją" -- wystarczające do sprawdzenia logiki orkiestracji bez
    prawdziwego `gh`."""

    def __init__(self, *, existing_tags: set[str] | None = None, fail_create: bool = False):
        self.calls: list[list[str]] = []
        self._existing_tags = set(existing_tags or set())
        self._fail_create = fail_create

    def __call__(self, argv, capture_output=True, text=True):
        self.calls.append(argv)
        if argv[1] == "release" and argv[2] == "view":
            tag = argv[3]
            return _FakeCompletedProcess(0 if tag in self._existing_tags else 1)
        if argv[1] == "release" and argv[2] == "create":
            if self._fail_create:
                return _FakeCompletedProcess(1, stderr="symulowany błąd gh release create")
            self._existing_tags.add(argv[3])
            return _FakeCompletedProcess(0)
        if argv[1] == "release" and argv[2] == "upload":
            return _FakeCompletedProcess(0)
        raise AssertionError(f"Nieoczekiwane wywołanie gh: {argv}")


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "live_scan_result.db"
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    yield path, conn
    conn.close()


def _seed_run(conn, *, run_id: str, shortlist_size: int = 5) -> None:
    insert_live_scan_run(
        conn, run_id=run_id, run_date="2026-10-07", config_version="v1",
        universe_size=501, decline_surfaced=156, prefilter_excluded=0,
        shortlist_limit=20, shortlist_size=shortlist_size,
    )
    conn.commit()


def test_should_publish_as_live_scan_matches_ui_queries_convention():
    """Test KLUCZOWY: ta sama konwencja co `ui/queries.
    get_latest_live_scan_run` -- validation-* NIGDY nie jest live
    market scanem."""
    assert should_publish_as_live_scan("live-scan-2026-10-06T083825543395Z") is True
    assert should_publish_as_live_scan("validation-6h-2026-10-06T165859543821Z") is False
    assert should_publish_as_live_scan("validation-6f-xyz") is False
    assert should_publish_as_live_scan("random-run-id") is False


def test_read_latest_run_summary_returns_none_for_empty_db(db_path):
    path, _conn = db_path
    assert read_latest_run_summary(path) is None


def test_read_latest_run_summary_reads_fields(db_path):
    path, conn = db_path
    _seed_run(conn, run_id="live-scan-2026-10-07T000000000000Z", shortlist_size=3)
    summary = read_latest_run_summary(path)
    assert summary.run_id == "live-scan-2026-10-07T000000000000Z"
    assert summary.run_date == "2026-10-07"
    assert summary.shortlist_size == 3


def test_publish_snapshot_skips_validation_run_without_calling_gh(db_path):
    """Test KLUCZOWY (Decyzja właścicielki): run walidacyjny NIGDY nie
    jest publikowany jako "najnowszy" snapshot -- gh w ogóle nie jest
    wołane."""
    path, conn = db_path
    _seed_run(conn, run_id="validation-6h-2026-10-06T165859543821Z")
    fake_cli = _FakeGhCli()
    client = GhReleaseClient(repo="owner/repo", run=fake_cli)
    result = publish_snapshot(path, gh_client=client, work_dir=path.parent)
    assert result is None
    assert fake_cli.calls == []


def test_publish_snapshot_skips_empty_db_without_calling_gh(db_path):
    path, _conn = db_path
    fake_cli = _FakeGhCli()
    client = GhReleaseClient(repo="owner/repo", run=fake_cli)
    result = publish_snapshot(path, gh_client=client, work_dir=path.parent)
    assert result is None
    assert fake_cli.calls == []


def test_publish_snapshot_creates_per_run_release_and_pointer_on_first_publish(db_path):
    path, conn = db_path
    run_id = "live-scan-2026-10-07T000000000000Z"
    _seed_run(conn, run_id=run_id, shortlist_size=5)
    fake_cli = _FakeGhCli()
    client = GhReleaseClient(repo="owner/repo", run=fake_cli)

    result = publish_snapshot(path, gh_client=client, work_dir=path.parent)

    assert result is not None
    assert result["run_id"] == run_id
    assert result["release_tag"] == f"{RELEASE_TAG_PREFIX}{run_id}"
    assert result["sha256"] == compute_sha256(path)

    create_calls = [c for c in fake_cli.calls if c[1:3] == ["release", "create"]]
    assert len(create_calls) == 2  # per-run release + pointer release (oba nowe)
    tags_created = {c[3] for c in create_calls}
    assert tags_created == {f"{RELEASE_TAG_PREFIX}{run_id}", SNAPSHOT_POINTER_TAG}

    pointer_file = path.parent / POINTER_ASSET_NAME
    assert pointer_file.exists()
    payload = json.loads(pointer_file.read_text(encoding="utf-8"))
    assert payload["run_id"] == run_id
    assert payload["sha256"] == compute_sha256(path)


def test_publish_snapshot_updates_pointer_not_per_run_release_on_second_publish(db_path):
    """Test KLUCZOWY (sekcja "immutable dla danego runu"): drugi
    live-scan NIGDY nie nadpisuje poprzedniego, immutable release'u --
    tworzy NOWY release per run_id, a nadpisuje WYŁĄCZNIE pointer."""
    path, conn = db_path
    first_run_id = "live-scan-2026-10-06T000000000000Z"
    _seed_run(conn, run_id=first_run_id)
    fake_cli = _FakeGhCli()
    client = GhReleaseClient(repo="owner/repo", run=fake_cli)
    publish_snapshot(path, gh_client=client, work_dir=path.parent)
    fake_cli.calls.clear()

    second_run_id = "live-scan-2026-10-07T000000000000Z"
    _seed_run(conn, run_id=second_run_id, shortlist_size=7)
    result = publish_snapshot(path, gh_client=client, work_dir=path.parent)

    assert result["run_id"] == second_run_id
    create_calls = [c for c in fake_cli.calls if c[1:3] == ["release", "create"]]
    upload_calls = [c for c in fake_cli.calls if c[1:3] == ["release", "upload"]]
    # Nowy immutable release dla second_run_id -- utworzony.
    assert any(c[3] == f"{RELEASE_TAG_PREFIX}{second_run_id}" for c in create_calls)
    # Pointer JUŻ istniał (z pierwszej publikacji) -- tylko upload (nadpisanie), nie create.
    assert any(c[3] == SNAPSHOT_POINTER_TAG for c in upload_calls)
    assert not any(c[3] == SNAPSHOT_POINTER_TAG for c in create_calls)
    # Release pierwszego runu NIGDY nie jest dotykany drugi raz.
    assert not any(c[3] == f"{RELEASE_TAG_PREFIX}{first_run_id}" for c in create_calls + upload_calls)


def test_publish_snapshot_does_not_recreate_existing_per_run_release(db_path):
    """Ten sam run_id (np. ponowne uruchomienie tego samego workflow
    joba) nie próbuje utworzyć release'u drugi raz (gh by na to
    i tak nie pozwolił, ale sprawdzamy, że kod sam tego nie robi)."""
    path, conn = db_path
    run_id = "live-scan-2026-10-07T000000000000Z"
    _seed_run(conn, run_id=run_id)
    fake_cli = _FakeGhCli(existing_tags={f"{RELEASE_TAG_PREFIX}{run_id}"})
    client = GhReleaseClient(repo="owner/repo", run=fake_cli)

    publish_snapshot(path, gh_client=client, work_dir=path.parent)

    create_calls = [c for c in fake_cli.calls if c[1:3] == ["release", "create"]]
    assert not any(c[3] == f"{RELEASE_TAG_PREFIX}{run_id}" for c in create_calls)


def test_publish_snapshot_raises_clear_error_when_gh_create_fails(db_path):
    path, conn = db_path
    _seed_run(conn, run_id="live-scan-2026-10-07T000000000000Z")
    fake_cli = _FakeGhCli(fail_create=True)
    client = GhReleaseClient(repo="owner/repo", run=fake_cli)
    with pytest.raises(SnapshotPublishError, match="gh release create"):
        publish_snapshot(path, gh_client=client, work_dir=path.parent)


def test_compute_sha256_changes_when_file_content_changes(tmp_path):
    f1 = tmp_path / "a.db"
    f1.write_bytes(b"hello")
    f2 = tmp_path / "b.db"
    f2.write_bytes(b"different content")
    assert compute_sha256(f1) != compute_sha256(f2)
    f3 = tmp_path / "c.db"
    f3.write_bytes(b"hello")
    assert compute_sha256(f1) == compute_sha256(f3)


def test_build_release_notes_includes_run_id_and_sha256(db_path):
    path, conn = db_path
    _seed_run(conn, run_id="live-scan-2026-10-07T000000000000Z")
    summary = read_latest_run_summary(path)
    notes = build_release_notes(summary, sha256="abc123")
    assert "live-scan-2026-10-07T000000000000Z" in notes
    assert "abc123" in notes
    assert "Immutable" in notes


def test_build_pointer_payload_shape(db_path):
    path, conn = db_path
    _seed_run(conn, run_id="live-scan-2026-10-07T000000000000Z", shortlist_size=9)
    summary = read_latest_run_summary(path)
    payload = build_pointer_payload(summary, release_tag="scanner-snapshot-x", sha256="deadbeef")
    assert payload["run_id"] == "live-scan-2026-10-07T000000000000Z"
    assert payload["release_tag"] == "scanner-snapshot-x"
    assert payload["sha256"] == "deadbeef"
    assert payload["shortlist_size"] == 9
    assert "published_at" in payload

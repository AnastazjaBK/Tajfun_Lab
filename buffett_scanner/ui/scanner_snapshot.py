"""Pobieranie read-only snapshotu scannera przez hostowaną appkę (Faza
8 "Hostowany V0", Etap C, Decyzja właścicielki).

Drugi koniec kontraktu zdefiniowanego w `snapshot_publish.py` (Etap B):
GitHub Release publiczny, dwupoziomowy (immutable per-run + mutable
pointer). Repo jest PUBLICZNE (zweryfikowane: `visibility: public`) --
pobieranie assetów Release przez zwykłe, nieautoryzowane HTTPS GET,
BEZ żadnego tokenu/sekretu. To dotyczy WYŁĄCZNIE danych SHARED
scannera (companies/analyses/live_scan_runs/...) -- portfel
użytkownika (Postgres/Supabase) jest całkowicie osobny i ten moduł go
nie dotyka.

KONTRAKT (sekcja "Scanner snapshot" decyzji właścicielki):
- immutable dla danego runu -- `ensure_local_snapshot` nigdy nie
  nadpisuje już poprawnie zweryfikowanego pliku dla tego samego
  `run_id`.
- jednoznacznie powiązany z `run_id` -- nazwa lokalnego pliku
  zawiera `run_id`, zwracany jest też cały `pointer` (słownik z
  `run_id`/`run_date`/...), więc wołający ZAWSZE wie, co pokazuje.
- możliwy do zweryfikowania przed użyciem -- SHA256 pobranego pliku
  jest liczone i porównywane z `pointer["sha256"]` PRZED zwróceniem
  ścieżki do wołającego; niezgodność = plik usuwany, wyjątek.
- pobierany jako read-only, cache'owany lokalnie TYLKO jako
  odtwarzalna kopia -- ten moduł nigdy nie zapisuje do pobranego
  pliku, tylko go czyta/weryfikuje; zgubienie cache'u (redeploy
  Streamlit, czyszczony filesystem) jest nieszkodliwe, bo kolejne
  wywołanie po prostu pobierze go ponownie.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import httpx

from buffett_scanner.snapshot_publish import (
    POINTER_ASSET_NAME,
    SNAPSHOT_POINTER_TAG,
    compute_sha256,
)

GITHUB_RELEASE_DOWNLOAD_BASE = "https://github.com"
DEFAULT_TIMEOUT = 30.0


class SnapshotUnavailableError(RuntimeError):
    """Snapshot nieosiągalny lub nie przeszedł weryfikacji (błąd sieci,
    404 -- jeszcze żaden live-scan nigdy się nie opublikował, zepsuty
    JSON, niezgodność SHA256). Wołający (przyszłe okablowanie UI, Etap
    D) łapie WYŁĄCZNIE ten jeden, nazwany typ i pokazuje czytelny
    komunikat -- nigdy goły traceback httpx/JSON."""


def _release_asset_url(owner: str, repo: str, tag: str, asset_name: str) -> str:
    return f"{GITHUB_RELEASE_DOWNLOAD_BASE}/{owner}/{repo}/releases/download/{tag}/{asset_name}"


def fetch_pointer(owner: str, repo: str, *, client: httpx.Client | None = None) -> dict:
    """Pobiera i parsuje `pointer.json` z release'u `scanner-snapshot-
    latest`. Rzuca `SnapshotUnavailableError` na KAŻDY błąd (sieć, 404,
    zepsuty JSON) -- nigdy nie zwraca `None`/pustego słownika jako
    cichego fallbacku."""
    url = _release_asset_url(owner, repo, SNAPSHOT_POINTER_TAG, POINTER_ASSET_NAME)
    owns_client = client is None
    client = client or httpx.Client(timeout=DEFAULT_TIMEOUT, follow_redirects=True)
    try:
        try:
            resp = client.get(url)
        except httpx.HTTPError as exc:
            raise SnapshotUnavailableError(f"Błąd sieci przy pobieraniu pointer.json: {exc}") from exc
        if resp.status_code != 200:
            raise SnapshotUnavailableError(
                f"Pointer snapshotu niedostępny (status {resp.status_code}) -- "
                "być może żaden live-scan jeszcze się nie opublikował."
            )
        try:
            pointer = resp.json()
        except ValueError as exc:
            raise SnapshotUnavailableError(f"pointer.json ma niepoprawny format: {exc}") from exc
        required_fields = {"run_id", "run_date", "release_tag", "asset_name", "sha256"}
        missing = required_fields - pointer.keys()
        if missing:
            raise SnapshotUnavailableError(f"pointer.json nie ma wymaganych pól: {sorted(missing)}")
        return pointer
    finally:
        if owns_client:
            client.close()


def _local_snapshot_path(cache_dir: str | Path, run_id: str) -> Path:
    # run_id jest znanym, bezpiecznym formatem (live-scan-<ISO timestamp>Z,
    # patrz `should_publish_as_live_scan`) -- zamiana ':' na '-' to jedyna
    # defensywna sanityzacja potrzebna dla nazwy pliku.
    safe_run_id = run_id.replace(":", "-").replace("/", "-")
    return Path(cache_dir) / f"scanner_snapshot_{safe_run_id}.db"


def download_snapshot(
    pointer: dict, owner: str, repo: str, *, dest_path: str | Path, client: httpx.Client | None = None,
) -> None:
    """Pobiera plik `.db` wskazany przez `pointer` do `dest_path` i
    weryfikuje SHA256 PRZED zakończeniem -- niezgodność usuwa plik i
    rzuca `SnapshotUnavailableError` (nigdy nie zostawia niezweryfikowanego
    albo uciętego pliku tak, jakby był poprawny)."""
    url = _release_asset_url(owner, repo, pointer["release_tag"], pointer["asset_name"])
    owns_client = client is None
    client = client or httpx.Client(timeout=DEFAULT_TIMEOUT, follow_redirects=True)
    dest_path = Path(dest_path)
    try:
        try:
            with client.stream("GET", url) as resp:
                if resp.status_code != 200:
                    raise SnapshotUnavailableError(
                        f"Pobieranie snapshotu nie powiodło się (status {resp.status_code})."
                    )
                digest = hashlib.sha256()
                with open(dest_path, "wb") as f:
                    for chunk in resp.iter_bytes():
                        f.write(chunk)
                        digest.update(chunk)
        except httpx.HTTPError as exc:
            dest_path.unlink(missing_ok=True)
            raise SnapshotUnavailableError(f"Błąd sieci przy pobieraniu snapshotu: {exc}") from exc

        actual_sha256 = digest.hexdigest()
        if actual_sha256 != pointer["sha256"]:
            dest_path.unlink(missing_ok=True)
            raise SnapshotUnavailableError(
                "Pobrany snapshot nie zgadza się z oczekiwanym SHA256 (uszkodzony/ucięty download) -- "
                f"oczekiwano {pointer['sha256']}, otrzymano {actual_sha256}."
            )
    finally:
        if owns_client:
            client.close()


def ensure_local_snapshot(
    owner: str, repo: str, *, cache_dir: str | Path, client: httpx.Client | None = None,
) -> tuple[Path, dict]:
    """Główna funkcja dla wołającego (przyszłe okablowanie UI, Etap D).

    1. Pobiera `pointer.json` -- wie, jaki `run_id` jest najnowszy.
    2. Jeśli lokalny plik dla TEGO `run_id` już istnieje i jego własne
       SHA256 się zgadza -- używa go bez ponownego pobierania (appka
       może wywoływać to przy każdym rerunie Streamlit bez pobierania
       za każdym razem na nowo).
    3. W przeciwnym razie pobiera świeżo i weryfikuje.

    Zwraca `(ścieżka_do_lokalnego_pliku, pointer)` -- wołający ZAWSZE
    ma `pointer["run_id"]` do pokazania w UI ("Co scanner znalazł --
    skan z ...")."""
    pointer = fetch_pointer(owner, repo, client=client)
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    local_path = _local_snapshot_path(cache_dir, pointer["run_id"])

    if local_path.exists() and compute_sha256(local_path) == pointer["sha256"]:
        return local_path, pointer

    download_snapshot(pointer, owner, repo, dest_path=local_path, client=client)
    return local_path, pointer

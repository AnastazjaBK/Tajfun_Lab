"""Publikacja snapshotu scannera jako GitHub Release asset (Faza 8
"Hostowany V0", Etap B, Decyzja właścicielki).

PROBLEM, KTÓRY TO ROZWIĄZUJE: `phase6-live-scan.yml` dziś NIE trzyma
danych scannera trwale nigdzie -- `live_scan_result.db` jest tworzone
od zera przy każdym runie i tylko wrzucane jako artefakt GitHub Actions
z 30-dniowym wygaśnięciem (znalezisko audytu "Hostowany V0"). Hostowana
appka Streamlit potrzebuje TRWAŁEGO miejsca, skąd może pobrać najnowszy,
realny snapshot danych SHARED (companies/analyses/live_scan_runs/
live_scan_candidates/price_daily/...) -- bez trzymania tych danych w
Postgresie (Decyzja właścicielki: Postgres WYŁĄCZNIE dla 7 tabel
user-generated, scanner data zostaje w SQLite).

ROZWIĄZANIE: GitHub Release, NIE branch (właścicielka wprost odrzuciła
branch z binarnym SQLite), NIE 30-dniowy artefakt Actions. Dwupoziomowo:

1. Jeden IMMUTABLE release PER RUN, tag `scanner-snapshot-<run_id>` --
   nigdy nadpisywany, zawsze można wrócić do konkretnego historycznego
   runu po jego run_id (sekcja "możliwy do zweryfikowania").
2. Jeden MUTABLE "pointer" release, tag stały (`SNAPSHOT_POINTER_TAG`)
   -- jego JEDYNY asset (`pointer.json`) jest NADPISYWANY przy każdej
   publikacji i wskazuje, który run_id/release_tag jest "najnowszy".
   UI (Etap C) czyta NAJPIERW `pointer.json` (mały, szybki plik), potem
   pobiera właściwy, immutable snapshot .db z release'u, na który
   pointer wskazuje -- UI zawsze wie DOKŁADNIE, jaki `run_id` pokazuje
   (sekcja "UI musi wiedzieć, jaki run_id aktualnie pokazuje").

WERYFIKACJA PRZED UŻYCIEM: `pointer.json` i notatki release'u niosą
SHA256 pliku .db w momencie publikacji -- UI (Etap C) po pobraniu liczy
SHA256 pobranego pliku i porównuje, zanim go otworzy (ucięty/uszkodzony
download nigdy nie trafia do Streamlit jako "dane scannera").

NIGDY VALIDATION-* JAKO LIVE MARKET SCAN: `should_publish_as_live_scan`
używa DOKŁADNIE tej samej konwencji co `ui/queries.
get_latest_live_scan_run` (`run_id` zaczyna się od `live-scan-`) --
diagnostyczne runy Faz 6f/6g/6h/walidacyjne NIGDY nie publikują się
jako najnowszy snapshot, nawet gdyby ktoś przez pomyłkę odpalił ten
skrypt na ich bazie."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

RELEASE_TAG_PREFIX = "scanner-snapshot-"
SNAPSHOT_POINTER_TAG = "scanner-snapshot-latest"
SNAPSHOT_ASSET_NAME = "live_scan_result.db"
POINTER_ASSET_NAME = "pointer.json"


class SnapshotPublishError(RuntimeError):
    """Błąd `gh` (sieć/uprawnienia/API GitHuba) -- nigdy nie łapany po
    cichu, workflow ma widocznie zawieść, żeby brak publikacji nie
    przeszedł niezauważony."""


@dataclass(frozen=True)
class RunSummary:
    run_id: str
    run_date: str
    universe_size: int
    decline_surfaced: int
    shortlist_size: int


def compute_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def should_publish_as_live_scan(run_id: str) -> bool:
    """Dokładnie ta sama konwencja co `ui/queries.
    get_latest_live_scan_run` (`run_id LIKE 'live-scan-%'`) --
    `validation-*` i wszystko inne NIGDY nie jest traktowane jako
    prawdziwy market scan."""
    return run_id.startswith("live-scan-")


def read_latest_run_summary(db_path: str | Path) -> RunSummary | None:
    """Czyta NAJNOWSZY wiersz `live_scan_runs` z podanego pliku SQLite.
    W praktyce `live_scan_result.db` jest tworzone OD ZERA przez
    `init-db` + `run-live-scan` w każdym jednym jobie GitHub Actions,
    więc ma dokładnie jeden wiersz -- to jedyny kontrakt, jaki ta
    funkcja gwarantuje. `ORDER BY created_at DESC, rowid DESC` to
    najlepszy dostępny tiebreak dla wielu wierszy w tej samej sekundzie
    (ten sam kompromis co `ui/queries.get_latest_live_scan_run`,
    `created_at` ma rozdzielczość do sekundy), ale ten skrypt NIE jest
    projektowany pod publikację z wieloma runami w jednym pliku.
    `None`, gdy tabela jest pusta."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT * FROM live_scan_runs ORDER BY created_at DESC, rowid DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return RunSummary(
        run_id=row["run_id"],
        run_date=row["run_date"],
        universe_size=row["universe_size"],
        decline_surfaced=row["decline_surfaced"],
        shortlist_size=row["shortlist_size"],
    )


def build_release_notes(summary: RunSummary, *, sha256: str) -> str:
    return (
        f"Snapshot danych scannera (SHARED, read-only) dla run_id `{summary.run_id}`.\n\n"
        f"- Data runu: {summary.run_date}\n"
        f"- Uniwersum: {summary.universe_size}\n"
        f"- Surfaced (decline screening): {summary.decline_surfaced}\n"
        f"- Shortlist: {summary.shortlist_size}\n"
        f"- SHA256 ({SNAPSHOT_ASSET_NAME}): `{sha256}`\n\n"
        "Immutable -- ten release nigdy nie jest nadpisywany. "
        "Zob. release `" + SNAPSHOT_POINTER_TAG + "` dla wskaźnika na najnowszy snapshot."
    )


def build_pointer_payload(summary: RunSummary, *, release_tag: str, sha256: str) -> dict:
    return {
        "run_id": summary.run_id,
        "run_date": summary.run_date,
        "release_tag": release_tag,
        "asset_name": SNAPSHOT_ASSET_NAME,
        "sha256": sha256,
        "shortlist_size": summary.shortlist_size,
        "published_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


class GhReleaseClient:
    """Cienki wrapper na `gh release ...` (CLI preinstalowane na
    GitHub-hosted runnerach, używa domyślnego GITHUB_TOKEN joba --
    zero nowego sekretu). Wydzielone w osobną klasę, żeby testy mogły
    podstawić fejka zamiast wołać prawdziwy `gh`/sieć."""

    def __init__(self, *, repo: str | None = None, run=subprocess.run):
        self._repo = repo
        self._run = run

    def _repo_args(self) -> list[str]:
        return ["--repo", self._repo] if self._repo else []

    def release_exists(self, tag: str) -> bool:
        result = self._run(
            ["gh", "release", "view", tag, *self._repo_args()],
            capture_output=True, text=True,
        )
        return result.returncode == 0

    def create_release(self, tag: str, *, title: str, notes: str, asset_path: str) -> None:
        result = self._run(
            [
                "gh", "release", "create", tag, asset_path,
                "--title", title, "--notes", notes, *self._repo_args(),
            ],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            raise SnapshotPublishError(f"gh release create {tag} nie powiodło się: {result.stderr}")

    def upload_asset(self, tag: str, asset_path: str) -> None:
        result = self._run(
            ["gh", "release", "upload", tag, asset_path, "--clobber", *self._repo_args()],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            raise SnapshotPublishError(f"gh release upload {tag} nie powiodło się: {result.stderr}")


def publish_snapshot(
    db_path: str | Path, *, gh_client: GhReleaseClient, work_dir: str | Path = ".",
) -> dict | None:
    """Główna orkiestracja. Zwraca podsumowanie publikacji, albo `None`
    gdy run_id NIE jest prawdziwym live-scanem (walidacja/diagnostyka)
    -- w tym wypadku NIC nie jest publikowane, funkcja NIE rzuca
    wyjątku (to prawidłowy, oczekiwany wynik, nie błąd)."""
    summary = read_latest_run_summary(db_path)
    if summary is None:
        return None
    if not should_publish_as_live_scan(summary.run_id):
        return None

    sha256 = compute_sha256(db_path)
    release_tag = f"{RELEASE_TAG_PREFIX}{summary.run_id}"

    # 1. Immutable release per run -- tworzony TYLKO jeśli jeszcze nie
    #    istnieje (ten sam run_id nigdy nie jest publikowany dwa razy
    #    z różną zawartością).
    if not gh_client.release_exists(release_tag):
        gh_client.create_release(
            release_tag, title=f"Scanner snapshot {summary.run_id}",
            notes=build_release_notes(summary, sha256=sha256), asset_path=str(db_path),
        )

    # 2. Mutable pointer -- zawsze nadpisywany (`--clobber`), wskazuje
    #    na NAJNOWSZY prawdziwy live-scan.
    pointer_payload = build_pointer_payload(summary, release_tag=release_tag, sha256=sha256)
    pointer_path = Path(work_dir) / POINTER_ASSET_NAME
    pointer_path.write_text(json.dumps(pointer_payload, indent=2, ensure_ascii=False), encoding="utf-8")
    if not gh_client.release_exists(SNAPSHOT_POINTER_TAG):
        gh_client.create_release(
            SNAPSHOT_POINTER_TAG, title="Najnowszy snapshot scannera (wskaźnik)",
            notes=(
                "Ten release NIE jest immutable -- jego jedyny asset (`pointer.json`) "
                "jest nadpisywany przy każdej publikacji nowego live-scanu. "
                "Wskazuje aktualny `run_id`/`release_tag` z prawdziwymi danymi."
            ),
            asset_path=str(pointer_path),
        )
    else:
        gh_client.upload_asset(SNAPSHOT_POINTER_TAG, str(pointer_path))

    return pointer_payload

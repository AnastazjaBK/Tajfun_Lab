"""Test integracyjny Faza 8 Etap D: `app._connect_backends()` w trybie
HOSTOWANYM -- dowód, że okablowanie dwóch osobnych połączeń (Postgres
dla portfela, read-only SQLite snapshot dla scannera) faktycznie
działa razem, nie tylko w izolacji (Etap A/C mają już własne testy
każdego backendu osobno).

Wymaga prawdziwego Postgresa (`TEST_POSTGRES_URL`, jak w
`test_pg_store.py`) -- pomijany domyślnie. Pobieranie snapshotu z
GitHub jest zamockowane (`ensure_local_snapshot` podmienione na
fejkową funkcję zwracającą lokalny, wcześniej zaseedowany plik SQLite)
-- ten test NIE zależy od tego, czy jakikolwiek live-scan już się
opublikował na prawdziwym repo (to osobno zweryfikowane w Etapie C)."""

from __future__ import annotations

import os
import sqlite3

import pytest

psycopg2 = pytest.importorskip("psycopg2")

import app  # noqa: E402 -- repo root, importowalny bo pytest.ini jest w tym samym katalogu
from buffett_scanner.db import SCHEMA, insert_live_scan_run, upsert_company  # noqa: E402
from buffett_scanner.pg_store import get_users  # noqa: E402

TEST_POSTGRES_URL_ENV_VAR = "TEST_POSTGRES_URL"


@pytest.fixture
def hosted_env(monkeypatch, tmp_path):
    url = os.environ.get(TEST_POSTGRES_URL_ENV_VAR)
    if not url:
        pytest.skip(f"Brak {TEST_POSTGRES_URL_ENV_VAR} -- pomijam test integracyjny trybu hostowanego.")
    monkeypatch.setenv("SUPABASE_DB_URL", url)
    monkeypatch.setattr(app.portfolio_backend, "HOSTED", True)

    # Zaseedowany lokalny plik SQLite, udający pobrany/zweryfikowany
    # snapshot -- `ensure_local_snapshot` jest tu podmienione, więc
    # realny network call do GitHub w ogóle się nie dzieje (ten aspekt
    # jest już osobno sprawdzony w Etapie C).
    snapshot_path = tmp_path / "fake_snapshot.db"
    conn = sqlite3.connect(snapshot_path)
    conn.executescript(SCHEMA)
    upsert_company(conn, cik="0000928054", name="CBOE Global Markets Inc.")
    insert_live_scan_run(
        conn, run_id="live-scan-2026-10-07T120000000000Z", run_date="2026-10-07",
        config_version="v1", universe_size=501, decline_surfaced=156,
        prefilter_excluded=0, shortlist_limit=20, shortlist_size=0,
    )
    conn.commit()
    conn.close()

    fake_pointer = {"run_id": "live-scan-2026-10-07T120000000000Z", "run_date": "2026-10-07"}
    monkeypatch.setattr(
        app, "ensure_local_snapshot",
        lambda owner, repo, *, cache_dir: (snapshot_path, fake_pointer),
    )

    yield

    # Sprzątanie: wyczyść tabele testowej bazy, żeby kolejne testy w tej
    # samej sesji (albo kolejne uruchomienia lokalnie) dostawały czysty stan.
    cleanup_conn = psycopg2.connect(url)
    with cleanup_conn.cursor() as cur:
        cur.execute(
            "TRUNCATE holding_user_actions, purchase_thesis, sale_transactions, "
            "purchase_transactions, positions, user_decisions, users RESTART IDENTITY CASCADE"
        )
    cleanup_conn.commit()
    cleanup_conn.close()


@pytest.mark.integration
def test_connect_backends_wires_real_postgres_and_snapshot_sqlite_together(hosted_env):
    backends = app._connect_backends()
    assert backends is not None
    portfolio_conn, scanner_conn = backends

    # Portfolio_conn jest prawdziwym, działającym połączeniem Postgres --
    # funkcje portfolio_backend (wybrane na Postgres, bo HOSTED=True)
    # działają na nim bez błędu.
    assert get_users(portfolio_conn) == []

    # Scanner_conn poprawnie czyta zaseedowany fake snapshot.
    row = scanner_conn.execute("SELECT * FROM live_scan_runs").fetchone()
    assert row["run_id"] == "live-scan-2026-10-07T120000000000Z"

    portfolio_conn.close()
    scanner_conn.close()


@pytest.mark.integration
def test_connect_backends_opens_scanner_conn_as_read_only(hosted_env):
    """Test KLUCZOWY: hostowana appka NIGDY nie zapisuje do danych
    scannera -- `scanner_conn` musi odrzucić próbę zapisu."""
    portfolio_conn, scanner_conn = app._connect_backends()
    with pytest.raises(sqlite3.OperationalError, match="readonly|read-only"):
        scanner_conn.execute("INSERT INTO companies (cik, name) VALUES ('X', 'Y')")
    portfolio_conn.close()
    scanner_conn.close()

import sqlite3

import pytest

from buffett_scanner.db import (
    create_user,
    get_price_series,
    init_db,
    insert_price_rows,
    upsert_company,
    upsert_ticker_history,
)


@pytest.fixture
def conn(tmp_path):
    return init_db(tmp_path / "test.db")


def test_init_db_creates_expected_tables(conn):
    tables = {
        row["name"]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert {"companies", "ticker_history", "price_daily", "users"} <= tables


def test_init_db_is_idempotent(tmp_path):
    path = tmp_path / "test.db"
    init_db(path)
    conn2 = init_db(path)  # nie powinno rzucić błędu przy istniejącym schemacie
    assert conn2 is not None


def test_upsert_company_identity_is_cik_not_ticker(conn):
    upsert_company(conn, cik="0000320193", name="Apple Inc.", sector="Technology")
    upsert_company(conn, cik="0000320193", name="Apple Inc. (updated)", sector="Technology")
    rows = conn.execute("SELECT * FROM companies").fetchall()
    assert len(rows) == 1
    assert rows[0]["name"] == "Apple Inc. (updated)"


def test_sector_profile_defaults_to_general_and_is_constrained(conn):
    upsert_company(conn, cik="0000320193", name="Apple Inc.")
    row = conn.execute("SELECT sector_profile FROM companies").fetchone()
    assert row["sector_profile"] == "GENERAL"

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO companies (cik, name, sector_profile) VALUES (?, ?, ?)",
            ("0000000001", "Nieprawidłowy sektor", "NOT_A_REAL_SECTOR"),
        )


def test_ticker_recycling_is_disambiguated_by_cik(conn):
    """Symulacja ryzyka z sekcji 5/14 design review: ten sam ticker,
    dwie różne spółki w różnych okresach — muszą pozostać rozróżnialne
    po CIK, nie po tickerze."""
    upsert_company(conn, cik="0000111111", name="SunTrust Banks (przykład)")
    upsert_ticker_history(conn, cik="0000111111", ticker="STI", start_date="2010-01-01")

    upsert_company(conn, cik="0000222222", name="Inna spółka (przykład)")
    upsert_ticker_history(conn, cik="0000222222", ticker="STI", start_date="2020-01-01")

    history = conn.execute(
        "SELECT cik, ticker, start_date, end_date FROM ticker_history "
        "WHERE ticker = 'STI' ORDER BY start_date"
    ).fetchall()
    assert len(history) == 2
    assert history[0]["cik"] == "0000111111"
    assert history[1]["cik"] == "0000222222"
    # rekord tylko przypisany do TEGO SAMEGO CIK jest domykany przy zmianie
    # tickera; ticker recycling na inny CIK nie zamyka cudzego wpisu
    assert history[0]["end_date"] is None


def test_insert_and_read_price_series_ordered_by_date(conn):
    upsert_company(conn, cik="0000320193", name="Apple Inc.")
    rows = [
        {"date": "2026-01-03", "open": 1, "high": 2, "low": 0.5, "close": 1.5, "adj_close": 1.5, "volume": 100},
        {"date": "2026-01-02", "open": 1, "high": 2, "low": 0.5, "close": 1.4, "adj_close": 1.4, "volume": 90},
    ]
    n = insert_price_rows(conn, "0000320193", source="fmp", rows=rows)
    conn.commit()
    assert n == 2

    series = get_price_series(conn, "0000320193")
    assert [r["date"] for r in series] == ["2026-01-02", "2026-01-03"]


def test_insert_price_rows_upserts_on_conflict(conn):
    upsert_company(conn, cik="0000320193", name="Apple Inc.")
    insert_price_rows(
        conn, "0000320193", source="fmp",
        rows=[{"date": "2026-01-02", "close": 1.0, "volume": 10}],
    )
    insert_price_rows(
        conn, "0000320193", source="fmp",
        rows=[{"date": "2026-01-02", "close": 9.9, "volume": 999}],
    )
    conn.commit()
    series = get_price_series(conn, "0000320193")
    assert len(series) == 1
    assert series[0]["close"] == 9.9
    assert series[0]["volume"] == 999


def test_create_user_minimal_no_auth(conn):
    user_id = create_user(conn, "Anastazja")
    conn.commit()
    row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
    assert row["display_name"] == "Anastazja"

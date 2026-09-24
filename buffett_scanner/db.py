"""Warstwa bazy danych — Faza 0.

Tylko tabele potrzebne w Fazie 0 (sekcja 15, punkty 0.2/0.3/0.5 planu
implementacji): companies, ticker_history, price_daily, users.
Tożsamość spółki to CIK, nigdy ticker (patrz sekcja 5 design review —
ryzyko "ticker recycling"). Pozostałe tabele ze zaprojektowanego
schematu (fundamentals_raw, analyses, watchlist, positions, moduł
BIOTECH, ...) należą do późniejszych faz i nie są tu tworzone — nie
rozszerzamy MVP przed czasem.

SQLite teraz, Postgres/Supabase od V1 (Decyzja D5) — typy i DDL
poniżej celowo unikają konstrukcji specyficznych dla SQLite, żeby
migracja nie wymagała przeprojektowania modelu danych.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS companies (
    cik             TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    sector          TEXT,
    industry        TEXT,
    sub_industry    TEXT,
    sector_profile  TEXT NOT NULL DEFAULT 'GENERAL'
                    CHECK (sector_profile IN ('GENERAL','BANK','INSURER','REIT','BIOTECH')),
    is_active       INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS ticker_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    cik         TEXT NOT NULL REFERENCES companies(cik),
    ticker      TEXT NOT NULL,
    start_date  TEXT NOT NULL,
    end_date    TEXT,
    UNIQUE (cik, ticker, start_date)
);
CREATE INDEX IF NOT EXISTS idx_ticker_history_ticker ON ticker_history(ticker);

CREATE TABLE IF NOT EXISTS price_daily (
    cik         TEXT NOT NULL REFERENCES companies(cik),
    date        TEXT NOT NULL,
    open        REAL,
    high        REAL,
    low         REAL,
    close       REAL,
    adj_close   REAL,
    volume      INTEGER,
    source      TEXT NOT NULL,
    ingested_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (cik, date)
);

-- Minimalna, bez auth — fundament pod user_id w Fazach 6/7/9
-- (sekcja 1.1 design review). Nie rozszerza zakresu Fazy 0 o UI/logowanie.
CREATE TABLE IF NOT EXISTS users (
    user_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    display_name TEXT NOT NULL,
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def connect(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: str | Path) -> sqlite3.Connection:
    """Tworzy schemat (idempotentnie) i zwraca otwarte połączenie."""
    conn = connect(db_path)
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def upsert_company(
    conn: sqlite3.Connection,
    *,
    cik: str,
    name: str,
    sector: str | None = None,
    industry: str | None = None,
    sub_industry: str | None = None,
    sector_profile: str = "GENERAL",
) -> None:
    conn.execute(
        """
        INSERT INTO companies (cik, name, sector, industry, sub_industry, sector_profile)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(cik) DO UPDATE SET
            name = excluded.name,
            sector = excluded.sector,
            industry = excluded.industry,
            sub_industry = excluded.sub_industry,
            sector_profile = excluded.sector_profile
        """,
        (cik, name, sector, industry, sub_industry, sector_profile),
    )


def upsert_ticker_history(
    conn: sqlite3.Connection, *, cik: str, ticker: str, start_date: str
) -> None:
    """Zamyka poprzedni aktywny wpis tickera dla tego CIK (jeśli inny) i
    dodaje nowy — ticker jest atrybutem zmiennym w czasie, nie tożsamością
    (sekcja 5 design review)."""
    conn.execute(
        """
        UPDATE ticker_history
        SET end_date = ?
        WHERE cik = ? AND end_date IS NULL AND ticker != ?
        """,
        (start_date, cik, ticker),
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO ticker_history (cik, ticker, start_date, end_date)
        VALUES (?, ?, ?, NULL)
        """,
        (cik, ticker, start_date),
    )


def insert_price_rows(conn: sqlite3.Connection, cik: str, source: str, rows: list[dict]) -> int:
    """rows: [{date, open, high, low, close, adj_close, volume}, ...]. Zwraca
    liczbę wstawionych/zaktualizowanych wierszy."""
    n = 0
    for r in rows:
        conn.execute(
            """
            INSERT INTO price_daily (cik, date, open, high, low, close, adj_close, volume, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(cik, date) DO UPDATE SET
                open = excluded.open, high = excluded.high, low = excluded.low,
                close = excluded.close, adj_close = excluded.adj_close,
                volume = excluded.volume, source = excluded.source
            """,
            (
                cik,
                r["date"],
                r.get("open"),
                r.get("high"),
                r.get("low"),
                r.get("close"),
                r.get("adj_close"),
                r.get("volume"),
                source,
            ),
        )
        n += 1
    return n


def get_price_series(conn: sqlite3.Connection, cik: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM price_daily WHERE cik = ? ORDER BY date ASC", (cik,)
    ).fetchall()


def create_user(conn: sqlite3.Connection, display_name: str) -> int:
    cur = conn.execute(
        "INSERT INTO users (display_name) VALUES (?)", (display_name,)
    )
    return cur.lastrowid

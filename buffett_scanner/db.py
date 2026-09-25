"""Warstwa bazy danych — Faza 0 + Faza 1.

Faza 0 (sekcja 15, punkty 0.2/0.3/0.5 planu implementacji): companies,
ticker_history, price_daily, users. Faza 1 (punkt 1.1): fundamentals_raw
(format long, surowe dane "as reported"), derived_metrics (wyliczone
wskaźniki, wersjonowane przez calc_version). Tożsamość spółki to CIK,
nigdy ticker (patrz sekcja 5 design review — ryzyko "ticker recycling").
Pozostałe tabele ze zaprojektowanego schematu (analyses, watchlist,
positions, moduł BIOTECH, ...) należą do późniejszych faz i nie są tu
tworzone — nie rozszerzamy MVP przed czasem.

SQLite teraz, Postgres/Supabase od V1 (Decyzja D5) — typy i DDL
poniżej celowo unikają konstrukcji specyficznych dla SQLite, żeby
migracja nie wymagała przeprojektowania modelu danych.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from buffett_scanner.fundamentals import FundamentalsPeriod

# Kanoniczne nazwy line_item używane przy zapisie/odczycie fundamentals_raw
# — muszą być spójne między ingestem (cli.py) a pivotowaniem tutaj.
_INCOME_STATEMENT_ITEMS = {"revenue", "net_income", "ebitda"}
_BALANCE_SHEET_ITEMS = {
    "total_debt", "cash_and_equivalents",
    "total_current_assets", "total_current_liabilities",
}
_CASH_FLOW_ITEMS = {"operating_cash_flow", "capital_expenditure"}

LINE_ITEM_STATEMENT_TYPE = {
    **{k: "INCOME_STATEMENT" for k in _INCOME_STATEMENT_ITEMS},
    **{k: "BALANCE_SHEET" for k in _BALANCE_SHEET_ITEMS},
    **{k: "CASH_FLOW" for k in _CASH_FLOW_ITEMS},
}

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

-- Faza 1 — surowe dane fundamentalne, format long: korekty/restatements
-- NIE nadpisują wartości "as reported" (nowy wiersz, nie UPDATE).
-- filed_date krytyczne dla point-in-time (sekcja 13 design review).
CREATE TABLE IF NOT EXISTS fundamentals_raw (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    cik             TEXT NOT NULL REFERENCES companies(cik),
    fiscal_period   TEXT NOT NULL,
    period_end_date TEXT NOT NULL,
    filed_date      TEXT,
    statement_type  TEXT NOT NULL
                    CHECK (statement_type IN ('INCOME_STATEMENT','BALANCE_SHEET','CASH_FLOW')),
    line_item       TEXT NOT NULL,
    value           REAL,
    unit            TEXT,
    source          TEXT NOT NULL,
    source_doc_id   TEXT,
    ingested_at     TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (cik, fiscal_period, statement_type, line_item, source)
);
CREATE INDEX IF NOT EXISTS idx_fundamentals_raw_cik_period
    ON fundamentals_raw(cik, fiscal_period);

-- Faza 1 — wskaźniki wyliczone z fundamentals_raw. calc_version pozwala
-- przeliczyć historię bez utraty poprzednich wyników (sekcja 10/11).
CREATE TABLE IF NOT EXISTS derived_metrics (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    cik          TEXT NOT NULL REFERENCES companies(cik),
    as_of_date   TEXT NOT NULL,
    metric_name  TEXT NOT NULL,
    value        REAL,
    calc_version TEXT NOT NULL,
    inputs_hash  TEXT,
    ingested_at  TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (cik, as_of_date, metric_name, calc_version)
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


def insert_fundamentals_rows(
    conn: sqlite3.Connection, cik: str, source: str, rows: list[dict]
) -> int:
    """rows: [{fiscal_period, period_end_date, filed_date, line_item, value,
    unit}, ...]. `statement_type` wyprowadzany z `line_item` przez
    LINE_ITEM_STATEMENT_TYPE — nazwy line_item muszą być kanoniczne (patrz
    moduł). Wartości None (brakujący line item w odpowiedzi providera) są
    zapisywane jako NULL, nigdy jako 0."""
    n = 0
    for r in rows:
        line_item = r["line_item"]
        statement_type = LINE_ITEM_STATEMENT_TYPE.get(line_item)
        if statement_type is None:
            raise ValueError(f"Nieznany kanoniczny line_item: {line_item!r}")
        conn.execute(
            """
            INSERT INTO fundamentals_raw
                (cik, fiscal_period, period_end_date, filed_date,
                 statement_type, line_item, value, unit, source, source_doc_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(cik, fiscal_period, statement_type, line_item, source)
            DO UPDATE SET
                period_end_date = excluded.period_end_date,
                filed_date = excluded.filed_date,
                value = excluded.value,
                unit = excluded.unit,
                source_doc_id = excluded.source_doc_id
            """,
            (
                cik,
                r["fiscal_period"],
                r["period_end_date"],
                r.get("filed_date"),
                statement_type,
                line_item,
                r.get("value"),
                r.get("unit"),
                source,
                r.get("source_doc_id"),
            ),
        )
        n += 1
    return n


def get_fundamentals_periods(conn: sqlite3.Connection, cik: str) -> list[FundamentalsPeriod]:
    """Pivotuje fundamentals_raw (format long) do listy `FundamentalsPeriod`,
    posortowanej rosnąco po period_end_date (konwencja: [-1] = najnowszy,
    patrz fundamentals.py). Brakujący line_item dla danego okresu -> None,
    nigdy 0 — pole po prostu nie trafia do słownika przed przekazaniem do
    FundamentalsPeriod(**{...}), gdzie dataclass ma domyślnie None."""
    rows = conn.execute(
        """
        SELECT fiscal_period, period_end_date, filed_date, line_item, value
        FROM fundamentals_raw
        WHERE cik = ?
        ORDER BY period_end_date ASC
        """,
        (cik,),
    ).fetchall()

    by_period: dict[str, dict] = {}
    order: list[str] = []
    for r in rows:
        fp = r["fiscal_period"]
        if fp not in by_period:
            by_period[fp] = {
                "fiscal_period": fp,
                "period_end_date": r["period_end_date"],
                "filed_date": r["filed_date"],
            }
            order.append(fp)
        by_period[fp][r["line_item"]] = r["value"]

    fields = (
        "revenue", "net_income", "ebitda", "operating_cash_flow",
        "capital_expenditure", "total_debt", "cash_and_equivalents",
        "total_current_assets", "total_current_liabilities",
    )
    periods = []
    for fp in order:
        data = by_period[fp]
        periods.append(
            FundamentalsPeriod(
                fiscal_period=data["fiscal_period"],
                period_end_date=data["period_end_date"],
                filed_date=data["filed_date"],
                **{f: data.get(f) for f in fields},
            )
        )
    return periods


def upsert_derived_metric(
    conn: sqlite3.Connection,
    *,
    cik: str,
    as_of_date: str,
    metric_name: str,
    value: float | None,
    calc_version: str,
    inputs_hash: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO derived_metrics
            (cik, as_of_date, metric_name, value, calc_version, inputs_hash)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(cik, as_of_date, metric_name, calc_version)
        DO UPDATE SET value = excluded.value, inputs_hash = excluded.inputs_hash
        """,
        (cik, as_of_date, metric_name, value, calc_version, inputs_hash),
    )

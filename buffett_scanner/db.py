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
_INCOME_STATEMENT_ITEMS = {"revenue", "net_income", "ebitda", "diluted_shares_outstanding"}
_BALANCE_SHEET_ITEMS = {
    "total_debt", "cash_and_equivalents",
    "total_current_assets", "total_current_liabilities",
}
_CASH_FLOW_ITEMS = {"operating_cash_flow", "capital_expenditure", "dividends_paid", "share_buybacks"}

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

-- Faza 4 — wersjonowanie modelu scoringu (sekcja 11 design review):
-- każdy wiersz `analyses` wskazuje na ZAMROŻONY snapshot wag/bramek tu
-- zapisany, nie na "aktualny" config — v1.3 configu nie może nadpisać
-- wyników policzonych pod v1.2.
CREATE TABLE IF NOT EXISTS scoring_model_versions (
    version        TEXT PRIMARY KEY,
    description    TEXT,
    weights_json   TEXT NOT NULL,
    gates_json     TEXT NOT NULL,
    effective_from TEXT NOT NULL DEFAULT (datetime('now')),
    effective_to   TEXT,
    created_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Faza 4 — wyniki analiz. IMMUTABLE: ponowna ocena spółki = nowy
-- wiersz (INSERT), nigdy UPDATE (sekcja 11). `input_dataset_snapshot_id`
-- z projektu schematu (sekcja 5) celowo pominięty na razie — pełna
-- infrastruktura data_snapshots/run_log nie jest jeszcze zbudowana
-- (poza zakresem "silnik scoringu + hard gates + raport" z sekcji 15).
-- margin_of_safety_bear/bull_pct: rozszerzenie względem pierwotnego
-- projektu schematu — zatwierdzony design (2026-09-25) wymaga widoczności
-- wszystkich trzech scenariuszy w raporcie, nie tylko BASE.
CREATE TABLE IF NOT EXISTS analyses (
    analysis_id               INTEGER PRIMARY KEY AUTOINCREMENT,
    cik                       TEXT NOT NULL REFERENCES companies(cik),
    run_date                  TEXT NOT NULL,
    price_at_analysis         REAL,
    scoring_model_version     TEXT NOT NULL REFERENCES scoring_model_versions(version),
    business_quality_score    REAL,
    moat_score                REAL,
    financial_quality_score   REAL,
    management_score          REAL,
    safety_score              REAL,
    valuation_score           REAL,
    fear_score                REAL,
    dividend_score            REAL,
    total_score               REAL,
    hard_flags                TEXT,     -- JSON
    hard_gates_passed         INTEGER,
    valuation_range_low       REAL,     -- BEAR intrinsic value/akcję
    valuation_range_base      REAL,     -- BASE intrinsic value/akcję
    valuation_range_high      REAL,     -- BULL intrinsic value/akcję
    margin_of_safety_pct      REAL,     -- BASE — używany przez hard gate
    margin_of_safety_bear_pct REAL,
    margin_of_safety_bull_pct REAL,
    fear_classification       TEXT,
    fear_confidence           TEXT,
    llm_model_id              TEXT,
    llm_schema_version        TEXT,
    llm_raw_output            TEXT,     -- JSON
    created_at                TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_analyses_cik_run_date ON analyses(cik, run_date);

-- Faza 4 — źródła przypięte do konkretnej analizy (domyka lukę z Fazy 2:
-- VerifiedSource nie miał gdzie trafić, bo analysis_id nie istniał).
-- WYŁĄCZNIE realnie pobrane i zweryfikowane (BLOCKER 3, sekcja 9) —
-- ta tabela nigdy nie jest zapisywana na podstawie twierdzenia LLM.
CREATE TABLE IF NOT EXISTS analysis_sources (
    source_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    analysis_id       INTEGER NOT NULL REFERENCES analyses(analysis_id),
    source_type       TEXT NOT NULL
                      CHECK (source_type IN ('SEC_FILING','IR_DOC','PRESS_RELEASE','EARNINGS_CALL','OTHER')),
    title             TEXT,
    issuer            TEXT,
    doc_date          TEXT,
    url               TEXT,
    accession_number  TEXT,
    section           TEXT,
    page              INTEGER,
    content_hash      TEXT,
    verified          INTEGER NOT NULL,
    reason            TEXT,
    question          TEXT
);
CREATE INDEX IF NOT EXISTS idx_analysis_sources_analysis_id ON analysis_sources(analysis_id);
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
        "dividends_paid", "share_buybacks", "diluted_shares_outstanding",
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


def upsert_scoring_model_version(
    conn: sqlite3.Connection,
    *,
    version: str,
    description: str | None,
    weights_json: str,
    gates_json: str,
) -> None:
    """Zamraża snapshot wag/bramek pod daną wersją (sekcja 11 design
    review) — `analyses.scoring_model_version` wskazuje na ten wiersz,
    nie na "aktualny" config, więc zmiana configu nigdy nie zmienia
    znaczenia już policzonych wyników."""
    conn.execute(
        """
        INSERT INTO scoring_model_versions (version, description, weights_json, gates_json)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(version) DO UPDATE SET
            description = excluded.description,
            weights_json = excluded.weights_json,
            gates_json = excluded.gates_json
        """,
        (version, description, weights_json, gates_json),
    )


def insert_analysis(conn: sqlite3.Connection, **fields) -> int:
    """INSERT-only (nigdy UPDATE) — ponowna ocena spółki to zawsze nowy
    wiersz, zgodnie z zasadą immutability z sekcji 11. `fields` to
    dowolny podzbiór kolumn tabeli `analyses` (cik/run_date/
    scoring_model_version wymagane przez NOT NULL w schemacie)."""
    columns = list(fields.keys())
    placeholders = ", ".join("?" for _ in columns)
    cur = conn.execute(
        f"INSERT INTO analyses ({', '.join(columns)}) VALUES ({placeholders})",
        [fields[c] for c in columns],
    )
    return cur.lastrowid


def insert_analysis_sources(conn: sqlite3.Connection, analysis_id: int, sources: list) -> int:
    """sources: lista `sources.VerifiedSource`. Jedyny sposób, w jaki
    wiersze tu powstają — nigdy na podstawie twierdzenia LLM (BLOCKER 3).
    Zwraca liczbę wstawionych wierszy."""
    n = 0
    for s in sources:
        conn.execute(
            """
            INSERT INTO analysis_sources
                (analysis_id, source_type, title, issuer, doc_date, url,
                 accession_number, section, page, content_hash, verified, reason, question)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                analysis_id, s.source_type, s.title, s.issuer, s.doc_date, s.url,
                s.accession_number, s.section, None, s.content_hash, int(s.verified),
                s.reason, None,
            ),
        )
        n += 1
    return n

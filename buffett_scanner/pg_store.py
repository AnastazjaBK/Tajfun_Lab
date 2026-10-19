"""Warstwa trwałości Postgres (Supabase) — WYŁĄCZNIE 7 tabel
USER-GENERATED (Faza 7 "Hostowany V0", Etap A, Decyzja właścicielki):

    users, positions, purchase_transactions, sale_transactions,
    user_decisions, purchase_thesis, holding_user_actions

Dane SHARED scannera (`companies`, `analyses`, `analysis_sources`,
`live_scan_runs`, `live_scan_candidates`, `price_daily`, ...) ZOSTAJĄ w
SQLite jako read-only snapshot (Etap B/C) — ten moduł ich NIE dotyka,
NIE tworzy, NIE czyta. `buffett_scanner/db.py` (SQLite, scanner, cały
pipeline) pozostaje KOMPLETNIE NIEZMIENIONY — to jest nowy, równoległy
moduł, nie refaktoryzacja istniejącego.

DLACZEGO OSOBNY MODUŁ, NIE "jedna warstwa z przełącznikiem silnika":
SQL w `db.py` używa składni SQLite (`?` placeholders, `AUTOINCREMENT`,
`datetime('now')`, `sqlite3.Row`) w 69 zapytaniach obejmujących CAŁY
pipeline scannera — przepisywanie tego na dialekt Postgres byłoby
dokładnie tą "dużą migracją bez potrzeby", której właścicielka
wprost zabroniła. Ten moduł przepisuje WYŁĄCZNIE 16 funkcji CRUD
Fazy 7 (sekcja `user_decisions`/`positions`/transakcje/`purchase_thesis`/
`holding_user_actions`/`users` w `db.py`), z DOKŁADNIE tymi samymi
nazwami/sygnaturami/semantyką — docelowo `ui/queries.py`/`app.py` będą
mogły zaimportować funkcje STĄD zamiast z `db.py` (przełączenie samego
importu, Etap D), zero zmian w resztą UI.

WAŻNA RÓŻNICA SCHEMATU WZGLĘDEM SQLITE — FK DO companies/analyses:
w `db.py` `positions.cik` i `user_decisions.cik` mają
`REFERENCES companies(cik)`, a `user_decisions.analysis_id`/
`purchase_thesis.analysis_id` mają `REFERENCES analyses(analysis_id)`.
`companies`/`analyses` ŻYJĄ WYŁĄCZNIE w SQLite snapshot, NIE w tej
bazie Postgres — nie da się (i nie powinno się) odtworzyć tych FK tutaj.
Kolumny `cik`/`analysis_id` ZOSTAJĄ (zwykły TEXT/INTEGER, bez FK) —
integralność względem danych scannera jest odpowiedzialnością
aplikacji (UI), nie bazy, dokładnie tak jak każda relacja SHARED↔USER-
SCOPED rozpięta na dwóch różnych silnikach bazodanowych musi działać.

ZWRACANE WIERSZE: `psycopg2.extras.RealDictCursor` — `row["pole"]`
działa identycznie jak `sqlite3.Row` z resztą kodu (`ui/portfolio.py`,
`ui/queries.py`), zero zmian w sposobie czytania wyników po stronie
wołającego.

SEKRET: connection string WYŁĄCZNIE ze zmiennej środowiskowej
`SUPABASE_DB_URL` (ten sam wzorzec co `DataProviderConfig.
resolve_api_key` w `config.py`) — nigdy w repo, nigdy zalogowany.
"""

from __future__ import annotations

import json
import os

import psycopg2
import psycopg2.errors
import psycopg2.extras

SUPABASE_DB_URL_ENV_VAR = "SUPABASE_DB_URL"


class PgStoreUnavailableError(RuntimeError):
    """Baza nieosiągalna -- np. spauzowany darmowy projekt Supabase
    (Decyzja właścicielki, Faza 7 "Hostowany V0" pkt 3: "Jeżeli baza
    jest paused/unavailable: UI ma pokazać czytelny komunikat zamiast
    tracebacka"). Wołający (przyszłe okablowanie UI, Etap C/D) łapie
    WYŁĄCZNIE ten jeden, nazwany typ zamiast gołego
    `psycopg2.OperationalError` -- nigdy nie próbuje automatycznie
    tworzyć nowej bazy (wprost zabronione)."""


PG_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id      SERIAL PRIMARY KEY,
    display_name TEXT NOT NULL,
    created_at   TEXT NOT NULL DEFAULT to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')
);

CREATE TABLE IF NOT EXISTS positions (
    position_id         SERIAL PRIMARY KEY,
    user_id             INTEGER NOT NULL REFERENCES users(user_id),
    cik                 TEXT,
    ticker              TEXT NOT NULL,
    company_name        TEXT NOT NULL,
    exchange            TEXT,
    instrument_currency TEXT,
    status              TEXT NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN','CLOSED')),
    created_at          TEXT NOT NULL DEFAULT to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS'),
    updated_at          TEXT NOT NULL DEFAULT to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')
);
CREATE INDEX IF NOT EXISTS idx_positions_user_id ON positions(user_id);

CREATE TABLE IF NOT EXISTS purchase_transactions (
    transaction_id    SERIAL PRIMARY KEY,
    position_id       INTEGER NOT NULL REFERENCES positions(position_id),
    broker            TEXT NOT NULL CHECK (broker IN ('TRADE_REPUBLIC','REVOLUT','CASHIFY','GOLD_SAVER','MENNICA_SKARBOWA','OTHER')),
    acquisition_type  TEXT NOT NULL CHECK (acquisition_type IN ('BUY','BONUS')),
    purchase_date     TEXT NOT NULL,
    shares            DOUBLE PRECISION NOT NULL,
    price_per_share   DOUBLE PRECISION,
    total_invested    DOUBLE PRECISION NOT NULL,
    currency          TEXT NOT NULL,
    fees              DOUBLE PRECISION,
    note              TEXT,
    superseded_by     INTEGER REFERENCES purchase_transactions(transaction_id),
    created_at        TEXT NOT NULL DEFAULT to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')
);
CREATE INDEX IF NOT EXISTS idx_purchase_transactions_position_id ON purchase_transactions(position_id);

CREATE TABLE IF NOT EXISTS sale_transactions (
    transaction_id  SERIAL PRIMARY KEY,
    position_id     INTEGER NOT NULL REFERENCES positions(position_id),
    broker          TEXT NOT NULL CHECK (broker IN ('TRADE_REPUBLIC','REVOLUT','CASHIFY','GOLD_SAVER','MENNICA_SKARBOWA','OTHER')),
    sale_date       TEXT NOT NULL,
    shares          DOUBLE PRECISION NOT NULL,
    sale_price      DOUBLE PRECISION NOT NULL,
    currency        TEXT NOT NULL,
    fees            DOUBLE PRECISION,
    note            TEXT,
    cost_basis_method_used TEXT,
    superseded_by   INTEGER REFERENCES sale_transactions(transaction_id),
    created_at      TEXT NOT NULL DEFAULT to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')
);
CREATE INDEX IF NOT EXISTS idx_sale_transactions_position_id ON sale_transactions(position_id);

CREATE TABLE IF NOT EXISTS user_decisions (
    decision_id  SERIAL PRIMARY KEY,
    user_id      INTEGER NOT NULL REFERENCES users(user_id),
    cik          TEXT NOT NULL,
    analysis_id  INTEGER,
    status       TEXT NOT NULL CHECK (status IN ('WATCH','REJECT','SNOOZE','BOUGHT')),
    decided_at   TEXT NOT NULL DEFAULT to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS'),
    note         TEXT
);
CREATE INDEX IF NOT EXISTS idx_user_decisions_user_cik ON user_decisions(user_id, cik);

CREATE TABLE IF NOT EXISTS purchase_thesis (
    thesis_id      SERIAL PRIMARY KEY,
    position_id    INTEGER NOT NULL UNIQUE REFERENCES positions(position_id),
    analysis_id    INTEGER,
    snapshot_json  TEXT,
    created_at     TEXT NOT NULL DEFAULT to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')
);

CREATE TABLE IF NOT EXISTS holding_user_actions (
    action_id              SERIAL PRIMARY KEY,
    position_id            INTEGER NOT NULL REFERENCES positions(position_id),
    action                 TEXT NOT NULL CHECK (action IN ('HOLD','REDUCE','SOLD','REVIEW_LATER')),
    decided_at              TEXT NOT NULL DEFAULT to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS'),
    note                   TEXT,
    exit_review_report_id  INTEGER,
    created_at             TEXT NOT NULL DEFAULT to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')
);
CREATE INDEX IF NOT EXISTS idx_holding_user_actions_position_id ON holding_user_actions(position_id);
"""

# Faza 9 (2026-10-17) -- kolumny dodane PO wdrożeniu Fazy 8 (żywa baza
# Supabase już ma te tabele z danymi). Ten sam cel co
# `db._COLUMN_MIGRATIONS`. `init_schema` jest wołane przy KAŻDYM
# połączeniu (każdy rerun appki), a `ALTER TABLE` bierze blokadę
# ACCESS EXCLUSIVE nawet z `IF NOT EXISTS` -- dlatego ALTER jest
# wykonywany wyłącznie, gdy `information_schema` mówi, że kolumny brak.
PG_COLUMN_MIGRATIONS: tuple[tuple[str, str, str], ...] = (
    ("positions", "instrument_confirmed_at", "TEXT"),
    ("positions", "voided_at", "TEXT"),
    ("purchase_transactions", "voided_at", "TEXT"),
    ("purchase_transactions", "void_reason", "TEXT"),
    ("sale_transactions", "voided_at", "TEXT"),
    ("sale_transactions", "void_reason", "TEXT"),
    # Faza 11 (P0b-P4, Decyzja właścicielki 2026-10-17) -- tożsamość
    # instrumentu i źródło ceny (P0b), kurs rzeczywisty brokera (P1),
    # klasy aktywów i dane metali fizycznych (P4). Wszystkie nullable:
    # NULL `asset_class` = STOCK (pozycje sprzed Fazy 11).
    ("positions", "isin", "TEXT"),
    ("positions", "quote_currency", "TEXT"),
    ("positions", "price_provider", "TEXT"),
    ("positions", "price_symbol", "TEXT"),
    ("positions", "asset_class", "TEXT"),
    ("positions", "metal", "TEXT"),
    ("positions", "product_form", "TEXT"),
    ("positions", "unit_weight", "DOUBLE PRECISION"),
    ("positions", "weight_unit", "TEXT"),
    ("positions", "fineness", "DOUBLE PRECISION"),
    ("positions", "storage_location", "TEXT"),
    ("positions", "is_collectible", "INTEGER"),
    ("positions", "exposure_type", "TEXT"),
    ("positions", "annual_fee_pct", "DOUBLE PRECISION"),
    ("purchase_transactions", "fx_rate_actual", "DOUBLE PRECISION"),
    ("sale_transactions", "fx_rate_actual", "DOUBLE PRECISION"),
)

_PG_NOW = "to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')"

# Faza 11 -- nowe tabele. `market_data_cache` jest WSPÓLNY dla wszystkich
# użytkowników i sesji (ceny, kursy NBP, historia, dywidendy) -- jedno
# zapytanie do dostawcy obsługuje wszystkich (limit EODHD Free 20/dzień).
PG_NEW_TABLES: tuple[tuple[str, str], ...] = (
    ("market_data_cache", f"""
        CREATE TABLE IF NOT EXISTS market_data_cache (
            cache_key   TEXT PRIMARY KEY,
            payload     TEXT NOT NULL,
            fetched_at  TEXT NOT NULL DEFAULT {_PG_NOW}
        )"""),
    ("dividend_receipts", f"""
        CREATE TABLE IF NOT EXISTS dividend_receipts (
            receipt_id       SERIAL PRIMARY KEY,
            position_id      INTEGER NOT NULL REFERENCES positions(position_id),
            broker           TEXT NOT NULL CHECK (broker IN ('TRADE_REPUBLIC','REVOLUT','CASHIFY','GOLD_SAVER','MENNICA_SKARBOWA','OTHER')),
            pay_date         TEXT NOT NULL,
            ex_date          TEXT,
            gross_amount     DOUBLE PRECISION NOT NULL,
            withholding_tax  DOUBLE PRECISION,
            net_amount       DOUBLE PRECISION,
            currency         TEXT NOT NULL,
            fx_rate_actual   DOUBLE PRECISION,
            note             TEXT,
            voided_at        TEXT,
            created_at       TEXT NOT NULL DEFAULT {_PG_NOW}
        )"""),
    ("manual_valuations", f"""
        CREATE TABLE IF NOT EXISTS manual_valuations (
            valuation_id     SERIAL PRIMARY KEY,
            position_id      INTEGER NOT NULL REFERENCES positions(position_id),
            kind             TEXT NOT NULL CHECK (kind IN ('MARKET','BUYBACK')),
            price_per_unit   DOUBLE PRECISION NOT NULL,
            currency         TEXT NOT NULL,
            valuation_date   TEXT NOT NULL,
            note             TEXT,
            voided_at        TEXT,
            created_at       TEXT NOT NULL DEFAULT {_PG_NOW}
        )"""),
)

PG_BACKUP_TABLE = f"""
CREATE TABLE IF NOT EXISTS portfolio_backups (
    backup_id   SERIAL PRIMARY KEY,
    created_at  TEXT NOT NULL DEFAULT {_PG_NOW},
    reason      TEXT NOT NULL,
    row_counts  TEXT NOT NULL,
    payload     TEXT NOT NULL
)"""

# Tabele z danymi użytkowników objęte kopią zapasową (cache rynkowy jest
# odtwarzalny, więc pomijany).
BACKUP_TABLES = (
    "users", "positions", "purchase_transactions", "sale_transactions",
    "user_decisions", "purchase_thesis", "holding_user_actions",
    "dividend_receipts", "manual_valuations",
)

# Kolumny pozycji, które wolno zmieniać przez `update_position_fields`
# (Faza 11) -- jawna lista, nazwy kolumn nigdy nie pochodzą z wejścia.
POSITION_EXTRA_FIELDS = (
    "isin", "quote_currency", "price_provider", "price_symbol", "asset_class",
    "metal", "product_form", "unit_weight", "weight_unit", "fineness",
    "storage_location", "is_collectible", "exposure_type", "annual_fee_pct",
)


# Dozwolone platformy (Decyzja właścicielki 2026-10-19: + Cashify, Gold
# Saver, Mennica Skarbowa). Tabele utworzone wcześniej mają ograniczenie
# CHECK ze starą listą -- `init_schema` wymienia je (po kopii zapasowej).
BROKER_CODES = ("TRADE_REPUBLIC", "REVOLUT", "CASHIFY", "GOLD_SAVER", "MENNICA_SKARBOWA", "OTHER")
_BROKER_TABLES = ("purchase_transactions", "sale_transactions", "dividend_receipts")


def _outdated_broker_checks(cur) -> list[tuple[str, str]]:
    """(tabela, nazwa ograniczenia) dla CHECK-ów `broker` bez nowych platform."""
    cur.execute(
        """
        SELECT c.conrelid::regclass::text AS table_name, c.conname, pg_get_constraintdef(c.oid) AS definition
        FROM pg_constraint c
        WHERE c.contype = 'c' AND c.conrelid::regclass::text = ANY(%s)
          AND pg_get_constraintdef(c.oid) ILIKE '%%broker%%'
        """,
        (list(_BROKER_TABLES),),
    )
    return [
        (r["table_name"], r["conname"]) for r in cur.fetchall()
        if not all(code in r["definition"] for code in BROKER_CODES)
    ]


class BackupVerificationError(RuntimeError):
    """Kopia zapasowa nie zgadza się z danymi -- migracja NIE jest
    wykonywana (Decyzja właścicielki: migracja wyłącznie po
    zweryfikowanym backupie)."""


def resolve_database_url() -> str:
    """Czyta connection string WYŁĄCZNIE ze zmiennej środowiskowej --
    nigdy z pliku w repo. Ten sam wzorzec co `DataProviderConfig.
    resolve_api_key` w `config.py`."""
    url = os.environ.get(SUPABASE_DB_URL_ENV_VAR)
    if not url:
        raise RuntimeError(
            f"Brak zmiennej środowiskowej '{SUPABASE_DB_URL_ENV_VAR}' z connection "
            "stringiem do Postgresa. Ustaw ją lokalnie (.env, niecommitowany) albo "
            "jako Secret w Streamlit Community Cloud / GitHub Actions."
        )
    return url


def connect(database_url: str | None = None):
    """Zwraca otwarte połączenie psycopg2 z `RealDictCursor` jako
    domyślnym kursorem (`row["pole"]` działa identycznie jak
    `sqlite3.Row`). `database_url=None` -> czyta `SUPABASE_DB_URL`.

    Błąd połączenia (w tym spauzowany darmowy projekt Supabase --
    Decyzja właścicielki pkt 3) jest opakowywany w `PgStoreUnavailableError`,
    NIGDY nie próbuje automatycznie tworzyć/naprawiać bazy."""
    url = database_url if database_url is not None else resolve_database_url()
    try:
        conn = psycopg2.connect(url, cursor_factory=psycopg2.extras.RealDictCursor)
    except psycopg2.OperationalError as exc:
        raise PgStoreUnavailableError(
            f"Baza Postgres nieosiągalna (możliwe, że darmowy projekt Supabase jest "
            f"spauzowany -- wznów go ręcznie w dashboardzie Supabase). Oryginalny błąd: {exc}"
        ) from exc
    return conn


def _existing_schema(cur) -> tuple[set[str], set[tuple[str, str]]]:
    cur.execute(
        "SELECT table_name, column_name FROM information_schema.columns "
        "WHERE table_schema = current_schema()"
    )
    columns = {(r["table_name"], r["column_name"]) for r in cur.fetchall()}
    return {t for t, _ in columns}, columns


def backup_payload(conn) -> tuple[dict[str, list[dict]], dict[str, int]]:
    """Pełna zawartość tabel użytkowników (`BACKUP_TABLES`, tylko
    istniejące) + liczba wierszy per tabela."""
    with conn.cursor() as cur:
        tables, _ = _existing_schema(cur)
        payload: dict[str, list[dict]] = {}
        for table in BACKUP_TABLES:
            if table in tables:
                cur.execute(f"SELECT * FROM {table}")
                payload[table] = [dict(r) for r in cur.fetchall()]
    return payload, {t: len(rows) for t, rows in payload.items()}


def create_verified_backup(conn, reason: str) -> int:
    """Faza 11: zapisuje kopię wszystkich danych użytkowników do
    `portfolio_backups` i WERYFIKUJE ją (odczyt z bazy, liczba wierszy
    per tabela == liczba wierszy w tabelach źródłowych). Niezgodność ->
    `BackupVerificationError` i rollback; wołający nie migruje."""
    payload, counts = backup_payload(conn)
    with conn.cursor() as cur:
        cur.execute(PG_BACKUP_TABLE)
        cur.execute(
            "INSERT INTO portfolio_backups (reason, row_counts, payload) VALUES (%s, %s, %s) RETURNING backup_id",
            (reason, json.dumps(counts), json.dumps(payload, default=str)),
        )
        backup_id = cur.fetchone()["backup_id"]
        cur.execute("SELECT payload FROM portfolio_backups WHERE backup_id = %s", (backup_id,))
        stored = json.loads(cur.fetchone()["payload"])
        for table, count in counts.items():
            cur.execute(f"SELECT count(*) AS n FROM {table}")
            if cur.fetchone()["n"] != count or len(stored.get(table, [])) != count:
                conn.rollback()
                raise BackupVerificationError(f"Kopia zapasowa niezgodna dla tabeli {table}.")
    conn.commit()
    return backup_id


def get_latest_backup_info(conn):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT backup_id, created_at, reason, row_counts FROM portfolio_backups "
            "ORDER BY backup_id DESC LIMIT 1"
        )
        return cur.fetchone()


def init_schema(conn) -> None:
    """Idempotentne -- bezpieczne do wywołania na już istniejącej bazie z
    danymi, nigdy nie kasuje/nadpisuje istniejących wierszy. Faza 11:
    jeśli brakuje jakiejkolwiek nowej tabeli/kolumny, NAJPIERW powstaje
    zweryfikowana kopia zapasowa (`create_verified_backup`), dopiero
    potem migracja (wyłącznie CREATE TABLE / ADD COLUMN)."""
    with conn.cursor() as cur:
        cur.execute(PG_SCHEMA)
        cur.execute(PG_BACKUP_TABLE)
        tables, columns = _existing_schema(cur)
        outdated_checks = _outdated_broker_checks(cur)
    conn.commit()
    pending = [name for name, _ in PG_NEW_TABLES if name not in tables]
    pending += [f"{t}.{c}" for t, c, _ in PG_COLUMN_MIGRATIONS if (t, c) not in columns]
    pending += [f"{t}: lista platform" for t, _ in outdated_checks]
    if not pending:
        return
    create_verified_backup(conn, reason="przed migracją: " + ", ".join(pending))
    allowed = ", ".join(f"'{code}'" for code in BROKER_CODES)
    with conn.cursor() as cur:
        for name, ddl in PG_NEW_TABLES:
            if name not in tables:
                cur.execute(ddl)
        for table, column, coltype in PG_COLUMN_MIGRATIONS:
            if (table, column) not in columns:
                cur.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {coltype}")
        for table, constraint in outdated_checks:
            # Nowa lista jest nadzbiorem starej -- istniejące wiersze ją spełniają.
            cur.execute(f'ALTER TABLE {table} DROP CONSTRAINT IF EXISTS "{constraint}"')
            cur.execute(f"ALTER TABLE {table} ADD CONSTRAINT {table}_broker_check CHECK (broker IN ({allowed}))")
    conn.commit()


# ---------------------------------------------------------------------------
# CRUD -- dokładnie te same nazwy/sygnatury/semantyka co odpowiadające
# funkcje w `db.py` (sekcja Faza 7), tylko inny silnik pod spodem.
# ---------------------------------------------------------------------------


def create_user(conn, display_name: str) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO users (display_name) VALUES (%s) RETURNING user_id",
            (display_name,),
        )
        return cur.fetchone()["user_id"]


def get_users(conn) -> list:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM users ORDER BY user_id")
        return cur.fetchall()


def insert_user_decision(
    conn, *, user_id: int, cik: str, status: str,
    analysis_id: int | None = None, note: str | None = None,
) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO user_decisions (user_id, cik, analysis_id, status, note)
            VALUES (%s, %s, %s, %s, %s) RETURNING decision_id
            """,
            (user_id, cik, analysis_id, status, note),
        )
        return cur.fetchone()["decision_id"]


def get_latest_user_decision(conn, *, user_id: int, cik: str):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT * FROM user_decisions WHERE user_id = %s AND cik = %s
            ORDER BY decision_id DESC LIMIT 1
            """,
            (user_id, cik),
        )
        return cur.fetchone()


def get_latest_user_decisions_for_user(conn, user_id: int) -> dict:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT ud.* FROM user_decisions ud
            WHERE ud.user_id = %s AND ud.decision_id = (
                SELECT MAX(decision_id) FROM user_decisions
                WHERE user_id = ud.user_id AND cik = ud.cik
            )
            """,
            (user_id,),
        )
        rows = cur.fetchall()
    return {r["cik"]: r for r in rows}


def insert_position(
    conn, *, user_id: int, ticker: str, company_name: str,
    cik: str | None = None, exchange: str | None = None,
    instrument_currency: str | None = None, instrument_confirmed: bool = False,
) -> int:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO positions (
                user_id, cik, ticker, company_name, exchange, instrument_currency, instrument_confirmed_at
            ) VALUES (%s, %s, %s, %s, %s, %s, CASE WHEN %s THEN {_PG_NOW} END) RETURNING position_id
            """,
            (user_id, cik, ticker, company_name, exchange, instrument_currency, instrument_confirmed),
        )
        return cur.fetchone()["position_id"]


def update_position_instrument(
    conn, *, position_id: int, ticker: str, company_name: str,
    cik: str | None, exchange: str | None, instrument_confirmed: bool,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE positions SET ticker = %s, company_name = %s, cik = %s, exchange = %s,
                instrument_confirmed_at = CASE WHEN %s THEN {_PG_NOW} END,
                updated_at = {_PG_NOW}
            WHERE position_id = %s
            """,
            (ticker, company_name, cik, exchange, instrument_confirmed, position_id),
        )


def void_position(conn, position_id: int) -> None:
    with conn.cursor() as cur:
        cur.execute(
            f"UPDATE positions SET voided_at = {_PG_NOW}, updated_at = {_PG_NOW} "
            "WHERE position_id = %s AND voided_at IS NULL",
            (position_id,),
        )


def get_positions_for_user(conn, user_id: int) -> list:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM positions WHERE user_id = %s AND voided_at IS NULL ORDER BY created_at", (user_id,),
        )
        return cur.fetchall()


def get_position(conn, position_id: int):
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM positions WHERE position_id = %s", (position_id,))
        return cur.fetchone()


def insert_purchase_transaction(
    conn, *, position_id: int, broker: str, acquisition_type: str, purchase_date: str,
    shares: float, total_invested: float, currency: str,
    price_per_share: float | None = None, fees: float | None = None, note: str | None = None,
) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO purchase_transactions (
                position_id, broker, acquisition_type, purchase_date, shares,
                price_per_share, total_invested, currency, fees, note
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING transaction_id
            """,
            (
                position_id, broker, acquisition_type, purchase_date, shares,
                price_per_share, total_invested, currency, fees, note,
            ),
        )
        return cur.fetchone()["transaction_id"]


def get_purchase_transactions(conn, position_id: int) -> list:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT * FROM purchase_transactions
            WHERE position_id = %s AND voided_at IS NULL AND superseded_by IS NULL
            ORDER BY purchase_date
            """,
            (position_id,),
        )
        return cur.fetchall()


def void_purchase_transaction(conn, transaction_id: int, reason: str | None = None) -> None:
    with conn.cursor() as cur:
        cur.execute(
            f"UPDATE purchase_transactions SET voided_at = {_PG_NOW}, void_reason = %s "
            "WHERE transaction_id = %s AND voided_at IS NULL",
            (reason, transaction_id),
        )


def insert_sale_transaction(
    conn, *, position_id: int, broker: str, sale_date: str, shares: float,
    sale_price: float, currency: str, fees: float | None = None, note: str | None = None,
) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO sale_transactions (
                position_id, broker, sale_date, shares, sale_price, currency, fees, note
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING transaction_id
            """,
            (position_id, broker, sale_date, shares, sale_price, currency, fees, note),
        )
        return cur.fetchone()["transaction_id"]


def get_sale_transactions(conn, position_id: int) -> list:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT * FROM sale_transactions
            WHERE position_id = %s AND voided_at IS NULL AND superseded_by IS NULL
            ORDER BY sale_date
            """,
            (position_id,),
        )
        return cur.fetchall()


def void_sale_transaction(conn, transaction_id: int, reason: str | None = None) -> None:
    with conn.cursor() as cur:
        cur.execute(
            f"UPDATE sale_transactions SET voided_at = {_PG_NOW}, void_reason = %s "
            "WHERE transaction_id = %s AND voided_at IS NULL",
            (reason, transaction_id),
        )


def insert_purchase_thesis(
    conn, *, position_id: int, analysis_id: int | None = None, snapshot_json: str | None = None,
) -> int:
    """`position_id` UNIQUE -- druga teza dla tej samej pozycji rzuci
    `psycopg2.errors.UniqueViolation` (odpowiednik `sqlite3.
    IntegrityError` w `db.py`)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO purchase_thesis (position_id, analysis_id, snapshot_json)
            VALUES (%s, %s, %s) RETURNING thesis_id
            """,
            (position_id, analysis_id, snapshot_json),
        )
        return cur.fetchone()["thesis_id"]


def get_purchase_thesis(conn, position_id: int):
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM purchase_thesis WHERE position_id = %s", (position_id,))
        return cur.fetchone()


def insert_holding_user_action(conn, *, position_id: int, action: str, note: str | None = None) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO holding_user_actions (position_id, action, note) VALUES (%s, %s, %s) "
            "RETURNING action_id",
            (position_id, action, note),
        )
        return cur.fetchone()["action_id"]


def get_latest_holding_user_action(conn, position_id: int):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT * FROM holding_user_actions WHERE position_id = %s
            ORDER BY action_id DESC LIMIT 1
            """,
            (position_id,),
        )
        return cur.fetchone()


# ---------------------------------------------------------------------------
# Faza 11 (P0b-P4)
# ---------------------------------------------------------------------------


def update_position_fields(conn, position_id: int, **fields) -> None:
    """Zmienia wyłącznie kolumny z `POSITION_EXTRA_FIELDS`."""
    unknown = set(fields) - set(POSITION_EXTRA_FIELDS)
    if unknown:
        raise ValueError(f"Niedozwolone pola pozycji: {sorted(unknown)}")
    if not fields:
        return
    assignments = ", ".join(f"{name} = %s" for name in fields)
    with conn.cursor() as cur:
        cur.execute(
            f"UPDATE positions SET {assignments}, updated_at = {_PG_NOW} WHERE position_id = %s",
            (*fields.values(), position_id),
        )


def set_transaction_fx_rate(conn, *, kind: str, transaction_id: int, fx_rate_actual: float | None) -> None:
    """Kurs rzeczywisty brokera (PLN za 1 jednostkę waluty transakcji).
    Uzupełnienie danych, nie zmiana transakcji: kwoty, daty i waluta
    zostają nietknięte."""
    table = {"PURCHASE": "purchase_transactions", "SALE": "sale_transactions"}[kind]
    with conn.cursor() as cur:
        cur.execute(f"UPDATE {table} SET fx_rate_actual = %s WHERE transaction_id = %s", (fx_rate_actual, transaction_id))


def get_cache_entry(conn, cache_key: str):
    with conn.cursor() as cur:
        cur.execute("SELECT payload, fetched_at FROM market_data_cache WHERE cache_key = %s", (cache_key,))
        return cur.fetchone()


def put_cache_entry(conn, cache_key: str, payload: str, fetched_at: str) -> None:
    """`fetched_at` (UTC "YYYY-MM-DD HH:MM:SS") podaje wołający -- ten sam
    zegar, którym potem liczy wiek wpisu."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO market_data_cache (cache_key, payload, fetched_at) VALUES (%s, %s, %s)
            ON CONFLICT (cache_key) DO UPDATE SET payload = EXCLUDED.payload, fetched_at = EXCLUDED.fetched_at
            """,
            (cache_key, payload, fetched_at),
        )


def insert_dividend_receipt(
    conn, *, position_id: int, broker: str, pay_date: str, gross_amount: float, currency: str,
    ex_date: str | None = None, withholding_tax: float | None = None, net_amount: float | None = None,
    fx_rate_actual: float | None = None, note: str | None = None,
) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO dividend_receipts (
                position_id, broker, pay_date, ex_date, gross_amount, withholding_tax,
                net_amount, currency, fx_rate_actual, note
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING receipt_id
            """,
            (position_id, broker, pay_date, ex_date, gross_amount, withholding_tax,
             net_amount, currency, fx_rate_actual, note),
        )
        return cur.fetchone()["receipt_id"]


def get_dividend_receipts(conn, position_id: int) -> list:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM dividend_receipts WHERE position_id = %s AND voided_at IS NULL ORDER BY pay_date",
            (position_id,),
        )
        return cur.fetchall()


def void_dividend_receipt(conn, receipt_id: int) -> None:
    with conn.cursor() as cur:
        cur.execute(
            f"UPDATE dividend_receipts SET voided_at = {_PG_NOW} WHERE receipt_id = %s AND voided_at IS NULL",
            (receipt_id,),
        )


def insert_manual_valuation(
    conn, *, position_id: int, kind: str, price_per_unit: float, currency: str,
    valuation_date: str, note: str | None = None,
) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO manual_valuations (position_id, kind, price_per_unit, currency, valuation_date, note)
            VALUES (%s, %s, %s, %s, %s, %s) RETURNING valuation_id
            """,
            (position_id, kind, price_per_unit, currency, valuation_date, note),
        )
        return cur.fetchone()["valuation_id"]


def get_latest_manual_valuation(conn, position_id: int, kind: str):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT * FROM manual_valuations WHERE position_id = %s AND kind = %s AND voided_at IS NULL
            ORDER BY valuation_date DESC, valuation_id DESC LIMIT 1
            """,
            (position_id, kind),
        )
        return cur.fetchone()

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
    broker            TEXT NOT NULL CHECK (broker IN ('TRADE_REPUBLIC','REVOLUT','OTHER')),
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
    broker          TEXT NOT NULL CHECK (broker IN ('TRADE_REPUBLIC','REVOLUT','OTHER')),
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


def init_schema(conn) -> None:
    """Idempotentne (`CREATE TABLE IF NOT EXISTS`) -- bezpieczne do
    wywołania na już istniejącej bazie z danymi, nigdy nie kasuje/
    nadpisuje istniejących wierszy (ten sam wzorzec co `db.init_db`)."""
    with conn.cursor() as cur:
        cur.execute(PG_SCHEMA)
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
    instrument_currency: str | None = None,
) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO positions (user_id, cik, ticker, company_name, exchange, instrument_currency)
            VALUES (%s, %s, %s, %s, %s, %s) RETURNING position_id
            """,
            (user_id, cik, ticker, company_name, exchange, instrument_currency),
        )
        return cur.fetchone()["position_id"]


def get_positions_for_user(conn, user_id: int) -> list:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM positions WHERE user_id = %s ORDER BY created_at", (user_id,))
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
            "SELECT * FROM purchase_transactions WHERE position_id = %s ORDER BY purchase_date",
            (position_id,),
        )
        return cur.fetchall()


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
            "SELECT * FROM sale_transactions WHERE position_id = %s ORDER BY sale_date",
            (position_id,),
        )
        return cur.fetchall()


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

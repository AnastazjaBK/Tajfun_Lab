"""Testy warstwy trwałości Postgres (Faza 7 "Hostowany V0", Etap A).

Integracyjne -- wymagają prawdziwego Postgresa (zmienna `TEST_POSTGRES_URL`,
CELOWO inna niż produkcyjna `SUPABASE_DB_URL` -- żeby pytest nigdy
przypadkiem nie dotknął prawdziwej bazy Supabase, nawet gdyby ta
zmienna była gdzieś ustawiona w środowisku). Pomijane domyślnie (ten
sam wzorzec co `test_fmp_client.py::test_live_smoke_sp500_constituents_shape`).

Każdy test dostaje CZYSTE tabele (TRUNCATE ... CASCADE przed testem) --
izolacja bez polegania na transakcjach (łatwiejsze do zrozumienia,
ten sam styl co `tests/test_db.py` z osobnym `tmp_path` per test)."""

from __future__ import annotations

import os

import pytest

psycopg2 = pytest.importorskip("psycopg2")

from buffett_scanner import pg_store  # noqa: E402

TEST_POSTGRES_URL_ENV_VAR = "TEST_POSTGRES_URL"

_TABLES_IN_FK_SAFE_TRUNCATE_ORDER = (
    "holding_user_actions", "purchase_thesis", "sale_transactions",
    "purchase_transactions", "positions", "user_decisions", "users",
)


@pytest.fixture
def conn():
    url = os.environ.get(TEST_POSTGRES_URL_ENV_VAR)
    if not url:
        pytest.skip(f"Brak {TEST_POSTGRES_URL_ENV_VAR} -- pomijam testy integracyjne Postgresa.")
    connection = pg_store.connect(database_url=url)
    pg_store.init_schema(connection)
    with connection.cursor() as cur:
        cur.execute("TRUNCATE " + ", ".join(_TABLES_IN_FK_SAFE_TRUNCATE_ORDER) + " RESTART IDENTITY CASCADE")
    connection.commit()
    yield connection
    connection.close()


@pytest.mark.integration
def test_init_schema_is_idempotent(conn):
    pg_store.init_schema(conn)  # drugie wywołanie nie powinno rzucić błędu
    pg_store.init_schema(conn)


@pytest.mark.integration
def test_create_user_and_get_users_orders_by_id(conn):
    uid_a = pg_store.create_user(conn, "Anastazja")
    uid_b = pg_store.create_user(conn, "Mąż")
    conn.commit()
    users = pg_store.get_users(conn)
    assert [u["user_id"] for u in users] == sorted([uid_a, uid_b])
    assert [u["display_name"] for u in users] == ["Anastazja", "Mąż"]


@pytest.mark.integration
def test_insert_position_with_nullable_cik_schneider_electric_style(conn):
    """Test KLUCZOWY (Decyzja właścicielki, Faza 7 pkt 5): `cik` musi
    pozostać NULLABLE w Postgresie tak samo jak w SQLite -- portfel
    NIE jest ograniczony do spółek z CIK (np. Schneider Electric,
    Euronext Paris)."""
    user_id = pg_store.create_user(conn, "Anastazja")
    position_id = pg_store.insert_position(
        conn, user_id=user_id, ticker="SU.PA", company_name="Schneider Electric S.E.",
        cik=None, exchange="PAR", instrument_currency="EUR",
    )
    conn.commit()
    position = pg_store.get_position(conn, position_id)
    assert position["cik"] is None
    assert position["ticker"] == "SU.PA"
    assert position["instrument_currency"] == "EUR"


@pytest.mark.integration
def test_purchase_transaction_bonus_zero_invested_and_nullable_price(conn):
    user_id = pg_store.create_user(conn, "Anastazja")
    position_id = pg_store.insert_position(
        conn, user_id=user_id, ticker="AAPL", company_name="Apple Inc.",
    )
    pg_store.insert_purchase_transaction(
        conn, position_id=position_id, broker="TRADE_REPUBLIC", acquisition_type="BONUS",
        purchase_date="2026-05-01", shares=3.0, total_invested=0.0, currency="USD",
    )
    conn.commit()
    rows = pg_store.get_purchase_transactions(conn, position_id)
    assert len(rows) == 1
    assert rows[0]["total_invested"] == 0.0
    assert rows[0]["price_per_share"] is None
    assert rows[0]["acquisition_type"] == "BONUS"


@pytest.mark.integration
def test_purchase_transaction_check_constraint_rejects_invalid_broker(conn):
    """Test KLUCZOWY: CHECK constraint musi działać identycznie jak w
    SQLite -- zły `broker` nie może trafić do bazy."""
    user_id = pg_store.create_user(conn, "Anastazja")
    position_id = pg_store.insert_position(
        conn, user_id=user_id, ticker="AAPL", company_name="Apple Inc.",
    )
    conn.commit()
    with pytest.raises(psycopg2.errors.CheckViolation):
        pg_store.insert_purchase_transaction(
            conn, position_id=position_id, broker="XTB", acquisition_type="BUY",
            purchase_date="2026-05-01", shares=1.0, total_invested=100.0, currency="USD",
        )
    conn.rollback()


@pytest.mark.integration
def test_sale_transaction_insert_and_get(conn):
    user_id = pg_store.create_user(conn, "Anastazja")
    position_id = pg_store.insert_position(
        conn, user_id=user_id, ticker="AAPL", company_name="Apple Inc.",
    )
    pg_store.insert_sale_transaction(
        conn, position_id=position_id, broker="REVOLUT", sale_date="2026-07-01",
        shares=2.0, sale_price=250.0, currency="USD",
    )
    conn.commit()
    rows = pg_store.get_sale_transactions(conn, position_id)
    assert len(rows) == 1
    assert rows[0]["sale_price"] == 250.0
    assert rows[0]["broker"] == "REVOLUT"


@pytest.mark.integration
def test_user_decision_append_only_latest_wins(conn):
    """Append-only -- korekta decyzji to nowy wiersz, `get_latest_
    user_decision` czyta najnowszy po `decision_id`, nie nadpisuje."""
    user_id = pg_store.create_user(conn, "Anastazja")
    pg_store.insert_user_decision(conn, user_id=user_id, cik="0000320193", status="WATCH")
    pg_store.insert_user_decision(conn, user_id=user_id, cik="0000320193", status="REJECT")
    conn.commit()
    latest = pg_store.get_latest_user_decision(conn, user_id=user_id, cik="0000320193")
    assert latest["status"] == "REJECT"
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM user_decisions WHERE user_id = %s", (user_id,))
        assert cur.fetchone()["n"] == 2  # obie decyzje zachowane, nic nie nadpisane


@pytest.mark.integration
def test_get_latest_user_decisions_for_user_groups_by_cik(conn):
    user_id = pg_store.create_user(conn, "Anastazja")
    pg_store.insert_user_decision(conn, user_id=user_id, cik="AAPL_CIK", status="WATCH")
    pg_store.insert_user_decision(conn, user_id=user_id, cik="AAPL_CIK", status="BOUGHT")
    pg_store.insert_user_decision(conn, user_id=user_id, cik="GSK_CIK", status="REJECT")
    conn.commit()
    latest_by_cik = pg_store.get_latest_user_decisions_for_user(conn, user_id)
    assert latest_by_cik["AAPL_CIK"]["status"] == "BOUGHT"
    assert latest_by_cik["GSK_CIK"]["status"] == "REJECT"


@pytest.mark.integration
def test_user_decisions_isolated_between_users(conn):
    """Test KLUCZOWY (sekcja 16 specyfikacji UI): Anastazja i mąż mogą
    mieć RÓŻNY status dla tej samej spółki."""
    uid_a = pg_store.create_user(conn, "Anastazja")
    uid_b = pg_store.create_user(conn, "Mąż")
    pg_store.insert_user_decision(conn, user_id=uid_a, cik="AAPL_CIK", status="WATCH")
    pg_store.insert_user_decision(conn, user_id=uid_b, cik="AAPL_CIK", status="REJECT")
    conn.commit()
    assert pg_store.get_latest_user_decision(conn, user_id=uid_a, cik="AAPL_CIK")["status"] == "WATCH"
    assert pg_store.get_latest_user_decision(conn, user_id=uid_b, cik="AAPL_CIK")["status"] == "REJECT"


@pytest.mark.integration
def test_purchase_thesis_unique_constraint_rejects_second_thesis(conn):
    user_id = pg_store.create_user(conn, "Anastazja")
    position_id = pg_store.insert_position(
        conn, user_id=user_id, ticker="AAPL", company_name="Apple Inc.",
    )
    pg_store.insert_purchase_thesis(conn, position_id=position_id, snapshot_json='{"bull_case": []}')
    conn.commit()
    with pytest.raises(psycopg2.errors.UniqueViolation):
        pg_store.insert_purchase_thesis(conn, position_id=position_id, snapshot_json='{}')
    conn.rollback()


@pytest.mark.integration
def test_holding_user_action_append_only_latest_wins(conn):
    user_id = pg_store.create_user(conn, "Anastazja")
    position_id = pg_store.insert_position(
        conn, user_id=user_id, ticker="AAPL", company_name="Apple Inc.",
    )
    pg_store.insert_holding_user_action(conn, position_id=position_id, action="HOLD")
    pg_store.insert_holding_user_action(conn, position_id=position_id, action="REVIEW_LATER")
    conn.commit()
    latest = pg_store.get_latest_holding_user_action(conn, position_id)
    assert latest["action"] == "REVIEW_LATER"


@pytest.mark.integration
def test_positions_isolated_between_users(conn):
    uid_a = pg_store.create_user(conn, "Anastazja")
    uid_b = pg_store.create_user(conn, "Mąż")
    pg_store.insert_position(conn, user_id=uid_a, ticker="AAPL", company_name="Apple Inc.")
    pg_store.insert_position(conn, user_id=uid_b, ticker="GSK", company_name="GSK plc")
    conn.commit()
    assert [p["ticker"] for p in pg_store.get_positions_for_user(conn, uid_a)] == ["AAPL"]
    assert [p["ticker"] for p in pg_store.get_positions_for_user(conn, uid_b)] == ["GSK"]


@pytest.mark.integration
def test_rows_from_postgres_work_unchanged_with_ui_portfolio_pure_functions(conn):
    """Test INTEGRACYJNY KLUCZOWY: dowód, że `ui/portfolio.py`
    (compute_broker_currency_subpositions/compute_position_summary) --
    zupełnie niezmieniony kod -- poprawnie liczy pozycję na wierszach
    ZWRÓCONYCH PRZEZ POSTGRES (RealDictCursor), nie tylko na
    `sqlite3.Row`. To jest cały sens tego, że te funkcje operują na
    zwykłych słownikach/`[...]`, nie na obiekcie konkretnego silnika."""
    from buffett_scanner.ui.portfolio import compute_position_summary

    user_id = pg_store.create_user(conn, "Anastazja")
    position_id = pg_store.insert_position(
        conn, user_id=user_id, ticker="AAPL", company_name="Apple Inc.",
    )
    pg_store.insert_purchase_transaction(
        conn, position_id=position_id, broker="TRADE_REPUBLIC", acquisition_type="BONUS",
        purchase_date="2026-05-01", shares=3.0, total_invested=0.0, currency="USD",
    )
    pg_store.insert_purchase_transaction(
        conn, position_id=position_id, broker="REVOLUT", acquisition_type="BUY",
        purchase_date="2026-06-01", shares=2.0, total_invested=380.0, currency="USD",
    )
    conn.commit()

    purchases = pg_store.get_purchase_transactions(conn, position_id)
    sales = pg_store.get_sale_transactions(conn, position_id)
    summary = compute_position_summary(
        position_id, purchases, sales, current_price=230.0, current_price_currency="USD",
    )
    assert summary.shares_held == 5.0
    assert summary.invested_by_currency == {"USD": 380.0}
    assert summary.current_value_by_currency == {"USD": pytest.approx(1150.0)}  # 5 * 230


def test_resolve_database_url_raises_clear_error_without_env_var(monkeypatch):
    """NIE oznaczony @integration -- nie wymaga działającego Postgresa."""
    monkeypatch.delenv(pg_store.SUPABASE_DB_URL_ENV_VAR, raising=False)
    with pytest.raises(RuntimeError, match=pg_store.SUPABASE_DB_URL_ENV_VAR):
        pg_store.resolve_database_url()


def test_connect_wraps_unreachable_host_as_pg_store_unavailable_error():
    """NIE oznaczony @integration -- nie wymaga działającego Postgresa,
    bo celowo łączy się z adresem, który nigdy nie odpowie. Dowodzi
    (Decyzja właścicielki pkt 3): błąd połączenia (np. spauzowany
    projekt Supabase) jest opakowany w jeden, nazwany, łatwy do
    złapania wyjątek -- nigdy goły traceback psycopg2."""
    bad_url = "postgresql://user:pass@127.0.0.1:1/nonexistent?connect_timeout=1"
    with pytest.raises(pg_store.PgStoreUnavailableError):
        pg_store.connect(database_url=bad_url)

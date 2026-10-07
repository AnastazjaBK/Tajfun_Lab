"""Wybór silnika dla 7 tabel user-generated (Faza 8 "Hostowany V0",
Etap D): SQLite (`db.py`, tryb lokalny/dev, domyślny) albo Postgres
(`pg_store.py`, tryb hostowany), sterowany WYŁĄCZNIE obecnością
zmiennej środowiskowej `SUPABASE_DB_URL` w momencie importu tego
modułu.

`db.py` i `pg_store.py` mają DOKŁADNIE te same nazwy/sygnatury funkcji
CRUD dla tych 7 tabel (Etap A) -- to jest WYŁĄCZNIE przełączenie, SKĄD
importujemy, zero zmian logiki w wołających (`app.py`, `ui/queries.py`).

`SUPABASE_DB_URL` jest ustawiane RAZ na starcie procesu (przez
hosting/shell) i nie zmienia się w trakcie jego życia -- wybór
backendu PONIŻEJ jest więc celowo wykonywany RAZ, przy pierwszym
imporcie tego modułu, nie przy każdym wywołaniu. Testy, które chcą
sprawdzić oba warianty w jednej sesji pytest, używają
`importlib.reload(portfolio_backend)` po `monkeypatch.setenv`/`delenv`."""

from __future__ import annotations

import os

SUPABASE_DB_URL_ENV_VAR = "SUPABASE_DB_URL"


def is_hosted() -> bool:
    return bool(os.environ.get(SUPABASE_DB_URL_ENV_VAR))


HOSTED = is_hosted()

if HOSTED:
    from buffett_scanner.pg_store import (
        create_user,
        get_latest_holding_user_action,
        get_latest_user_decision,
        get_latest_user_decisions_for_user,
        get_position,
        get_positions_for_user,
        get_purchase_thesis,
        get_purchase_transactions,
        get_sale_transactions,
        get_users,
        insert_holding_user_action,
        insert_position,
        insert_purchase_thesis,
        insert_purchase_transaction,
        insert_sale_transaction,
        insert_user_decision,
    )
else:
    from buffett_scanner.db import (
        create_user,
        get_latest_holding_user_action,
        get_latest_user_decision,
        get_latest_user_decisions_for_user,
        get_position,
        get_positions_for_user,
        get_purchase_thesis,
        get_purchase_transactions,
        get_sale_transactions,
        get_users,
        insert_holding_user_action,
        insert_position,
        insert_purchase_thesis,
        insert_purchase_transaction,
        insert_sale_transaction,
        insert_user_decision,
    )


def connect_portfolio(sqlite_db_path: str | None = None):
    """Zwraca otwarte połączenie do silnika portfela wybranego przy
    imporcie tego modułu (patrz `HOSTED`).

    `sqlite_db_path` jest używany WYŁĄCZNIE w trybie lokalnym (ten sam
    plik, co dane scannera -- dokładnie jak w Fazie 7, zero zmian w
    tym trybie) -- w trybie hostowanym jest ignorowany, Postgres nie
    jest plikiem. W trybie hostowanym baza nieosiągalna (np. spauzowany
    darmowy projekt Supabase) rzuca `pg_store.PgStoreUnavailableError`
    -- wołający (`app.py`) łapie ten jeden, nazwany typ i pokazuje
    czytelny komunikat, NIGDY nie próbuje automatycznie tworzyć/
    naprawiać bazy (Decyzja właścicielki pkt 3)."""
    if HOSTED:
        from buffett_scanner.pg_store import connect, init_schema
        conn = connect()
        init_schema(conn)
        return conn
    from buffett_scanner.db import init_db
    return init_db(sqlite_db_path)

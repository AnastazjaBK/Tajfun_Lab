"""Warstwa odczytu dla UI (Faza 7, UI + PORTFOLIO V0).

WYŁĄCZNIE SELECT-y (albo proste złożenia kilku istniejących `db.get_*`)
-- zero logiki biznesowej. Liczenie pozycji "on-read" mieszka w
`ui/portfolio.py` (czyste funkcje, testowalne bez bazy); ten moduł je
tylko zasila realnymi danymi z SQLite.

WYBÓR "OSTATNIEGO WŁAŚCIWEGO SKANU" (Decyzja właścicielki, Faza 7 pkt 1):
`run_id LIKE 'live-scan-%'`, z ignorowaniem `validation-*` (jednorazowe
techniczne walidacje kontraktu LLM, Fazy 6f/6g/6h -- NIE są kolejnym
skanem rynku). To jest konwencja nazewnictwa `run_id`, nie kolumna w
bazie -- `run_type` NIE jest dodawany tylko na potrzeby UI (decyzja
właścicielki, pkt 1: "Nie dodawaj teraz run_type tylko na potrzeby UI").
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import replace

from buffett_scanner.analysis_schema import AnalysisOutput
from buffett_scanner.config import load_config
from buffett_scanner import portfolio_backend
from buffett_scanner.db import (
    get_analysis,
    get_analysis_sources,
    get_fundamentals_periods,
    get_price_series,
)
from buffett_scanner.portfolio_backend import (
    get_latest_holding_user_action,
    get_positions_for_user,
    get_purchase_transactions,
    get_sale_transactions,
)
from buffett_scanner.scanner import PriceBar, compute_price_changes
from buffett_scanner.ui.portfolio import (
    TRANSACTION_TABLE,
    PositionSummary,
    compute_position_summary,
    find_negative_holding,
    replace_transaction,
)
from buffett_scanner.ui.pricing import FxRates, Quote
from buffett_scanner.valuation import compute_valuation


def get_latest_live_scan_run(scanner_conn: sqlite3.Connection) -> sqlite3.Row | None:
    """Najnowszy PRAWDZIWY live-scan (nigdy diagnostyczny `validation-*`)
    -- Decyzja właścicielki, Faza 7 pkt 1. `created_at` jest jedynym
    monotonicznym znacznikiem czasu w `live_scan_runs` (`run_date` może
    nieść sufiksy diagnostyczne typu `-validation6h`, patrz Faza 6h).
    `scanner_conn` -- w trybie hostowanym (Faza 8) to snapshot SQLite
    pobrany z GitHub Release, zawsze SQLite niezależnie od trybu."""
    return scanner_conn.execute(
        """
        SELECT * FROM live_scan_runs
        WHERE run_id LIKE 'live-scan-%'
        ORDER BY created_at DESC
        LIMIT 1
        """
    ).fetchone()


def get_synthesis_rows(scanner_conn: sqlite3.Connection, run_id: str) -> list[dict]:
    """Jeden wiersz per finalista shortlisty (Decyzja właścicielki, Faza
    7 pkt 2: pokazujemy WSZYSTKICH finalistów niezależnie od
    `llm_status` -- FAILED to status RAPORTU, nie ocena spółki, i nie
    blokuje wyświetlenia deterministycznych danych/wyceny)."""
    rows = scanner_conn.execute(
        """
        SELECT lsc.*, c.name AS company_name
        FROM live_scan_candidates lsc
        JOIN companies c ON c.cik = lsc.cik
        WHERE lsc.run_id = ? AND lsc.in_shortlist = 1
        ORDER BY lsc.rank
        """,
        (run_id,),
    ).fetchall()

    result = []
    for row in rows:
        decline_flags = json.loads(row["decline_flags_json"])
        triggered_flags = [k for k, v in decline_flags.items() if v]

        full_score = None
        margin_of_safety_pct = row["margin_of_safety_base_pct"]  # deterministyczny fallback
        bull_case_first = None
        biggest_risk = None
        if row["analysis_id"] is not None:
            analysis_row = get_analysis(scanner_conn, row["analysis_id"])
            full_score = analysis_row["total_score"]
            if analysis_row["margin_of_safety_pct"] is not None:
                margin_of_safety_pct = analysis_row["margin_of_safety_pct"]
            analysis = AnalysisOutput.model_validate(json.loads(analysis_row["llm_raw_output"]))
            if analysis.bull_case:
                bull_case_first = analysis.bull_case[0]
            if analysis.thesis_invalidation:
                biggest_risk = analysis.thesis_invalidation[0]
            elif analysis.bear_case:
                biggest_risk = analysis.bear_case[0]

        result.append({
            "ticker": row["ticker"],
            "cik": row["cik"],
            "finalist_rank_key": _finalist_rank_key(analysis_row if row["analysis_id"] is not None else None),
            "company_name": row["company_name"],
            "current_price": row["current_price"],
            "triggered_decline_flags": triggered_flags,
            "deterministic_score_pct": row["deterministic_score_pct"],
            "full_score": full_score,
            "margin_of_safety_pct": margin_of_safety_pct,
            "bull_case_first": bull_case_first,
            "biggest_risk": biggest_risk,
            "llm_status": row["llm_status"],
            "llm_error": row["llm_error"],
            "analysis_id": row["analysis_id"],
        })
    for rank, r in enumerate(sorted(
        (r for r in result if r["finalist_rank_key"] is not None), key=lambda r: r["finalist_rank_key"],
    )[:FINALIST_LIMIT], start=1):
        r["finalist_position"] = rank
    for r in result:
        r.setdefault("finalist_position", None)
        r.pop("finalist_rank_key")
    return result


# Faza 11 (P2): finaliści = ta sama reguła co raport live-scanu
# (`live_scan._rank_key` + `rank_candidates(limit=5)`, domyślne
# `--limit 5`): kompletny `total_score` przed PARTIAL, w kategorii wyżej
# lepiej; liczone z ZAPISANYCH wyników analiz, zero przeliczania scoringu.
FINALIST_LIMIT = 5


def _finalist_rank_key(analysis_row) -> tuple[int, float] | None:
    if analysis_row is None:
        return None
    if analysis_row["total_score"] is not None:
        return (0, -analysis_row["total_score"])
    partial = sum(
        analysis_row[k] for k in ("business_quality_score", "safety_score", "fear_score", "dividend_score")
        if analysis_row[k] is not None
    )
    return (1, -partial)


def get_scan_price_rows(scanner_conn: sqlite3.Connection, cik: str) -> list[dict]:
    """Notowania ze snapshotu skanu (Faza 11, P2) -- stan na dzień skanu,
    nigdy podmieniane na dzisiejsze."""
    return [
        {"date": r["date"], "close": r["close"], "volume": r["volume"]}
        for r in get_price_series(scanner_conn, cik)
    ]


def get_current_price_for_position(scanner_conn: sqlite3.Connection, position) -> tuple[float | None, str | None]:
    """Cena bieżąca = ostatni dzienny close z `price_daily` (ten sam
    mechanizm co cały scanner -- EOD, NIE live/intraday). Działa
    WYŁĄCZNIE dla pozycji z ustawionym `cik` (resolved przez FMP przy
    dodawaniu transakcji -- patrz KROK 7) -- `price_daily` nie ma
    kolumny currency, cały istniejący pipeline FMP niejawnie zakłada
    USD dla notowań amerykańskich, więc to samo założenie jest tu
    powtórzone, nie wymyślone na nowo. Pozycja bez `cik` -> (None, None),
    UI pokazuje "cena bieżąca niedostępna", nigdy 0. `position` pochodzi
    z `portfolio_conn` (inny silnik w trybie hostowanym, Faza 8) --
    `price_daily` jest zawsze SQLite (`scanner_conn`)."""
    if position["cik"] is None:
        return None, None
    row = scanner_conn.execute(
        "SELECT close FROM price_daily WHERE cik = ? ORDER BY date DESC LIMIT 1",
        (position["cik"],),
    ).fetchone()
    if row is None or row["close"] is None:
        return None, None
    return row["close"], "USD"


def is_instrument_confirmed(position) -> bool:
    """Pozycja ma potwierdzoną tożsamość instrumentu, gdy użytkownik
    jawnie zaznaczył wynik FMP ("Tak, to właściwy instrument") --
    `instrument_confirmed_at` (Faza 9) albo, dla pozycji sprzed Fazy 9,
    ustawione `cik` (było ustawiane WYŁĄCZNIE po potwierdzeniu). Tylko
    takie pozycje dostają cenę z FMP po tickerze -- niepotwierdzony
    ticker może wskazywać inną spółkę (`SU` = Suncor, nie Schneider)."""
    keys = position.keys()
    if "instrument_confirmed_at" in keys and position["instrument_confirmed_at"]:
        return True
    return position["cik"] is not None


def get_current_quote_for_position(scanner_conn: sqlite3.Connection, position, quote_fn=None) -> Quote | None:
    """Faza 9/11: najpierw dostawca ceny pozycji (FMP albo EODHD --
    `quote_fn(position)` wstrzykiwane przez UI, zwykle
    `MarketData.quote_for_position`; tylko pozycja z potwierdzonym
    instrumentem), potem dotychczasowy fallback `price_daily` po `cik`
    (EOD, USD)."""
    if quote_fn is not None and is_instrument_confirmed(position):
        quote = quote_fn(position)
        if quote is not None:
            return quote
    price, currency = get_current_price_for_position(scanner_conn, position)
    if price is None:
        return None
    return Quote(price=price, currency=currency, source="scanner (EOD)")


def get_position_summary(
    portfolio_conn, scanner_conn: sqlite3.Connection, position, *, broker: str | None = None,
    quote_fn=None, fx: FxRates | None = None, pln_rate_fn=None,
) -> PositionSummary:
    """`broker=None` (domyślnie) -- wszystkie platformy, bez zmian.
    `broker="TRADE_REPUBLIC"`/`"REVOLUT"`/`"OTHER"` -- filtr platformy
    (Decyzja właścicielki, Faza 7 "FILTR PLATFORMY W PORTFELU"):
    transakcje innych brokerów są odrzucane PRZED przekazaniem do
    `compute_position_summary` -- ta sama, niezmieniona, czysta funkcja
    liczy wynik tak, jakby pozycja istniała tylko na wybranym brokerze.
    Model danych/logika average-cost w `ui/portfolio.py` NIE są
    zmieniane -- filtr działa wyłącznie na poziomie tego, co dostaje.
    `portfolio_conn`/`scanner_conn` -- dwa osobne silniki w trybie
    hostowanym (Faza 8 Etap D), ten sam obiekt w trybie lokalnym.
    `quote_fn`/`fx` -- Faza 9, patrz `get_current_quote_for_position`
    i `compute_position_summary`."""
    purchases = get_purchase_transactions(portfolio_conn, position["position_id"])
    sales = get_sale_transactions(portfolio_conn, position["position_id"])
    if broker is not None:
        purchases = [p for p in purchases if p["broker"] == broker]
        sales = [s for s in sales if s["broker"] == broker]
    quote = get_current_quote_for_position(scanner_conn, position, quote_fn=quote_fn)
    summary = compute_position_summary(
        position["position_id"], purchases, sales,
        current_price=quote.price if quote else None,
        current_price_currency=quote.currency if quote else None,
        fx=fx, pln_rate_fn=pln_rate_fn,
    )
    if quote is None:
        return summary
    return replace(summary, quote_source=quote.source, quote_as_of=quote.as_of, quote_stale=quote.stale)


def get_user_positions_with_summaries(
    portfolio_conn, scanner_conn: sqlite3.Connection, user_id: int, *, broker: str | None = None,
    quote_fn=None, fx: FxRates | None = None, pln_rate_fn=None,
) -> list[tuple[object, PositionSummary]]:
    """`broker` -- patrz `get_position_summary`. Gdy ustawiony, pozycje
    bez ŻADNEJ transakcji na tym brokerze są pomijane całkowicie (nie
    pokazywane jako wiersz z 0 akcji) -- widok "Trade Republic" ma
    pokazywać WYŁĄCZNIE to, co jest na Trade Republic."""
    positions = get_positions_for_user(portfolio_conn, user_id)
    result = []
    for p in positions:
        summary = get_position_summary(
            portfolio_conn, scanner_conn, p, broker=broker, quote_fn=quote_fn, fx=fx, pln_rate_fn=pln_rate_fn,
        )
        if broker is not None and summary.shares_held == 0 and not summary.by_broker_currency:
            continue
        result.append((p, summary))
    return result


def get_brokers_in_use_for_user(portfolio_conn, user_id: int) -> set[str]:
    """Brokery z co najmniej jedną realną transakcją (zakup/bonus LUB
    sprzedaż) dla tego użytkownika -- używane wyłącznie do decyzji, czy
    pokazać opcję "Inny" w filtrze platformy (Decyzja właścicielki:
    "Other -- tylko jeśli istnieją realne transakcje OTHER").

    Celowo przez `get_positions_for_user`/`get_purchase_transactions`/
    `get_sale_transactions` (funkcje `portfolio_backend`, działające w
    OBU silnikach), NIE przez surowy SQL JOIN -- surowy SQL z `?`
    placeholderami działałby wyłącznie w trybie lokalnym (SQLite),
    psycopg2 w trybie hostowanym wymaga `%s`. N+1 zapytań jest tu bez
    znaczenia (mała liczba pozycji per użytkownik)."""
    brokers: set[str] = set()
    for position in get_positions_for_user(portfolio_conn, user_id):
        for row in get_purchase_transactions(portfolio_conn, position["position_id"]):
            brokers.add(row["broker"])
        for row in get_sale_transactions(portfolio_conn, position["position_id"]):
            brokers.add(row["broker"])
    return brokers


def get_review_needed_count(portfolio_conn, user_id: int) -> int:
    """Liczba pozycji, których NAJNOWSZA `holding_user_actions.action`
    to `REVIEW_LATER` -- pozycja bez żadnej zapisanej akcji NIE jest
    liczona jako wymagająca review (domyślny, niejawny status to HOLD,
    Exit Review automatyczny jest poza zakresem Fazy 7)."""
    count = 0
    for position in get_positions_for_user(portfolio_conn, user_id):
        action = get_latest_holding_user_action(portfolio_conn, position["position_id"])
        if action is not None and action["action"] == "REVIEW_LATER":
            count += 1
    return count


def get_candidate_detail(scanner_conn: sqlite3.Connection, run_id: str, cik: str) -> dict:
    """Pełne dane karty kandydata (sekcja 15 specyfikacji UI).

    Deterministyczne dane (decline snapshot, wycena DCF BEAR/BASE/BULL)
    są ZAWSZE dostępne, niezależnie od `llm_status` -- re-liczone tu
    TYMI SAMYMI, niezmienionymi, czystymi funkcjami co produkcyjny
    pipeline (`compute_valuation`/`compute_price_changes`, zero LLM,
    zero nowej logiki/metodologii) z już zaingestowanych fundamentals/
    cen. Pola jakościowe (`analysis`) są `None`, gdy `analysis_id` nie
    istnieje (FAILED) -- UI pokazuje wtedy "Analiza jakościowa
    niekompletna", NIGDY nie ukrywa deterministycznej części raportu."""
    candidate_row = scanner_conn.execute(
        "SELECT * FROM live_scan_candidates WHERE run_id = ? AND cik = ?", (run_id, cik),
    ).fetchone()
    company_row = scanner_conn.execute("SELECT * FROM companies WHERE cik = ?", (cik,)).fetchone()
    periods = get_fundamentals_periods(scanner_conn, cik)
    config = load_config()

    valuation_result = compute_valuation(
        company_row["sector_profile"], periods,
        current_price=candidate_row["current_price"], config=config.valuation,
    )

    price_rows = get_price_series(scanner_conn, cik)
    decline_snapshot = (
        compute_price_changes([
            PriceBar(
                date=r["date"], open=r["open"], high=r["high"], low=r["low"],
                close=r["close"], adj_close=r["adj_close"], volume=r["volume"],
            )
            for r in price_rows
        ])
        if price_rows else None
    )

    analysis: AnalysisOutput | None = None
    analysis_sources = []
    if candidate_row["analysis_id"] is not None:
        analysis_row = get_analysis(scanner_conn, candidate_row["analysis_id"])
        analysis = AnalysisOutput.model_validate(json.loads(analysis_row["llm_raw_output"]))
        analysis_sources = get_analysis_sources(scanner_conn, candidate_row["analysis_id"])

    return {
        "ticker": candidate_row["ticker"],
        "company_name": company_row["name"],
        "current_price": candidate_row["current_price"],
        "triggered_decline_flags": [
            k for k, v in json.loads(candidate_row["decline_flags_json"]).items() if v
        ],
        "decline_snapshot": decline_snapshot,
        "valuation_result": valuation_result,
        "llm_status": candidate_row["llm_status"],
        "llm_error": candidate_row["llm_error"],
        "analysis": analysis,
        "analysis_sources": [s for s in analysis_sources if s.verified],
    }


class TransactionChangeError(ValueError):
    """Zmiana zablokowana -- stan jednostek spadłby poniżej zera."""


_TYPE_LABELS = {"BUY": "Zakup", "SELL": "Sprzedaż", "BONUS": "Bonus"}


def apply_transaction_change(
    conn, position_id: int, *, kind: str, old_id: int, current_type: str, new_type: str, new_row: dict,
    fx_rate: float = 0.0, note: str = "", store=portfolio_backend,
) -> int:
    """Edycja jednego wpisu, w tym zmiana typu (BUY/SELL/BONUS), w ramach
    istniejącego mechanizmu korekt: nowy wpis właściwego typu + anulowanie
    starego z powodem wskazującym nowy wpis. Nic nie jest kasowane ani
    nadpisywane. Przed zapisem cała oś czasu pozycji jest sprawdzana
    ponownie (dane z bazy, nie z formularza) -- ujemny stan jednostek
    blokuje zapis. Błąd w trakcie -> rollback. Zwraca id nowego wpisu.

    `new_row`: broker, currency, shares, purchase_date/sale_date,
    total_invested (BUY), sale_price (SELL), fees."""
    purchases = [dict(r) for r in store.get_purchase_transactions(conn, position_id)]
    sales = [dict(r) for r in store.get_sale_transactions(conn, position_id)]
    active = purchases if kind == "PURCHASE" else sales
    if not any(r["transaction_id"] == old_id for r in active):
        raise TransactionChangeError("Ten wpis nie jest już aktywny (został zmieniony albo anulowany).")
    negative = find_negative_holding(*replace_transaction(
        purchases, sales, kind=kind, transaction_id=old_id, new_type=new_type, new_row=new_row,
    ))
    if negative:
        raise TransactionChangeError(
            f"{negative['date']} ({negative['broker']}, {negative['currency']}): sprzedaż {negative['sold']:g}, "
            f"posiadane {negative['held']:g}."
        )
    try:
        if TRANSACTION_TABLE[new_type] == "PURCHASE":
            total = new_row["total_invested"] if new_type == "BUY" else 0.0
            new_id = store.insert_purchase_transaction(
                conn, position_id=position_id, broker=new_row["broker"], acquisition_type=new_type,
                purchase_date=new_row["purchase_date"], shares=new_row["shares"], total_invested=total,
                currency=new_row["currency"], price_per_share=(total / new_row["shares"]) if new_type == "BUY" else None,
                fees=new_row.get("fees"), note=note or None, fee_status=new_row.get("fee_status"),
            )
            new_kind, table = "PURCHASE", "zakup"
        else:
            new_id = store.insert_sale_transaction(
                conn, position_id=position_id, broker=new_row["broker"], sale_date=new_row["sale_date"],
                shares=new_row["shares"], sale_price=new_row["sale_price"], currency=new_row["currency"],
                fees=new_row.get("fees"), note=note or None, fee_status=new_row.get("fee_status"),
            )
            new_kind, table = "SALE", "sprzedaż"
        if fx_rate and str(new_row["currency"]).upper() != "PLN":
            store.set_transaction_fx_rate(conn, kind=new_kind, transaction_id=new_id, fx_rate_actual=fx_rate)
        reason = (
            f"Zmiana typu: {_TYPE_LABELS[current_type]} -> {_TYPE_LABELS[new_type]} (nowy wpis: {table} #{new_id})"
            if new_type != current_type else f"Poprawka danych (nowy wpis: {table} #{new_id})"
        )
        void = store.void_purchase_transaction if kind == "PURCHASE" else store.void_sale_transaction
        void(conn, old_id, reason)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return new_id

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

from buffett_scanner.analysis_schema import AnalysisOutput
from buffett_scanner.config import load_config
from buffett_scanner.db import (
    get_analysis,
    get_analysis_sources,
    get_fundamentals_periods,
    get_latest_holding_user_action,
    get_positions_for_user,
    get_price_series,
    get_purchase_transactions,
    get_sale_transactions,
)
from buffett_scanner.scanner import PriceBar, compute_price_changes
from buffett_scanner.ui.portfolio import PositionSummary, compute_position_summary
from buffett_scanner.valuation import compute_valuation


def get_latest_live_scan_run(conn: sqlite3.Connection) -> sqlite3.Row | None:
    """Najnowszy PRAWDZIWY live-scan (nigdy diagnostyczny `validation-*`)
    -- Decyzja właścicielki, Faza 7 pkt 1. `created_at` jest jedynym
    monotonicznym znacznikiem czasu w `live_scan_runs` (`run_date` może
    nieść sufiksy diagnostyczne typu `-validation6h`, patrz Faza 6h)."""
    return conn.execute(
        """
        SELECT * FROM live_scan_runs
        WHERE run_id LIKE 'live-scan-%'
        ORDER BY created_at DESC
        LIMIT 1
        """
    ).fetchone()


def get_synthesis_rows(conn: sqlite3.Connection, run_id: str) -> list[dict]:
    """Jeden wiersz per finalista shortlisty (Decyzja właścicielki, Faza
    7 pkt 2: pokazujemy WSZYSTKICH finalistów niezależnie od
    `llm_status` -- FAILED to status RAPORTU, nie ocena spółki, i nie
    blokuje wyświetlenia deterministycznych danych/wyceny)."""
    rows = conn.execute(
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
            analysis_row = get_analysis(conn, row["analysis_id"])
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
    return result


def get_current_price_for_position(conn: sqlite3.Connection, position: sqlite3.Row) -> tuple[float | None, str | None]:
    """Cena bieżąca = ostatni dzienny close z `price_daily` (ten sam
    mechanizm co cały scanner -- EOD, NIE live/intraday). Działa
    WYŁĄCZNIE dla pozycji z ustawionym `cik` (resolved przez FMP przy
    dodawaniu transakcji -- patrz KROK 7) -- `price_daily` nie ma
    kolumny currency, cały istniejący pipeline FMP niejawnie zakłada
    USD dla notowań amerykańskich, więc to samo założenie jest tu
    powtórzone, nie wymyślone na nowo. Pozycja bez `cik` -> (None, None),
    UI pokazuje "cena bieżąca niedostępna", nigdy 0."""
    if position["cik"] is None:
        return None, None
    row = conn.execute(
        "SELECT close FROM price_daily WHERE cik = ? ORDER BY date DESC LIMIT 1",
        (position["cik"],),
    ).fetchone()
    if row is None or row["close"] is None:
        return None, None
    return row["close"], "USD"


def get_position_summary(
    conn: sqlite3.Connection, position: sqlite3.Row, *, broker: str | None = None,
) -> PositionSummary:
    """`broker=None` (domyślnie) -- wszystkie platformy, bez zmian.
    `broker="TRADE_REPUBLIC"`/`"REVOLUT"`/`"OTHER"` -- filtr platformy
    (Decyzja właścicielki, Faza 7 "FILTR PLATFORMY W PORTFELU"):
    transakcje innych brokerów są odrzucane PRZED przekazaniem do
    `compute_position_summary` -- ta sama, niezmieniona, czysta funkcja
    liczy wynik tak, jakby pozycja istniała tylko na wybranym brokerze.
    Model danych/logika average-cost w `ui/portfolio.py` NIE są
    zmieniane -- filtr działa wyłącznie na poziomie tego, co dostaje."""
    purchases = get_purchase_transactions(conn, position["position_id"])
    sales = get_sale_transactions(conn, position["position_id"])
    if broker is not None:
        purchases = [p for p in purchases if p["broker"] == broker]
        sales = [s for s in sales if s["broker"] == broker]
    current_price, current_price_currency = get_current_price_for_position(conn, position)
    return compute_position_summary(
        position["position_id"], purchases, sales,
        current_price=current_price, current_price_currency=current_price_currency,
    )


def get_user_positions_with_summaries(
    conn: sqlite3.Connection, user_id: int, *, broker: str | None = None,
) -> list[tuple[sqlite3.Row, PositionSummary]]:
    """`broker` -- patrz `get_position_summary`. Gdy ustawiony, pozycje
    bez ŻADNEJ transakcji na tym brokerze są pomijane całkowicie (nie
    pokazywane jako wiersz z 0 akcji) -- widok "Trade Republic" ma
    pokazywać WYŁĄCZNIE to, co jest na Trade Republic."""
    positions = get_positions_for_user(conn, user_id)
    result = []
    for p in positions:
        summary = get_position_summary(conn, p, broker=broker)
        if broker is not None and summary.shares_held == 0 and not summary.by_broker_currency:
            continue
        result.append((p, summary))
    return result


def get_brokers_in_use_for_user(conn: sqlite3.Connection, user_id: int) -> set[str]:
    """Brokery z co najmniej jedną realną transakcją (zakup/bonus LUB
    sprzedaż) dla tego użytkownika -- używane wyłącznie do decyzji, czy
    pokazać opcję "Inny" w filtrze platformy (Decyzja właścicielki:
    "Other -- tylko jeśli istnieją realne transakcje OTHER")."""
    rows = conn.execute(
        """
        SELECT DISTINCT pt.broker AS broker
        FROM purchase_transactions pt
        JOIN positions p ON p.position_id = pt.position_id
        WHERE p.user_id = ?
        UNION
        SELECT DISTINCT st.broker AS broker
        FROM sale_transactions st
        JOIN positions p ON p.position_id = st.position_id
        WHERE p.user_id = ?
        """,
        (user_id, user_id),
    ).fetchall()
    return {row["broker"] for row in rows}


def get_review_needed_count(conn: sqlite3.Connection, user_id: int) -> int:
    """Liczba pozycji, których NAJNOWSZA `holding_user_actions.action`
    to `REVIEW_LATER` -- pozycja bez żadnej zapisanej akcji NIE jest
    liczona jako wymagająca review (domyślny, niejawny status to HOLD,
    Exit Review automatyczny jest poza zakresem Fazy 7)."""
    count = 0
    for position in get_positions_for_user(conn, user_id):
        action = get_latest_holding_user_action(conn, position["position_id"])
        if action is not None and action["action"] == "REVIEW_LATER":
            count += 1
    return count


def get_candidate_detail(conn: sqlite3.Connection, run_id: str, cik: str) -> dict:
    """Pełne dane karty kandydata (sekcja 15 specyfikacji UI).

    Deterministyczne dane (decline snapshot, wycena DCF BEAR/BASE/BULL)
    są ZAWSZE dostępne, niezależnie od `llm_status` -- re-liczone tu
    TYMI SAMYMI, niezmienionymi, czystymi funkcjami co produkcyjny
    pipeline (`compute_valuation`/`compute_price_changes`, zero LLM,
    zero nowej logiki/metodologii) z już zaingestowanych fundamentals/
    cen. Pola jakościowe (`analysis`) są `None`, gdy `analysis_id` nie
    istnieje (FAILED) -- UI pokazuje wtedy "Analiza jakościowa
    niekompletna", NIGDY nie ukrywa deterministycznej części raportu."""
    candidate_row = conn.execute(
        "SELECT * FROM live_scan_candidates WHERE run_id = ? AND cik = ?", (run_id, cik),
    ).fetchone()
    company_row = conn.execute("SELECT * FROM companies WHERE cik = ?", (cik,)).fetchone()
    periods = get_fundamentals_periods(conn, cik)
    config = load_config()

    valuation_result = compute_valuation(
        company_row["sector_profile"], periods,
        current_price=candidate_row["current_price"], config=config.valuation,
    )

    price_rows = get_price_series(conn, cik)
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
        analysis_row = get_analysis(conn, candidate_row["analysis_id"])
        analysis = AnalysisOutput.model_validate(json.loads(analysis_row["llm_raw_output"]))
        analysis_sources = get_analysis_sources(conn, candidate_row["analysis_id"])

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

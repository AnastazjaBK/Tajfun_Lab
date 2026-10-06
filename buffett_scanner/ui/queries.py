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
from buffett_scanner.db import (
    get_analysis,
    get_latest_holding_user_action,
    get_positions_for_user,
    get_purchase_transactions,
    get_sale_transactions,
)
from buffett_scanner.ui.portfolio import PositionSummary, compute_position_summary


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


def get_position_summary(conn: sqlite3.Connection, position: sqlite3.Row) -> PositionSummary:
    purchases = get_purchase_transactions(conn, position["position_id"])
    sales = get_sale_transactions(conn, position["position_id"])
    current_price, current_price_currency = get_current_price_for_position(conn, position)
    return compute_position_summary(
        position["position_id"], purchases, sales,
        current_price=current_price, current_price_currency=current_price_currency,
    )


def get_user_positions_with_summaries(
    conn: sqlite3.Connection, user_id: int,
) -> list[tuple[sqlite3.Row, PositionSummary]]:
    positions = get_positions_for_user(conn, user_id)
    return [(p, get_position_summary(conn, p)) for p in positions]


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

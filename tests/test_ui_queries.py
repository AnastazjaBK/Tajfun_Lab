"""Testy warstwy odczytu dla UI (Faza 7, UI + PORTFOLIO V0) -- realna
SQLite (tmp_path), zero sieci/Claude API."""

from __future__ import annotations

import json

import pytest

from buffett_scanner.db import (
    create_user,
    init_db,
    insert_analysis,
    insert_holding_user_action,
    insert_live_scan_candidate,
    insert_live_scan_run,
    insert_position,
    insert_purchase_transaction,
    insert_sale_transaction,
    insert_price_rows,
    upsert_company,
    upsert_scoring_model_version,
)
from buffett_scanner.ui.queries import (
    get_current_price_for_position,
    get_latest_live_scan_run,
    get_position_summary,
    get_review_needed_count,
    get_synthesis_rows,
    get_user_positions_with_summaries,
)


@pytest.fixture
def conn(tmp_path):
    return init_db(tmp_path / "test.db")


def _make_analysis_output(**overrides) -> dict:
    base = {
        "ticker": "CBOE", "schema_version": "1.0",
        "business_understandability": {"score": 6, "max_score": 7, "confidence": "HIGH"},
        "moat": {"score": 10, "max_score": 12, "confidence": "MEDIUM"},
        "financial_quality_commentary": {"confidence": "HIGH", "reasoning": "solid"},
        "management_capital_allocation": {"score": 8, "max_score": 10, "confidence": "MEDIUM"},
        "fear_analysis": {"classification": "TEMPORARY", "confidence": "MEDIUM", "trigger": "x"},
        "dividend_trap_alert": {"triggered": False},
        "bull_case": ["Silny moat oparty na efektach sieciowych i wysokich kosztach zmiany."],
        "bear_case": ["Rosnąca konkurencja regulacyjna może ograniczyć marże."],
        "why_market_may_be_right": ["Spadek może odzwierciedlać trwałe spowolnienie wzrostu."],
        "why_this_may_not_be_a_bargain": ["Obecna wycena może już uwzględniać ryzyko."],
        "thesis_invalidation": ["Utrata kluczowego klienta odpowiadającego za istotną część przychodów."],
        "biggest_unknown": "Nie wiadomo, czy spadek marży w ostatnim kwartale jest trwały czy cykliczny.",
        "cited_source_ids": [],
    }
    base.update(overrides)
    return base


def _seed_live_scan_run(conn, run_id: str, run_date: str = "2026-10-06") -> None:
    upsert_scoring_model_version(conn, version="v1", description="test", weights_json="{}", gates_json="{}")
    upsert_company(conn, cik="0000928054", name="CBOE Global Markets Inc.")
    upsert_company(conn, cik="0001099800", name="Paychex Inc.")
    insert_live_scan_run(
        conn, run_id=run_id, run_date=run_date, config_version="v1",
        universe_size=501, decline_surfaced=156, prefilter_excluded=0,
        shortlist_limit=20, shortlist_size=2,
    )
    # CBOE -- COMPLETE, pełna analiza.
    insert_live_scan_candidate(
        conn, run_id=run_id, cik="0000928054", ticker="CBOE", rank=1, current_price=210.5,
        decline_flags={"daily_decline": True, "week_decline": False},
        deterministic_score_pct=55.0, deterministic_partial_score=25.0,
        available_components=("safety",), missing_components=(),
        safety_score=12.0, valuation_score=8.0, dividend_score=5.0,
        margin_of_safety_base_pct=15.0, hard_gate_passed_deterministic=True,
        hard_gate_triggered_deterministic=(), in_shortlist=True,
    )
    analysis_id = insert_analysis(
        conn, cik="0000928054", run_date=run_date, price_at_analysis=210.5,
        scoring_model_version="v1", total_score=72.5, margin_of_safety_pct=18.2,
        llm_raw_output=json.dumps(_make_analysis_output()),
    )
    conn.execute(
        "UPDATE live_scan_candidates SET llm_status='COMPLETE', analysis_id=? WHERE run_id=? AND cik=?",
        (analysis_id, run_id, "0000928054"),
    )
    # PAYX -- FAILED (analiza jakościowa niekompletna).
    insert_live_scan_candidate(
        conn, run_id=run_id, cik="0001099800", ticker="PAYX", rank=2, current_price=145.0,
        decline_flags={"daily_decline": True}, deterministic_score_pct=50.0,
        deterministic_partial_score=22.0, available_components=("safety",), missing_components=(),
        safety_score=11.0, valuation_score=7.0, dividend_score=6.0,
        margin_of_safety_base_pct=10.0, hard_gate_passed_deterministic=True,
        hard_gate_triggered_deterministic=(), in_shortlist=True,
    )
    conn.execute(
        "UPDATE live_scan_candidates SET llm_status='FAILED', llm_error=? WHERE run_id=? AND cik=?",
        ("thesis_invalidation jest semantycznie pusty", run_id, "0001099800"),
    )
    conn.commit()


def test_get_latest_live_scan_run_ignores_validation_runs(conn):
    """Test KLUCZOWY (Decyzja właścicielki, Faza 7 pkt 1): walidacje
    techniczne (`validation-6h-...`) NIE są kolejnym skanem rynku i
    muszą być ignorowane, nawet jeśli są NOWSZE niż realny skan."""
    _seed_live_scan_run(conn, "live-scan-2026-10-06T083825543395Z", run_date="2026-10-06")
    # "nowszy" wpis walidacyjny, ale to NIE jest live-scan.
    conn.execute(
        """
        INSERT INTO live_scan_runs (run_id, run_date, config_version, universe_size,
            decline_surfaced, prefilter_excluded, shortlist_limit, shortlist_size, created_at)
        VALUES (?, ?, 'v1', 5, 5, 0, 5, 5, datetime('now', '+1 hour'))
        """,
        ("validation-6h-2026-10-06T165859543821Z", "2026-10-06-validation6h"),
    )
    conn.commit()

    latest = get_latest_live_scan_run(conn)
    assert latest["run_id"] == "live-scan-2026-10-06T083825543395Z"


def test_get_latest_live_scan_run_returns_none_when_no_real_scan_exists(conn):
    conn.execute(
        """
        INSERT INTO live_scan_runs (run_id, run_date, config_version, universe_size,
            decline_surfaced, prefilter_excluded, shortlist_limit, shortlist_size)
        VALUES ('validation-6f-xyz', '2026-10-06-validation6f', 'v1', 5, 5, 0, 5, 5)
        """
    )
    conn.commit()
    assert get_latest_live_scan_run(conn) is None


def test_synthesis_rows_includes_complete_and_failed_with_translatable_status(conn):
    """Test (Decyzja właścicielki, Faza 7 pkt 2): FAILED NIE jest oceną
    spółki -- deterministyczne dane/wycena pozostają widoczne, tylko
    pola jakościowe (bull_case/biggest_risk) są None dla FAILED."""
    run_id = "live-scan-2026-10-06T083825543395Z"
    _seed_live_scan_run(conn, run_id)

    rows = get_synthesis_rows(conn, run_id)
    by_ticker = {r["ticker"]: r for r in rows}

    cboe = by_ticker["CBOE"]
    assert cboe["llm_status"] == "COMPLETE"
    assert cboe["company_name"] == "CBOE Global Markets Inc."
    assert cboe["current_price"] == 210.5
    assert cboe["full_score"] == 72.5
    assert cboe["margin_of_safety_pct"] == 18.2  # analiza COMPLETE -- preferowana nad deterministyczną
    assert "daily_decline" in cboe["triggered_decline_flags"]
    assert "week_decline" not in cboe["triggered_decline_flags"]
    assert cboe["bull_case_first"] == "Silny moat oparty na efektach sieciowych i wysokich kosztach zmiany."
    assert cboe["biggest_risk"] == "Utrata kluczowego klienta odpowiadającego za istotną część przychodów."

    payx = by_ticker["PAYX"]
    assert payx["llm_status"] == "FAILED"
    assert payx["llm_error"] == "thesis_invalidation jest semantycznie pusty"
    # Deterministyczne dane WCIĄŻ widoczne mimo FAILED analizy jakościowej.
    assert payx["current_price"] == 145.0
    assert payx["margin_of_safety_pct"] == 10.0  # fallback na deterministyczny MoS (brak analysis_id)
    assert payx["deterministic_score_pct"] == 50.0
    # Pola jakościowe niedostępne -- UI pokaże "Analiza jakościowa niekompletna".
    assert payx["bull_case_first"] is None
    assert payx["biggest_risk"] is None
    assert payx["full_score"] is None


def test_get_current_price_for_position_returns_none_without_cik(conn):
    """Test (sekcja 19 specyfikacji): brak CIK -> brak automatycznej
    ceny, nigdy 0."""
    user_id = create_user(conn, "Anastazja")
    position_id = insert_position(conn, user_id=user_id, ticker="SU.PA", company_name="Schneider Electric SE")
    conn.commit()
    from buffett_scanner.db import get_position
    position = get_position(conn, position_id)
    price, currency = get_current_price_for_position(conn, position)
    assert price is None
    assert currency is None


def test_get_current_price_for_position_uses_latest_price_daily_close(conn):
    user_id = create_user(conn, "Anastazja")
    upsert_company(conn, cik="0000320193", name="Apple Inc.")
    insert_price_rows(conn, "0000320193", source="fmp", rows=[
        {"date": "2026-10-01", "open": 100, "high": 101, "low": 99, "close": 150.0, "adjClose": 150.0, "volume": 1000},
        {"date": "2026-10-02", "open": 100, "high": 101, "low": 99, "close": 155.0, "adjClose": 155.0, "volume": 1000},
    ])
    position_id = insert_position(
        conn, user_id=user_id, cik="0000320193", ticker="AAPL", company_name="Apple Inc.",
    )
    conn.commit()
    from buffett_scanner.db import get_position
    position = get_position(conn, position_id)
    price, currency = get_current_price_for_position(conn, position)
    assert price == 155.0  # najnowszy close, nie pierwszy
    assert currency == "USD"


def test_get_user_positions_with_summaries_isolates_users(conn):
    user_a = create_user(conn, "Anastazja")
    user_b = create_user(conn, "Mąż")
    position_a = insert_position(conn, user_id=user_a, ticker="AAPL", company_name="Apple Inc.")
    insert_position(conn, user_id=user_b, ticker="GSK", company_name="GSK plc")
    insert_purchase_transaction(
        conn, position_id=position_a, broker="TRADE_REPUBLIC", acquisition_type="BONUS",
        purchase_date="2026-05-01", shares=3.0, total_invested=0.0, currency="USD",
    )
    conn.commit()

    results_a = get_user_positions_with_summaries(conn, user_a)
    results_b = get_user_positions_with_summaries(conn, user_b)
    assert len(results_a) == 1
    assert results_a[0][0]["ticker"] == "AAPL"
    assert results_a[0][1].shares_held == 3.0
    assert len(results_b) == 1
    assert results_b[0][1].shares_held == 0.0  # GSK: zero transakcji wpisanych


def test_get_review_needed_count_counts_only_review_later_action(conn):
    user_id = create_user(conn, "Anastazja")
    position_hold = insert_position(conn, user_id=user_id, ticker="AAPL", company_name="Apple Inc.")
    position_review = insert_position(conn, user_id=user_id, ticker="GSK", company_name="GSK plc")
    position_untouched = insert_position(conn, user_id=user_id, ticker="PBR", company_name="Petrobras")
    insert_holding_user_action(conn, position_id=position_hold, action="HOLD")
    insert_holding_user_action(conn, position_id=position_review, action="REVIEW_LATER")
    conn.commit()

    assert get_review_needed_count(conn, user_id) == 1  # position_untouched (brak akcji) NIE liczy się

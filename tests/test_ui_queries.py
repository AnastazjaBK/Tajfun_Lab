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
    get_brokers_in_use_for_user,
    get_candidate_detail,
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


def test_get_candidate_detail_complete_includes_analysis_and_recomputed_valuation(conn):
    """Test (sekcja 15 specyfikacji): karta kandydata dla COMPLETE ma
    pełny `AnalysisOutput` ORAZ deterministyczną wycenę, re-liczoną TĄ
    SAMĄ, niezmienioną `compute_valuation` co produkcyjny pipeline
    (zero nowej logiki/metodologii)."""
    run_id = "live-scan-2026-10-06T083825543395Z"
    _seed_live_scan_run(conn, run_id)

    detail = get_candidate_detail(conn, run_id, "0000928054")  # CBOE, COMPLETE
    assert detail["ticker"] == "CBOE"
    assert detail["company_name"] == "CBOE Global Markets Inc."
    assert detail["llm_status"] == "COMPLETE"
    assert detail["analysis"] is not None
    assert detail["analysis"].bull_case == ["Silny moat oparty na efektach sieciowych i wysokich kosztach zmiany."]
    # Brak zaingestowanych fundamentals w tym teście -> wycena honestnie
    # NOT_IMPLEMENTED (ten sam, niezmieniony kod co produkcyjny pipeline),
    # nigdy fikcyjna liczba.
    assert detail["valuation_result"].implemented is False
    assert detail["valuation_result"].reason is not None
    # Brak zaingestowanych cen -> decline snapshot honestnie None.
    assert detail["decline_snapshot"] is None
    assert "daily_decline" in detail["triggered_decline_flags"]


def test_get_candidate_detail_failed_has_no_analysis_but_keeps_deterministic_data(conn):
    """Test KLUCZOWY (Decyzja właścicielki, Faza 7 pkt 2): FAILED ->
    `analysis=None` (brak pól jakościowych), ale cena/deterministic
    score/decline trigger pozostają dostępne -- UI pokazuje "Analiza
    jakościowa niekompletna", NIGDY ukrywa resztę raportu."""
    run_id = "live-scan-2026-10-06T083825543395Z"
    _seed_live_scan_run(conn, run_id)

    detail = get_candidate_detail(conn, run_id, "0001099800")  # PAYX, FAILED
    assert detail["ticker"] == "PAYX"
    assert detail["llm_status"] == "FAILED"
    assert detail["llm_error"] == "thesis_invalidation jest semantycznie pusty"
    assert detail["analysis"] is None
    assert detail["analysis_sources"] == []
    assert detail["current_price"] == 145.0
    # Deterministyczna wycena nadal re-liczana (honestnie NOT_IMPLEMENTED
    # tu, bo brak fundamentals w tym teście, ale funkcja się nie wywala).
    assert detail["valuation_result"].implemented is False


def test_broker_filter_shows_only_matching_broker_subposition(conn):
    """Test KLUCZOWY (Decyzja właścicielki, "FILTR PLATFORMY W PORTFELU"):
    pozycja AAPL z 3 akcjami BONUS na Trade Republic + 2 akcjami BUY na
    Revolut -- filtr broker='TRADE_REPUBLIC' ma pokazać WYŁĄCZNIE 3
    akcje/0 USD invested, filtr broker='REVOLUT' WYŁĄCZNIE 2 akcje/380
    USD invested, bez filtra (None) -- sumę obu (5 akcji)."""
    user_id = create_user(conn, "Anastazja")
    position_id = insert_position(conn, user_id=user_id, ticker="AAPL", company_name="Apple Inc.")
    insert_purchase_transaction(
        conn, position_id=position_id, broker="TRADE_REPUBLIC", acquisition_type="BONUS",
        purchase_date="2026-05-01", shares=3.0, total_invested=0.0, currency="USD",
    )
    insert_purchase_transaction(
        conn, position_id=position_id, broker="REVOLUT", acquisition_type="BUY",
        purchase_date="2026-06-01", shares=2.0, total_invested=380.0, currency="USD",
    )
    conn.commit()
    from buffett_scanner.db import get_position
    position = get_position(conn, position_id)

    summary_all = get_position_summary(conn, position)
    assert summary_all.shares_held == 5.0

    summary_tr = get_position_summary(conn, position, broker="TRADE_REPUBLIC")
    assert summary_tr.shares_held == 3.0
    assert summary_tr.invested_by_currency == {"USD": 0.0}

    summary_revolut = get_position_summary(conn, position, broker="REVOLUT")
    assert summary_revolut.shares_held == 2.0
    assert summary_revolut.invested_by_currency == {"USD": 380.0}


def test_broker_filter_excludes_positions_with_no_transactions_on_that_broker(conn):
    """Pozycja istniejąca WYŁĄCZNIE na Revolut nie może się pojawić w
    widoku "Trade Republic" jako wiersz z 0 akcji -- ma być całkowicie
    pominięta (sekcja "nie mieszaj akcji pomiędzy brokerami")."""
    user_id = create_user(conn, "Anastazja")
    position_tr = insert_position(conn, user_id=user_id, ticker="AAPL", company_name="Apple Inc.")
    position_revolut = insert_position(conn, user_id=user_id, ticker="GSK", company_name="GSK plc")
    insert_purchase_transaction(
        conn, position_id=position_tr, broker="TRADE_REPUBLIC", acquisition_type="BUY",
        purchase_date="2026-05-01", shares=1.0, total_invested=100.0, currency="USD",
    )
    insert_purchase_transaction(
        conn, position_id=position_revolut, broker="REVOLUT", acquisition_type="BUY",
        purchase_date="2026-05-01", shares=1.0, total_invested=50.0, currency="USD",
    )
    conn.commit()

    results_all = get_user_positions_with_summaries(conn, user_id)
    assert {p["ticker"] for p, _ in results_all} == {"AAPL", "GSK"}

    results_tr = get_user_positions_with_summaries(conn, user_id, broker="TRADE_REPUBLIC")
    assert {p["ticker"] for p, _ in results_tr} == {"AAPL"}  # GSK pominięty, nie 0-akcyjny wiersz

    results_revolut = get_user_positions_with_summaries(conn, user_id, broker="REVOLUT")
    assert {p["ticker"] for p, _ in results_revolut} == {"GSK"}


def test_broker_filter_keeps_fully_sold_position_on_that_broker_visible(conn):
    """Pozycja w pełni sprzedana NA TYM BROKERZE (shares_held=0, ale z
    realną historią transakcji) różni się od pozycji BEZ ŻADNEJ
    transakcji na tym brokerze -- ta pierwsza NIE powinna być cicho
    pomijana (to legalny stan "zamknięta pozycja", nie "nie istnieje
    tu")."""
    user_id = create_user(conn, "Anastazja")
    position_id = insert_position(conn, user_id=user_id, ticker="AAPL", company_name="Apple Inc.")
    insert_purchase_transaction(
        conn, position_id=position_id, broker="TRADE_REPUBLIC", acquisition_type="BUY",
        purchase_date="2026-05-01", shares=2.0, total_invested=200.0, currency="USD",
    )
    insert_sale_transaction(
        conn, position_id=position_id, broker="TRADE_REPUBLIC",
        sale_date="2026-06-01", shares=2.0, sale_price=120.0, currency="USD",
    )
    conn.commit()

    results = get_user_positions_with_summaries(conn, user_id, broker="TRADE_REPUBLIC")
    assert len(results) == 1
    assert results[0][1].shares_held == 0.0


def test_get_brokers_in_use_for_user_excludes_other_when_unused(conn):
    user_id = create_user(conn, "Anastazja")
    position_id = insert_position(conn, user_id=user_id, ticker="AAPL", company_name="Apple Inc.")
    insert_purchase_transaction(
        conn, position_id=position_id, broker="TRADE_REPUBLIC", acquisition_type="BUY",
        purchase_date="2026-05-01", shares=1.0, total_invested=100.0, currency="USD",
    )
    conn.commit()
    assert get_brokers_in_use_for_user(conn, user_id) == {"TRADE_REPUBLIC"}


def test_get_brokers_in_use_for_user_includes_other_when_used_via_sale(conn):
    """Broker może pojawić się WYŁĄCZNIE przez sprzedaż (np. pozycja
    kupiona na Trade Republic, częściowo sprzedana przez Inny broker po
    transferze) -- funkcja musi uwzględniać obie tabele transakcji."""
    user_id = create_user(conn, "Anastazja")
    position_id = insert_position(conn, user_id=user_id, ticker="AAPL", company_name="Apple Inc.")
    insert_purchase_transaction(
        conn, position_id=position_id, broker="TRADE_REPUBLIC", acquisition_type="BUY",
        purchase_date="2026-05-01", shares=2.0, total_invested=200.0, currency="USD",
    )
    insert_sale_transaction(
        conn, position_id=position_id, broker="OTHER",
        sale_date="2026-06-01", shares=1.0, sale_price=120.0, currency="USD",
    )
    conn.commit()
    assert get_brokers_in_use_for_user(conn, user_id) == {"TRADE_REPUBLIC", "OTHER"}


def test_get_brokers_in_use_for_user_isolates_users(conn):
    user_a = create_user(conn, "Anastazja")
    user_b = create_user(conn, "Mąż")
    position_a = insert_position(conn, user_id=user_a, ticker="AAPL", company_name="Apple Inc.")
    insert_purchase_transaction(
        conn, position_id=position_a, broker="REVOLUT", acquisition_type="BUY",
        purchase_date="2026-05-01", shares=1.0, total_invested=100.0, currency="USD",
    )
    conn.commit()
    assert get_brokers_in_use_for_user(conn, user_a) == {"REVOLUT"}
    assert get_brokers_in_use_for_user(conn, user_b) == set()


def test_get_review_needed_count_counts_only_review_later_action(conn):
    user_id = create_user(conn, "Anastazja")
    position_hold = insert_position(conn, user_id=user_id, ticker="AAPL", company_name="Apple Inc.")
    position_review = insert_position(conn, user_id=user_id, ticker="GSK", company_name="GSK plc")
    position_untouched = insert_position(conn, user_id=user_id, ticker="PBR", company_name="Petrobras")
    insert_holding_user_action(conn, position_id=position_hold, action="HOLD")
    insert_holding_user_action(conn, position_id=position_review, action="REVIEW_LATER")
    conn.commit()

    assert get_review_needed_count(conn, user_id) == 1  # position_untouched (brak akcji) NIE liczy się

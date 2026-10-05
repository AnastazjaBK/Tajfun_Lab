"""Testy generatora raportu Markdown (Faza 4, punkt 4.3)."""

from __future__ import annotations

from buffett_scanner.analysis_schema import (
    AnalysisOutput,
    DividendTrapAlert,
    FearAnalysis,
    FinancialQualityCommentary,
    ManagementSection,
    MoatSection,
    ScoredSection,
)
from buffett_scanner.config import load_config
from buffett_scanner.fundamentals import FundamentalsPeriod
from buffett_scanner.report import render_markdown_report
from buffett_scanner.scanner import PriceChangeSnapshot
from buffett_scanner.scoring import compute_score
from buffett_scanner.sources import VerifiedSource


def _analysis(**overrides) -> AnalysisOutput:
    base = dict(
        ticker="AAPL", schema_version="1.0",
        business_understandability=ScoredSection(score=6, confidence="HIGH"),
        moat=MoatSection(score=8, confidence="MEDIUM"),
        financial_quality_commentary=FinancialQualityCommentary(confidence="HIGH", reasoning="ok"),
        management_capital_allocation=ManagementSection(score=7, confidence="MEDIUM"),
        fear_analysis=FearAnalysis(classification="UNCERTAIN", confidence="MEDIUM", trigger="x", reasoning="y"),
        dividend_trap_alert=DividendTrapAlert(triggered=False, reasoning=""),
        cited_source_ids=["src-1"],
    )
    base.update(overrides)
    return AnalysisOutput.model_validate(base)


def _period(fp: str, **kw) -> FundamentalsPeriod:
    base = dict(
        fiscal_period=fp, period_end_date=f"{fp}-12-31", filed_date=None,
        revenue=None, net_income=None, ebitda=None, operating_cash_flow=None,
        capital_expenditure=None, total_debt=None, cash_and_equivalents=None,
        total_current_assets=None, total_current_liabilities=None,
    )
    base.update(kw)
    return FundamentalsPeriod(**base)


def test_render_markdown_report_includes_all_scenarios_when_implemented():
    config = load_config()
    analysis = _analysis()
    periods = [
        _period("FY2023", revenue=900.0, net_income=50.0, ebitda=200.0, operating_cash_flow=150.0,
                capital_expenditure=20.0, total_debt=100.0, cash_and_equivalents=150.0,
                total_current_assets=400.0, total_current_liabilities=200.0,
                dividends_paid=10.0, share_buybacks=10.0, diluted_shares_outstanding=100.0),
        _period("FY2024", revenue=1000.0, net_income=70.0, ebitda=220.0, operating_cash_flow=170.0,
                capital_expenditure=20.0, total_debt=100.0, cash_and_equivalents=150.0,
                total_current_assets=400.0, total_current_liabilities=200.0,
                dividends_paid=12.0, share_buybacks=10.0, diluted_shares_outstanding=100.0),
    ]
    score = compute_score(
        analysis=analysis, periods=periods, sector_profile="GENERAL",
        current_price=15.0, config=config,
    )
    report = render_markdown_report(
        ticker="AAPL", cik="0000320193", run_date="2026-09-25", current_price=15.0,
        analysis=analysis, score=score, config=config,
    )
    assert "# AAPL (0000320193) — 2026-09-25" in report
    assert "BEAR" in report and "BASE" in report and "BULL" in report
    assert "TOTAL" in report
    assert "UNCALIBRATED" in report
    assert "N/A" not in report  # wszystkie pola dividend policzalne w tym przykładzie


def test_render_markdown_report_shows_partial_when_valuation_not_implemented():
    config = load_config()
    analysis = _analysis()
    periods = [_period("FY2024", revenue=1000.0)]  # za mało danych na wycenę
    score = compute_score(
        analysis=analysis, periods=periods, sector_profile="BANK",  # brak metody
        current_price=10.0, config=config,
    )
    report = render_markdown_report(
        ticker="XYZ", cik="0000000001", run_date="2026-09-25", current_price=10.0,
        analysis=analysis, score=score, config=config,
    )
    assert "PARTIAL" in report
    assert "NOT_YET_IMPLEMENTED" in report


def test_render_markdown_report_shows_hard_flag_candidates():
    config = load_config()
    analysis = _analysis(
        hard_flag_candidates=[
            {"type": "GOING_CONCERN", "evidence_source_id": "src-1", "quoted_text": "substantial doubt"},
        ],
    )
    periods = [_period("FY2024", revenue=1000.0)]
    score = compute_score(
        analysis=analysis, periods=periods, sector_profile="BANK",
        current_price=10.0, config=config,
    )
    report = render_markdown_report(
        ticker="XYZ", cik="0000000001", run_date="2026-09-25", current_price=10.0,
        analysis=analysis, score=score, config=config,
    )
    assert "GOING_CONCERN" in report
    assert "substantial doubt" in report


def test_render_markdown_report_omits_decline_and_sources_sections_when_not_provided():
    """Faza 6 GAP ANALYSIS: parametry nowe (opcjonalne, domyślnie None)
    nie zmieniają zachowania istniejących callerów (`cmd_score`)."""
    config = load_config()
    analysis = _analysis()
    periods = [_period("FY2024", revenue=1000.0)]
    score = compute_score(
        analysis=analysis, periods=periods, sector_profile="BANK",
        current_price=10.0, config=config,
    )
    report = render_markdown_report(
        ticker="XYZ", cik="0000000001", run_date="2026-09-25", current_price=10.0,
        analysis=analysis, score=score, config=config,
    )
    assert "Dlaczego spółka została wytypowana" not in report
    assert "## Źródła" not in report


def test_render_markdown_report_includes_decline_trigger_when_provided():
    config = load_config()
    analysis = _analysis()
    periods = [_period("FY2024", revenue=1000.0)]
    score = compute_score(
        analysis=analysis, periods=periods, sector_profile="BANK",
        current_price=10.0, config=config,
    )
    snapshot = PriceChangeSnapshot(
        as_of_date="2026-10-05", daily_pct=-6.0, week_pct=-9.0, month_pct=-12.0,
        quarter_pct=None, ytd_pct=None, year_pct=None,
        drawdown_from_52w_high_pct=-30.0, relative_volume=2.1,
    )
    report = render_markdown_report(
        ticker="XYZ", cik="0000000001", run_date="2026-09-25", current_price=10.0,
        analysis=analysis, score=score, config=config,
        decline_snapshot=snapshot, triggered_decline_flags={"month_decline": True, "daily_decline": False},
    )
    assert "Dlaczego spółka została wytypowana" in report
    assert "month_decline" in report
    assert "daily_decline" not in report.split("Dlaczego spółka została wytypowana")[1].split("## Wynik")[0]


def test_render_markdown_report_shows_anti_bias_fields():
    config = load_config()
    analysis = _analysis(
        bull_case=["Silny moat"], bear_case=["Rosnąca konkurencja"],
        why_market_may_be_right=["Marże strukturalnie pod presją"],
        why_this_may_not_be_a_bargain=["MoS oparty na optymistycznej CAGR"],
        thesis_invalidation=["Spadek marży brutto > 5pp r/r"],
        biggest_unknown="Wpływ nowej regulacji na pricing",
        verification_items=[{"source_id": "src-1", "document": "10-K", "question": "Sprawdź przypis X"}],
        cited_source_ids=["src-1"],
    )
    periods = [_period("FY2024", revenue=1000.0)]
    score = compute_score(
        analysis=analysis, periods=periods, sector_profile="BANK",
        current_price=10.0, config=config,
    )
    report = render_markdown_report(
        ticker="XYZ", cik="0000000001", run_date="2026-09-25", current_price=10.0,
        analysis=analysis, score=score, config=config,
    )
    assert "Silny moat" in report
    assert "Rosnąca konkurencja" in report
    assert "Marże strukturalnie pod presją" in report
    assert "MoS oparty na optymistycznej CAGR" in report
    assert "Spadek marży brutto > 5pp r/r" in report
    assert "Wpływ nowej regulacji na pricing" in report
    assert "Sprawdź przypis X" in report


def test_render_markdown_report_shows_source_not_verified():
    config = load_config()
    analysis = _analysis()
    periods = [_period("FY2024", revenue=1000.0)]
    score = compute_score(
        analysis=analysis, periods=periods, sector_profile="BANK",
        current_price=10.0, config=config,
    )
    packet = [
        VerifiedSource(
            source_type="SEC_FILING", title="10-K (2026-01-01)", issuer="XYZ Inc.",
            doc_date="2026-01-01", url="https://www.sec.gov/doc1.htm",
            accession_number="0001", section=None, content_hash="abc123def456",
            verified=True, reason=None,
        ),
        VerifiedSource(
            source_type="SEC_FILING", title="10-Q (2026-04-01)", issuer="XYZ Inc.",
            doc_date="2026-04-01", url="", accession_number="0002", section=None,
            content_hash=None, verified=False, reason="404 Not Found",
        ),
    ]
    report = render_markdown_report(
        ticker="XYZ", cik="0000000001", run_date="2026-09-25", current_price=10.0,
        analysis=analysis, score=score, config=config, source_packet=packet,
    )
    assert "## Źródła" in report
    assert "doc1.htm" in report
    assert "SOURCE NOT VERIFIED" in report
    assert "404 Not Found" in report


def test_render_markdown_report_sources_section_handles_empty_packet():
    config = load_config()
    analysis = _analysis()
    periods = [_period("FY2024", revenue=1000.0)]
    score = compute_score(
        analysis=analysis, periods=periods, sector_profile="BANK",
        current_price=10.0, config=config,
    )
    report = render_markdown_report(
        ticker="XYZ", cik="0000000001", run_date="2026-09-25", current_price=10.0,
        analysis=analysis, score=score, config=config, source_packet=[],
    )
    assert "## Źródła" in report
    assert "brak źródeł" in report

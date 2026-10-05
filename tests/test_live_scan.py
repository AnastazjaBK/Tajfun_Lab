"""Testy Fazy 6 (domknięcie MVP V0) — ranking kandydatów i finalny
raport live scanu. Czyste funkcje, zero sieci/Claude API (ten sam
wzorzec co test_report.py: `compute_score` na syntetycznych
`AnalysisOutput`/`FundamentalsPeriod`, żeby mieć realny `ScoreResult`
bez mockowania providerów)."""

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
from buffett_scanner.live_scan import LiveCandidate, rank_candidates, render_live_scan_report
from buffett_scanner.scanner import PriceChangeSnapshot
from buffett_scanner.scoring import compute_score


def _analysis(**overrides) -> AnalysisOutput:
    base = dict(
        ticker="AAPL", schema_version="1.0",
        business_understandability=ScoredSection(score=6, confidence="HIGH"),
        moat=MoatSection(score=8, confidence="MEDIUM"),
        financial_quality_commentary=FinancialQualityCommentary(confidence="HIGH", reasoning="ok"),
        management_capital_allocation=ManagementSection(score=7, confidence="MEDIUM"),
        fear_analysis=FearAnalysis(classification="UNCERTAIN", confidence="MEDIUM", trigger="x", reasoning="y"),
        dividend_trap_alert=DividendTrapAlert(triggered=False, reasoning=""),
        cited_source_ids=[],
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


def _snapshot() -> PriceChangeSnapshot:
    return PriceChangeSnapshot(
        as_of_date="2026-10-05", daily_pct=-6.0, week_pct=-9.0, month_pct=-12.0,
        quarter_pct=-15.0, ytd_pct=-20.0, year_pct=-10.0,
        drawdown_from_52w_high_pct=-30.0, relative_volume=2.1,
    )


def _candidate(ticker: str, *, sector_profile: str = "GENERAL", revenue: float = 1000.0) -> LiveCandidate:
    config = load_config()
    analysis = _analysis(ticker=ticker)
    periods = [
        _period("FY2023", revenue=revenue, net_income=50.0, ebitda=200.0, operating_cash_flow=150.0,
                capital_expenditure=20.0, total_debt=100.0, cash_and_equivalents=150.0,
                total_current_assets=400.0, total_current_liabilities=200.0,
                dividends_paid=10.0, share_buybacks=10.0, diluted_shares_outstanding=100.0),
        _period("FY2024", revenue=revenue * 1.1, net_income=70.0, ebitda=220.0, operating_cash_flow=170.0,
                capital_expenditure=20.0, total_debt=100.0, cash_and_equivalents=150.0,
                total_current_assets=400.0, total_current_liabilities=200.0,
                dividends_paid=12.0, share_buybacks=10.0, diluted_shares_outstanding=100.0),
    ]
    score = compute_score(
        analysis=analysis, periods=periods, sector_profile=sector_profile,
        current_price=15.0, config=config,
    )
    return LiveCandidate(
        ticker=ticker, cik=f"000000000{ticker[0]}", run_date="2026-10-05", current_price=15.0,
        decline_snapshot=_snapshot(), triggered_decline_flags={"month_decline": True},
        analysis=analysis, score=score, source_packet=[],
    )


def test_rank_candidates_sorts_complete_before_partial():
    complete = _candidate("AAPL", sector_profile="GENERAL")
    partial = _candidate("BANK", sector_profile="BANK")  # wycena NOT_YET_IMPLEMENTED -> total_score None
    assert complete.score.total_score is not None
    assert partial.score.total_score is None

    ranked = rank_candidates([partial, complete], limit=5)
    assert [c.ticker for c in ranked] == ["AAPL", "BANK"]


def test_rank_candidates_sorts_by_total_score_descending_within_complete():
    higher = _candidate("HIGH", sector_profile="GENERAL", revenue=2000.0)
    lower = _candidate("LOW", sector_profile="GENERAL", revenue=500.0)
    assert higher.score.total_score is not None and lower.score.total_score is not None

    ranked = rank_candidates([lower, higher], limit=5)
    assert [c.score.total_score for c in ranked] == sorted(
        (c.score.total_score for c in [lower, higher]), reverse=True
    )


def test_rank_candidates_limit_truncates_without_padding():
    candidates = [_candidate(f"T{i}") for i in range(7)]
    ranked = rank_candidates(candidates, limit=5)
    assert len(ranked) == 5


def test_rank_candidates_empty_input_is_valid():
    assert rank_candidates([], limit=5) == []


def test_render_live_scan_report_shows_no_qualifying_opportunities_when_empty():
    config = load_config()
    report = render_live_scan_report(
        run_date="2026-10-05", universe_size=503, decline_surfaced=0,
        prefilter_excluded=0, analysis_failed=0, candidates=[], config=config,
    )
    assert "No qualifying opportunities today" in report
    assert "0 kandydatów jest prawidłowym wynikiem" in report
    assert "503" in report


def test_render_live_scan_report_includes_audit_trail_and_candidate_detail():
    config = load_config()
    candidate = _candidate("AAPL")
    report = render_live_scan_report(
        run_date="2026-10-05", universe_size=503, decline_surfaced=12,
        prefilter_excluded=3, analysis_failed=2, candidates=[candidate], config=config,
    )
    assert "Uniwersum" in report and "503" in report
    assert "12" in report  # decline_surfaced
    assert "Kandydat 1: AAPL" in report
    assert "## Analiza jakościowa — anti-confirmation-bias" in report
    assert "Dlaczego spółka została wytypowana" in report
    assert "NIE kolejną rundą kalibracji" in report

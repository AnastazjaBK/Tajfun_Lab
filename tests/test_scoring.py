"""Testy silnika scoringu (Faza 4) — wartości referencyjne policzone
ręcznie, nie odtworzone z kodu pod testem."""

from __future__ import annotations

import pytest

from buffett_scanner.analysis_schema import (
    AnalysisOutput,
    DividendTrapAlert,
    FearAnalysis,
    FinancialQualityCommentary,
    ManagementSection,
    MoatSection,
    ScoredSection,
)
from buffett_scanner.config import (
    DcfOwnerEarningsConfig,
    DividendShareholderReturnConfig,
    DividendShareholderReturnWeights,
    FearOpportunityConfig,
    FinancialQualityConfig,
    FinancialQualityWeights,
    HardGatesConfig,
    ScenarioFloats,
    ScoringConfig,
    ScoringWeights,
    ValuationConfig,
    load_config,
)
from buffett_scanner.fundamentals import FundamentalsPeriod
from buffett_scanner.scoring import (
    business_quality_score,
    compute_score,
    evaluate_hard_gates,
    fear_opportunity_raw_points,
    financial_quality_score,
    valuation_score,
)


def make_period(
    fiscal_period: str,
    *,
    revenue=None, net_income=None, ebitda=None,
    operating_cash_flow=None, capital_expenditure=None,
    total_debt=None, cash_and_equivalents=None,
    total_current_assets=None, total_current_liabilities=None,
    dividends_paid=None, share_buybacks=None, diluted_shares_outstanding=None,
) -> FundamentalsPeriod:
    return FundamentalsPeriod(
        fiscal_period=fiscal_period, period_end_date=f"{fiscal_period}-12-31", filed_date=None,
        revenue=revenue, net_income=net_income, ebitda=ebitda,
        operating_cash_flow=operating_cash_flow, capital_expenditure=capital_expenditure,
        total_debt=total_debt, cash_and_equivalents=cash_and_equivalents,
        total_current_assets=total_current_assets, total_current_liabilities=total_current_liabilities,
        dividends_paid=dividends_paid, share_buybacks=share_buybacks,
        diluted_shares_outstanding=diluted_shares_outstanding,
    )


# ---------------------------------------------------------------------------
# financial_quality_score
# ---------------------------------------------------------------------------

def _app_config():
    return load_config()


def test_financial_quality_score_all_criteria_met():
    config = _app_config()
    periods = [
        # 3 okresy zyskowne pod rząd (lookback=3 w domyślnym configu)
        make_period("FY2022", revenue=900.0, net_income=50.0, ebitda=200.0,
                    operating_cash_flow=150.0, capital_expenditure=20.0,
                    total_debt=100.0, cash_and_equivalents=150.0,
                    total_current_assets=400.0, total_current_liabilities=200.0),
        make_period("FY2023", revenue=950.0, net_income=60.0, ebitda=210.0,
                    operating_cash_flow=160.0, capital_expenditure=20.0,
                    total_debt=100.0, cash_and_equivalents=150.0,
                    total_current_assets=400.0, total_current_liabilities=200.0),
        make_period("FY2024", revenue=1000.0, net_income=70.0, ebitda=220.0,
                    operating_cash_flow=170.0, capital_expenditure=20.0,
                    total_debt=100.0, cash_and_equivalents=150.0,
                    total_current_assets=400.0, total_current_liabilities=200.0),
    ]
    result = financial_quality_score(periods, config)
    # fcf = 170-20=150 > 0 -> fcf_positive
    # fcf_margin = 150/1000*100=15% >= 10% próg -> healthy
    # net_debt = 100-150=-50; net_debt_to_ebitda = -50/220 <= 2.0 próg -> low_leverage
    # current_ratio = 400/200=2.0 >= 1.5 próg -> good_liquidity
    # revenue_yoy = (1000-950)/950*100 > 0 -> positive_growth
    # 3 okresy zyskowne -> no_persistent_losses
    assert result.raw_score == pytest.approx(16.0)  # wszystkie kryteria = pełne 16 pkt
    assert all(result.breakdown.values())


def test_financial_quality_score_missing_data_never_credits():
    config = _app_config()
    periods = [make_period("FY2024")]  # same None
    result = financial_quality_score(periods, config)
    assert result.raw_score == pytest.approx(0.0)
    assert not any(result.breakdown.values())


def test_financial_quality_score_partial_credit():
    config = _app_config()
    periods = [make_period(
        "FY2024", revenue=1000.0, net_income=-10.0,  # strata -> no_persistent_losses zależy od >=3 okresów, tu 1 okres -> False
        ebitda=200.0, operating_cash_flow=50.0, capital_expenditure=100.0,  # FCF=-50 -> fcf_positive False, margin False
        total_debt=1000.0, cash_and_equivalents=0.0,  # wysoka dźwignia -> low_leverage False
        total_current_assets=100.0, total_current_liabilities=200.0,  # current_ratio=0.5 -> good_liquidity False
    )]
    result = financial_quality_score(periods, config)
    assert result.raw_score == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# business_quality_score
# ---------------------------------------------------------------------------

def _analysis(*, bu_score=7, moat_score=12, mgmt_score=10, fear_classification="TEMPORARY",
              fear_confidence="MEDIUM") -> AnalysisOutput:
    return AnalysisOutput(
        ticker="TEST", schema_version="1.0",
        business_understandability=ScoredSection(score=bu_score, confidence="HIGH"),
        moat=MoatSection(score=moat_score, confidence="MEDIUM"),
        financial_quality_commentary=FinancialQualityCommentary(confidence="MEDIUM", reasoning=""),
        management_capital_allocation=ManagementSection(score=mgmt_score, confidence="MEDIUM"),
        fear_analysis=FearAnalysis(
            classification=fear_classification, confidence=fear_confidence, trigger="x", reasoning="y",
        ),
        dividend_trap_alert=DividendTrapAlert(triggered=False, reasoning=""),
        cited_source_ids=[],
    )


def test_business_quality_score_full_marks():
    analysis = _analysis(bu_score=7, moat_score=12, mgmt_score=10)  # raw_sum=29=raw_max
    assert business_quality_score(analysis, weight=45.0) == pytest.approx(45.0)


def test_business_quality_score_zero():
    analysis = _analysis(bu_score=0, moat_score=0, mgmt_score=0)
    assert business_quality_score(analysis, weight=45.0) == pytest.approx(0.0)


def test_business_quality_score_partial():
    # raw_sum = 7 (tylko business_understandability na maksa) / raw_max 29 * waga 45
    analysis = _analysis(bu_score=7, moat_score=0, mgmt_score=0)
    expected = 7 * 45.0 / 29.0
    assert business_quality_score(analysis, weight=45.0) == pytest.approx(expected)


# ---------------------------------------------------------------------------
# fear_opportunity_raw_points
# ---------------------------------------------------------------------------

FEAR_CONFIG = FearOpportunityConfig(
    points_by_classification_confidence={
        "TEMPORARY": {"HIGH": 10, "MEDIUM": 7, "LOW": 4},
        "UNCERTAIN": {"HIGH": 6, "MEDIUM": 4, "LOW": 2},
        "STRUCTURAL": {"HIGH": 0, "MEDIUM": 1, "LOW": 2},
    },
)


class _FakeConfigForFear:
    fear_opportunity = FEAR_CONFIG


def test_fear_opportunity_temporary_high_confidence():
    analysis = _analysis(fear_classification="TEMPORARY", fear_confidence="HIGH")
    assert fear_opportunity_raw_points(analysis.fear_analysis, _FakeConfigForFear()) == 10


def test_fear_opportunity_structural_high_confidence():
    analysis = _analysis(fear_classification="STRUCTURAL", fear_confidence="HIGH")
    assert fear_opportunity_raw_points(analysis.fear_analysis, _FakeConfigForFear()) == 0


# ---------------------------------------------------------------------------
# valuation_score — mapowanie MoS (BASE) -> punkty
# ---------------------------------------------------------------------------

class _FakeConfigForValuation:
    class scoring:
        class weights:
            valuation = 20.0

    class valuation:
        class dcf_owner_earnings:
            mos_pct_for_full_score = 50.0


def test_valuation_score_none_when_mos_none():
    assert valuation_score(None, _FakeConfigForValuation()) is None


def test_valuation_score_zero_when_mos_non_positive():
    assert valuation_score(-5.0, _FakeConfigForValuation()) == pytest.approx(0.0)
    assert valuation_score(0.0, _FakeConfigForValuation()) == pytest.approx(0.0)


def test_valuation_score_full_when_mos_at_or_above_cap():
    assert valuation_score(50.0, _FakeConfigForValuation()) == pytest.approx(20.0)
    assert valuation_score(80.0, _FakeConfigForValuation()) == pytest.approx(20.0)


def test_valuation_score_linear_between():
    # 25% MoS / 50% cap * waga 20 = 10.0
    assert valuation_score(25.0, _FakeConfigForValuation()) == pytest.approx(10.0)


# ---------------------------------------------------------------------------
# evaluate_hard_gates
# ---------------------------------------------------------------------------

class _FakeConfigForGates:
    def __init__(self, hard_gates):
        self.hard_gates = hard_gates


def test_hard_gates_all_inactive_by_default_never_block():
    config = _FakeConfigForGates(HardGatesConfig())  # wszystkie None -> UNCALIBRATED, nieaktywne
    result = evaluate_hard_gates(
        business_quality=0.0, safety=0.0, margin_of_safety_base_pct=-100.0, config=config,
    )
    assert result.passed is True
    assert result.triggered == []


def test_hard_gates_business_quality_triggers():
    config = _FakeConfigForGates(HardGatesConfig(min_business_quality=30.0))
    result = evaluate_hard_gates(
        business_quality=20.0, safety=0.0, margin_of_safety_base_pct=None, config=config,
    )
    assert result.passed is False
    assert any("business_quality" in t for t in result.triggered)


def test_hard_gates_margin_of_safety_missing_triggers_when_gate_active():
    config = _FakeConfigForGates(HardGatesConfig(min_margin_of_safety_pct=10.0))
    result = evaluate_hard_gates(
        business_quality=100.0, safety=100.0, margin_of_safety_base_pct=None, config=config,
    )
    assert result.passed is False


def test_hard_gates_margin_of_safety_below_threshold_triggers():
    config = _FakeConfigForGates(HardGatesConfig(min_margin_of_safety_pct=20.0))
    result = evaluate_hard_gates(
        business_quality=100.0, safety=100.0, margin_of_safety_base_pct=10.0, config=config,
    )
    assert result.passed is False


# ---------------------------------------------------------------------------
# compute_score — integracja end-to-end na małym, w pełni skonstruowanym configu
# ---------------------------------------------------------------------------

def _minimal_full_config():
    """Odrębny, w pełni ręczny AppConfig (nie load_config()), żeby test
    integracyjny nie zależał od wartości w config.yaml, które mogą się
    zmienić przy kalibracji w Fazie 5."""
    from buffett_scanner.config import AppConfig

    base = load_config()
    return AppConfig(
        universe=base.universe,
        decline_scanner=base.decline_scanner,
        prefilter=base.prefilter,
        sources=base.sources,
        llm=base.llm,
        scoring=ScoringConfig(
            version="test",
            weights=ScoringWeights(
                business_quality=45, financial_safety=15, valuation=20,
                fear_opportunity=10, dividend_shareholder_return=10,
            ),
        ),
        financial_quality=FinancialQualityConfig(
            weights=FinancialQualityWeights(
                fcf_positive=3, fcf_margin_healthy=3, low_leverage=3,
                good_liquidity=3, positive_revenue_growth=2, no_persistent_losses=2,
            ),
            fcf_margin_healthy_threshold_pct=10.0,
            net_debt_to_ebitda_low_leverage_threshold=2.0,
            current_ratio_good_threshold=1.5,
            persistent_losses_lookback_years=2,
        ),
        fear_opportunity=FEAR_CONFIG,
        dividend_shareholder_return=DividendShareholderReturnConfig(
            weights=DividendShareholderReturnWeights(
                positive_shareholder_yield=3, no_dividend_cut=3,
                sustainable_payout_ratio=2, shrinking_or_flat_share_count=2,
            ),
            max_sustainable_payout_ratio_pct=75.0,
            min_shareholder_yield_pct=0.0,
        ),
        valuation=ValuationConfig(
            method_by_sector_profile={"GENERAL": "dcf_owner_earnings"},
            dcf_owner_earnings=DcfOwnerEarningsConfig(
                projection_years=1,
                discount_rate_pct=ScenarioFloats(bear=12.0, base=10.0, bull=8.0),
                terminal_growth_rate_pct=ScenarioFloats(bear=0.0, base=0.0, bull=0.0),
                historical_growth_multiplier=ScenarioFloats(bear=1.0, base=1.0, bull=1.0),
                max_projected_growth_rate_pct=20.0,
                min_projected_growth_rate_pct=-5.0,
                mos_pct_for_full_score=50.0,
            ),
        ),
        hard_gates=HardGatesConfig(),
        data_provider=base.data_provider,
    )


def test_compute_score_full_credit_everywhere_sums_to_100():
    config = _minimal_full_config()
    analysis = _analysis(bu_score=7, moat_score=12, mgmt_score=10,
                          fear_classification="TEMPORARY", fear_confidence="HIGH")
    periods = [
        make_period("FY2023", revenue=900.0, net_income=50.0, ebitda=200.0,
                    operating_cash_flow=150.0, capital_expenditure=20.0,
                    total_debt=0.0, cash_and_equivalents=0.0,
                    total_current_assets=400.0, total_current_liabilities=200.0,
                    dividends_paid=10.0, share_buybacks=10.0, diluted_shares_outstanding=100.0),
        make_period("FY2024", revenue=1000.0, net_income=70.0, ebitda=220.0,
                    operating_cash_flow=150.0, capital_expenditure=20.0,  # FCF płaski=130 -> CAGR=0
                    total_debt=0.0, cash_and_equivalents=0.0,
                    total_current_assets=400.0, total_current_liabilities=200.0,
                    dividends_paid=10.0, share_buybacks=10.0, diluted_shares_outstanding=100.0),
    ]
    result = compute_score(
        analysis=analysis, periods=periods, sector_profile="GENERAL",
        current_price=1.0,  # bardzo nisko -> wysoki MoS -> pełne 20 pkt valuation
        config=config,
    )
    assert result.is_partial is False
    assert result.business_quality_score == pytest.approx(45.0)
    assert result.safety_score == pytest.approx(15.0)  # financial_quality 16/16 -> pełne 15
    assert result.fear_score == pytest.approx(10.0)  # TEMPORARY/HIGH = 10/10 -> pełne 10
    assert result.valuation_score == pytest.approx(20.0)  # cena=1.0 << intrinsic -> MoS >= cap
    assert result.total_score == pytest.approx(
        result.business_quality_score + result.safety_score + result.valuation_score
        + result.fear_score + result.dividend_score
    )
    assert result.total_score <= 100.0 + 1e-6


def test_compute_score_partial_when_valuation_not_implemented():
    config = _minimal_full_config()
    analysis = _analysis()
    periods = [make_period("FY2024", revenue=1000.0)]  # za mało danych na wycenę
    result = compute_score(
        analysis=analysis, periods=periods, sector_profile="BANK",  # brak metody -> NOT_YET_IMPLEMENTED
        current_price=10.0, config=config,
    )
    assert result.is_partial is True
    assert "valuation" in result.missing_components
    assert result.total_score is None
    assert result.valuation_result.implemented is False

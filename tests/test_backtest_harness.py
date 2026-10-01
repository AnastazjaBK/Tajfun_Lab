"""Testy deterministycznego walk-forward backtest harnessu (Faza 5.3,
sekcja 13, zaprojektowany i zatwierdzony przez właścicielkę 2026-10-01).
Wartości referencyjne policzone ręcznie, nie odtworzone z kodu pod testem."""

from __future__ import annotations

import pytest

from buffett_scanner.backtest_harness import (
    BacktestFunnelResult,
    add_months,
    attach_forward_returns,
    compute_deterministic_score,
    compute_forward_returns,
    evaluate_candidate_at_date,
    evaluate_deterministic_hard_gates,
    forward_return_pct,
    generate_rebalance_dates,
)
from buffett_scanner.config import (
    AppConfig,
    DcfOwnerEarningsConfig,
    DeclineScannerConfig,
    DeclineScannerThresholds,
    DividendShareholderReturnConfig,
    DividendShareholderReturnWeights,
    FearOpportunityConfig,
    FinancialQualityConfig,
    FinancialQualityWeights,
    HardGatesConfig,
    PrefilterConfig,
    PrefilterRule,
    ScenarioFloats,
    ScoringConfig,
    ScoringWeights,
    ValuationConfig,
    load_config,
)
from buffett_scanner.fundamentals import FundamentalsPeriod
from buffett_scanner.scanner import PriceBar


def _period(fiscal_period, end_date, filed_date, **kw) -> FundamentalsPeriod:
    defaults = dict(
        revenue=None, net_income=None, ebitda=None, operating_cash_flow=None,
        capital_expenditure=None, total_debt=None, cash_and_equivalents=None,
        total_current_assets=None, total_current_liabilities=None,
        dividends_paid=None, share_buybacks=None, diluted_shares_outstanding=None,
    )
    defaults.update(kw)
    return FundamentalsPeriod(
        fiscal_period=fiscal_period, period_end_date=end_date, filed_date=filed_date, **defaults
    )


def _bar(date, close) -> PriceBar:
    return PriceBar(date=date, open=close, high=close, low=close, close=close, adj_close=close, volume=1000)


def _config(*, hard_gates=None, prefilter=None, decline_thresholds=None) -> AppConfig:
    base = load_config()
    return AppConfig(
        universe=base.universe,
        decline_scanner=DeclineScannerConfig(
            thresholds=decline_thresholds or DeclineScannerThresholds(
                daily_pct=-5.0, week_pct=-10.0, month_pct=-15.0, quarter_pct=-20.0,
                drawdown_from_52w_high_pct=-20.0, relative_volume_multiple=2.0,
            ),
        ),
        prefilter=prefilter or PrefilterConfig(),
        sources=base.sources,
        llm=base.llm,
        scoring=ScoringConfig(
            version="test-v1",
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
        fear_opportunity=FearOpportunityConfig(
            points_by_classification_confidence={
                "TEMPORARY": {"HIGH": 10, "MEDIUM": 7, "LOW": 4},
                "UNCERTAIN": {"HIGH": 6, "MEDIUM": 4, "LOW": 2},
                "STRUCTURAL": {"HIGH": 0, "MEDIUM": 1, "LOW": 2},
            },
        ),
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
        hard_gates=hard_gates or HardGatesConfig(),
        data_provider=base.data_provider,
        backtest=base.backtest,
    )


# ---------------------------------------------------------------------------
# generate_rebalance_dates / add_months
# ---------------------------------------------------------------------------


def test_generate_rebalance_dates_monthly():
    dates = generate_rebalance_dates("2012-01-15", "2012-04-01", "MONTHLY")
    assert dates == ["2012-02-01", "2012-03-01", "2012-04-01"]


def test_generate_rebalance_dates_monthly_starts_on_first_of_month():
    dates = generate_rebalance_dates("2012-01-01", "2012-03-01", "MONTHLY")
    assert dates == ["2012-01-01", "2012-02-01", "2012-03-01"]


def test_generate_rebalance_dates_quarterly():
    dates = generate_rebalance_dates("2012-01-01", "2012-10-01", "QUARTERLY")
    assert dates == ["2012-01-01", "2012-04-01", "2012-07-01", "2012-10-01"]


def test_generate_rebalance_dates_empty_when_start_after_end():
    assert generate_rebalance_dates("2012-06-01", "2012-01-01", "MONTHLY") == []


def test_generate_rebalance_dates_crosses_year_boundary():
    dates = generate_rebalance_dates("2012-11-15", "2013-02-01", "MONTHLY")
    assert dates == ["2012-12-01", "2013-01-01", "2013-02-01"]


def test_add_months_basic():
    assert add_months("2012-01-15", 1) == "2012-02-15"
    assert add_months("2012-01-15", 12) == "2013-01-15"


def test_add_months_clamps_day_to_shorter_month():
    assert add_months("2024-01-31", 1) == "2024-02-29"  # 2024 przestępny
    assert add_months("2023-01-31", 1) == "2023-02-28"  # 2023 nie


# ---------------------------------------------------------------------------
# forward_return_pct / compute_forward_returns
# ---------------------------------------------------------------------------


def test_forward_return_pct_basic():
    bars = [_bar("2012-01-01", 100.0), _bar("2012-02-05", 110.0)]
    result = forward_return_pct(bars, "2012-01-01", 100.0, horizon_months=1)
    assert result == pytest.approx(10.0)


def test_forward_return_pct_none_when_insufficient_future_data():
    bars = [_bar("2012-01-01", 100.0)]
    assert forward_return_pct(bars, "2012-01-01", 100.0, horizon_months=1) is None


def test_forward_return_pct_none_for_nonpositive_decision_price():
    bars = [_bar("2012-01-01", 100.0), _bar("2012-02-05", 110.0)]
    assert forward_return_pct(bars, "2012-01-01", 0.0, horizon_months=1) is None
    assert forward_return_pct(bars, "2012-01-01", -5.0, horizon_months=1) is None


def test_forward_return_pct_picks_first_bar_on_or_after_target():
    bars = [_bar("2012-01-01", 100.0), _bar("2012-02-10", 105.0), _bar("2012-02-20", 120.0)]
    # target = 2012-02-01; pierwszy bar >= target to 2012-02-10 (105), nie 2012-02-20
    result = forward_return_pct(bars, "2012-01-01", 100.0, horizon_months=1)
    assert result == pytest.approx(5.0)


def test_compute_forward_returns_all_horizons():
    bars = [
        _bar("2012-01-01", 100.0),
        _bar("2012-02-01", 110.0),
        _bar("2012-04-01", 90.0),
        _bar("2012-07-01", 130.0),
        _bar("2013-01-01", 150.0),
    ]
    result = compute_forward_returns(bars, "2012-01-01", 100.0)
    assert result.return_1m_pct == pytest.approx(10.0)
    assert result.return_3m_pct == pytest.approx(-10.0)
    assert result.return_6m_pct == pytest.approx(30.0)
    assert result.return_12m_pct == pytest.approx(50.0)


def test_compute_forward_returns_missing_horizon_is_none_not_zero():
    bars = [_bar("2012-01-01", 100.0), _bar("2012-02-01", 110.0)]
    result = compute_forward_returns(bars, "2012-01-01", 100.0)
    assert result.return_1m_pct == pytest.approx(10.0)
    assert result.return_3m_pct is None
    assert result.return_6m_pct is None
    assert result.return_12m_pct is None


# ---------------------------------------------------------------------------
# compute_deterministic_score
# ---------------------------------------------------------------------------


def test_compute_deterministic_score_all_components_available():
    config = _config()
    periods = [
        _period("FY2023", "2023-12-31", "2024-02-01", revenue=900.0, net_income=50.0, ebitda=100.0,
                operating_cash_flow=150.0, capital_expenditure=20.0,
                total_debt=0.0, cash_and_equivalents=0.0,
                total_current_assets=400.0, total_current_liabilities=200.0,
                dividends_paid=10.0, diluted_shares_outstanding=100.0),
        _period("FY2024", "2024-12-31", "2025-02-01", revenue=1000.0, net_income=70.0, ebitda=110.0,
                operating_cash_flow=150.0, capital_expenditure=20.0,
                total_debt=0.0, cash_and_equivalents=0.0,
                total_current_assets=400.0, total_current_liabilities=200.0,
                dividends_paid=10.0, diluted_shares_outstanding=100.0),
    ]
    result = compute_deterministic_score(
        periods=periods, sector_profile="GENERAL", current_price=1.0, config=config,
    )
    assert result.full_score is None
    assert result.available_components == ("safety", "valuation", "dividend")
    assert result.missing_components == ("business_quality", "fear")
    # safety: financial_quality 16/16 (fcf+, margin>=10%, leverage 0<=2, liquidity 2>=1.5,
    # growth 1000>900, no persistent losses) -> 16/16*15 = 15.0
    assert result.safety_score == pytest.approx(15.0)
    # cena=1.0, bardzo nisko -> MoS >= cap -> pełne 20 pkt
    assert result.valuation_score == pytest.approx(20.0)
    expected_points = result.safety_score + result.valuation_score + result.dividend_score
    assert result.deterministic_partial_score == pytest.approx(expected_points)
    expected_max = 15.0 + 20.0 + 10.0
    assert result.deterministic_score_pct == pytest.approx(expected_points / expected_max * 100)


def test_compute_deterministic_score_valuation_unavailable_excluded_from_both_sides():
    config = _config()
    periods = [_period("FY2024", "2024-12-31", "2025-02-01", revenue=1000.0, net_income=70.0)]
    result = compute_deterministic_score(
        periods=periods, sector_profile="BANK",  # brak zaimplementowanej metody -> NOT_YET_IMPLEMENTED
        current_price=10.0, config=config,
    )
    assert result.valuation_score is None
    assert "valuation" in result.missing_components
    assert result.available_components == ("safety", "dividend")
    expected_max = 15.0 + 10.0  # BEZ 20 pkt valuation w mianowniku
    expected_points = result.safety_score + result.dividend_score
    assert result.deterministic_score_pct == pytest.approx(expected_points / expected_max * 100)


# ---------------------------------------------------------------------------
# evaluate_deterministic_hard_gates
# ---------------------------------------------------------------------------


def test_deterministic_hard_gates_never_check_business_quality():
    """Kontrola architektoniczna: nawet jeśli min_business_quality jest
    ustawiony w configu, ta funkcja go IGNORUJE (nie ma historycznego
    LLM output, żeby to ocenić) — to jedyna różnica względem
    scoring.evaluate_hard_gates."""
    config = _config(hard_gates=HardGatesConfig(min_business_quality=999.0))
    result = evaluate_deterministic_hard_gates(
        safety=15.0, margin_of_safety_base_pct=50.0, config=config,
    )
    assert result.passed is True
    assert result.triggered == []


def test_deterministic_hard_gates_safety_gate_triggers():
    config = _config(hard_gates=HardGatesConfig(min_financial_safety=10.0))
    result = evaluate_deterministic_hard_gates(
        safety=5.0, margin_of_safety_base_pct=None, config=config,
    )
    assert result.passed is False
    assert any("safety" in t for t in result.triggered)


def test_deterministic_hard_gates_margin_of_safety_gate_triggers_on_none():
    config = _config(hard_gates=HardGatesConfig(min_margin_of_safety_pct=10.0))
    result = evaluate_deterministic_hard_gates(
        safety=15.0, margin_of_safety_base_pct=None, config=config,
    )
    assert result.passed is False


def test_deterministic_hard_gates_pass_when_all_satisfied():
    config = _config(hard_gates=HardGatesConfig(min_financial_safety=5.0, min_margin_of_safety_pct=10.0))
    result = evaluate_deterministic_hard_gates(
        safety=15.0, margin_of_safety_base_pct=20.0, config=config,
    )
    assert result.passed is True


# ---------------------------------------------------------------------------
# evaluate_candidate_at_date — pełny funnel
# ---------------------------------------------------------------------------


def _full_periods():
    return [
        _period("FY2023", "2023-12-31", "2024-02-01", revenue=900.0, net_income=50.0, ebitda=100.0,
                operating_cash_flow=150.0, capital_expenditure=20.0,
                total_debt=0.0, cash_and_equivalents=0.0,
                total_current_assets=400.0, total_current_liabilities=200.0,
                diluted_shares_outstanding=100.0),
        _period("FY2024", "2024-12-31", "2025-02-01", revenue=1000.0, net_income=70.0, ebitda=110.0,
                operating_cash_flow=150.0, capital_expenditure=20.0,
                total_debt=0.0, cash_and_equivalents=0.0,
                total_current_assets=400.0, total_current_liabilities=200.0,
                diluted_shares_outstanding=100.0),
    ]


def _decline_bars():
    # spadek dzienny z -10% << próg -5.0 -> daily_decline=True
    return [_bar("2025-02-27", 100.0), _bar("2025-02-28", 90.0)]


def test_evaluate_candidate_no_fundamentals_when_periods_empty():
    config = _config()
    result = evaluate_candidate_at_date(
        cik="0001", ticker_as_of_date="AAA", decision_date="2025-03-01",
        bars=_decline_bars(), periods=[], sector_profile="GENERAL",
        config=config, run_id="run1", config_version="cfgv1", universe_provenance="prov1",
    )
    assert result.stage == "NO_FUNDAMENTALS"
    assert result.candidate is None


def test_evaluate_candidate_no_decline_signal_when_prices_flat():
    config = _config()
    flat_bars = [_bar("2025-02-27", 100.0), _bar("2025-02-28", 100.0)]
    result = evaluate_candidate_at_date(
        cik="0001", ticker_as_of_date="AAA", decision_date="2025-03-01",
        bars=flat_bars, periods=_full_periods(), sector_profile="GENERAL",
        config=config, run_id="run1", config_version="cfgv1", universe_provenance="prov1",
    )
    assert result.stage == "NO_DECLINE_SIGNAL"
    assert result.candidate is None
    assert any(result.decline_flags.values()) is False


def test_evaluate_candidate_excluded_by_prefilter():
    prefilter = PrefilterConfig(
        exclude_rules=[PrefilterRule(metric="revenue_yoy_growth_pct", condition="negative", reason="spadek przychodów")],
    )
    config = _config(prefilter=prefilter)
    declining_revenue_periods = [
        _period("FY2023", "2023-12-31", "2024-02-01", revenue=1000.0, net_income=50.0),
        _period("FY2024", "2024-12-31", "2025-02-01", revenue=900.0, net_income=70.0),  # spadek
    ]
    result = evaluate_candidate_at_date(
        cik="0001", ticker_as_of_date="AAA", decision_date="2025-03-01",
        bars=_decline_bars(), periods=declining_revenue_periods, sector_profile="GENERAL",
        config=config, run_id="run1", config_version="cfgv1", universe_provenance="prov1",
    )
    assert result.stage == "EXCLUDED_BY_PREFILTER"
    assert result.candidate is None
    assert "spadek przychodów" in result.prefilter_result.excludes


def test_evaluate_candidate_hard_gate_failed():
    config = _config(hard_gates=HardGatesConfig(min_financial_safety=100.0))  # niemożliwe do spełnienia
    result = evaluate_candidate_at_date(
        cik="0001", ticker_as_of_date="AAA", decision_date="2025-03-01",
        bars=_decline_bars(), periods=_full_periods(), sector_profile="GENERAL",
        config=config, run_id="run1", config_version="cfgv1", universe_provenance="prov1",
    )
    assert result.stage == "HARD_GATE_FAILED"
    assert result.candidate is None
    assert result.score is not None  # score policzony, tylko kandydat odrzucony


def test_evaluate_candidate_becomes_full_candidate():
    config = _config()
    result = evaluate_candidate_at_date(
        cik="0001156039", ticker_as_of_date="ELV", decision_date="2025-03-01",
        bars=_decline_bars(), periods=_full_periods(), sector_profile="GENERAL",
        config=config, run_id="run-xyz", config_version="cfgv1", universe_provenance="CURATED_ALLOWLIST",
    )
    assert result.stage == "CANDIDATE"
    c = result.candidate
    assert c is not None
    assert c.cik == "0001156039"
    assert c.ticker_as_of_date == "ELV"
    assert c.decision_date == "2025-03-01"
    assert c.decision_price == 90.0  # ostatni bar <= decision_date
    assert c.full_score is None
    assert c.missing_components == ("business_quality", "fear")
    assert c.hard_gate_passed is True
    assert c.run_id == "run-xyz"
    assert c.config_version == "cfgv1"
    assert c.scoring_version == "test-v1"
    assert c.universe_provenance == "CURATED_ALLOWLIST"
    assert c.forward_returns is None  # jeszcze nie dołączone


def test_attach_forward_returns_only_touches_forward_returns_field():
    config = _config()
    result = evaluate_candidate_at_date(
        cik="0001", ticker_as_of_date="AAA", decision_date="2025-03-01",
        bars=_decline_bars(), periods=_full_periods(), sector_profile="GENERAL",
        config=config, run_id="run1", config_version="cfgv1", universe_provenance="prov1",
    )
    candidate = result.candidate
    future_bars = _decline_bars() + [_bar("2025-04-05", 99.0)]
    updated = attach_forward_returns(candidate, future_bars)
    assert updated.forward_returns.return_1m_pct == pytest.approx((99.0 / 90.0 - 1) * 100)
    # nic innego się nie zmieniło
    assert updated.safety_score == candidate.safety_score
    assert updated.hard_gate_passed == candidate.hard_gate_passed
    assert updated.decision_price == candidate.decision_price

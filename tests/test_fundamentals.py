"""Testy jednostkowe silnika wskaźników fundamentalnych — wartości
referencyjne policzone ręcznie, nie odtworzone z kodu pod testem.

Konwencja: periods[-1] to najnowszy okres. Zero I/O, zero LLM.
"""

import pytest

from buffett_scanner.config import PrefilterConfig, PrefilterRule
from buffett_scanner.fundamentals import (
    FundamentalsPeriod,
    compute_metrics,
    current_ratio,
    evaluate_prefilter,
    fcf_margin_pct,
    free_cash_flow,
    net_debt,
    net_debt_to_ebitda,
    persistent_negative_fcf,
    persistent_net_losses,
    revenue_yoy_growth_pct,
)


def make_period(
    fiscal_period: str,
    *,
    revenue=None,
    net_income=None,
    ebitda=None,
    operating_cash_flow=None,
    capital_expenditure=None,
    total_debt=None,
    cash_and_equivalents=None,
    total_current_assets=None,
    total_current_liabilities=None,
) -> FundamentalsPeriod:
    return FundamentalsPeriod(
        fiscal_period=fiscal_period,
        period_end_date=f"{fiscal_period}-12-31",
        filed_date=f"{fiscal_period}-12-31",
        revenue=revenue,
        net_income=net_income,
        ebitda=ebitda,
        operating_cash_flow=operating_cash_flow,
        capital_expenditure=capital_expenditure,
        total_debt=total_debt,
        cash_and_equivalents=cash_and_equivalents,
        total_current_assets=total_current_assets,
        total_current_liabilities=total_current_liabilities,
    )


# ---------------------------------------------------------------------------
# Pojedyncze wskaźniki — wartości ręcznie policzone
# ---------------------------------------------------------------------------

def test_free_cash_flow_is_ocf_minus_capex():
    p = make_period("FY2024", operating_cash_flow=1000.0, capital_expenditure=300.0)
    assert free_cash_flow(p) == pytest.approx(700.0)


def test_free_cash_flow_none_when_capex_missing():
    p = make_period("FY2024", operating_cash_flow=1000.0)
    assert free_cash_flow(p) is None


def test_net_debt_is_total_debt_minus_cash():
    p = make_period("FY2024", total_debt=500.0, cash_and_equivalents=200.0)
    assert net_debt(p) == pytest.approx(300.0)


def test_net_debt_to_ebitda():
    p = make_period("FY2024", total_debt=500.0, cash_and_equivalents=200.0, ebitda=150.0)
    assert net_debt_to_ebitda(p) == pytest.approx(2.0)


def test_net_debt_to_ebitda_none_when_ebitda_zero():
    p = make_period("FY2024", total_debt=500.0, cash_and_equivalents=200.0, ebitda=0.0)
    assert net_debt_to_ebitda(p) is None


def test_net_debt_to_ebitda_none_when_ebitda_missing():
    p = make_period("FY2024", total_debt=500.0, cash_and_equivalents=200.0)
    assert net_debt_to_ebitda(p) is None


def test_current_ratio():
    p = make_period("FY2024", total_current_assets=400.0, total_current_liabilities=200.0)
    assert current_ratio(p) == pytest.approx(2.0)


def test_current_ratio_none_when_liabilities_zero():
    p = make_period("FY2024", total_current_assets=400.0, total_current_liabilities=0.0)
    assert current_ratio(p) is None


def test_fcf_margin_pct():
    p = make_period(
        "FY2024", operating_cash_flow=1000.0, capital_expenditure=300.0, revenue=10000.0
    )
    assert fcf_margin_pct(p) == pytest.approx(7.0)  # 700/10000*100


def test_fcf_margin_pct_none_when_revenue_zero():
    p = make_period("FY2024", operating_cash_flow=1000.0, capital_expenditure=300.0, revenue=0.0)
    assert fcf_margin_pct(p) is None


def test_revenue_yoy_growth_pct():
    current = make_period("FY2024", revenue=110.0)
    prior = make_period("FY2023", revenue=100.0)
    assert revenue_yoy_growth_pct(current, prior) == pytest.approx(10.0)


def test_revenue_yoy_growth_pct_none_when_prior_revenue_missing():
    current = make_period("FY2024", revenue=110.0)
    prior = make_period("FY2023")
    assert revenue_yoy_growth_pct(current, prior) is None


# ---------------------------------------------------------------------------
# Sygnały wieloletnie — nigdy nie fabrykują wyniku przy brakujących danych
# ---------------------------------------------------------------------------

def test_persistent_negative_fcf_true_when_all_periods_negative():
    periods = [
        make_period("FY2022", operating_cash_flow=-100.0, capital_expenditure=50.0),
        make_period("FY2023", operating_cash_flow=-80.0, capital_expenditure=40.0),
        make_period("FY2024", operating_cash_flow=-50.0, capital_expenditure=30.0),
    ]
    assert persistent_negative_fcf(periods, lookback=3) is True


def test_persistent_negative_fcf_false_when_not_enough_periods():
    periods = [
        make_period("FY2023", operating_cash_flow=-80.0, capital_expenditure=40.0),
        make_period("FY2024", operating_cash_flow=-50.0, capital_expenditure=30.0),
    ]
    assert persistent_negative_fcf(periods, lookback=3) is False


def test_persistent_negative_fcf_false_when_one_period_missing_data():
    periods = [
        make_period("FY2022", operating_cash_flow=-100.0, capital_expenditure=50.0),
        make_period("FY2023", operating_cash_flow=-80.0),  # capex brak -> fcf None
        make_period("FY2024", operating_cash_flow=-50.0, capital_expenditure=30.0),
    ]
    assert persistent_negative_fcf(periods, lookback=3) is False


def test_persistent_negative_fcf_false_when_one_period_positive():
    periods = [
        make_period("FY2022", operating_cash_flow=-100.0, capital_expenditure=50.0),
        make_period("FY2023", operating_cash_flow=200.0, capital_expenditure=40.0),
        make_period("FY2024", operating_cash_flow=-50.0, capital_expenditure=30.0),
    ]
    assert persistent_negative_fcf(periods, lookback=3) is False


def test_persistent_net_losses_true_when_all_periods_negative():
    periods = [
        make_period("FY2022", net_income=-10.0),
        make_period("FY2023", net_income=-5.0),
    ]
    assert persistent_net_losses(periods, lookback=2) is True


def test_persistent_net_losses_false_when_missing_data():
    periods = [
        make_period("FY2022", net_income=-10.0),
        make_period("FY2023"),
    ]
    assert persistent_net_losses(periods, lookback=2) is False


# ---------------------------------------------------------------------------
# compute_metrics — dict dla najnowszego okresu
# ---------------------------------------------------------------------------

def test_compute_metrics_uses_latest_period_and_prior_for_yoy():
    prior = make_period("FY2023", revenue=100.0)
    latest = make_period(
        "FY2024",
        revenue=110.0,
        operating_cash_flow=1000.0,
        capital_expenditure=300.0,
        total_debt=500.0,
        cash_and_equivalents=200.0,
        ebitda=150.0,
        total_current_assets=400.0,
        total_current_liabilities=200.0,
    )
    metrics = compute_metrics([prior, latest])
    assert metrics["fcf_ttm"] == pytest.approx(700.0)
    assert metrics["net_debt_to_ebitda"] == pytest.approx(2.0)
    assert metrics["current_ratio"] == pytest.approx(2.0)
    assert metrics["fcf_margin_pct"] == pytest.approx(700.0 / 110.0 * 100.0)
    assert metrics["revenue_yoy_growth_pct"] == pytest.approx(10.0)


def test_compute_metrics_revenue_yoy_none_with_single_period():
    latest = make_period("FY2024", revenue=110.0)
    metrics = compute_metrics([latest])
    assert metrics["revenue_yoy_growth_pct"] is None


def test_compute_metrics_requires_at_least_one_period():
    with pytest.raises(ValueError):
        compute_metrics([])


# ---------------------------------------------------------------------------
# evaluate_prefilter — reguły FLAG/EXCLUDE, missing metric nigdy nie odpala
# ---------------------------------------------------------------------------

SAMPLE_CONFIG = PrefilterConfig(
    flag_rules=[
        PrefilterRule(metric="fcf_ttm", condition="negative", reason="Ujemny FCF"),
        PrefilterRule(
            metric="revenue_yoy_growth_pct", condition="below", threshold=0.0,
            reason="Malejące przychody",
        ),
    ],
    exclude_rules=[
        PrefilterRule(
            metric="current_ratio", condition="below", threshold=0.5,
            reason="Krytycznie niska płynność",
        ),
    ],
)


def test_evaluate_prefilter_flags_negative_fcf_without_blocking():
    metrics = {"fcf_ttm": -10.0, "revenue_yoy_growth_pct": 5.0, "current_ratio": 2.0}
    result = evaluate_prefilter(metrics, SAMPLE_CONFIG)
    assert result.flags == ["Ujemny FCF"]
    assert result.excludes == []
    assert result.passed is True  # FLAG nigdy nie blokuje samo w sobie (BLOCKER 5)


def test_evaluate_prefilter_exclude_blocks():
    metrics = {"fcf_ttm": 10.0, "revenue_yoy_growth_pct": 5.0, "current_ratio": 0.3}
    result = evaluate_prefilter(metrics, SAMPLE_CONFIG)
    assert result.excludes == ["Krytycznie niska płynność"]
    assert result.passed is False


def test_evaluate_prefilter_missing_metric_never_triggers():
    metrics = {"fcf_ttm": None, "revenue_yoy_growth_pct": None, "current_ratio": None}
    result = evaluate_prefilter(metrics, SAMPLE_CONFIG)
    assert result.flags == []
    assert result.excludes == []
    assert result.passed is True

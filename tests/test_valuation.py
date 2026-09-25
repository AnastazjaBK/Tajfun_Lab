"""Testy silnika wyceny (DCF na Owner Earnings) — wartości referencyjne
policzone ręcznie, nie odtworzone z kodu pod testem."""

from __future__ import annotations

import pytest

from buffett_scanner.config import DcfOwnerEarningsConfig, ScenarioFloats, ValuationConfig
from buffett_scanner.fundamentals import FundamentalsPeriod
from buffett_scanner.valuation import (
    ValuationResult,
    compute_valuation,
    historical_owner_earnings_cagr_pct,
    owner_earnings_proxy_fcf,
)


def make_period(
    fiscal_period: str,
    *,
    operating_cash_flow=None,
    capital_expenditure=None,
    total_debt=None,
    cash_and_equivalents=None,
    diluted_shares_outstanding=None,
) -> FundamentalsPeriod:
    return FundamentalsPeriod(
        fiscal_period=fiscal_period,
        period_end_date=f"{fiscal_period}-12-31",
        filed_date=None,
        revenue=None, net_income=None, ebitda=None,
        operating_cash_flow=operating_cash_flow,
        capital_expenditure=capital_expenditure,
        total_debt=total_debt,
        cash_and_equivalents=cash_and_equivalents,
        total_current_assets=None, total_current_liabilities=None,
        diluted_shares_outstanding=diluted_shares_outstanding,
    )


# ---------------------------------------------------------------------------
# owner_earnings_proxy_fcf / historical_owner_earnings_cagr_pct
# ---------------------------------------------------------------------------

def test_owner_earnings_proxy_fcf_is_explicitly_named_fcf_alias():
    p = make_period("FY2024", operating_cash_flow=1000.0, capital_expenditure=300.0)
    assert owner_earnings_proxy_fcf(p) == pytest.approx(700.0)


def test_historical_cagr_two_periods():
    periods = [
        make_period("FY2023", operating_cash_flow=100.0, capital_expenditure=0.0),  # FCF=100
        make_period("FY2024", operating_cash_flow=121.0, capital_expenditure=0.0),  # FCF=121
    ]
    # CAGR = (121/100)^(1/1) - 1 = 0.21 -> 21%
    assert historical_owner_earnings_cagr_pct(periods) == pytest.approx(21.0)


def test_historical_cagr_three_periods():
    periods = [
        make_period("FY2022", operating_cash_flow=100.0, capital_expenditure=0.0),
        make_period("FY2023", operating_cash_flow=120.0, capital_expenditure=0.0),
        make_period("FY2024", operating_cash_flow=144.0, capital_expenditure=0.0),  # FCF=144
    ]
    # CAGR = (144/100)^(1/2) - 1 = sqrt(1.44) - 1 = 1.2 - 1 = 0.20 -> 20%
    assert historical_owner_earnings_cagr_pct(periods) == pytest.approx(20.0)


def test_historical_cagr_none_with_single_period():
    periods = [make_period("FY2024", operating_cash_flow=100.0, capital_expenditure=0.0)]
    assert historical_owner_earnings_cagr_pct(periods) is None


def test_historical_cagr_none_when_base_non_positive():
    periods = [
        make_period("FY2023", operating_cash_flow=-10.0, capital_expenditure=0.0),  # FCF=-10
        make_period("FY2024", operating_cash_flow=100.0, capital_expenditure=0.0),
    ]
    assert historical_owner_earnings_cagr_pct(periods) is None


def test_historical_cagr_none_when_end_non_positive():
    periods = [
        make_period("FY2023", operating_cash_flow=100.0, capital_expenditure=0.0),
        make_period("FY2024", operating_cash_flow=0.0, capital_expenditure=0.0),  # FCF=0
    ]
    assert historical_owner_earnings_cagr_pct(periods) is None


# ---------------------------------------------------------------------------
# compute_valuation — NOT_YET_IMPLEMENTED ścieżki
# ---------------------------------------------------------------------------

def _flat_growth_config(*, discount_bear=12.0, discount_base=10.0, discount_bull=8.0) -> ValuationConfig:
    """Config testowy: terminal_growth=0 i multiplier=1.0 dla wszystkich
    scenariuszy -> przy CAGR=0 (płaski FCF) projected_growth=0 dla
    wszystkich -> enterprise_value staje się czystą perpetuitą
    (OE / discount_rate), łatwą do ręcznego zweryfikowania."""
    return ValuationConfig(
        method_by_sector_profile={
            "GENERAL": "dcf_owner_earnings", "BANK": None, "INSURER": None,
            "REIT": None, "BIOTECH": None,
        },
        dcf_owner_earnings=DcfOwnerEarningsConfig(
            projection_years=1,
            discount_rate_pct=ScenarioFloats(bear=discount_bear, base=discount_base, bull=discount_bull),
            terminal_growth_rate_pct=ScenarioFloats(bear=0.0, base=0.0, bull=0.0),
            historical_growth_multiplier=ScenarioFloats(bear=1.0, base=1.0, bull=1.0),
            max_projected_growth_rate_pct=20.0,
            min_projected_growth_rate_pct=-5.0,
            mos_pct_for_full_score=50.0,
        ),
    )


def test_compute_valuation_not_implemented_for_bank():
    config = _flat_growth_config()
    result = compute_valuation("BANK", [], current_price=10.0, config=config)
    assert result.implemented is False
    assert "BANK" in result.reason


def test_compute_valuation_not_implemented_when_latest_fcf_non_positive():
    config = _flat_growth_config()
    periods = [
        make_period("FY2023", operating_cash_flow=100.0, capital_expenditure=0.0),
        make_period("FY2024", operating_cash_flow=-10.0, capital_expenditure=0.0),
    ]
    result = compute_valuation("GENERAL", periods, current_price=10.0, config=config)
    assert result.implemented is False
    assert "ujemn" in result.reason.lower() or "None" in result.reason


def test_compute_valuation_not_implemented_when_insufficient_history():
    config = _flat_growth_config()
    periods = [make_period("FY2024", operating_cash_flow=100.0, capital_expenditure=0.0)]
    result = compute_valuation("GENERAL", periods, current_price=10.0, config=config)
    assert result.implemented is False


def test_compute_valuation_not_implemented_when_net_debt_missing():
    config = _flat_growth_config()
    periods = [
        make_period("FY2023", operating_cash_flow=100.0, capital_expenditure=0.0),
        make_period("FY2024", operating_cash_flow=100.0, capital_expenditure=0.0,
                    diluted_shares_outstanding=100.0),
    ]
    result = compute_valuation("GENERAL", periods, current_price=10.0, config=config)
    assert result.implemented is False
    assert "bilans" in result.reason.lower()


def test_compute_valuation_not_implemented_when_shares_missing():
    config = _flat_growth_config()
    periods = [
        make_period("FY2023", operating_cash_flow=100.0, capital_expenditure=0.0,
                    total_debt=0.0, cash_and_equivalents=0.0),
        make_period("FY2024", operating_cash_flow=100.0, capital_expenditure=0.0,
                    total_debt=0.0, cash_and_equivalents=0.0),
    ]
    result = compute_valuation("GENERAL", periods, current_price=10.0, config=config)
    assert result.implemented is False
    assert "akcji" in result.reason.lower()


# ---------------------------------------------------------------------------
# compute_valuation — pełny sukces, wartości ręcznie policzone
# ---------------------------------------------------------------------------

def test_compute_valuation_flat_fcf_is_a_pure_perpetuity():
    """Gdy CAGR=0 (płaski FCF) i terminal_growth=0, enterprise_value =
    OE / discount_rate dokładnie (wzór perpetuity), niezależnie od
    projection_years — silny, niezależny sposób weryfikacji poprawności
    formuły DCF."""
    config = _flat_growth_config(discount_bear=12.0, discount_base=10.0, discount_bull=8.0)
    periods = [
        make_period("FY2023", operating_cash_flow=100.0, capital_expenditure=0.0,
                    total_debt=0.0, cash_and_equivalents=0.0, diluted_shares_outstanding=100.0),
        make_period("FY2024", operating_cash_flow=100.0, capital_expenditure=0.0,
                    total_debt=0.0, cash_and_equivalents=0.0, diluted_shares_outstanding=100.0),
    ]
    result = compute_valuation("GENERAL", periods, current_price=8.0, config=config)

    assert result.implemented is True
    assert result.historical_growth_cagr_pct == pytest.approx(0.0)

    # net_debt=0, shares=100 -> intrinsic_value_per_share = (OE/discount_rate) / 100
    base = result.scenarios["base"]
    assert base.intrinsic_value_per_share == pytest.approx(100.0 / 0.10 / 100.0)  # = 10.0
    assert base.margin_of_safety_pct == pytest.approx((10.0 - 8.0) / 10.0 * 100.0)  # 20%

    bear = result.scenarios["bear"]
    assert bear.intrinsic_value_per_share == pytest.approx(100.0 / 0.12 / 100.0)

    bull = result.scenarios["bull"]
    assert bull.intrinsic_value_per_share == pytest.approx(100.0 / 0.08 / 100.0)

    # BEAR (wyższe dyskonto) daje niższą wycenę niż BASE, BULL wyższą
    assert bear.intrinsic_value_per_share < base.intrinsic_value_per_share < bull.intrinsic_value_per_share


def test_compute_valuation_subtracts_net_debt():
    config = _flat_growth_config()
    periods = [
        make_period("FY2023", operating_cash_flow=100.0, capital_expenditure=0.0,
                    total_debt=200.0, cash_and_equivalents=0.0, diluted_shares_outstanding=100.0),
        make_period("FY2024", operating_cash_flow=100.0, capital_expenditure=0.0,
                    total_debt=200.0, cash_and_equivalents=0.0, diluted_shares_outstanding=100.0),
    ]
    result = compute_valuation("GENERAL", periods, current_price=5.0, config=config)
    base = result.scenarios["base"]
    # enterprise_value = 100/0.10 = 1000; equity = 1000 - 200 (net_debt) = 800; /100 shares = 8.0
    assert base.intrinsic_value_per_share == pytest.approx(8.0)


def test_compute_valuation_growth_rate_is_capped_by_config():
    """Ograniczenie sufitem/podłogą z configu, nie tylko wzięte z CAGR
    wprost — sprawdzone przez skrajnie wysoką historyczną CAGR."""
    config = ValuationConfig(
        method_by_sector_profile={"GENERAL": "dcf_owner_earnings"},
        dcf_owner_earnings=DcfOwnerEarningsConfig(
            projection_years=1,
            discount_rate_pct=ScenarioFloats(bear=12.0, base=10.0, bull=8.0),
            terminal_growth_rate_pct=ScenarioFloats(bear=0.0, base=0.0, bull=0.0),
            historical_growth_multiplier=ScenarioFloats(bear=1.0, base=1.0, bull=1.0),
            max_projected_growth_rate_pct=5.0,   # sufit dużo niższy niż realna CAGR
            min_projected_growth_rate_pct=-5.0,
            mos_pct_for_full_score=50.0,
        ),
    )
    periods = [
        make_period("FY2023", operating_cash_flow=100.0, capital_expenditure=0.0,
                    total_debt=0.0, cash_and_equivalents=0.0, diluted_shares_outstanding=100.0),
        make_period("FY2024", operating_cash_flow=1000.0, capital_expenditure=0.0,
                    total_debt=0.0, cash_and_equivalents=0.0, diluted_shares_outstanding=100.0),
    ]
    # CAGR realna = (1000/100)-1 = 900%, ale sufit configu to 5%
    result = compute_valuation("GENERAL", periods, current_price=10.0, config=config)
    assert result.historical_growth_cagr_pct == pytest.approx(900.0)
    assert result.scenarios["base"].projected_growth_rate_pct == pytest.approx(5.0)

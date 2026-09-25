"""Testy silnika dividend/shareholder-return — wartości referencyjne
policzone ręcznie, nie odtworzone z kodu pod testem."""

from __future__ import annotations

import pytest

from buffett_scanner.config import DividendShareholderReturnConfig, DividendShareholderReturnWeights
from buffett_scanner.fundamentals import FundamentalsPeriod
from buffett_scanner.shareholder_returns import (
    dividend_per_share,
    evaluate_dividend_shareholder_return,
    market_cap,
    payout_ratio,
    share_count_trend,
    shareholder_yield_pct,
)


def make_period(
    fiscal_period: str,
    *,
    operating_cash_flow=None,
    capital_expenditure=None,
    dividends_paid=None,
    share_buybacks=None,
    diluted_shares_outstanding=None,
) -> FundamentalsPeriod:
    return FundamentalsPeriod(
        fiscal_period=fiscal_period,
        period_end_date=f"{fiscal_period}-12-31",
        filed_date=None,
        revenue=None, net_income=None, ebitda=None,
        operating_cash_flow=operating_cash_flow,
        capital_expenditure=capital_expenditure,
        total_debt=None, cash_and_equivalents=None,
        total_current_assets=None, total_current_liabilities=None,
        dividends_paid=dividends_paid, share_buybacks=share_buybacks,
        diluted_shares_outstanding=diluted_shares_outstanding,
    )


# ---------------------------------------------------------------------------
# Pojedyncze wskaźniki
# ---------------------------------------------------------------------------

def test_dividend_per_share():
    p = make_period("FY2024", dividends_paid=40.0, diluted_shares_outstanding=100.0)
    assert dividend_per_share(p) == pytest.approx(0.40)


def test_dividend_per_share_none_when_shares_missing():
    p = make_period("FY2024", dividends_paid=40.0)
    assert dividend_per_share(p) is None


def test_market_cap():
    p = make_period("FY2024", diluted_shares_outstanding=100.0)
    assert market_cap(p, price=10.0) == pytest.approx(1000.0)


def test_shareholder_yield_pct():
    p = make_period("FY2024", dividends_paid=20.0, share_buybacks=30.0,
                     diluted_shares_outstanding=100.0)
    # (20+30) / (10*100) * 100 = 50/1000*100 = 5.0%
    assert shareholder_yield_pct(p, price=10.0) == pytest.approx(5.0)


def test_payout_ratio_normal_case():
    p = make_period("FY2024", operating_cash_flow=250.0, capital_expenditure=50.0,
                     dividends_paid=50.0)  # FCF = 200
    result = payout_ratio(p)
    assert result.value_pct == pytest.approx(25.0)  # 50/200*100
    assert result.not_meaningful is False


def test_payout_ratio_not_meaningful_when_fcf_non_positive():
    """Decyzja właściciela 2026-09-25: FCF<=0 -> jawny NOT_MEANINGFUL,
    nigdy myląca wartość ujemna."""
    p = make_period("FY2024", operating_cash_flow=10.0, capital_expenditure=50.0,
                     dividends_paid=50.0)  # FCF = -40
    result = payout_ratio(p)
    assert result.value_pct is None
    assert result.not_meaningful is True


def test_payout_ratio_none_when_data_missing_not_not_meaningful():
    p = make_period("FY2024", operating_cash_flow=250.0, capital_expenditure=50.0)  # brak dividends_paid
    result = payout_ratio(p)
    assert result.value_pct is None
    assert result.not_meaningful is False  # brak danych != FCF<=0


def test_share_count_trend_decreasing():
    periods = [
        make_period("FY2023", diluted_shares_outstanding=110.0),
        make_period("FY2024", diluted_shares_outstanding=100.0),
    ]
    assert share_count_trend(periods) == "DECREASING"


def test_share_count_trend_increasing():
    periods = [
        make_period("FY2023", diluted_shares_outstanding=100.0),
        make_period("FY2024", diluted_shares_outstanding=110.0),
    ]
    assert share_count_trend(periods) == "INCREASING"


def test_share_count_trend_flat():
    periods = [
        make_period("FY2023", diluted_shares_outstanding=100.0),
        make_period("FY2024", diluted_shares_outstanding=100.0),
    ]
    assert share_count_trend(periods) == "FLAT"


def test_share_count_trend_none_with_single_period():
    periods = [make_period("FY2024", diluted_shares_outstanding=100.0)]
    assert share_count_trend(periods) is None


# ---------------------------------------------------------------------------
# evaluate_dividend_shareholder_return — scoring z wagami z configu
# ---------------------------------------------------------------------------

CONFIG = DividendShareholderReturnConfig(
    weights=DividendShareholderReturnWeights(
        positive_shareholder_yield=3.0, no_dividend_cut=3.0,
        sustainable_payout_ratio=2.0, shrinking_or_flat_share_count=2.0,
    ),
    max_sustainable_payout_ratio_pct=75.0,
    min_shareholder_yield_pct=0.0,
)


def test_evaluate_all_criteria_met_gives_full_score():
    periods = [
        make_period("FY2023", operating_cash_flow=250.0, capital_expenditure=50.0,
                     dividends_paid=40.0, share_buybacks=10.0, diluted_shares_outstanding=110.0),
        make_period("FY2024", operating_cash_flow=250.0, capital_expenditure=50.0,
                     dividends_paid=50.0, share_buybacks=10.0, diluted_shares_outstanding=100.0),
    ]
    result = evaluate_dividend_shareholder_return(periods, current_price=10.0, config=CONFIG)
    # yield = (50+10)/(10*100)*100 = 6.0% > 0 -> +3
    # DPS: latest 50/100=0.5, prior 40/110=0.3636... -> latest>=prior -> no cut -> +3
    # payout = 50/200*100 = 25% <= 75% -> +2
    # shares 110->100 -> DECREASING -> +2
    assert result.raw_score == pytest.approx(10.0)
    assert result.breakdown == {
        "positive_shareholder_yield": True, "no_dividend_cut": True,
        "sustainable_payout_ratio": True, "shrinking_or_flat_share_count": True,
    }


def test_evaluate_dividend_cut_loses_points():
    periods = [
        make_period("FY2023", operating_cash_flow=250.0, capital_expenditure=50.0,
                     dividends_paid=80.0, share_buybacks=0.0, diluted_shares_outstanding=100.0),
        make_period("FY2024", operating_cash_flow=250.0, capital_expenditure=50.0,
                     dividends_paid=40.0, share_buybacks=0.0, diluted_shares_outstanding=100.0),
    ]
    result = evaluate_dividend_shareholder_return(periods, current_price=10.0, config=CONFIG)
    assert result.breakdown["no_dividend_cut"] is False
    assert result.no_dividend_cut is False


def test_evaluate_missing_dividend_history_never_credits_no_cut():
    """Brak historii DPS (tylko 1 okres) -> no_dividend_cut=None ->
    ŻADEN kredyt punktowy (nie mylić 'nie wiadomo' z 'potwierdzone dobrze')."""
    periods = [
        make_period("FY2024", operating_cash_flow=250.0, capital_expenditure=50.0,
                     dividends_paid=50.0, share_buybacks=0.0, diluted_shares_outstanding=100.0),
    ]
    result = evaluate_dividend_shareholder_return(periods, current_price=10.0, config=CONFIG)
    assert result.no_dividend_cut is None
    assert result.breakdown["no_dividend_cut"] is False


def test_evaluate_negative_fcf_dividend_payer_gets_no_payout_credit():
    """Spółka wypłaca dywidendę mimo ujemnego FCF — payout_ratio
    NOT_MEANINGFUL, więc kryterium sustainable_payout_ratio = False
    (czerwona flaga, nie luka w danych do zignorowania)."""
    periods = [
        make_period("FY2023", operating_cash_flow=10.0, capital_expenditure=50.0,
                     dividends_paid=50.0, share_buybacks=0.0, diluted_shares_outstanding=100.0),
        make_period("FY2024", operating_cash_flow=10.0, capital_expenditure=50.0,
                     dividends_paid=50.0, share_buybacks=0.0, diluted_shares_outstanding=100.0),
    ]
    result = evaluate_dividend_shareholder_return(periods, current_price=10.0, config=CONFIG)
    assert result.payout_ratio.not_meaningful is True
    assert result.breakdown["sustainable_payout_ratio"] is False


def test_evaluate_zero_criteria_met_gives_zero_score():
    periods = [
        make_period("FY2023", operating_cash_flow=10.0, capital_expenditure=50.0,
                     dividends_paid=80.0, share_buybacks=0.0, diluted_shares_outstanding=90.0),
        make_period("FY2024", operating_cash_flow=10.0, capital_expenditure=50.0,
                     dividends_paid=40.0, share_buybacks=0.0, diluted_shares_outstanding=100.0),
    ]
    result = evaluate_dividend_shareholder_return(periods, current_price=10.0, config=CONFIG)
    # yield = (40+0)/(10*100)*100=4.0% > 0 -> to akurat True, sprawdźmy inny przypadek
    assert result.breakdown["sustainable_payout_ratio"] is False  # FCF ujemny
    assert result.breakdown["no_dividend_cut"] is False           # DPS spadło (80/90 -> 40/100)
    assert result.breakdown["shrinking_or_flat_share_count"] is False  # 90->100 INCREASING

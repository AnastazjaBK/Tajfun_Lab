"""Faza 11 (P4): klasy aktywów -- masa czystego metalu, ekspozycja bez
podwójnego liczenia, pozycje sprzed Fazy 11 = akcje."""

from __future__ import annotations

import pytest

from buffett_scanner.ui.assets import (
    TROY_OUNCE_G,
    asset_class_of,
    exposure_summary,
    pure_grams_per_piece,
)
from buffett_scanner.ui.portfolio import compute_position_summary
from buffett_scanner.ui.pricing import FxRates

FX = FxRates(mid_pln={"PLN": 1.0, "EUR": 4.25, "USD": 3.70}, effective_date="2026-10-16")


def test_pure_grams_for_ounce_coin_and_gram_bar():
    assert pure_grams_per_piece(1.0, "OZT", 0.9167) == pytest.approx(TROY_OUNCE_G * 0.9167)  # Krugerrand
    assert pure_grams_per_piece(100.0, "G", 999.9) == pytest.approx(99.99)  # próba w promilach
    assert pure_grams_per_piece(None, "G", 0.999) is None
    assert pure_grams_per_piece(10.0, "G", 1.5) is None


def test_legacy_position_without_class_is_stock():
    assert asset_class_of({"asset_class": None}) == "STOCK"
    assert asset_class_of({"ticker": "AAPL"}) == "STOCK"


def _summary(pid, price, currency, invested=100.0):
    purchases = [{"broker": "OTHER", "currency": "PLN", "purchase_date": "2026-10-01", "shares": 1.0,
                  "total_invested": invested, "acquisition_type": "BUY"}]
    return compute_position_summary(pid, purchases, [], current_price=price, current_price_currency=currency, fx=FX)


def test_gold_exposure_splits_physical_and_exchange_traded_without_double_counting():
    positions = [
        ({"ticker": "Krugerrand", "asset_class": "PHYSICAL_GOLD", "metal": None}, _summary(1, 16000.0, "PLN")),
        ({"ticker": "4GLD.DE", "asset_class": "ETC", "metal": "GOLD"}, _summary(2, 119.43, "EUR")),
        ({"ticker": "AAPL", "asset_class": None, "metal": None}, _summary(3, 230.0, "USD")),
        ({"ticker": "NYMT", "asset_class": "STOCK", "metal": None}, _summary(4, None, None)),
    ]
    exposure = exposure_summary(positions)
    assert exposure["metals"]["GOLD"]["physical"] == pytest.approx(16000.0)
    assert exposure["metals"]["GOLD"]["exchange"] == pytest.approx(119.43 * 4.25)
    assert exposure["metals"]["SILVER"] == {"physical": 0.0, "platform": 0.0, "exchange": 0.0}
    assert exposure["by_class"]["STOCK"] == pytest.approx(230.0 * 3.70)
    assert exposure["unpriced"] == ["NYMT"]


# --- Metal na platformie (COMMODITY, np. XAG/XAU w Revolut) ---

from buffett_scanner.ui.assets import (  # noqa: E402
    COMMODITY,
    commodity_cost_error,
    realizable_value_pln,
)

# Rzeczywista transakcja właścicielki (Revolut, 21.04.2021).
REVOLUT_XAG = {"broker": "REVOLUT", "currency": "PLN", "purchase_date": "2021-04-21", "shares": 2.950729,
               "total_invested": 300.00, "acquisition_type": "BUY", "fees": 4.50, "price_per_share": 100.14}


def test_revolut_example_cost_matches_quantity_price_and_fee():
    assert commodity_cost_error(2.950729, 100.14, 4.50, 300.00) is None
    assert 2.950729 * 100.14 == pytest.approx(295.50, abs=0.02)  # wartość metalu z potwierdzenia
    assert commodity_cost_error(29.50729, 100.14, 4.50, 300.00) is not None  # literówka w ilości
    assert commodity_cost_error(2.950729, 10.014, 4.50, 300.00) is not None  # literówka w cenie


def test_revolut_example_valuation_cost_basis_and_eight_decimals():
    # Cena testowa (stała, fikcyjna): srebro 50 USD/oz, USD = 3,70 PLN.
    summary = compute_position_summary(1, [REVOLUT_XAG], [], current_price=50.0, current_price_currency="USD", fx=FX)
    [sub] = summary.by_broker_currency
    assert sub.shares_held == 2.950729
    assert sub.total_invested == 300.00  # koszt = cała kwota z opłatą
    assert sub.current_value_pln == pytest.approx(2.950729 * 50.0 * 3.70)
    tiny = dict(REVOLUT_XAG, shares=0.12345678, total_invested=12.0)
    assert compute_position_summary(2, [tiny], [], current_price=None, current_price_currency=None,
                                    fx=FX).shares_held == 0.12345678


def test_platform_metal_is_its_own_exposure_bucket_without_double_counting():
    xag = compute_position_summary(1, [REVOLUT_XAG], [], current_price=50.0, current_price_currency="USD", fx=FX)
    positions = [
        ({"ticker": "XAG", "asset_class": COMMODITY, "metal": "SILVER"}, xag),
        ({"ticker": "Moneta", "asset_class": "PHYSICAL_SILVER", "metal": None}, _summary(2, 150.0, "PLN")),
        ({"ticker": "PHAG", "asset_class": "ETC", "metal": "SILVER"}, _summary(3, 30.0, "EUR")),
    ]
    exposure = exposure_summary(positions)
    silver = exposure["metals"]["SILVER"]
    assert silver["platform"] == pytest.approx(2.950729 * 50.0 * 3.70)
    assert silver["physical"] == pytest.approx(150.0)
    assert silver["exchange"] == pytest.approx(30.0 * 4.25)
    assert sum(silver.values()) == pytest.approx(sum(exposure["by_class"].values()))
    assert exposure["by_class"][COMMODITY] == pytest.approx(silver["platform"])


def test_realizable_value_is_separate_from_market_value_and_never_guessed():
    assert realizable_value_pln(545.89) == (None, None)  # brak opłaty i ceny -> brak kwoty
    value, basis = realizable_value_pln(545.89, sale_fee_pct=1.5)
    assert value == pytest.approx(545.89 * 0.985) and "1.5%" in basis
    assert realizable_value_pln(545.89, sale_fee_pct=1.5, sale_price_value_pln=520.0)[0] == 520.0
    assert realizable_value_pln(None, sale_fee_pct=1.5) == (None, None)

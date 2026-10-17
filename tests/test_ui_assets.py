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
    assert exposure["metals"]["SILVER"] == {"physical": 0.0, "exchange": 0.0}
    assert exposure["by_class"]["STOCK"] == pytest.approx(230.0 * 3.70)
    assert exposure["unpriced"] == ["NYMT"]

"""Testy cen bieżących i kursów NBP (Faza 9) -- czyste funkcje, zero
sieci. Kształt odpowiedzi NBP w testach odpowiada dokumentacji API NBP
(`tables/a`); na żywym API zweryfikowany dopiero po wdrożeniu (sandbox
deweloperski nie ma dostępu do api.nbp.pl)."""

from __future__ import annotations

import pytest

from buffett_scanner.ui import pricing
from buffett_scanner.ui.portfolio import compute_position_summary
from buffett_scanner.ui.pricing import (
    FxRates,
    convert,
    normalize_quote,
    parse_nbp_table,
    total_in_currency,
)


def _nbp_payload(**mids):
    return [{
        "table": "A", "no": "201/A/NBP/2026", "effectiveDate": "2026-10-16",
        "rates": [{"currency": code.lower(), "code": code, "mid": mid} for code, mid in mids.items()],
    }]


FX = FxRates(mid_pln={"PLN": 1.0, "EUR": 4.25, "USD": 3.70, "GBP": 4.90}, effective_date="2026-10-16")


def test_normalize_quote_divides_london_pence_by_100():
    """Regresja na realne zachowanie FMP (Faza 7): `GSK.L` -> currency
    "GBp", price=1765.5 to 17.655 GBP, nie 1765.5 GBP."""
    assert normalize_quote(1765.5, "GBp") == (pytest.approx(17.655), "GBP")


def test_normalize_quote_divides_johannesburg_cents_by_100():
    assert normalize_quote(25000, "ZAc") == (pytest.approx(250.0), "ZAR")


def test_normalize_quote_keeps_major_currency_and_uppercases():
    assert normalize_quote(42.5, "eur") == (42.5, "EUR")


def test_normalize_quote_gbp_upper_case_is_pounds_not_pence():
    assert normalize_quote(17.6, "GBP") == (17.6, "GBP")


@pytest.mark.parametrize("price,currency", [(None, "USD"), (10.0, None), (0, "USD"), (-1, "USD"), ("x", "USD"), (5, " ")])
def test_normalize_quote_rejects_unusable_values(price, currency):
    assert normalize_quote(price, currency) is None


def test_parse_nbp_table_reads_mid_rates_and_date():
    fx = parse_nbp_table(_nbp_payload(EUR=4.2512, USD=3.7034))
    assert fx.effective_date == "2026-10-16"
    assert fx.mid_pln == {"PLN": 1.0, "EUR": 4.2512, "USD": 3.7034}


@pytest.mark.parametrize("payload", [None, [], {}, [{"rates": []}], [{"effectiveDate": "2026-10-16", "rates": []}], "x"])
def test_parse_nbp_table_rejects_unexpected_shapes(payload):
    assert parse_nbp_table(payload) is None


def test_convert_same_currency_needs_no_rates():
    assert convert(100.0, "PLN", "pln", None) == 100.0


def test_convert_eur_to_pln_and_cross_rate_eur_to_usd():
    assert convert(10.0, "EUR", "PLN", FX) == pytest.approx(42.5)
    assert convert(10.0, "EUR", "USD", FX) == pytest.approx(42.5 / 3.70)


def test_convert_missing_rate_returns_none_never_guess():
    assert convert(10.0, "BRL", "PLN", FX) is None
    assert convert(10.0, "EUR", "PLN", None) is None


def test_total_in_currency_none_when_any_currency_has_no_rate():
    assert total_in_currency({"PLN": 100.0, "USD": 10.0}, "PLN", FX) == pytest.approx(137.0)
    assert total_in_currency({"PLN": 100.0, "BRL": 10.0}, "PLN", FX) is None


def test_schneider_bought_in_pln_valued_in_pln_through_eur_rate():
    """Scenariusz właścicielki: SU.PA (EUR) kupione w Trade Republic za
    PLN. Wartość = akcje x cena EUR x kurs NBP EUR, P/L w PLN."""
    purchases = [{
        "broker": "TRADE_REPUBLIC", "currency": "PLN", "purchase_date": "2026-10-06",
        "shares": 0.15, "total_invested": 154.54, "acquisition_type": "BUY",
    }]
    summary = compute_position_summary(1, purchases, [], current_price=250.0, current_price_currency="EUR", fx=FX)
    sub = summary.by_broker_currency[0]
    assert sub.current_value == pytest.approx(0.15 * 250.0 * 4.25)
    assert sub.unrealized_pl == pytest.approx(0.15 * 250.0 * 4.25 - 154.54)
    assert summary.current_value_by_currency == {"PLN": pytest.approx(159.375)}


def test_foreign_currency_without_fx_stays_unknown_not_zero():
    purchases = [{
        "broker": "TRADE_REPUBLIC", "currency": "PLN", "purchase_date": "2026-10-06",
        "shares": 1.0, "total_invested": 100.0, "acquisition_type": "BUY",
    }]
    summary = compute_position_summary(1, purchases, [], current_price=25.0, current_price_currency="EUR", fx=None)
    assert summary.by_broker_currency[0].current_value is None
    assert summary.current_value_by_currency is None


def test_fetch_quote_returns_none_without_api_key(monkeypatch):
    def _no_config():
        raise FileNotFoundError("brak config")
    monkeypatch.setattr(pricing, "load_config", _no_config)
    assert pricing.fetch_quote("SU.PA") is None


def test_fetch_quote_normalizes_pence_from_fmp_profile(monkeypatch):
    class _Provider:
        def resolve_api_key(self):
            return "k"

    class _Config:
        data_provider = _Provider()

    class _Client:
        def __init__(self, *a, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return None

        def get_company_profile(self, symbol):
            return {"symbol": symbol, "price": 1765.5, "currency": "GBp"}

    monkeypatch.setattr(pricing, "load_config", lambda: _Config())
    monkeypatch.setattr(pricing, "FMPClient", _Client)
    quote = pricing.fetch_quote("GSK.L")
    assert quote.currency == "GBP"
    assert quote.price == pytest.approx(17.655)


def test_fetch_nbp_rates_returns_none_on_network_error(monkeypatch):
    def _boom(*a, **kw):
        raise pricing.httpx.ConnectError("offline")
    monkeypatch.setattr(pricing.httpx, "get", _boom)
    assert pricing.fetch_nbp_rates() is None

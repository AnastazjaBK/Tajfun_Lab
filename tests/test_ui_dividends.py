"""Faza 11 (P3): metryki dywidend -- yield TTM, częstotliwość, trend,
specjalne, pensy, brak look-ahead, potwierdzone daty."""

from __future__ import annotations

import pytest

from buffett_scanner.ui.dividends import (
    REGULAR,
    SPECIAL,
    compute_dividend_metrics,
    cut_risk_note,
    events_from_eodhd,
    events_from_fmp,
)


def _quarterly_fmp(years, amount, extra=()):
    rows = [{"date": f"{y}-{m:02d}-10", "dividend": amount(y), "frequency": "Quarterly",
             "paymentDate": f"{y}-{m:02d}-20", "declarationDate": f"{y}-{m - 1:02d}-25"}
            for y in years for m in (2, 5, 8, 11)]
    return rows + list(extra)


def test_quarterly_payer_yield_frequency_and_rising_trend():
    events = events_from_fmp(_quarterly_fmp((2023, 2024, 2025, 2026), lambda y: 0.20 + 0.02 * (y - 2023)), "USD")
    m = compute_dividend_metrics(events, price=100.0, price_currency="USD", as_of="2026-10-16")
    # ostatnie 365 dni: 2025-11, 2026-02, 2026-05, 2026-08
    assert m.ttm_dps == pytest.approx(0.24 + 3 * 0.26)
    assert m.yield_ttm_pct == pytest.approx(1.02)
    assert m.gross_per_100_pln == pytest.approx(1.02)
    assert m.frequency == "QUARTERLY"
    assert m.trend == "UP"
    assert m.ytd_dps == pytest.approx(3 * 0.26)
    assert m.last_event.ex_date == "2026-08-10"


def test_special_dividend_is_excluded_from_yield_and_shown_separately():
    special = {"date": "2026-06-01", "dividend": 5.0, "frequency": "Special"}
    events = events_from_fmp(_quarterly_fmp((2025, 2026), lambda y: 0.25), "USD") + events_from_fmp([special], "USD")
    m = compute_dividend_metrics(sorted(events, key=lambda e: e.ex_date), price=50.0, price_currency="USD",
                                 as_of="2026-10-16")
    assert m.ttm_dps == pytest.approx(1.0)
    assert m.ttm_special == pytest.approx(5.0)
    assert m.yield_ttm_pct == pytest.approx(2.0)


def test_london_pence_are_normalized_for_fmp_and_eodhd():
    fmp = events_from_fmp([{"date": "2026-08-13", "dividend": 17, "frequency": "Quarterly"}], "GBp")
    eod = events_from_eodhd([{"date": "2026-08-13", "value": 0.17, "currency": "GBP", "period": "Quarterly"}])
    assert (fmp[0].amount, fmp[0].currency) == (pytest.approx(0.17), "GBP")
    assert (eod[0].amount, eod[0].currency) == (0.17, "GBP")
    m = compute_dividend_metrics(eod, price=18.625, price_currency="GBP", as_of="2026-10-16")
    assert m.yield_ttm_pct == pytest.approx(0.17 / 18.625 * 100)


def test_scan_date_view_has_no_look_ahead():
    events = events_from_fmp(_quarterly_fmp((2025, 2026), lambda y: 0.25), "USD")
    m = compute_dividend_metrics(events, price=100.0, price_currency="USD", as_of="2026-06-01")
    assert m.last_event.ex_date == "2026-05-10"
    assert all(e <= "2026-06-01" for e in [m.last_event.ex_date])


def test_cut_is_detected_and_explained_without_using_yield():
    events = events_from_fmp(_quarterly_fmp((2024, 2025, 2026), lambda y: 0.5 if y < 2026 else 0.1), "USD")
    m = compute_dividend_metrics(events, price=10.0, price_currency="USD", as_of="2026-10-16")
    assert m.trend == "CUT"
    assert "25%" in cut_risk_note(m, None)
    assert cut_risk_note(m, 130.0).count(";") == 1


def test_confirmed_future_ex_date_requires_declaration():
    rows = [{"date": "2026-11-10", "dividend": 0.3, "frequency": "Quarterly", "declarationDate": "2026-10-01"},
            {"date": "2027-02-10", "dividend": 0.3, "frequency": "Quarterly", "declarationDate": None}]
    m = compute_dividend_metrics(events_from_fmp(rows, "USD"), price=10.0, price_currency="USD", as_of="2026-10-16")
    assert m.next_confirmed.ex_date == "2026-11-10"


def test_no_dividends_and_short_history():
    m = compute_dividend_metrics([], price=10.0, price_currency="USD", as_of="2026-10-16")
    assert (m.frequency, m.trend, m.yield_ttm_pct, m.ttm_dps) == ("NONE", "NO_DATA", None, 0.0)
    eod = events_from_eodhd([{"date": "2026-05-11", "value": 4.2, "currency": "EUR", "period": "Final"}])
    m = compute_dividend_metrics(eod, price=253.3, price_currency="EUR", as_of="2026-10-16")
    assert m.trend == "NO_DATA" and m.frequency == "IRREGULAR"
    assert eod[0].kind == REGULAR and SPECIAL != REGULAR


def test_currency_mismatch_gives_no_yield():
    events = events_from_eodhd([{"date": "2026-05-11", "value": 4.2, "currency": "EUR", "period": "Final"}])
    m = compute_dividend_metrics(events, price=100.0, price_currency="USD", as_of="2026-10-16")
    assert m.yield_ttm_pct is None


def test_receipts_summary_gross_net_tax_and_pln():
    from buffett_scanner.ui.dividends import summarize_receipts

    receipts = [
        {"currency": "USD", "pay_date": "2026-08-13", "gross_amount": 1.0, "withholding_tax": 0.15,
         "net_amount": None, "fx_rate_actual": None},
        {"currency": "PLN", "pay_date": "2025-12-01", "gross_amount": 10.0, "withholding_tax": 1.9,
         "net_amount": 8.1, "fx_rate_actual": None},
    ]

    def rate(currency, date, actual):
        return (1.0, "PLN") if currency == "PLN" else (3.8, "NBP")

    s = summarize_receipts(receipts, pln_rate_fn=rate, year=2026)
    assert s.net_by_currency == {"USD": pytest.approx(0.85), "PLN": pytest.approx(8.1)}
    assert s.tax_by_currency["USD"] == pytest.approx(0.15)
    assert s.gross_pln == pytest.approx(3.8 + 10.0)
    assert s.net_pln == pytest.approx(0.85 * 3.8 + 8.1)
    assert s.ytd_net_pln == pytest.approx(0.85 * 3.8)
    assert s.estimated is True
    missing = summarize_receipts(receipts, pln_rate_fn=lambda c, d, a: None, year=2026)
    assert missing.net_pln is None

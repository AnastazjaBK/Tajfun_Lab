"""Faza 11: wspólna warstwa danych rynkowych -- cache w bazie, budżet
EODHD, ostatnia poprawna wartość, kursy NBP sprzed daty transakcji.
Atrapy klientów, zero sieci. Kształty odpowiedzi jak w diagnostyce z
2026-10-17 (EODHD run 39070026144, NBP run 39070662443)."""

from __future__ import annotations

import datetime as dt

import pytest

from buffett_scanner.db import init_db
from buffett_scanner.providers.eodhd import EODHDError, to_eodhd_symbol
from buffett_scanner.ui import market_data as md
from buffett_scanner.ui.market_data import EODHD_DAILY_BUDGET, MarketData


class Clock:
    def __init__(self):
        self.now = dt.datetime(2026, 10, 17, 12, 0, 0)

    def __call__(self):
        return self.now


class FakeEODHD:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    def eod(self, symbol, *, from_date, to_date):
        self.calls.append(("eod", symbol))
        if self.fail:
            raise EODHDError("boom")
        return [
            {"date": "2026-10-15", "close": 1868.5, "adjusted_close": 1868.5, "volume": 1},
            {"date": "2026-10-16", "close": 1862.5, "adjusted_close": 1862.5, "volume": 1},
        ]

    def search(self, symbol):
        self.calls.append(("search", symbol))
        return [{"Code": "GSK", "Exchange": "LSE", "Currency": "GBX", "ISIN": "GB00BN7SWP63"}]


class FakeResp:
    def __init__(self, payload, status=200):
        self._payload, self.status_code = payload, status

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise md.httpx.HTTPStatusError("x", request=None, response=None)


@pytest.fixture
def conn(tmp_path):
    return init_db(tmp_path / "t.db")


def _market(conn, eodhd=None, clock=None, http_get=None):
    return MarketData(
        conn, eodhd_factory=lambda: eodhd, fmp_factory=lambda: None,
        now_fn=clock or Clock(), http_get=http_get or (lambda *a, **k: None),
    )


def test_eodhd_quote_normalizes_pence_and_keeps_date(conn):
    fake = FakeEODHD()
    quote = _market(conn, fake).quote_for_symbol("EODHD", "GSK.LSE", "GBX")
    assert quote.currency == "GBP"
    assert quote.price == pytest.approx(18.625)
    assert quote.as_of == "2026-10-16"
    assert quote.stale is False


def test_cache_is_shared_second_call_hits_database_not_provider(conn):
    fake = FakeEODHD()
    _market(conn, fake).eodhd_eod("GSK.LSE")
    _market(conn, fake).eodhd_eod("GSK.LSE")  # nowa "sesja", ta sama baza
    assert fake.calls == [("eod", "GSK.LSE")]


def test_expired_entry_with_provider_failure_returns_last_good_value_as_stale(conn):
    clock = Clock()
    _market(conn, FakeEODHD(), clock).eodhd_eod("GSK.LSE")
    clock.now += dt.timedelta(hours=13)  # po TTL notowań EODHD (12 h)
    failing = FakeEODHD(fail=True)
    cached = _market(conn, failing, clock).eodhd_eod("GSK.LSE")
    assert cached.stale is True
    assert cached.value[-1]["close"] == 1862.5
    # kolejna próba w oknie backoff nie odpytuje dostawcy ponownie
    _market(conn, failing, clock).eodhd_eod("GSK.LSE")
    assert len(failing.calls) == 1


def test_eodhd_daily_budget_is_never_exceeded(conn):
    fake = FakeEODHD()
    market = _market(conn, fake)
    for i in range(EODHD_DAILY_BUDGET + 5):
        market.eodhd_search(f"X{i}.PA")
    assert len(fake.calls) == EODHD_DAILY_BUDGET
    assert market.eodhd_calls_today() == EODHD_DAILY_BUDGET


def test_no_eodhd_key_means_no_call_and_no_price(conn):
    assert _market(conn, None).quote_for_symbol("EODHD", "SU.PA", "EUR") is None


def test_nbp_rate_before_takes_last_business_day_before_transaction(conn):
    requested = []

    def http_get(url, **kw):
        requested.append(url)
        return FakeResp({"table": "A", "code": "USD", "rates": [
            {"no": "190/A/NBP/2026", "effectiveDate": "2026-09-30", "mid": 3.8449},
            {"no": "191/A/NBP/2026", "effectiveDate": "2026-10-01", "mid": 3.8762},
            {"no": "192/A/NBP/2026", "effectiveDate": "2026-10-02", "mid": 3.8881},
        ]})

    market = _market(conn, http_get=http_get)
    assert market.nbp_rate_before("USD", "2026-10-05") == ("2026-10-02", 3.8881)
    assert "2026-10-04" in requested[0]  # zakres kończy się dzień PRZED transakcją
    market.nbp_rate_before("usd", "2026-10-05")
    assert len(requested) == 1  # dane historyczne cache'owane na stałe
    assert market.nbp_rate_before("PLN", "2026-10-05") == ("2026-10-05", 1.0)


def test_nbp_gold_price(conn):
    market = _market(conn, http_get=lambda url, **kw: FakeResp([{"data": "2026-10-16", "cena": 519.85}]))
    assert market.nbp_gold_pln_per_gram() == ("2026-10-16", 519.85)


@pytest.mark.parametrize("symbol,expected", [
    ("SU.PA", "SU.PA"), ("GSK.L", "GSK.LSE"), ("4GLD.DE", "4GLD.XETRA"), ("eunl.xetra", "EUNL.XETRA"),
    ("AAPL", None), ("BRK.B", None),
])
def test_to_eodhd_symbol(symbol, expected):
    assert to_eodhd_symbol(symbol) == expected

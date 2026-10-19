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


# --- Faza 11 (P4): metale fizyczne, kryptowaluty ---

from buffett_scanner.db import create_user, insert_manual_valuation, insert_position, update_position_fields  # noqa: E402


class FakeFMP:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return None

    def get_quote(self, symbol):
        return {"SIUSD": {"symbol": "SIUSD", "price": 57.305, "timestamp": 1792184402},
                "BTCUSD": {"symbol": "BTCUSD", "price": 81543.5, "timestamp": 1792268808}}.get(symbol)


def _metal_position(conn, asset_class, **fields):
    uid = create_user(conn, "A")
    pid = insert_position(conn, user_id=uid, ticker="METAL", company_name="Moneta", instrument_confirmed=True)
    update_position_fields(conn, pid, asset_class=asset_class, **fields)
    conn.commit()
    return conn.execute("SELECT * FROM positions WHERE position_id = ?", (pid,)).fetchone()


def test_physical_gold_valued_from_nbp_gold_price(conn):
    position = _metal_position(conn, "PHYSICAL_GOLD", unit_weight=1.0, weight_unit="OZT", fineness=0.9999)
    market = MarketData(conn, eodhd_factory=lambda: None, fmp_factory=lambda: None, now_fn=Clock(),
                        http_get=lambda url, **kw: FakeResp([{"data": "2026-10-16", "cena": 519.85}]))
    quote = market.quote_for_position(position)
    assert quote.currency == "PLN"
    assert quote.price == pytest.approx(31.1034768 * 0.9999 * 519.85)
    assert quote.as_of == "2026-10-16"


def test_physical_silver_uses_fmp_futures_per_gram(conn):
    position = _metal_position(conn, "PHYSICAL_SILVER", unit_weight=100.0, weight_unit="G", fineness=999.0)
    market = MarketData(conn, eodhd_factory=lambda: None, fmp_factory=FakeFMP, now_fn=Clock())
    quote = market.quote_for_position(position)
    assert (quote.currency, quote.source) == ("USD", "FMP (kontrakt na srebro)")
    assert quote.price == pytest.approx(99.9 * 57.305 / 31.1034768)


def test_collectible_coin_uses_manual_valuation_only(conn):
    position = _metal_position(conn, "PHYSICAL_GOLD", unit_weight=1.0, weight_unit="OZT", fineness=0.9999,
                               is_collectible=1)
    market = MarketData(conn, eodhd_factory=lambda: None, fmp_factory=lambda: None, now_fn=Clock(),
                        http_get=lambda url, **kw: FakeResp([{"data": "2026-10-16", "cena": 519.85}]))
    assert market.quote_for_position(position) is None
    insert_manual_valuation(conn, position_id=position["position_id"], kind="MARKET", price_per_unit=25000.0,
                            currency="pln", valuation_date="2026-10-10")
    conn.commit()
    quote = market.quote_for_position(position)
    assert (quote.price, quote.currency, quote.source) == (25000.0, "PLN", "wycena ręczna")


def test_crypto_quote(conn):
    uid = create_user(conn, "A")
    pid = insert_position(conn, user_id=uid, ticker="BTCUSD", company_name="Bitcoin", instrument_confirmed=True)
    update_position_fields(conn, pid, asset_class="CRYPTO", price_symbol="BTCUSD")
    conn.commit()
    position = conn.execute("SELECT * FROM positions WHERE position_id = ?", (pid,)).fetchone()
    quote = MarketData(conn, eodhd_factory=lambda: None, fmp_factory=FakeFMP, now_fn=Clock()).quote_for_position(position)
    assert (quote.price, quote.currency) == (81543.5, "USD")


# --- 2026-10-19: pamięć procesu przed cache w bazie (szybkość aplikacji) ---


def test_memory_layer_serves_fresh_entries_without_database_and_respects_data_ttl(conn, tmp_path):
    memory, clock, fake = {}, Clock(), FakeEODHD()
    MarketData(conn, eodhd_factory=lambda: fake, fmp_factory=lambda: None, now_fn=clock, memory=memory).eodhd_eod("GSK.LSE")
    empty_db = init_db(tmp_path / "other.db")  # brak wpisu w bazie -> trafienie musi pochodzić z pamięci
    second = MarketData(empty_db, eodhd_factory=lambda: fake, fmp_factory=lambda: None, now_fn=clock, memory=memory)
    assert second.eodhd_eod("GSK.LSE").value[-1]["close"] == 1862.5
    assert fake.calls == [("eod", "GSK.LSE")]
    clock.now += dt.timedelta(minutes=11)  # po MEMORY_TTL_S -> znowu baza (tu pusta) -> dostawca
    second.eodhd_eod("GSK.LSE")
    assert fake.calls == [("eod", "GSK.LSE"), ("eod", "GSK.LSE")]


def test_memory_layer_remembers_failure_only_for_backoff_window(conn):
    memory, clock, failing = {}, Clock(), FakeEODHD(fail=True)
    market = MarketData(conn, eodhd_factory=lambda: failing, fmp_factory=lambda: None, now_fn=clock, memory=memory)
    assert market.eodhd_eod("SU.PA") is None
    assert market.eodhd_eod("SU.PA") is None
    assert len(failing.calls) == 1
    clock.now += dt.timedelta(minutes=16)  # po oknie backoff (15 min) -> nowa próba
    market.eodhd_eod("SU.PA")
    assert len(failing.calls) == 2


def _commodity_position(conn, symbol, metal):
    uid = create_user(conn, "A")
    pid = insert_position(conn, user_id=uid, ticker=symbol, company_name=symbol, instrument_confirmed=True)
    update_position_fields(conn, pid, asset_class="COMMODITY", metal=metal, price_symbol=symbol,
                           unit_weight=1.0, weight_unit="OZT", sale_fee_pct=1.5)
    conn.commit()
    return conn.execute("SELECT * FROM positions WHERE position_id = ?", (pid,)).fetchone()


def test_platform_gold_xau_is_priced_per_troy_ounce_from_nbp(conn):
    position = _commodity_position(conn, "XAU", "GOLD")
    market = MarketData(conn, eodhd_factory=lambda: None, fmp_factory=lambda: None, now_fn=Clock(),
                        http_get=lambda url, **kw: FakeResp([{"data": "2026-10-16", "cena": 519.85}]))
    quote = market.quote_for_position(position)
    assert (quote.currency, quote.source, quote.as_of) == ("PLN", "NBP (cena złota)", "2026-10-16")
    assert quote.price == pytest.approx(31.1034768 * 519.85)


def test_platform_silver_xag_uses_fmp_price_per_ounce_and_falls_back_to_manual(conn):
    position = _commodity_position(conn, "XAG", "SILVER")
    no_fmp = MarketData(conn, eodhd_factory=lambda: None, fmp_factory=lambda: None, now_fn=Clock())
    assert no_fmp.quote_for_position(position) is None  # brak ceny -> N/A, nie zgadujemy
    insert_manual_valuation(conn, position_id=position["position_id"], kind="MARKET", price_per_unit=210.0,
                            currency="PLN", valuation_date="2026-10-17")
    conn.commit()
    assert no_fmp.quote_for_position(position).source == "wycena ręczna"
    clock = Clock()
    clock.now += dt.timedelta(minutes=16)  # po oknie backoff nieudanej próby
    quote = MarketData(conn, eodhd_factory=lambda: None, fmp_factory=FakeFMP, now_fn=clock).quote_for_position(position)
    assert (quote.price, quote.currency, quote.source) == (57.305, "USD", "FMP (kontrakt na srebro)")

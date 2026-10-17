"""Testy `ui/instrument_lookup.py` (Faza 7 KROK 7). Zero realnych
wywołań sieciowych -- `FMPClient`/`load_config` podstawione fejkami,
ten sam wzorzec co `monkeypatch.setattr(cli, "FMPClient", ...)` w
`test_cli.py`."""

from __future__ import annotations

import pytest

from buffett_scanner.providers.fmp import FMPError
from buffett_scanner.ui import instrument_lookup


class _FakeFMPClient:
    """`profile` zwraca z góry ustalony słownik per symbol; symbol
    nieznany -> FMPError (dokładnie zachowanie realnego klienta, gdy
    FMP nie rozpoznaje instrumentu)."""

    PROFILES = {
        "SU.PA": {
            "symbol": "SU.PA", "companyName": "Schneider Electric S.E.",
            "exchange": "PAR", "currency": "EUR", "price": 260.5, "cik": None,
        },
        "GSK.L": {
            "symbol": "GSK.L", "companyName": "GSK plc",
            "exchange": "LSE", "currency": "GBp", "price": 1765.5, "cik": None,
        },
        "AAPL": {
            "symbol": "AAPL", "companyName": "Apple Inc.",
            "exchange": "NASDAQ", "currency": "USD", "price": 333.63, "cik": "0000320193",
        },
    }

    def __init__(self, api_key):
        self._api_key = api_key

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass

    def get_company_profile(self, symbol):
        if symbol not in self.PROFILES:
            raise FMPError(f"Brak profilu dla {symbol} (pusta lista odpowiedzi FMP).")
        return self.PROFILES[symbol]


class _FakeResolvedConfig:
    class _DataProvider:
        def resolve_api_key(self):
            return "fake-key"

    data_provider = _DataProvider()


class _FakeUnresolvedConfig:
    class _DataProvider:
        def resolve_api_key(self):
            raise RuntimeError("Brak zmiennej środowiskowej z kluczem API.")

    data_provider = _DataProvider()


def test_lookup_known_european_listing_returns_fmp_fields_verbatim(monkeypatch):
    """SU.PA -- realny wynik technicznego testu (Faza 7 KROK 7): FMP
    rozpoznaje Euronext Paris, cik=None (brak SEC CIK dla spółki
    francuskiej) -- zwracane dokładnie, nie zgadywane."""
    monkeypatch.setattr(instrument_lookup, "load_config", lambda: _FakeResolvedConfig())
    monkeypatch.setattr(instrument_lookup, "FMPClient", _FakeFMPClient)

    result = instrument_lookup.lookup_instrument("SU.PA")
    assert result is not None
    assert result.symbol == "SU.PA"
    assert result.company_name == "Schneider Electric S.E."
    assert result.exchange == "PAR"
    assert result.currency == "EUR"
    assert result.cik is None


def test_lookup_lse_listing_keeps_gbp_pence_currency_string_verbatim(monkeypatch):
    """GSK.L -- FMP zwraca walutę "GBp" (pensy), NIE "GBP" (funty).
    Funkcja NIGDY nie normalizuje/konwertuje tego stringa -- UI musi
    pokazać dokładnie to, co zwrócił dostawca."""
    monkeypatch.setattr(instrument_lookup, "load_config", lambda: _FakeResolvedConfig())
    monkeypatch.setattr(instrument_lookup, "FMPClient", _FakeFMPClient)

    result = instrument_lookup.lookup_instrument("GSK.L")
    assert result.currency == "GBp"


def test_lookup_unrecognized_symbol_returns_none_not_exception(monkeypatch):
    """Realny bug znaleziony w technicznym teście: bare "SU" (bez
    sufiksu giełdy) trafia na CAŁKOWICIE INNĄ spółkę (Suncor Energy) --
    tu symulujemy po prostu przypadek "FMP nie rozpoznaje" (404/pusta
    odpowiedź), bo to jest przypadek, który ta funkcja ma obsłużyć
    defensywnie (poprawne rozróżnienie dwóch różnych spółek o tym samym
    skróconym symbolu to odpowiedzialność UI -- pokazanie company_name
    do potwierdzenia, nie tej funkcji)."""
    monkeypatch.setattr(instrument_lookup, "load_config", lambda: _FakeResolvedConfig())
    monkeypatch.setattr(instrument_lookup, "FMPClient", _FakeFMPClient)

    assert instrument_lookup.lookup_instrument("SCHN.PA") is None


def test_lookup_without_configured_api_key_returns_none_not_exception(monkeypatch):
    """Sekcja 6 decyzji właścicielki: brak klucza API (np. lokalny
    Streamlit bez .env) NIGDY nie wywala UI -- traktowane identycznie
    jak "FMP nie rozpoznaje", formularz pozwala zapisać bez ceny."""
    monkeypatch.setattr(instrument_lookup, "load_config", lambda: _FakeUnresolvedConfig())

    assert instrument_lookup.lookup_instrument("AAPL") is None


def test_lookup_empty_symbol_returns_none_without_calling_fmp(monkeypatch):
    def _boom():
        raise AssertionError("load_config nie powinien być wołany dla pustego symbolu")

    monkeypatch.setattr(instrument_lookup, "load_config", _boom)
    assert instrument_lookup.lookup_instrument("   ") is None


# --- Faza 9: blokada zapisu bez potwierdzenia ---

from buffett_scanner.ui.instrument_lookup import InstrumentLookupResult, instrument_save_errors  # noqa: E402

_SUNCOR = InstrumentLookupResult(
    symbol="SU", company_name="Suncor Energy Inc.", exchange="NYSE", currency="USD", price=30.0, cik="0000311337",
)


def test_save_blocked_when_fmp_recognized_but_not_confirmed():
    errors = instrument_save_errors("SU", looked_up=True, result=_SUNCOR, confirmed=False)
    assert len(errors) == 1
    assert "Suncor" in errors[0]


def test_save_blocked_when_symbol_not_checked():
    assert instrument_save_errors("SU.PA", looked_up=False, result=None, confirmed=False)


def test_save_allowed_when_confirmed():
    assert instrument_save_errors("SU", looked_up=True, result=_SUNCOR, confirmed=True) == []


def test_save_allowed_manually_when_fmp_did_not_recognize():
    assert instrument_save_errors("XYZ.WA", looked_up=True, result=None, confirmed=False) == []


def test_save_blocked_on_empty_symbol():
    assert instrument_save_errors("  ", looked_up=True, result=None, confirmed=False)

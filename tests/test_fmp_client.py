"""Testy klienta FMP.

Warstwa jednostkowa (mock httpx, bez sieci) + jeden test integracyjny
oznaczony `integration`, pominięty domyślnie i uruchamiany tylko z
prawdziwym FMP_API_KEY w środowisku (`pytest -m integration`) — to
"manualny smoke-test przed deployem" z planu testów design review.
"""

from __future__ import annotations

import os

import httpx
import pytest

from buffett_scanner.config import load_config
from buffett_scanner.providers.fmp import FMPClient, FMPError, normalize_fundamentals_rows


class _FakeResponse:
    def __init__(self, status_code: int, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload

    @property
    def text(self):
        return str(self._payload)


def test_fmp_client_rejects_empty_api_key():
    with pytest.raises(FMPError):
        FMPClient("")


def test_get_sp500_constituents_parses_list(monkeypatch):
    client = FMPClient("dummy-key")
    fake_payload = [
        {"symbol": "AAPL", "name": "Apple Inc.", "sector": "Technology",
         "subSector": "Consumer Electronics", "cik": "0000320193"},
    ]
    monkeypatch.setattr(
        client._client, "get", lambda url, params=None: _FakeResponse(200, fake_payload)
    )
    result = client.get_sp500_constituents()
    assert result == fake_payload


def test_get_sp500_constituents_raises_on_unexpected_shape(monkeypatch):
    client = FMPClient("dummy-key")
    monkeypatch.setattr(
        client._client, "get", lambda url, params=None: _FakeResponse(200, {"not": "a list"})
    )
    with pytest.raises(FMPError):
        client.get_sp500_constituents()


def test_get_company_profile_parses_first_element(monkeypatch):
    client = FMPClient("dummy-key")
    fake_payload = [{"symbol": "AAPL", "cik": "0000320193", "companyName": "Apple Inc."}]
    monkeypatch.setattr(
        client._client, "get", lambda url, params=None: _FakeResponse(200, fake_payload)
    )
    profile = client.get_company_profile("AAPL")
    assert profile["cik"] == "0000320193"


def test_get_company_profile_raises_on_empty_result(monkeypatch):
    client = FMPClient("dummy-key")
    monkeypatch.setattr(
        client._client, "get", lambda url, params=None: _FakeResponse(200, [])
    )
    with pytest.raises(FMPError):
        client.get_company_profile("NOPE")


def test_get_company_profile_accepts_bare_dict_shape(monkeypatch):
    """FMP stable może zwrócić pojedynczy obiekt zamiast listy z jednym
    elementem — kod musi obsłużyć oba warianty (patrz docstring fmp.py)."""
    client = FMPClient("dummy-key")
    fake_payload = {"symbol": "AAPL", "cik": "0000320193", "companyName": "Apple Inc."}
    monkeypatch.setattr(
        client._client, "get", lambda url, params=None: _FakeResponse(200, fake_payload)
    )
    profile = client.get_company_profile("AAPL")
    assert profile["cik"] == "0000320193"


def test_get_historical_prices_accepts_flat_list_shape(monkeypatch):
    """FMP stable prawdopodobnie zwraca płaską listę zamiast starego
    opakowania {"historical": [...]} z v3 — kod musi obsłużyć oba warianty."""
    client = FMPClient("dummy-key")
    fake_payload = [
        {"date": "2026-01-03", "open": 3, "high": 3, "low": 3, "close": 3, "adjClose": 3, "volume": 300},
        {"date": "2026-01-02", "open": 2, "high": 2, "low": 2, "close": 2, "adjClose": 2, "volume": 200},
    ]
    monkeypatch.setattr(
        client._client, "get", lambda url, params=None: _FakeResponse(200, fake_payload)
    )
    rows = client.get_historical_prices("AAPL", from_date="2026-01-01", to_date="2026-01-03")
    assert [r["date"] for r in rows] == ["2026-01-02", "2026-01-03"]


def test_get_historical_prices_normalizes_field_names_and_sorts_ascending(monkeypatch):
    client = FMPClient("dummy-key")
    fake_payload = {
        "symbol": "AAPL",
        "historical": [
            {"date": "2026-01-03", "open": 3, "high": 3, "low": 3, "close": 3, "adjClose": 3, "volume": 300},
            {"date": "2026-01-02", "open": 2, "high": 2, "low": 2, "close": 2, "adjClose": 2, "volume": 200},
        ],
    }
    monkeypatch.setattr(
        client._client, "get", lambda url, params=None: _FakeResponse(200, fake_payload)
    )
    rows = client.get_historical_prices("AAPL", from_date="2026-01-01", to_date="2026-01-03")
    assert [r["date"] for r in rows] == ["2026-01-02", "2026-01-03"]
    assert rows[0]["adj_close"] == 2  # adjClose -> adj_close


def test_non_200_status_includes_truncated_error_body(monkeypatch):
    """FMP zwraca generyczne komunikaty błędów (np. "Invalid API KEY..."),
    bez danych konta — bezpiecznie je pokazać, nawet w publicznym logu
    GitHub Actions, żeby diagnoza nie wymagała zgadywania (patrz historia
    w docstring fmp.py)."""
    client = FMPClient("dummy-key")

    class _FakeTextResponse(_FakeResponse):
        @property
        def text(self):
            return '{"Error Message":"Invalid API KEY."}'

    monkeypatch.setattr(
        client._client, "get",
        lambda url, params=None: _FakeTextResponse(403, {"Error Message": "Invalid API KEY."}),
    )
    with pytest.raises(FMPError) as exc_info:
        client.get_sp500_constituents()
    assert "Invalid API KEY" in str(exc_info.value)


def test_get_income_statement_parses_list(monkeypatch):
    client = FMPClient("dummy-key")
    fake_payload = [
        {"date": "2024-12-31", "fiscalYear": 2024, "period": "FY",
         "revenue": 1000.0, "netIncome": 100.0, "ebitda": 200.0},
    ]
    monkeypatch.setattr(
        client._client, "get", lambda url, params=None: _FakeResponse(200, fake_payload)
    )
    result = client.get_income_statement("AAPL")
    assert result == fake_payload


def test_get_income_statement_raises_on_unexpected_shape(monkeypatch):
    client = FMPClient("dummy-key")
    monkeypatch.setattr(
        client._client, "get", lambda url, params=None: _FakeResponse(200, {"not": "a list"})
    )
    with pytest.raises(FMPError):
        client.get_income_statement("AAPL")


def test_get_balance_sheet_statement_parses_list(monkeypatch):
    client = FMPClient("dummy-key")
    fake_payload = [{"date": "2024-12-31", "fiscalYear": 2024, "period": "FY", "totalDebt": 500.0}]
    monkeypatch.setattr(
        client._client, "get", lambda url, params=None: _FakeResponse(200, fake_payload)
    )
    assert client.get_balance_sheet_statement("AAPL") == fake_payload


def test_get_cash_flow_statement_parses_list(monkeypatch):
    client = FMPClient("dummy-key")
    fake_payload = [
        {"date": "2024-12-31", "fiscalYear": 2024, "period": "FY", "operatingCashFlow": 900.0},
    ]
    monkeypatch.setattr(
        client._client, "get", lambda url, params=None: _FakeResponse(200, fake_payload)
    )
    assert client.get_cash_flow_statement("AAPL") == fake_payload


def test_normalize_fundamentals_rows_maps_canonical_line_items():
    income = [{"date": "2024-12-31", "fiscalYear": 2024, "period": "FY",
               "revenue": 1000.0, "netIncome": 100.0, "ebitda": 200.0}]
    balance = [{"date": "2024-12-31", "fiscalYear": 2024, "period": "FY",
                "totalDebt": 500.0, "cashAndCashEquivalents": 150.0,
                "totalCurrentAssets": 400.0, "totalCurrentLiabilities": 250.0}]
    cashflow = [{"date": "2024-12-31", "fiscalYear": 2024, "period": "FY",
                 "operatingCashFlow": 900.0, "capitalExpenditure": -300.0}]

    rows = normalize_fundamentals_rows(income, balance, cashflow)
    by_item = {r["line_item"]: r["value"] for r in rows}

    assert by_item["revenue"] == 1000.0
    assert by_item["net_income"] == 100.0
    assert by_item["ebitda"] == 200.0
    assert by_item["total_debt"] == 500.0
    assert by_item["cash_and_equivalents"] == 150.0
    assert by_item["operating_cash_flow"] == 900.0
    # capex ujemny w źródle FMP -> zapisany jako dodatnia kwota wydatku
    assert by_item["capital_expenditure"] == 300.0
    assert all(r["fiscal_period"] == "2024-FY" for r in rows)


def test_normalize_fundamentals_rows_skips_missing_fields_without_fabricating():
    income = [{"date": "2024-12-31", "fiscalYear": 2024, "period": "FY", "revenue": 1000.0}]
    rows = normalize_fundamentals_rows(income, [], [])
    line_items = {r["line_item"] for r in rows}
    assert line_items == {"revenue"}  # netIncome/ebitda brak w źródle -> nie fabrykujemy 0/None


@pytest.mark.integration
def test_live_smoke_sp500_constituents_shape():
    """Wymaga prawdziwego FMP_API_KEY. Potwierdza (albo obala) założenia
    o kształcie odpowiedzi opisane w providers/fmp.py."""
    config = load_config()
    api_key = os.environ.get(config.data_provider.api_key_env_var)
    if not api_key:
        pytest.skip(f"Brak {config.data_provider.api_key_env_var} — pomijam test integracyjny.")
    with FMPClient(api_key) as client:
        data = client.get_sp500_constituents()
        assert isinstance(data, list) and len(data) > 400
        sample = data[0]
        for field in ("symbol", "name", "cik"):
            assert field in sample, f"Oczekiwane pole '{field}' nie występuje — zaktualizuj fmp.py"

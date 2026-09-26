"""Testy klienta transportowego holdingów IVV (Faza 5.2, research
v1.27). Warstwa jednostkowa (mock httpx, bez sieci)."""

from __future__ import annotations

import httpx
import pytest

from buffett_scanner.providers.ivv_holdings import IvvHoldingsError, fetch_ivv_holdings_csv


class _FakeResponse:
    def __init__(self, status_code: int, text: str = ""):
        self.status_code = status_code
        self.text = text


def test_fetch_ivv_holdings_csv_converts_iso_date_to_yyyymmdd(monkeypatch):
    captured = {}

    def fake_get(url, params=None, timeout=None, follow_redirects=None, headers=None):
        captured["params"] = params
        return _FakeResponse(200, "Ticker,Name\nAAPL,Apple\n")

    monkeypatch.setattr(httpx, "get", fake_get)
    result = fetch_ivv_holdings_csv("2012-01-31")
    assert captured["params"]["asOfDate"] == "20120131"
    assert "AAPL" in result


def test_fetch_ivv_holdings_csv_omits_as_of_date_when_none(monkeypatch):
    captured = {}

    def fake_get(url, params=None, timeout=None, follow_redirects=None, headers=None):
        captured["params"] = params
        return _FakeResponse(200, "ok")

    monkeypatch.setattr(httpx, "get", fake_get)
    fetch_ivv_holdings_csv(None)
    assert "asOfDate" not in captured["params"]


def test_fetch_ivv_holdings_csv_raises_on_non_200(monkeypatch):
    monkeypatch.setattr(
        httpx, "get",
        lambda url, params=None, timeout=None, follow_redirects=None, headers=None: _FakeResponse(404, "Not Found"),
    )
    with pytest.raises(IvvHoldingsError, match="404"):
        fetch_ivv_holdings_csv("2012-01-31")


def test_fetch_ivv_holdings_csv_raises_on_network_error(monkeypatch):
    def _raise(*args, **kwargs):
        raise httpx.ConnectTimeout("timeout")

    monkeypatch.setattr(httpx, "get", _raise)
    with pytest.raises(IvvHoldingsError):
        fetch_ivv_holdings_csv("2012-01-31")

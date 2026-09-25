"""Testy klienta `fja05680/sp500` (Faza 5, punkt 5.2). Warstwa
jednostkowa (mock httpx, bez sieci)."""

from __future__ import annotations

import httpx
import pytest

from buffett_scanner.providers.sp500_history import Sp500HistoryError, fetch_components_csv


class _FakeResponse:
    def __init__(self, status_code: int, text: str = ""):
        self.status_code = status_code
        self.text = text


def test_fetch_components_csv_returns_text_on_200(monkeypatch):
    fake_text = "date,tickers\n2012-01-01,\"AAA,BBB\"\n"
    monkeypatch.setattr(httpx, "get", lambda url, timeout, follow_redirects: _FakeResponse(200, fake_text))
    result = fetch_components_csv()
    assert result == fake_text


def test_fetch_components_csv_raises_on_non_200(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda url, timeout, follow_redirects: _FakeResponse(404))
    with pytest.raises(Sp500HistoryError):
        fetch_components_csv()


def test_fetch_components_csv_raises_on_network_error(monkeypatch):
    def _raise(*args, **kwargs):
        raise httpx.ConnectTimeout("timeout")

    monkeypatch.setattr(httpx, "get", _raise)
    with pytest.raises(Sp500HistoryError):
        fetch_components_csv()

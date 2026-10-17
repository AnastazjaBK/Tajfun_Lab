"""Minimalny klient EODHD (Faza 11, P0b -- Decyzja właścicielki
2026-10-17: FMP dla USA, EODHD Free dla instrumentów europejskich).

Formaty odpowiedzi potwierdzone empirycznie diagnostyką z 2026-10-17
(run 39070026144): `search/{symbol}` (Code, Exchange, Name, Type,
Currency, ISIN, previousClose, previousCloseDate), `eod/{symbol}`
(date, open, high, low, close, adjusted_close, volume; na planie Free
tylko ostatni rok + pole `warning`), `div/{symbol}` (date=ex-dividend,
paymentDate, declarationDate, period, value, unadjustedValue, currency).

Token wyłącznie ze zmiennej środowiskowej `EODHD_API_KEY` (Streamlit
Secrets / GitHub Secrets); nigdy nie trafia do komunikatów błędów."""

from __future__ import annotations

import os

import httpx

BASE_URL = "https://eodhd.com/api"
API_KEY_ENV_VAR = "EODHD_API_KEY"
DEFAULT_TIMEOUT = 15.0


class EODHDError(RuntimeError):
    pass


def resolve_api_key() -> str | None:
    return os.environ.get(API_KEY_ENV_VAR) or None


class EODHDClient:
    def __init__(self, api_key: str, *, http_get=httpx.get):
        if not api_key:
            raise EODHDError("Pusty klucz API EODHD.")
        self._api_key = api_key
        self._http_get = http_get

    def _get(self, path: str, **params) -> object:
        try:
            resp = self._http_get(
                f"{BASE_URL}/{path}", params={**params, "api_token": self._api_key, "fmt": "json"},
                timeout=DEFAULT_TIMEOUT,
            )
        except httpx.HTTPError as exc:
            raise EODHDError(f"Błąd sieci EODHD ({path}): {type(exc).__name__}") from None
        if resp.status_code != 200:
            body = resp.text[:200].replace(self._api_key, "***")
            raise EODHDError(f"EODHD zwrócił status {resp.status_code} dla {path}: {body}")
        try:
            return resp.json()
        except ValueError:
            raise EODHDError(f"EODHD zwrócił niepoprawny JSON dla {path}") from None

    def search(self, symbol: str) -> list[dict]:
        data = self._get(f"search/{symbol}")
        return data if isinstance(data, list) else []

    def eod(self, symbol: str, *, from_date: str, to_date: str) -> list[dict]:
        data = self._get(f"eod/{symbol}", **{"from": from_date, "to": to_date})
        if not isinstance(data, list):
            raise EODHDError(f"Nieoczekiwany kształt odpowiedzi eod dla {symbol}.")
        return sorted((r for r in data if isinstance(r, dict) and r.get("date")), key=lambda r: r["date"])

    def dividends(self, symbol: str, *, from_date: str) -> list[dict]:
        data = self._get(f"div/{symbol}", **{"from": from_date})
        if not isinstance(data, list):
            raise EODHDError(f"Nieoczekiwany kształt odpowiedzi div dla {symbol}.")
        return sorted((r for r in data if isinstance(r, dict) and r.get("date")), key=lambda r: r["date"])


# Sufiks giełdy w konwencji FMP/użytkownika -> sufiks EODHD. Empirycznie
# potwierdzone (2026-10-17): PA, LSE, XETRA, F. Pozostałe wg konwencji
# EODHD -- błędny sufiks daje "nie rozpoznano", nigdy cichą pomyłkę, bo
# wynik wyszukiwania (nazwa, giełda, ISIN) użytkownik zawsze potwierdza.
EUROPEAN_SUFFIX_TO_EODHD: dict[str, str] = {
    "PA": "PA", "L": "LSE", "LSE": "LSE", "DE": "XETRA", "XETRA": "XETRA", "F": "F",
    "AS": "AS", "BR": "BR", "LS": "LS", "MI": "MI", "MC": "MC", "SW": "SW", "VI": "VI",
    "HE": "HE", "ST": "ST", "CO": "CO", "OL": "OL", "IR": "IR", "WA": "WAR", "WAR": "WAR",
}


def to_eodhd_symbol(symbol: str) -> str | None:
    """`GSK.L` -> `GSK.LSE`, `4GLD.DE` -> `4GLD.XETRA`, `SU.PA` -> `SU.PA`.
    `None`, gdy symbol nie ma europejskiego sufiksu giełdy."""
    symbol = symbol.strip().upper()
    if "." not in symbol:
        return None
    code, suffix = symbol.rsplit(".", 1)
    exchange = EUROPEAN_SUFFIX_TO_EODHD.get(suffix)
    if not code or exchange is None:
        return None
    return f"{code}.{exchange}"

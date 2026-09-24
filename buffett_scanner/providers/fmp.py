"""Cienki klient FMP (Financial Modeling Prep) — Faza 0.

ZAŁOŻENIA DO ZWERYFIKOWANIA NA ŻYWO (ważne, przeczytaj przed użyciem):
Ścieżki endpointów i kształt JSON poniżej opierają się na ogólnej,
długo udokumentowanej strukturze API v3 FMP (`/api/v3/...`), NIE na
bezpośrednim odczycie aktualnej dokumentacji — dostęp WebFetch do
site.financialmodelingprep.com był zablokowany w sesji, w której
projektowano tę architekturę (patrz docs/buffett-scanner-design-review.md,
sekcja Sources / FINAL PRE-IMPLEMENTATION STATUS). Zanim zaufasz
wynikom ingestii:

    python -m buffett_scanner.providers.fmp_smoketest

(albo `pytest -m integration`, patrz tests/test_fmp_client.py) —
uruchamia pojedyncze, tanie wywołania z Twoim prawdziwym kluczem i
pokazuje surową odpowiedź, żebyś (lub kolejna tura tej pracy) mogła
potwierdzić realny kształt danych. Jeśli któryś endpoint się nie
zgadza, ten plik jest jedynym miejscem, które trzeba poprawić — reszta
pipeline'u (db.py, scanner.py) nie zależy od szczegółów FMP.

Nigdy nie loguje ani nie wypisuje wartości klucza API.
"""

from __future__ import annotations

import time

import httpx

BASE_URL = "https://financialmodelingprep.com/api/v3"
DEFAULT_TIMEOUT = 15.0


class FMPError(RuntimeError):
    pass


class FMPClient:
    def __init__(self, api_key: str, *, base_url: str = BASE_URL, min_interval_s: float = 0.05):
        if not api_key:
            raise FMPError("Pusty klucz API FMP.")
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._min_interval_s = min_interval_s  # throttling — plan Starter: 300 wywołań/min
        self._last_call_ts = 0.0
        self._client = httpx.Client(timeout=DEFAULT_TIMEOUT)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "FMPClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_call_ts
        if elapsed < self._min_interval_s:
            time.sleep(self._min_interval_s - elapsed)

    def _get(self, path: str, **params) -> object:
        self._throttle()
        params = {**params, "apikey": self._api_key}
        url = f"{self._base_url}/{path.lstrip('/')}"
        try:
            resp = self._client.get(url, params=params)
        except httpx.HTTPError as exc:
            raise FMPError(f"Błąd sieci przy wywołaniu FMP ({path}): {exc}") from exc
        finally:
            self._last_call_ts = time.monotonic()
        if resp.status_code != 200:
            raise FMPError(
                f"FMP zwrócił status {resp.status_code} dla {path} "
                f"(treść nieujawniona tutaj celowo — może zawierać dane konta)"
            )
        try:
            return resp.json()
        except ValueError as exc:
            raise FMPError(f"FMP zwrócił niepoprawny JSON dla {path}") from exc

    def get_sp500_constituents(self) -> list[dict]:
        """Aktualny skład S&P 500 (Decyzja D4 — endpoint dostawcy).

        Założony kształt: lista obiektów z polami symbol/name/sector/
        subSector/cik. DO ZWERYFIKOWANIA — patrz docstring modułu.
        """
        data = self._get("sp500_constituent")
        if not isinstance(data, list):
            raise FMPError("Nieoczekiwany kształt odpowiedzi sp500_constituent (oczekiwano listy).")
        return data

    def get_company_profile(self, symbol: str) -> dict:
        """Profil spółki (m.in. CIK, sector, industry) dla pojedynczego tickera.

        Założony kształt: lista z jednym obiektem. DO ZWERYFIKOWANIA.
        """
        data = self._get(f"profile/{symbol}")
        if not isinstance(data, list) or not data:
            raise FMPError(f"Brak profilu dla {symbol} (pusta odpowiedź FMP).")
        return data[0]

    def get_historical_prices(self, symbol: str, *, from_date: str, to_date: str) -> list[dict]:
        """Dzienne OHLCV dla tickera w zadanym zakresie dat (ISO YYYY-MM-DD).

        Założony kształt: {"symbol": ..., "historical": [{"date","open",
        "high","low","close","adjClose","volume",...}, ...]} — malejąco
        po dacie. DO ZWERYFIKOWANIA.
        """
        data = self._get(
            f"historical-price-full/{symbol}", **{"from": from_date, "to": to_date}
        )
        if not isinstance(data, dict) or "historical" not in data:
            raise FMPError(
                f"Nieoczekiwany kształt odpowiedzi historical-price-full dla {symbol}."
            )
        rows = data["historical"]
        # normalizacja do rosnącego porządku + nazw pól zgodnych z db.insert_price_rows
        normalized = [
            {
                "date": r["date"],
                "open": r.get("open"),
                "high": r.get("high"),
                "low": r.get("low"),
                "close": r.get("close"),
                "adj_close": r.get("adjClose", r.get("close")),
                "volume": r.get("volume"),
            }
            for r in rows
        ]
        normalized.sort(key=lambda r: r["date"])
        return normalized

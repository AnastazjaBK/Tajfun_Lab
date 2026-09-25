"""Cienki klient FMP (Financial Modeling Prep) — Faza 0.

HISTORIA ZAŁOŻEŃ (ważne, przeczytaj przed dalszą zmianą tego pliku):
Pierwsza wersja tego klienta używała starszej rodziny endpointów
`/api/v3/...` — dla klucza właścicielki (plan Free, potwierdzony jako
działający przez wsparcie FMP na endpointcie `/stable/earnings-calendar`)
te stare endpointy konsekwentnie zwracały 403, podczas gdy `/stable/...`
działa. Dlatego cały klient przepisany na rodzinę `/stable/...`.

Mimo to dokładne nazwy pól w odpowiedziach (`historical-price-eod/full`,
`sp500-constituent`) NIE zostały potwierdzone bezpośrednim odczytem
dokumentacji — WebFetch do site.financialmodelingprep.com był
zablokowany w sesji projektowej. Parsowanie poniżej jest więc celowo
DEFENSYWNE (akceptuje kilka prawdopodobnych kształtów odpowiedzi) i
loguje surowy kształt w fmp_smoketest.py, żeby dało się to szybko
poprawić, jeśli któreś założenie się nie zgadza — bez zgadywania na
ślepo po raz kolejny.

Treść błędów FMP (np. "Invalid API KEY. Feel free to create...") jest
generycznym komunikatem, nie zawiera danych konta ani klucza — dlatego
FMPError bezpiecznie pokazuje jej fragment, nawet w publicznym logu
GitHub Actions.
"""

from __future__ import annotations

import time

import httpx

BASE_URL = "https://financialmodelingprep.com/stable"
DEFAULT_TIMEOUT = 15.0
MAX_ERROR_BODY_CHARS = 300


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
            body_preview = resp.text[:MAX_ERROR_BODY_CHARS]
            raise FMPError(
                f"FMP zwrócił status {resp.status_code} dla {path}. "
                f"Treść odpowiedzi (skrócona): {body_preview}"
            )
        try:
            return resp.json()
        except ValueError as exc:
            raise FMPError(f"FMP zwrócił niepoprawny JSON dla {path}") from exc

    def get_sp500_constituents(self) -> list[dict]:
        """Aktualny skład S&P 500 (Decyzja D4 — endpoint dostawcy).

        Oczekiwany kształt: lista obiektów z polami symbol/name/sector/
        cik (nazwy dokładnych pól niepotwierdzone — patrz docstring modułu).
        """
        data = self._get("sp500-constituent")
        if not isinstance(data, list):
            raise FMPError(
                f"Nieoczekiwany kształt odpowiedzi sp500-constituent "
                f"(oczekiwano listy, dostałam {type(data).__name__})."
            )
        return data

    def get_company_profile(self, symbol: str) -> dict:
        """Profil spółki (m.in. CIK, sector, industry) dla pojedynczego tickera.

        FMP stable może zwrócić pojedynczy obiekt albo listę z jednym
        elementem — obsługujemy oba warianty defensywnie.
        """
        data = self._get("profile", symbol=symbol)
        if isinstance(data, list):
            if not data:
                raise FMPError(f"Brak profilu dla {symbol} (pusta lista odpowiedzi FMP).")
            return data[0]
        if isinstance(data, dict):
            if not data:
                raise FMPError(f"Brak profilu dla {symbol} (pusty obiekt odpowiedzi FMP).")
            return data
        raise FMPError(
            f"Nieoczekiwany kształt odpowiedzi profile dla {symbol} "
            f"(dostałam {type(data).__name__})."
        )

    def get_historical_prices(self, symbol: str, *, from_date: str, to_date: str) -> list[dict]:
        """Dzienne OHLCV dla tickera w zadanym zakresie dat (ISO YYYY-MM-DD).

        FMP stable prawdopodobnie zwraca płaską listę (bez opakowania w
        {"historical": [...]} jak stare v3) — obsługujemy oba warianty.
        """
        data = self._get(
            "historical-price-eod/full", symbol=symbol,
            **{"from": from_date, "to": to_date},
        )
        if isinstance(data, dict) and "historical" in data:
            rows = data["historical"]
        elif isinstance(data, list):
            rows = data
        else:
            raise FMPError(
                f"Nieoczekiwany kształt odpowiedzi historical-price-eod dla {symbol} "
                f"(dostałam {type(data).__name__})."
            )
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

"""Cienki klient FMP (Financial Modeling Prep) — Faza 0.

HISTORIA ZAŁOŻEŃ (ważne, przeczytaj przed dalszą zmianą tego pliku):
Pierwsza wersja tego klienta używała starszej rodziny endpointów
`/api/v3/...`, która dla klucza właścicielki konsekwentnie zwracała
403. Przepisany na `/stable/...` i **empirycznie potwierdzony** przez
`fmp_smoketest.py` uruchomiony z prawdziwym kluczem (plan Free):

- `profile` — POTWIERDZONY: zwraca pojedynczy płaski obiekt (nie listę),
  z polem `cik` dokładnie tam, gdzie zakładał kod. Działa na planie Free.
- `historical-price-eod/full` — POTWIERDZONY: zwraca płaską listę
  obiektów z polami `date/open/high/low/close/volume` (bez `adjClose`
  w przetestowanej odpowiedzi — kod używa `close` jako fallbacku, patrz
  `get_historical_prices`). Działa na planie Free.
- `sp500-constituent` — endpoint istnieje i jest poprawnie zaadresowany,
  ale zwraca 402 „Restricted Endpoint" na planie Free — **wymaga planu
  płatnego** (Starter lub wyższego). To nie jest błąd klucza ani kodu.

Wniosek dla Fazy 0: ingest pojedynczych spółek (profil + ceny) działa
już na planie Free — pełne uniwersum S&P 500 (0.2) będzie wymagało
Startera dopiero wtedy, gdy faktycznie zechcemy go zaingestować, nie
teraz. Do tego czasu `ingest-prices`/`scan` testujemy na ręcznie
podanej liście tickerów (patrz cli.py).

Treść błędów FMP (np. "Invalid API KEY. Feel free to create...") jest
generycznym komunikatem, nie zawiera danych konta ani klucza — dlatego
FMPError bezpiecznie pokazuje jej fragment, nawet w publicznym logu
GitHub Actions.

FAZA 1 — endpointy fundamentalne (income-statement, balance-sheet-statement,
cash-flow-statement): ścieżki i nazwy pól NIE zostały jeszcze potwierdzone
przez rzeczywiste wywołanie (WebFetch do dokumentacji FMP zablokowany
przez proxy sieciowe sesji przez cały czas trwania tego projektu). Kod
poniżej jest napisany defensywnie na bazie publicznie znanej konwencji
nazewnictwa `/stable/`, dokładnie tym samym trybem co profile/historical
w Fazie 0 — do zweryfikowania empirycznie przez `fmp_smoketest.py` na
prawdziwym koncie, nie do potraktowania jako fakt, dopóki nie przyjdzie
potwierdzenie.

**EMPIRYCZNIE POTWIERDZONE (workflow „Phase 1 Proof Run", 2026-09-25,
plan Free):** ścieżka `income-statement` jest poprawnie zaadresowana
(FMP nie zwrócił 404) — zwróciła **402** wyłącznie z powodu parametru
`limit`: „The values for 'limit' must be between 0 and 5 based on your
current subscription." Plan Free pozwala maksymalnie na 5 okresów na
zapytanie. To NIE oznacza, że endpoint wymaga planu płatnego (w
przeciwieństwie do `sp500-constituent` w Fazie 0, który dawał jawne
„Restricted Endpoint") — wymaga tylko poprawnego parametru. Kod
poprawiony: domyślny `limit` to teraz `STATEMENT_LIMIT_FREE_PLAN = 5`.
Kształt samej odpowiedzi (nazwy pól w JSON) wciąż niepotwierdzony —
czeka na kolejne uruchomienie.
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

    def _get_statement(self, path: str, symbol: str, *, period: str, limit: int) -> list[dict]:
        data = self._get(path, symbol=symbol, period=period, limit=limit)
        if not isinstance(data, list):
            raise FMPError(
                f"Nieoczekiwany kształt odpowiedzi {path} dla {symbol} "
                f"(oczekiwano listy, dostałam {type(data).__name__})."
            )
        return data

    # limit=5: POTWIERDZONY empirycznie sufit dla planu Free (Phase 1 Proof
    # Run, 2026-09-25) — FMP zwraca 402 z komunikatem "The values for
    # 'limit' must be between 0 and 5 based on your current subscription"
    # dla income-statement przy limit=10 (domyślna wartość biblioteki dla
    # planów płatnych). Nie zgadywane — to bezpośrednia treść błędu FMP.
    STATEMENT_LIMIT_FREE_PLAN = 5

    def get_income_statement(
        self, symbol: str, *, period: str = "annual", limit: int = STATEMENT_LIMIT_FREE_PLAN
    ) -> list[dict]:
        """Surowe wiersze rachunku wyników. Ścieżka i nazwy pól w
        odpowiedzi wciąż NIEPOTWIERDZONE (patrz docstring modułu) —
        `limit` natomiast JEST potwierdzony (patrz STATEMENT_LIMIT_FREE_PLAN)."""
        return self._get_statement("income-statement", symbol, period=period, limit=limit)

    def get_balance_sheet_statement(
        self, symbol: str, *, period: str = "annual", limit: int = STATEMENT_LIMIT_FREE_PLAN
    ) -> list[dict]:
        """Surowe wiersze bilansu (kształt NIEPOTWIERDZONY — jak wyżej)."""
        return self._get_statement("balance-sheet-statement", symbol, period=period, limit=limit)

    def get_cash_flow_statement(
        self, symbol: str, *, period: str = "annual", limit: int = STATEMENT_LIMIT_FREE_PLAN
    ) -> list[dict]:
        """Surowe wiersze cash flow (kształt NIEPOTWIERDZONY — jak wyżej)."""
        return self._get_statement("cash-flow-statement", symbol, period=period, limit=limit)


def _statement_period_key(row: dict) -> str:
    """Wyprowadza stabilny klucz okresu fiskalnego z wiersza sprawozdania.
    Preferuje (fiscalYear|calendarYear)+period; fallback na `date`, bo
    dokładne nazwy pól nie są potwierdzone (patrz docstring modułu)."""
    fiscal_year = row.get("fiscalYear") or row.get("calendarYear")
    period = row.get("period")
    if fiscal_year and period:
        return f"{fiscal_year}-{period}"
    date = row.get("date")
    if date:
        return str(date)
    raise FMPError("Nie można wyznaczyć fiscal_period — brak fiscalYear/period/date w wierszu.")


def normalize_fundamentals_rows(
    income_rows: list[dict], balance_rows: list[dict], cashflow_rows: list[dict]
) -> list[dict]:
    """Łączy trzy surowe sprawozdania FMP w jedną listę wierszy w formacie
    oczekiwanym przez `db.insert_fundamentals_rows` (long, kanoniczne
    line_item — patrz `buffett_scanner.db.LINE_ITEM_STATEMENT_TYPE`).

    Brakujące pole w danym wierszu (np. spółka bez `ebitda` w odpowiedzi)
    jest po prostu pomijane — nigdy nie zapisujemy zgadywanej wartości.
    `capital_expenditure`: FMP prawdopodobnie raportuje capex jako wartość
    ujemną (odpływ gotówki); zapisujemy `abs()`, zgodnie z konwencją
    `FundamentalsPeriod.capital_expenditure` (dodatnia kwota wydatku).
    """
    rows: list[dict] = []

    def _emit(source_rows: list[dict], field_map: dict[str, str]) -> None:
        for r in source_rows:
            period_end_date = r.get("date")
            if not period_end_date:
                continue
            fiscal_period = _statement_period_key(r)
            filed_date = r.get("filingDate") or r.get("acceptedDate")
            for line_item, raw_key in field_map.items():
                value = r.get(raw_key)
                if value is None:
                    continue
                if line_item == "capital_expenditure":
                    value = abs(value)
                rows.append(
                    {
                        "fiscal_period": fiscal_period,
                        "period_end_date": period_end_date,
                        "filed_date": filed_date,
                        "line_item": line_item,
                        "value": value,
                        "unit": "USD",
                    }
                )

    _emit(income_rows, {"revenue": "revenue", "net_income": "netIncome", "ebitda": "ebitda"})
    _emit(
        balance_rows,
        {
            "total_debt": "totalDebt",
            "cash_and_equivalents": "cashAndCashEquivalents",
            "total_current_assets": "totalCurrentAssets",
            "total_current_liabilities": "totalCurrentLiabilities",
        },
    )
    _emit(
        cashflow_rows,
        {"operating_cash_flow": "operatingCashFlow", "capital_expenditure": "capitalExpenditure"},
    )
    return rows

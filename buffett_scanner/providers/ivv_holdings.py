"""Klient historycznych holdingów ETF iShares Core S&P 500 (IVV) —
Faza 5.2, research alternatywnego, niezależnego źródła walidacji
`universe_membership` 2012+ (v1.27 design review).

Darmowe, bez klucza API — publiczny CSV z ishares.com, parametr
`asOfDate=YYYYMMDD` (potwierdzone dwoma niezależnymi narzędziami
trzecimi w researchu v1.27, NIE bezpośrednim testem — `ishares.com`
jest zablokowany przez proxy sieciowy w sesji interaktywnej). To jest
KLIENT TRANSPORTOWY (pobiera surowy tekst), zero logiki parsującej —
dokładny kształt CSV (liczba wierszy preambuły, nazwy kolumn) jest
NIEPOTWIERDZONY, więc parsowanie w osobnym module musi być defensywne
i nigdy nie zakładać stałej liczby wierszy nagłówka."""

from __future__ import annotations

import httpx

IVV_HOLDINGS_URL = (
    "https://www.ishares.com/us/products/239726/ishares-core-sp-500-etf/"
    "1467271812596.ajax"
)
DEFAULT_TIMEOUT = 30.0

# Realistyczny nagłówek User-Agent — defensywne zabezpieczenie na wypadek,
# gdyby ishares.com odrzucał żądania bez wyglądającego na przeglądarkę
# nagłówka (NIEPOTWIERDZONE, czy jest to faktycznie wymagane).
_USER_AGENT = (
    "Mozilla/5.0 (compatible; TajfunLabResearch/1.0; "
    "+https://github.com/AnastazjaBK/Tajfun_Lab)"
)


class IvvHoldingsError(RuntimeError):
    pass


def fetch_ivv_holdings_csv(as_of_date: str | None = None, *, timeout: float = DEFAULT_TIMEOUT) -> str:
    """Pobiera surowy tekst CSV holdingów IVV. `as_of_date` w formacie
    ISO (YYYY-MM-DD) — konwertowane na YYYYMMDD wymagane przez
    `asOfDate`. `as_of_date=None` -> bieżące holdingi (bez parametru).
    Zwraca surowy tekst do inspekcji/parsowania przez wywołującego —
    ten moduł nigdy nie zakłada, że odpowiedź jest poprawnym/oczekiwanym
    CSV, to zadanie warstwy diagnostycznej (Proof Run)."""
    params = {"fileType": "csv", "fileName": "IVV_holdings", "dataType": "fund"}
    if as_of_date:
        params["asOfDate"] = as_of_date.replace("-", "")

    try:
        resp = httpx.get(
            IVV_HOLDINGS_URL, params=params, timeout=timeout,
            follow_redirects=True, headers={"User-Agent": _USER_AGENT},
        )
    except httpx.HTTPError as exc:
        raise IvvHoldingsError(f"Błąd sieci przy pobieraniu holdingów IVV: {exc}") from exc

    if resp.status_code != 200:
        raise IvvHoldingsError(
            f"ishares.com zwrócił status {resp.status_code} dla asOfDate={as_of_date}. "
            f"Treść odpowiedzi (skrócona): {resp.text[:300]}"
        )
    return resp.text

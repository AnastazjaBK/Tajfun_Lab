"""Ceny bieżące i kursy walut dla PORTFELA (Faza 9, Decyzja właścicielki
2026-10-17: "Wprowadź wszystko. Kursy NBP.").

Dwa źródła, oba wyłącznie do WYCENY posiadanych pozycji (nigdy do
scoringu/wyceny DCF scannera):

- Cena: profil FMP (`FMPClient.get_company_profile`, ten sam endpoint co
  weryfikacja instrumentu -- empirycznie potwierdzony dla `SU.PA` (EUR) i
  `GSK.L` (GBp) na planie Free, Faza 7). Cena z opóźnieniem, NIE live.
- Kursy: NBP, tabela A (kursy średnie), `https://api.nbp.pl` -- oficjalne,
  darmowe, bez klucza. Wszystkie kursy są "PLN za 1 jednostkę waluty".

NOTOWANIA W JEDNOSTKACH ZDAWKOWYCH: LSE podaje ceny w pensach (`GBp`),
JSE w centach (`ZAc`), TASE w agorach (`ILA`). `normalize_quote` dzieli
je przez 100 i zwraca walutę główną (GBP/ZAR/ILS) -- inaczej wartość
pozycji z Londynu byłaby zawyżona 100x (systematyczny błąd obliczeniowy).

Czyste funkcje (`normalize_quote`, `parse_nbp_table`, `convert`) są
oddzielone od I/O (`fetch_quote`, `fetch_nbp_rates`) -- I/O nigdy nie
podnosi wyjątku do UI, zwraca `None` (UI pokazuje wtedy "niedostępne",
nigdy 0 ani zgadniętą wartość).
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from buffett_scanner.config import load_config
from buffett_scanner.providers.fmp import FMPClient, FMPError

NBP_TABLE_A_URL = "https://api.nbp.pl/api/exchangerates/tables/a/?format=json"
NBP_TIMEOUT_S = 10.0

# kod waluty zdawkowej (dokładnie jak zwraca FMP) -> (waluta główna, dzielnik)
MINOR_UNIT_CURRENCIES: dict[str, tuple[str, float]] = {
    "GBp": ("GBP", 100.0),
    "GBX": ("GBP", 100.0),
    "ZAc": ("ZAR", 100.0),
    "ZAC": ("ZAR", 100.0),
    "ILA": ("ILS", 100.0),
}

BASE_CURRENCY = "PLN"


@dataclass(frozen=True)
class Quote:
    price: float
    currency: str  # zawsze waluta GŁÓWNA (po `normalize_quote`)
    source: str


@dataclass(frozen=True)
class FxRates:
    """`mid_pln[code]` = ile PLN kosztuje 1 jednostka `code` (kurs średni
    NBP). PLN jest zawsze obecny z kursem 1.0."""

    mid_pln: dict[str, float]
    effective_date: str


def normalize_quote(price: float | None, currency: str | None) -> tuple[float, str] | None:
    if price is None or currency is None:
        return None
    try:
        price = float(price)
    except (TypeError, ValueError):
        return None
    if price <= 0:
        return None
    currency = currency.strip()
    if not currency:
        return None
    if currency in MINOR_UNIT_CURRENCIES:
        major, divisor = MINOR_UNIT_CURRENCIES[currency]
        return price / divisor, major
    return price, currency.upper()


def parse_nbp_table(payload: object) -> FxRates | None:
    """Odpowiedź NBP `tables/a`: lista z jednym obiektem
    `{"table": "A", "effectiveDate": "...", "rates": [{"code", "mid"}, ...]}`.
    Każdy inny kształt -> `None` (nigdy częściowo zgadnięte kursy)."""
    if not isinstance(payload, list) or not payload or not isinstance(payload[0], dict):
        return None
    table = payload[0]
    effective_date = table.get("effectiveDate")
    rates = table.get("rates")
    if not isinstance(effective_date, str) or not isinstance(rates, list):
        return None
    mid_pln: dict[str, float] = {BASE_CURRENCY: 1.0}
    for rate in rates:
        if not isinstance(rate, dict):
            continue
        code, mid = rate.get("code"), rate.get("mid")
        if isinstance(code, str) and isinstance(mid, (int, float)) and mid > 0:
            mid_pln[code.upper()] = float(mid)
    if len(mid_pln) == 1:
        return None
    return FxRates(mid_pln=mid_pln, effective_date=effective_date)


def convert(amount: float, from_currency: str, to_currency: str, fx: FxRates | None) -> float | None:
    """Przelicza przez PLN (kursy krzyżowe NBP). Ta sama waluta -> bez
    zmian, nawet bez kursów. Brak kursu którejkolwiek waluty -> `None`."""
    from_currency, to_currency = from_currency.upper(), to_currency.upper()
    if from_currency == to_currency:
        return amount
    if fx is None:
        return None
    from_mid = fx.mid_pln.get(from_currency)
    to_mid = fx.mid_pln.get(to_currency)
    if from_mid is None or to_mid is None:
        return None
    return amount * from_mid / to_mid


def total_in_currency(
    by_currency: dict[str, float], to_currency: str, fx: FxRates | None,
) -> float | None:
    """Suma słownika `{waluta: kwota}` w jednej walucie -- `None`, gdy
    choć jedna waluta nie ma kursu (nigdy suma częściowa udająca pełną)."""
    total = 0.0
    for currency, amount in by_currency.items():
        converted = convert(amount, currency, to_currency, fx)
        if converted is None:
            return None
        total += converted
    return total


def fetch_quote(symbol: str) -> Quote | None:
    symbol = symbol.strip()
    if not symbol:
        return None
    try:
        api_key = load_config().data_provider.resolve_api_key()
    except (FileNotFoundError, RuntimeError):
        return None
    try:
        # max_retries=1: to wywołanie blokuje render strony -- lepiej
        # "cena niedostępna" niż minuta czekania na backoff.
        with FMPClient(api_key, max_retries=1) as client:
            profile = client.get_company_profile(symbol)
    except FMPError:
        return None
    normalized = normalize_quote(profile.get("price"), profile.get("currency"))
    if normalized is None:
        return None
    price, currency = normalized
    return Quote(price=price, currency=currency, source="FMP")


def fetch_nbp_rates() -> FxRates | None:
    try:
        resp = httpx.get(NBP_TABLE_A_URL, timeout=NBP_TIMEOUT_S, headers={"Accept": "application/json"})
        resp.raise_for_status()
        payload = resp.json()
    except (httpx.HTTPError, ValueError):
        return None
    return parse_nbp_table(payload)

"""Wspólna warstwa danych rynkowych portfela (Faza 11, P0b-P4).

Jedno miejsce dla: tożsamości źródła ceny -> dostawca (FMP / EODHD /
NBP) -> notowania, historia, dywidendy, zdarzenia korporacyjne, kursy.
Każda odpowiedź dostawcy trafia do WSPÓLNEJ tabeli `market_data_cache`
w bazie portfela -- jedno zapytanie obsługuje obu użytkowników i
wszystkie sesje, także po restarcie aplikacji (Decyzja właścicielki
2026-10-17: "wspólny cache cen EODHD, żeby nie zużywać limitu osobno dla
każdego użytkownika i każdej sesji").

Zasady:
- Świeży wpis (młodszy niż TTL) -> zero zapytań do dostawcy.
- Nieświeży wpis + błąd dostawcy -> ostatnia poprawna wartość z
  oznaczeniem `stale=True` i datą pobrania, nigdy 0 ani zgadywanie.
- Nieudane zapytanie blokuje kolejne próby na `FAILURE_BACKOFF_S`
  (bez tego każde kliknięcie ponawiałoby błąd i spowalniało stronę).
- EODHD Free: twardy budżet `EODHD_DAILY_BUDGET` zapytań dziennie
  (licznik w tej samej tabeli; limit dostawcy to 20).
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from typing import Callable

import httpx

from buffett_scanner.config import load_config
from buffett_scanner.portfolio_backend import get_cache_entry, get_latest_manual_valuation, put_cache_entry
from buffett_scanner.providers.eodhd import EODHDClient, EODHDError
from buffett_scanner.providers.eodhd import resolve_api_key as resolve_eodhd_key
from buffett_scanner.providers.fmp import FMPClient, FMPError
from buffett_scanner.ui.assets import (
    CRYPTO,
    PHYSICAL,
    PHYSICAL_GOLD,
    PHYSICAL_SILVER,
    TROY_OUNCE_G,
    asset_class_of,
    pure_grams_per_piece,
)
from buffett_scanner.ui.pricing import (
    MINOR_UNIT_CURRENCIES,
    NBP_TABLE_A_URL,
    NBP_TIMEOUT_S,
    FxRates,
    Quote,
    normalize_quote,
    parse_nbp_table,
)

EODHD_DAILY_BUDGET = 18
FMP_ROWS_PER_REQUEST = 5000
FMP_HISTORY_MAX_CHUNKS = 3
FAILURE_BACKOFF_S = 15 * 60

TTL_EODHD_EOD_S = 12 * 3600  # notowania dzienne: zamknięcie zmienia się raz dziennie
TTL_EODHD_SEARCH_S = 7 * 24 * 3600
TTL_FMP_PROFILE_S = 3600
TTL_FMP_QUOTE_S = 15 * 60
TTL_HISTORY_S = 12 * 3600
TTL_DIVIDENDS_S = 24 * 3600
TTL_EODHD_DIVIDENDS_S = 3 * 24 * 3600  # oszczędza limit EODHD Free
TTL_SPLITS_S = 24 * 3600
TTL_NBP_TABLE_S = 3600
TTL_NBP_GOLD_S = 3600
TTL_FOREVER = None  # dane historyczne NBP się nie zmieniają

NBP_RATES_URL = "https://api.nbp.pl/api/exchangerates/rates/a/{code}/{start}/{end}/?format=json"
NBP_GOLD_URL = "https://api.nbp.pl/api/cenyzlota/?format=json"

PROVIDER_FMP = "FMP"
PROVIDER_EODHD = "EODHD"


@dataclass(frozen=True)
class Cached:
    value: object
    fetched_at: str  # UTC, "YYYY-MM-DD HH:MM:SS"
    stale: bool


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None, microsecond=0)


def _parse_ts(value: str) -> dt.datetime | None:
    try:
        return dt.datetime.strptime(str(value)[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


class MarketData:
    """Wstrzykiwalne fabryki klientów -- testy podają atrapy, zero sieci."""

    def __init__(
        self,
        conn,
        *,
        fmp_factory: Callable[[], FMPClient] | None = None,
        eodhd_factory: Callable[[], EODHDClient] | None = None,
        http_get=httpx.get,
        now_fn: Callable[[], dt.datetime] = _utcnow,
    ):
        self._conn = conn
        self._fmp_factory = fmp_factory or _default_fmp_factory
        self._eodhd_factory = eodhd_factory or _default_eodhd_factory
        self._http_get = http_get
        self._now = now_fn

    # --- cache ---------------------------------------------------------

    def _put(self, key: str, value) -> None:
        put_cache_entry(self._conn, key, json.dumps(value), self._now().strftime("%Y-%m-%d %H:%M:%S"))
        self._conn.commit()

    def _cached(self, key: str, ttl_s: int | None, fetch: Callable[[], object]) -> Cached | None:
        now = self._now()
        row = get_cache_entry(self._conn, key)
        if row is not None:
            fetched = _parse_ts(row["fetched_at"])
            fresh = ttl_s is None or (fetched is not None and (now - fetched).total_seconds() < ttl_s)
            if fresh:
                return Cached(json.loads(row["payload"]), row["fetched_at"], False)
        failure = get_cache_entry(self._conn, f"fail:{key}")
        recently_failed = failure is not None and (
            (now - (_parse_ts(failure["fetched_at"]) or now)).total_seconds() < FAILURE_BACKOFF_S
        )
        value = None
        if not recently_failed:
            try:
                value = fetch()
            except (FMPError, EODHDError, httpx.HTTPError, ValueError, KeyError, TypeError):
                value = None
            if value is None:
                self._put(f"fail:{key}", True)
        if value is not None:
            self._put(key, value)
            return Cached(value, now.strftime("%Y-%m-%d %H:%M:%S"), False)
        if row is not None:
            return Cached(json.loads(row["payload"]), row["fetched_at"], True)
        return None

    def eodhd_calls_today(self) -> int:
        row = get_cache_entry(self._conn, f"quota:eodhd:{self._now().date().isoformat()}")
        return int(json.loads(row["payload"])) if row is not None else 0

    def _eodhd(self, call: Callable[[EODHDClient], object]):
        """Zwraca None (bez zapytania), gdy brak klucza albo wyczerpany
        dzienny budżet. Licznik jest zwiększany PRZED zapytaniem."""
        client = self._eodhd_factory()
        if client is None:
            return None
        used = self.eodhd_calls_today()
        if used >= EODHD_DAILY_BUDGET:
            return None
        self._put(f"quota:eodhd:{self._now().date().isoformat()}", used + 1)
        return call(client)

    def _fmp(self, call: Callable[[FMPClient], object]):
        client = self._fmp_factory()
        if client is None:
            return None
        with client:
            return call(client)

    # --- EODHD ---------------------------------------------------------

    def eodhd_search(self, eodhd_symbol: str) -> Cached | None:
        return self._cached(
            f"eodhd:search:{eodhd_symbol}", TTL_EODHD_SEARCH_S,
            lambda: self._eodhd(lambda c: c.search(eodhd_symbol)),
        )

    def eodhd_eod(self, eodhd_symbol: str) -> Cached | None:
        """Notowania dzienne z ostatniego roku (limit planu Free) -- jedno
        zapytanie daje i cenę bieżącą (ostatnie zamknięcie), i zmiany
        1D-1Y."""
        today = self._now().date()
        start = (today - dt.timedelta(days=372)).isoformat()

        def fetch():
            rows = self._eodhd(lambda c: c.eod(eodhd_symbol, from_date=start, to_date=today.isoformat()))
            if not rows:
                return None
            return [
                {"date": r["date"], "close": r.get("close"), "adjusted_close": r.get("adjusted_close"),
                 "volume": r.get("volume")}
                for r in rows
            ]

        return self._cached(f"eodhd:eod:{eodhd_symbol}", TTL_EODHD_EOD_S, fetch)

    def eodhd_dividends(self, eodhd_symbol: str) -> Cached | None:
        start = (self._now().date() - dt.timedelta(days=6 * 366)).isoformat()
        return self._cached(
            f"eodhd:div:{eodhd_symbol}", TTL_EODHD_DIVIDENDS_S,
            lambda: self._eodhd(lambda c: c.dividends(eodhd_symbol, from_date=start)),
        )

    # --- FMP -----------------------------------------------------------

    def fmp_profile(self, symbol: str) -> Cached | None:
        def fetch():
            profile = self._fmp(lambda c: c.get_company_profile(symbol))
            if not profile:
                return None
            keep = ("symbol", "price", "currency", "companyName", "exchange", "exchangeShortName",
                    "isin", "cik", "isEtf", "isFund", "lastDividend")
            return {k: profile.get(k) for k in keep}

        return self._cached(f"fmp:profile:{symbol}", TTL_FMP_PROFILE_S, fetch)

    def fmp_quote(self, symbol: str) -> Cached | None:
        def fetch():
            quote = self._fmp(lambda c: c.get_quote(symbol))
            if not quote:
                return None
            return {k: quote.get(k) for k in ("symbol", "name", "price", "timestamp", "exchange")}

        return self._cached(f"fmp:quote:{symbol}", TTL_FMP_QUOTE_S, fetch)

    def fmp_history(self, symbol: str) -> Cached | None:
        """Pełna dostępna historia: FMP zwraca maks. 5000 sesji na
        zapytanie (ok. 20 lat, potwierdzone 2026-10-17), więc przy pełnej
        porcji dociągamy starsze (maks. `FMP_HISTORY_MAX_CHUNKS` zapytań).
        Payload: {"rows": [{date, close, volume}], "complete": bool} --
        `complete=False` == nawet po dociąganiu historia może być dłuższa
        (wtedy MAX = N/A, nie "najstarsza dostępna")."""
        today = self._now().date().isoformat()

        def fetch():
            rows: list[dict] = []
            to_date = today
            complete = False
            for _ in range(FMP_HISTORY_MAX_CHUNKS):
                chunk = self._fmp(lambda c: c.get_historical_prices(symbol, from_date="1970-01-01", to_date=to_date))
                if chunk is None:
                    return None
                chunk = [r for r in chunk if not rows or r["date"] < rows[0]["date"]]
                rows = [{"date": r["date"], "close": r.get("close"), "volume": r.get("volume")} for r in chunk] + rows
                if len(chunk) < FMP_ROWS_PER_REQUEST:
                    complete = True
                    break
                to_date = (dt.date.fromisoformat(rows[0]["date"]) - dt.timedelta(days=1)).isoformat()
            return {"rows": rows, "complete": complete} if rows else None

        return self._cached(f"fmp:history:{symbol}", TTL_HISTORY_S, fetch)

    def history_for_symbol(self, provider: str | None, symbol: str) -> tuple[list[dict], bool, str] | None:
        """(notowania [{date, close, volume}], czy historia pełna, źródło)
        -- EODHD Free daje tylko ostatni rok (historia niepełna)."""
        if provider == PROVIDER_EODHD:
            cached = self.eodhd_eod(symbol)
            if cached is None:
                return None
            return cached.value, False, "EODHD (plan Free: 1 rok)"
        cached = self.fmp_history(symbol)
        if cached is None:
            return None
        return cached.value["rows"], bool(cached.value["complete"]), "FMP"

    def has_recent_spin_off(self, symbol: str, since: str) -> str | None:
        """Data wydzielenia (FMP `splits`, splitType=spin-off) od `since`."""
        cached = self.fmp_splits(symbol)
        if cached is None:
            return None
        dates = [
            r.get("date") for r in cached.value
            if isinstance(r, dict) and str(r.get("splitType", "")).lower() == "spin-off" and str(r.get("date", "")) >= since
        ]
        return max(dates) if dates else None

    def fmp_dividends(self, symbol: str) -> Cached | None:
        def fetch():
            rows = self._fmp(lambda c: c.get_dividends(symbol))
            if rows is None:
                return None
            keep = ("date", "paymentDate", "declarationDate", "recordDate", "dividend", "adjDividend", "frequency")
            return [{k: r.get(k) for k in keep} for r in rows if isinstance(r, dict)]

        return self._cached(f"fmp:div:{symbol}", TTL_DIVIDENDS_S, fetch)

    def fmp_splits(self, symbol: str) -> Cached | None:
        return self._cached(
            f"fmp:splits:{symbol}", TTL_SPLITS_S,
            lambda: self._fmp(lambda c: c.get_splits(symbol)),
        )

    # --- NBP -----------------------------------------------------------

    def _http_json(self, url: str):
        resp = self._http_get(url, timeout=NBP_TIMEOUT_S, headers={"Accept": "application/json"})
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()

    def nbp_table_a(self) -> FxRates | None:
        cached = self._cached("nbp:tableA:latest", TTL_NBP_TABLE_S, lambda: self._http_json(NBP_TABLE_A_URL))
        return parse_nbp_table(cached.value) if cached is not None else None

    def nbp_rate_before(self, currency: str, date: str) -> tuple[str, float] | None:
        """Ostatni kurs średni NBP (tabela A) z dnia roboczego PRZED
        `date` -- Decyzja właścicielki 2026-10-17 dla transakcji bez
        zapisanego kursu brokera. `(data kursu, kurs)` albo None."""
        currency = currency.upper()
        if currency == "PLN":
            return (date, 1.0)
        day = dt.date.fromisoformat(date[:10])
        start, end = (day - dt.timedelta(days=14)).isoformat(), (day - dt.timedelta(days=1)).isoformat()

        def fetch():
            data = self._http_json(NBP_RATES_URL.format(code=currency.lower(), start=start, end=end))
            if not isinstance(data, dict) or not isinstance(data.get("rates"), list):
                return None
            rates = [r for r in data["rates"] if isinstance(r, dict) and r.get("effectiveDate") and r.get("mid")]
            if not rates:
                return None
            last = max(rates, key=lambda r: r["effectiveDate"])
            return [last["effectiveDate"], float(last["mid"])]

        cached = self._cached(f"nbp:A:{currency}:before:{day.isoformat()}", TTL_FOREVER, fetch)
        if cached is None:
            return None
        effective_date, mid = cached.value
        return effective_date, mid

    def nbp_gold_pln_per_gram(self) -> tuple[str, float] | None:
        """Cena NBP 1 g złota (próba 1000), PLN. Potwierdzone 2026-10-17:
        `[{"data": "2026-10-16", "cena": 519.85}]` (zgodne z GCUSD z FMP)."""
        def fetch():
            data = self._http_json(NBP_GOLD_URL)
            if not isinstance(data, list) or not data or "cena" not in data[-1]:
                return None
            return [data[-1]["data"], float(data[-1]["cena"])]

        cached = self._cached("nbp:gold:latest", TTL_NBP_GOLD_S, fetch)
        return tuple(cached.value) if cached is not None else None

    def pln_rate(self, currency: str, date: str, fx_rate_actual: float | None):
        """Kurs do przeliczenia kwoty historycznej na PLN (Decyzja
        właścicielki 2026-10-17): najpierw kurs rzeczywisty brokera, jeśli
        zapisany, inaczej ostatni kurs NBP sprzed daty transakcji
        (orientacyjny). Waluty zdawkowe (GBp/GBX) przez walutę główną."""
        from buffett_scanner.ui.portfolio import PLN_RATE_ACTUAL, PLN_RATE_NBP, PLN_RATE_PLN

        if fx_rate_actual:
            return float(fx_rate_actual), PLN_RATE_ACTUAL
        code = (currency or "").strip()
        major, divisor = MINOR_UNIT_CURRENCIES.get(code, (code.upper(), 1.0))
        if major == "PLN":
            return 1.0, PLN_RATE_PLN
        found = self.nbp_rate_before(major, date)
        if found is None:
            return None
        return found[1] / divisor, PLN_RATE_NBP

    def dividend_events_for_symbol(self, provider: str | None, symbol: str, quote_currency: str | None):
        """Znormalizowane wypłaty (Faza 11, P3) albo None przy braku danych."""
        from buffett_scanner.ui.dividends import events_from_eodhd, events_from_fmp

        if provider == PROVIDER_EODHD:
            cached = self.eodhd_dividends(symbol)
            return None if cached is None else events_from_eodhd(cached.value)
        cached = self.fmp_dividends(symbol)
        if cached is None:
            return None
        if quote_currency is None:
            profile = self.fmp_profile(symbol)
            quote_currency = profile.value.get("currency") if profile is not None else None
        return events_from_fmp(cached.value, quote_currency)

    # --- cena pozycji --------------------------------------------------

    def quote_for_symbol(self, provider: str | None, symbol: str, quote_currency: str | None = None) -> Quote | None:
        if provider == PROVIDER_EODHD:
            cached = self.eodhd_eod(symbol)
            if cached is None or not cached.value:
                return None
            last = cached.value[-1]
            normalized = normalize_quote(last.get("close"), quote_currency)
            if normalized is None:
                return None
            return Quote(price=normalized[0], currency=normalized[1], source="EODHD",
                         as_of=last["date"], stale=cached.stale)
        cached = self.fmp_profile(symbol)
        if cached is None:
            return None
        normalized = normalize_quote(cached.value.get("price"), cached.value.get("currency"))
        if normalized is None:
            return None
        return Quote(price=normalized[0], currency=normalized[1], source="FMP",
                     as_of=cached.fetched_at[:10], stale=cached.stale)

    def manual_valuation(self, position, kind: str) -> Quote | None:
        """Ostatnia wycena ręczna (P4): MARKET (np. srebro, moneta
        kolekcjonerska) albo BUYBACK (szacunkowa cena odkupu u dealera)."""
        row = get_latest_manual_valuation(self._conn, position["position_id"], kind)
        if row is None:
            return None
        return Quote(price=row["price_per_unit"], currency=str(row["currency"]).upper(),
                     source="wycena ręczna", as_of=row["valuation_date"])

    def _physical_metal_quote(self, position) -> Quote | None:
        """Cena JEDNEJ sztuki = czysty metal x cena spot (złoto: NBP PLN/g;
        srebro: FMP SIUSD -- kontrakt terminowy jako przybliżenie spot).
        Moneta kolekcjonerska albo brak ceny automatycznej -> wycena ręczna."""
        def field(name):
            return position[name] if name in position.keys() else None

        if not field("is_collectible"):
            grams = pure_grams_per_piece(field("unit_weight"), field("weight_unit"), field("fineness"))
            if grams is not None and asset_class_of(position) == PHYSICAL_GOLD:
                gold = self.nbp_gold_pln_per_gram()
                if gold is not None:
                    return Quote(price=grams * gold[1], currency="PLN", source="NBP (cena złota)", as_of=gold[0])
            if grams is not None and asset_class_of(position) == PHYSICAL_SILVER:
                cached = self.fmp_quote("SIUSD")
                if cached is not None and cached.value.get("price"):
                    return Quote(
                        price=grams * cached.value["price"] / TROY_OUNCE_G, currency="USD",
                        source="FMP (kontrakt na srebro)", as_of=_timestamp_date(cached.value.get("timestamp")),
                        stale=cached.stale,
                    )
        return self.manual_valuation(position, "MARKET")

    def crypto_quote(self, symbol: str) -> Quote | None:
        cached = self.fmp_quote(symbol)
        if cached is None or not cached.value.get("price"):
            return None
        currency = symbol[-3:].upper() if len(symbol) > 3 else "USD"
        return Quote(price=float(cached.value["price"]), currency=currency, source="FMP (krypto)",
                     as_of=_timestamp_date(cached.value.get("timestamp")), stale=cached.stale)

    def quote_for_position(self, position) -> Quote | None:
        keys = position.keys()
        asset_class = asset_class_of(position)
        if asset_class in PHYSICAL:
            return self._physical_metal_quote(position)
        if asset_class == CRYPTO:
            symbol = (position["price_symbol"] if "price_symbol" in keys else None) or position["ticker"]
            return self.crypto_quote(symbol)
        provider = position["price_provider"] if "price_provider" in keys else None
        symbol = (position["price_symbol"] if "price_symbol" in keys else None) or position["ticker"]
        quote_currency = position["quote_currency"] if "quote_currency" in keys else None
        return self.quote_for_symbol(provider, symbol, quote_currency)


def _timestamp_date(timestamp) -> str | None:
    try:
        return dt.datetime.fromtimestamp(int(timestamp), dt.timezone.utc).date().isoformat()
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _default_fmp_factory() -> FMPClient | None:
    try:
        api_key = load_config().data_provider.resolve_api_key()
    except (FileNotFoundError, RuntimeError):
        return None
    try:
        return FMPClient(api_key, max_retries=1)
    except FMPError:
        return None


def _default_eodhd_factory() -> EODHDClient | None:
    api_key = resolve_eodhd_key()
    return EODHDClient(api_key) if api_key else None

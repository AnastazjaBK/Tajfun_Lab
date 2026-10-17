"""Weryfikacja instrumentu przez FMP przy dodawaniu nowej pozycji
(Faza 7 KROK 7).

Techniczny test (nie-Claude, wynik wyciągnięty i opisany w commitu
usuwającym jednorazowe narzędzie diagnostyczne, patrz git log) wykazał
na realnym koncie: `FMPClient.get_company_profile` (NIEZMIENIONY)
poprawnie rozpoznaje zarówno amerykańskie tickery, jak i europejskie
listingi pod konwencją <symbol>.<sufiks giełdy> (np. "SU.PA" ->
Schneider Electric S.E., exchange PAR, EUR; "GSK.L" -> GSK plc, LSE,
currency "GBp" -- pensy, NIE funty), ale symbol BEZ sufiksu giełdy
("SU") może trafić na CAŁKOWICIE INNĄ spółkę (Suncor Energy Inc.,
NYSE). Dlatego wynik lookupu jest ZAWSZE pokazywany użytkownikowi do
jawnego potwierdzenia (sekcja 9/19 specyfikacji) -- ta funkcja nigdy
nie zgaduje/poprawia symbolu, zwraca dokładnie to, co FMP zwróciło dla
DOKŁADNIE symbolu podanego przez użytkownika.

`lookup_instrument` zwraca `None`, gdy weryfikacja nie jest możliwa
(brak skonfigurowanego klucza FMP, FMP nie rozpoznał symbolu, błąd
sieci) -- NIGDY nie podnosi wyjątku do UI. Wołający (formularz w
`app.py`) musi w tym przypadku pozwolić zapisać pozycję bez
automatycznej ceny/cik, pokazując "Cena bieżąca niedostępna" --
nigdy current_price=0 jako substytut braku danych (Decyzja
właścicielki, Faza 7 pkt 6)."""

from __future__ import annotations

from dataclasses import dataclass

from buffett_scanner.config import load_config
from buffett_scanner.providers.fmp import FMPClient, FMPError


@dataclass(frozen=True)
class InstrumentLookupResult:
    symbol: str
    company_name: str | None
    exchange: str | None
    currency: str | None
    price: float | None
    cik: str | None
    # Faza 11 (P0b): tożsamość i źródło ceny.
    isin: str | None = None
    provider: str = "FMP"
    provider_symbol: str | None = None
    asset_type: str | None = None  # typ wg dostawcy -- tylko podpowiedź, klasę potwierdza użytkownik


def lookup_instrument(symbol: str) -> InstrumentLookupResult | None:
    symbol = symbol.strip()
    if not symbol:
        return None
    try:
        config = load_config()
        api_key = config.data_provider.resolve_api_key()
    except (FileNotFoundError, RuntimeError):
        return None
    try:
        with FMPClient(api_key) as client:
            profile = client.get_company_profile(symbol)
    except FMPError:
        return None
    resolved = profile.get("symbol") or symbol
    return InstrumentLookupResult(
        symbol=resolved,
        company_name=profile.get("companyName"),
        exchange=profile.get("exchange") or profile.get("exchangeShortName"),
        currency=profile.get("currency"),
        price=profile.get("price"),
        cik=profile.get("cik"),
        isin=profile.get("isin"),
        provider="FMP",
        provider_symbol=resolved,
        asset_type="ETF" if profile.get("isEtf") else ("Common Stock" if profile.get("companyName") else None),
    )


def lookup_instrument_routed(symbol: str, market) -> InstrumentLookupResult | None:
    """Faza 11 (P0b, Decyzja właścicielki 2026-10-17): symbol z
    europejskim sufiksem giełdy (`SU.PA`, `GSK.L`, `EUNL.DE`, ...) ->
    wyszukiwarka EODHD (wspólny cache + budżet dzienny przez `market`),
    pozostałe -> profil FMP jak dotąd. Z wyników EODHD brany jest
    WYŁĄCZNIE wpis o dokładnie tym kodzie i giełdzie -- nigdy dopasowanie
    po nazwie ani "najbliższy" listing."""
    from buffett_scanner.providers.eodhd import to_eodhd_symbol

    symbol = symbol.strip()
    eodhd_symbol = to_eodhd_symbol(symbol)
    if eodhd_symbol is None:
        return lookup_instrument(symbol)
    cached = market.eodhd_search(eodhd_symbol)
    if cached is None:
        return None
    code, exchange = eodhd_symbol.rsplit(".", 1)
    matches = [
        r for r in cached.value
        if isinstance(r, dict) and str(r.get("Code", "")).upper() == code and str(r.get("Exchange", "")).upper() == exchange
    ]
    if not matches:
        return None
    row = matches[0]
    return InstrumentLookupResult(
        symbol=symbol.upper(),
        company_name=row.get("Name"),
        exchange=row.get("Exchange"),
        currency=row.get("Currency"),
        price=row.get("previousClose"),
        cik=None,
        isin=row.get("ISIN"),
        provider="EODHD",
        provider_symbol=eodhd_symbol,
        asset_type=row.get("Type"),
    )


def instrument_save_errors(
    symbol: str, *, looked_up: bool, result: InstrumentLookupResult | None, confirmed: bool,
) -> list[str]:
    """Faza 9 (Decyzja właścicielki 2026-10-17): zapis pozycji jest
    ZABLOKOWANY, gdy FMP rozpoznał symbol, ale użytkownik nie potwierdził
    wyniku -- realny przypadek: `SU` (FMP: Suncor) zapisane jako
    Schneider Electric. Zapis bez weryfikacji jest dozwolony WYŁĄCZNIE,
    gdy FMP symbolu nie rozpoznał (ręczny wpis, bez automatycznej ceny,
    Faza 7 pkt 6). `looked_up` = sprawdzenie wykonano dla DOKŁADNIE
    obecnego symbolu."""
    if not symbol.strip():
        return ["Symbol/ticker jest wymagany."]
    if not looked_up:
        return ["Kliknij „Sprawdź instrument w FMP” przed zapisem."]
    if result is not None and not confirmed:
        return [
            f"FMP rozpoznał ten symbol jako {result.company_name or '—'} ({result.exchange or '—'}). "
            "Zaznacz „Tak, to właściwy instrument” albo zmień symbol (np. dodaj sufiks giełdy: SU.PA, GSK.L)."
        ]
    return []

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
    return InstrumentLookupResult(
        symbol=profile.get("symbol") or symbol,
        company_name=profile.get("companyName"),
        exchange=profile.get("exchange") or profile.get("exchangeShortName"),
        currency=profile.get("currency"),
        price=profile.get("price"),
        cik=profile.get("cik"),
    )

"""Parsowanie i rekonstrukcja logu zdarzeń FMP `historical-sp500-constituent`
(Faza 5.2, krok 1/3, OPEN BLOCKER 2) — czysta logika, zero I/O.

Kształt potwierdzony bezpośrednio na koncie Premium (2026-09-26): lista
zdarzeń zmiany składu, jedno zdarzenie = jedna spółka dodana + (opcjonalnie)
jedna spółka usunięta TEGO SAMEGO dnia (typowy wzorzec S&P DJI —
zastąpienie). Pola: `date` (ISO), `dateAdded` (czytelny format, np.
"September 21, 2026"), `symbol` (dodany ticker), `addedSecurity`,
`removedTicker` (może być pusty string — dodanie bez sparowanego
usunięcia, np. rozszerzenie indeksu), `removedSecurity`, `reason`.

W przeciwieństwie do fja05680/sp500 (pełne snapshoty per data zmiany),
FMP daje LOG ZDARZEŃ bez snapshotu bazowego — odtworzenie składu na
dowolną datę wymaga punktu odniesienia. Jedynym pewnym punktem
odniesienia jest DZISIEJSZY, potwierdzony skład (z `sp500-constituent`,
Faza 0) — więc rekonstrukcja idzie WSTECZ w czasie od dziś, odwracając
kolejne zdarzenia."""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass

from buffett_scanner.universe_history import ticker_format_variants


@dataclass(frozen=True)
class FmpConstituentEvent:
    date: str  # ISO YYYY-MM-DD
    date_added_raw: str  # oryginalny czytelny format, do wykrywania rozbieżności z `date`
    added_symbol: str
    added_security: str
    removed_ticker: str | None  # None = brak sparowanego usunięcia w tym zdarzeniu
    removed_security: str | None
    reason: str


def parse_fmp_events(raw_rows: list[dict]) -> list[FmpConstituentEvent]:
    """Defensywnie parsuje surowe wiersze FMP. Wiersz bez `date` lub
    `symbol` jest pomijany, nigdy nie fabrykowany. Pusty string w
    `removedTicker`/`removedSecurity` -> `None` (brak sparowanego
    usunięcia, nie fałszywy pusty ticker). Posortowane rosnąco po dacie."""
    events: list[FmpConstituentEvent] = []
    for r in raw_rows:
        date = r.get("date")
        symbol = r.get("symbol")
        if not date or not symbol:
            continue
        events.append(
            FmpConstituentEvent(
                date=date,
                date_added_raw=r.get("dateAdded") or "",
                added_symbol=symbol,
                added_security=r.get("addedSecurity") or "",
                removed_ticker=r.get("removedTicker") or None,
                removed_security=r.get("removedSecurity") or None,
                reason=r.get("reason") or "",
            )
        )
    events.sort(key=lambda e: e.date)
    return events


def _parse_date_added(date_added_raw: str) -> str | None:
    """Parsuje czytelny format `dateAdded` (np. "September 21, 2026")
    na ISO YYYY-MM-DD. `None`, jeśli żaden ze znanych formatów nie
    pasuje — nigdy nie zgadujemy daty."""
    for fmt in ("%B %d, %Y", "%b %d, %Y"):
        try:
            return dt.datetime.strptime(date_added_raw.strip(), fmt).date().isoformat()
        except (ValueError, AttributeError):
            continue
    return None


def find_date_added_mismatches(events: list[FmpConstituentEvent]) -> list[tuple[FmpConstituentEvent, str]]:
    """Sprawdza, czy `date` (ISO) i `dateAdded` (czytelny format, np.
    "September 21, 2026") wskazują tę samą kalendarzową datę. Zwraca
    listę (zdarzenie, parsed_date_added_iso) dla wierszy, gdzie się nie
    zgadzają, LUB `dateAdded` nie dało się sparsować w żadnym ze
    znanych formatów — jawnie odnotowane, nie ukrywane. Motywacja:
    realne znalezisko z Fazy 5.2 v1.31 — dla starych wierszy (np. 1957)
    `date` i `dateAdded` różnią się o 1 dzień."""
    mismatches = []
    for e in events:
        parsed = _parse_date_added(e.date_added_raw)
        if parsed is None:
            mismatches.append((e, "NIEPARSOWALNE"))
        elif parsed != e.date:
            mismatches.append((e, parsed))
    return mismatches


def reconstruct_membership_backward(
    events: list[FmpConstituentEvent], current_members: set[str], as_of_date: str
) -> set[str]:
    """Odtwarza skład na `as_of_date`, zaczynając od DZISIEJSZEGO,
    potwierdzonego składu (`current_members`, ze `sp500-constituent`) i
    cofając się w czasie: dla każdego zdarzenia z `date` > `as_of_date`
    (czyli zdarzenia, które nastąpiło PO badanej dacie) — usuwa
    `added_symbol` (bo go tam jeszcze nie było) i przywraca
    `removed_ticker`, jeśli był (bo jeszcze nie odszedł). Zdarzenia z
    `date` <= `as_of_date` już się wydarzyły z punktu widzenia badanej
    daty — nie są odwracane."""
    members = set(current_members)
    for event in sorted(events, key=lambda e: e.date, reverse=True):
        if event.date <= as_of_date:
            break
        members.discard(event.added_symbol)
        if event.removed_ticker:
            members.add(event.removed_ticker)
    return members


@dataclass(frozen=True)
class ChangeEvent:
    date: str
    ticker: str
    action: str  # "ADD" | "REMOVE"


def fmp_change_events(events: list[FmpConstituentEvent], *, cutoff_date: str) -> frozenset[ChangeEvent]:
    """Zdarzenia zmiany składu z FMP w oknie [cutoff_date, ...], jako
    zbiór (date, ticker, ADD/REMOVE) — do bezpośredniego porównania z
    `fja_change_events`."""
    result: set[ChangeEvent] = set()
    for e in events:
        if e.date < cutoff_date:
            continue
        result.add(ChangeEvent(date=e.date, ticker=e.added_symbol, action="ADD"))
        if e.removed_ticker:
            result.add(ChangeEvent(date=e.date, ticker=e.removed_ticker, action="REMOVE"))
    return frozenset(result)


def fmp_change_events_by_date_added(
    events: list[FmpConstituentEvent], *, cutoff_date: str
) -> tuple[frozenset[ChangeEvent], tuple[str, ...]]:
    """Wariant `fmp_change_events` używający SPARSOWANEGO `dateAdded`
    zamiast `date` jako daty zdarzenia — do empirycznego porównania,
    które pole daje lepszą zgodność z fja05680 (część 4 domknięcia
    OPEN BLOCKER 2, v1.34: 11,2% wierszy ma `date` != `dateAdded`,
    NIE wybieramy pola arbitralnie, tylko mierzymy wpływ obu wariantów
    na wynik dopasowania z tolerancją). Zdarzenie, którego `dateAdded`
    nie da się sparsować, ZACHOWUJE oryginalne `date` (jedyna dostępna
    wartość — nigdy nie odrzucamy zdarzenia z tego powodu), a jego
    `added_symbol` trafia jawnie do drugiego elementu zwracanej krotki
    (`unparseable_date_added_tickers`), żeby było widać, że dla tych
    wierszy `dateAdded` i `date` w praktyce oznaczają to samo pole w
    wyniku, nie dwie niezależne obserwacje. Filtr `cutoff_date` nadal
    stosowany względem oryginalnego `date` (jedyne pole gwarantowane
    ISO, porównywalne leksykograficznie, niezależnie od tego czy
    `dateAdded` się sparsowało)."""
    result: set[ChangeEvent] = set()
    unparseable: set[str] = set()
    for e in events:
        if e.date < cutoff_date:
            continue
        effective_date = _parse_date_added(e.date_added_raw)
        if effective_date is None:
            effective_date = e.date
            unparseable.add(e.added_symbol)
        result.add(ChangeEvent(date=effective_date, ticker=e.added_symbol, action="ADD"))
        if e.removed_ticker:
            result.add(ChangeEvent(date=effective_date, ticker=e.removed_ticker, action="REMOVE"))
    return frozenset(result), tuple(sorted(unparseable))


@dataclass(frozen=True)
class ChangeEventComparison:
    common: frozenset[ChangeEvent]
    only_a: frozenset[ChangeEvent]
    only_b: frozenset[ChangeEvent]


def compare_change_events(a: frozenset[ChangeEvent], b: frozenset[ChangeEvent]) -> ChangeEventComparison:
    """Czyste porównanie dwóch zbiorów zdarzeń zmiany składu (np. FMP
    vs fja05680) — dokładne dopasowanie (date, ticker, action). Żadnej
    interpretacji przyczyn rozbieżności (to wymaga kontekstu
    biznesowego po zobaczeniu realnych wyników)."""
    return ChangeEventComparison(common=a & b, only_a=a - b, only_b=b - a)


# ---------------------------------------------------------------------------
# Domknięcie OPEN BLOCKER 2, część 1: rozwiązanie CIK dla rekordów FMP
# (v1.34, zaprojektowane po zatwierdzeniu wyników Kroku 3 przez
# właściciela). fja05680 pozostaje kanonicznym źródłem membership — to
# poniżej służy WYŁĄCZNIE do (a) rozwiązania CIK dla zdarzeń FMP jako
# niezależnego walidatora i (b) wykrycia recyklingu tickerów, NIE do
# nadpisywania kanonicznego składu.
# ---------------------------------------------------------------------------

_CORPORATE_NOISE_TOKENS = frozenset(
    {
        "inc", "incorporated", "corp", "corporation", "co", "company",
        "ltd", "limited", "plc", "llc", "lp", "llp", "group", "holdings",
        "holding", "the", "class", "sa", "nv", "se", "ag",
    }
)


def normalize_company_name_tokens(name: str) -> frozenset[str]:
    """Normalizuje nazwę spółki do zbioru tokenów porównywalnych: małe
    litery, zamiana znaków niealfanumerycznych na spacje, usunięcie
    typowych przyrostków/form prawnych (Inc/Corp/Ltd/... — patrz
    `_CORPORATE_NOISE_TOKENS`) i słowa "the". Reguła v1 — jawnie
    wersjonowana, bo dobór przyrostków wpływa na wynik porównania i
    każda przyszła zmiana musi być cytowalna."""
    cleaned = re.sub(r"[^a-z0-9\s]", " ", name.lower())
    return frozenset(t for t in cleaned.split() if t and t not in _CORPORATE_NOISE_TOKENS)


def names_plausibly_match(name_a: str, name_b: str) -> bool:
    """Reguła v1 (deterministyczna, wersjonowana): dwie nazwy spółek
    "prawdopodobnie" oznaczają tę samą spółkę, jeśli po normalizacji
    dzielą ŚCISŁĄ WIĘKSZOŚĆ tokenów krótszej z dwóch nazw (2 * overlap
    > min(len_a, len_b)). Pojedynczy wspólny token NIE wystarcza przy
    >=2 tokenach z każdej strony (np. "General Electric" i "General
    Dynamics" dzielą tylko "general" — to muszą pozostać różne spółki),
    ale wystarcza przy nazwach jednotokenowych po normalizacji (np.
    "Apple Inc." i "Apple Inc" -> oba {"apple"}). Brak tokenów po
    którejkolwiek stronie (pusta/nieobecna nazwa) -> zawsze `False`,
    nigdy nie zgadujemy zgodności bez danych. UWAGA (jawne ograniczenie
    tej reguły, do raportowania): prawdziwa zmiana nazwy spółki przy
    NIEZMIENIONYM CIK i tickerze (np. rebranding) też może dać `False`
    — to oczekiwany, nieszkodliwy false positive przy wykrywaniu
    recyklingu (CIK i tak jest już poprawnie rozwiązany przez ticker,
    ta funkcja tylko oznacza przypadek do ręcznego przejrzenia)."""
    tokens_a = normalize_company_name_tokens(name_a)
    tokens_b = normalize_company_name_tokens(name_b)
    if not tokens_a or not tokens_b:
        return False
    overlap = len(tokens_a & tokens_b)
    shorter_len = min(len(tokens_a), len(tokens_b))
    return 2 * overlap > shorter_len


def collect_fmp_ticker_names(events: list[FmpConstituentEvent]) -> dict[str, str]:
    """Dla każdego tickera pojawiającego się w logu FMP (jako dodany
    lub usunięty), zwraca NAJNOWSZĄ (wg daty zdarzenia) znaną nazwę
    spółki. Motywacja: SEC `title` też jest stanem DZISIEJSZYM, więc
    do porównania "aktualne vs aktualne" właściwa jest najnowsza nazwa
    FMP dla danego tickera, nie pierwsza historyczna. Starsze nazwy
    tego samego tickera (ślad ewentualnego recyklingu) wychwytuje
    osobno `find_tickers_with_multiple_names`."""
    names: dict[str, str] = {}
    for e in sorted(events, key=lambda ev: ev.date):
        if e.added_symbol and e.added_security:
            names[e.added_symbol] = e.added_security
        if e.removed_ticker and e.removed_security:
            names[e.removed_ticker] = e.removed_security
    return names


def find_tickers_with_multiple_names(events: list[FmpConstituentEvent]) -> dict[str, frozenset[str]]:
    """Wewnętrzny sprawdzian spójności SAMEGO logu FMP (niezależny od
    SEC): dla każdego tickera zbiera wszystkie różne nazwy spółki, pod
    jakimi kiedykolwiek wystąpił w źródle. Zwraca WYŁĄCZNIE tickery, dla
    których istnieje PARA nazw wzajemnie niezgodnych wg
    `names_plausibly_match` — sygnał, że ten sam ticker mógł w historii
    FMP oznaczać dwie różne spółki (recykling), zanim jeszcze
    spróbujemy cokolwiek rozwiązać przez SEC. Większość tickerów ma
    jedną nazwę albo warianty pisowni tej samej nazwy i nie trafia do
    wyniku."""
    names_by_ticker: dict[str, set[str]] = {}
    for e in events:
        if e.added_symbol and e.added_security:
            names_by_ticker.setdefault(e.added_symbol, set()).add(e.added_security)
        if e.removed_ticker and e.removed_security:
            names_by_ticker.setdefault(e.removed_ticker, set()).add(e.removed_security)

    result: dict[str, frozenset[str]] = {}
    for ticker, names in names_by_ticker.items():
        names_list = sorted(names)
        if len(names_list) < 2:
            continue
        has_mismatch = any(
            not names_plausibly_match(a, b)
            for i, a in enumerate(names_list)
            for b in names_list[i + 1 :]
        )
        if has_mismatch:
            result[ticker] = frozenset(names_list)
    return result


@dataclass(frozen=True)
class FmpTickerResolution:
    resolved: dict[str, str]  # ticker (pisownia FMP) -> cik
    resolved_via_format_variant: dict[str, str]  # ticker -> wariant zapisu, który dopasował
    unresolved: tuple[str, ...]  # posortowane tickery bez pewnego mapowania CIK
    name_mismatch_suspicious: dict[str, dict[str, str]]  # ticker -> {cik, sec_title, fmp_name}


def resolve_fmp_tickers(
    fmp_names_by_ticker: dict[str, str],
    sec_ticker_map: dict[str, str],
    sec_titles: dict[str, str],
) -> FmpTickerResolution:
    """Rozwiązuje tickery FMP na CIK wyłącznie przez `sec_ticker_map`
    (dokładne dopasowanie, potem warianty formatu zapisu — kropka/
    myślnik, `universe_history.ticker_format_variants`), analogicznie
    do `universe_history.resolve_tickers_to_cik`, ale DODATKOWO
    krzyżowo sprawdza nazwę spółki: dla każdego rozwiązanego CIK
    porównuje `fmp_names_by_ticker[ticker]` (np. z
    `collect_fmp_ticker_names`) z `sec_titles[ticker_lub_wariant]`
    (tytuł zarejestrowany w SEC, z `get_company_tickers_full()`) przez
    `names_plausibly_match`. Niezgodność NIE usuwa wyniku z `resolved`
    — CIK pozostaje jedynym potwierdzonym, zweryfikowanym przez ticker
    faktem — tylko trafia jawnie do `name_mismatch_suspicious` do
    dalszej, ręcznej/audytowej oceny (możliwy recykling tickera ALBO
    nieszkodliwy rebranding przy niezmienionym CIK — patrz zastrzeżenie
    w `names_plausibly_match`). Ticker nieobecny w `sec_ticker_map` pod
    żadnym wariantem -> `unresolved`, NIGDY nie zgadywany."""
    resolved: dict[str, str] = {}
    resolved_via_variant: dict[str, str] = {}
    unresolved: list[str] = []
    name_mismatch: dict[str, dict[str, str]] = {}

    for ticker in sorted(fmp_names_by_ticker):
        cik = sec_ticker_map.get(ticker)
        matched_variant: str | None = None
        if not cik:
            for variant in ticker_format_variants(ticker):
                cik = sec_ticker_map.get(variant)
                if cik:
                    matched_variant = variant
                    break
        if not cik:
            unresolved.append(ticker)
            continue

        resolved[ticker] = cik
        if matched_variant:
            resolved_via_variant[ticker] = matched_variant

        fmp_name = fmp_names_by_ticker[ticker]
        sec_title = sec_titles.get(matched_variant or ticker, "")
        if fmp_name and sec_title and not names_plausibly_match(fmp_name, sec_title):
            name_mismatch[ticker] = {"cik": cik, "sec_title": sec_title, "fmp_name": fmp_name}

    return FmpTickerResolution(
        resolved=resolved,
        resolved_via_format_variant=resolved_via_variant,
        unresolved=tuple(sorted(unresolved)),
        name_mismatch_suspicious=name_mismatch,
    )

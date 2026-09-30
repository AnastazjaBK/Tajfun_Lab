"""Domknięcie OPEN BLOCKER 2, części 2-3 (Faza 5.2, v1.34) — pogodzenie
fja05680 (KANONICZNE źródło membership) z FMP (WALIDATOR, nigdy nie
nadpisuje kanonicznego składu) na poziomie CIK, z tolerancją dat.

Zasada architektoniczna (zatwierdzona przez właściciela): fja05680
pozostaje jedynym źródłem prawdy dla `universe_membership`. Nic w tym
module nie konstruuje ani nie modyfikuje membership — wyłącznie
DIAGNOSTYCZNY raport rozbieżności do ręcznej/audytowej oceny. FMP nigdy
automatycznie nie nadpisuje fja05680, niezależnie od wyniku porównania.

Motywacja tolerancji dat: krok 3 Fazy 5.2 (v1.33) wykazał na realnych
danych systematyczne przesunięcia 1-3 dni między FMP a fja05680 dla
TEGO SAMEGO realnego zdarzenia zmiany składu (np. FOSL/MHS/PSX/SVU/
ALXN/EP/KMI) — bez tolerancji dokładne dopasowanie date+ticker+action
myli te przesunięcia z realnymi konfliktami. Reguła dopasowania jest
DETERMINISTYCZNA i WERSJONOWANA przez parametr `tolerance_days`, a jej
wpływ na wynik ma być mierzony (`tolerance_impact_curve`), nie
zakładany arbitralnie.

Zero I/O — czyste transformacje już rozwiązanych (CIK) zdarzeń."""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from dataclasses import dataclass

from buffett_scanner.fmp_sp500_events import ChangeEvent

# Wersja LOGIKI dopasowania (nie parametrów — te, tolerance_days i
# date_field, są przechowywane osobno per wiersz walidacji). Bump tego
# stringa przy KAŻDEJ zmianie samego algorytmu w
# `match_cik_events_with_tolerance` (np. zmiana strategii greedy,
# reguły remisu, definicji koszyka) — inaczej stare i nowe wyniki
# walidacji byłyby nierozróżnialne w bazie, mimo że policzone inną
# logiką. Zgłoszone jawnie przez właścicielkę jako wymóg przed
# implementacją `universe_membership` (v1.35).
MATCH_ALGORITHM_VERSION = "cik_tolerance_match_v1"


@dataclass(frozen=True)
class CikEvent:
    date: str  # ISO YYYY-MM-DD
    cik: str
    action: str  # "ADD" | "REMOVE"


@dataclass(frozen=True)
class CikEventConversion:
    events: frozenset[CikEvent]
    dropped_unresolved_tickers: tuple[str, ...]  # tickery zdarzeń pominiętych z braku potwierdzonego CIK


def change_events_to_cik_events(
    ticker_events: frozenset[ChangeEvent], resolved: dict[str, str]
) -> CikEventConversion:
    """Konwertuje zdarzenia na poziomie tickera (fja05680 lub FMP) na
    zdarzenia na poziomie CIK, używając WYŁĄCZNIE potwierdzonego
    mapowania `resolved` (z `universe_history.resolve_tickers_to_cik`
    dla fja05680, `fmp_sp500_events.resolve_fmp_tickers` dla FMP —
    NIGDY nie zgadujemy CIK w tej funkcji). Zdarzenie, którego ticker
    nie ma potwierdzonego CIK, jest pomijane w wyniku, a jego ticker
    trafia jawnie do `dropped_unresolved_tickers` (posortowane, bez
    duplikatów) — nie znika bez śladu."""
    events: set[CikEvent] = set()
    dropped: set[str] = set()
    for e in ticker_events:
        cik = resolved.get(e.ticker)
        if cik is None:
            dropped.add(e.ticker)
            continue
        events.add(CikEvent(date=e.date, cik=cik, action=e.action))
    return CikEventConversion(events=frozenset(events), dropped_unresolved_tickers=tuple(sorted(dropped)))


@dataclass(frozen=True)
class MatchedPair:
    canonical: CikEvent  # z fja05680
    validator: CikEvent  # z FMP
    day_diff: int  # validator.date - canonical.date, w dniach (może być ujemne)


@dataclass(frozen=True)
class ToleranceMatchResult:
    matched: tuple[MatchedPair, ...]
    only_canonical: tuple[CikEvent, ...]  # kandydaci na konflikt/lukę walidatora — NIE potwierdzony błąd
    only_validator: tuple[CikEvent, ...]  # kandydaci na konflikt/lukę kanonicznego źródła — NIE potwierdzony błąd
    tolerance_days: int


def match_cik_events_with_tolerance(
    canonical_events: frozenset[CikEvent],
    validator_events: frozenset[CikEvent],
    *,
    tolerance_days: int,
) -> ToleranceMatchResult:
    """Reguła v1 (deterministyczna, WERSJONOWANA przez `tolerance_days`,
    do jawnego cytowania przy każdej zmianie): dopasowuje zdarzenia z
    dwóch źródeł po (cik, action), pozwalając na przesunięcie daty do
    `tolerance_days` dni w dowolną stronę. W obrębie każdego koszyka
    (cik, action) dopasowanie jest GREEDY: kandydatów kanonicznych
    (fja05680) przetwarzamy w kolejności rosnącej daty, dla każdego
    wybierając NIEPRZYPISANEGO jeszcze kandydata walidatora (FMP) z
    najmniejszą |różnicą dni| w granicach tolerancji; remis rozstrzyga
    wcześniejsza data kandydata walidatora. To NIE jest globalnie
    optymalne dopasowanie (możliwe przy rzadkich duplikatach w tym
    samym koszyku), ale jest deterministyczne, proste do zweryfikowania
    ręcznie i wystarczające przy typowej gęstości zdarzeń S&P 500 (rzadko
    >1 ADD/REMOVE tej samej spółki w krótkim odstępie). Zdarzenie bez
    dopasowania w granicy tolerancji trafia do `only_canonical`/
    `only_validator` — to kandydaci na konflikt do DALSZEJ oceny, nie
    automatycznie potwierdzone błędy żadnej ze stron."""
    canonical_by_bucket: dict[tuple[str, str], list[CikEvent]] = defaultdict(list)
    validator_by_bucket: dict[tuple[str, str], list[CikEvent]] = defaultdict(list)
    for e in canonical_events:
        canonical_by_bucket[(e.cik, e.action)].append(e)
    for e in validator_events:
        validator_by_bucket[(e.cik, e.action)].append(e)

    matched: list[MatchedPair] = []
    only_canonical: list[CikEvent] = []
    only_validator: list[CikEvent] = []

    all_buckets = set(canonical_by_bucket) | set(validator_by_bucket)
    for bucket in sorted(all_buckets):
        c_list = sorted(canonical_by_bucket.get(bucket, []), key=lambda e: e.date)
        v_list = sorted(validator_by_bucket.get(bucket, []), key=lambda e: e.date)
        used_v: set[int] = set()
        for c in c_list:
            c_date = dt.date.fromisoformat(c.date)
            best_idx: int | None = None
            best_diff: int | None = None
            for i, v in enumerate(v_list):
                if i in used_v:
                    continue
                diff = (dt.date.fromisoformat(v.date) - c_date).days
                if abs(diff) > tolerance_days:
                    continue
                if (
                    best_idx is None
                    or abs(diff) < abs(best_diff)
                    or (abs(diff) == abs(best_diff) and v.date < v_list[best_idx].date)
                ):
                    best_idx = i
                    best_diff = diff
            if best_idx is not None:
                used_v.add(best_idx)
                matched.append(MatchedPair(canonical=c, validator=v_list[best_idx], day_diff=best_diff))
            else:
                only_canonical.append(c)
        for i, v in enumerate(v_list):
            if i not in used_v:
                only_validator.append(v)

    matched.sort(key=lambda p: (p.canonical.cik, p.canonical.action, p.canonical.date))
    only_canonical.sort(key=lambda e: (e.cik, e.action, e.date))
    only_validator.sort(key=lambda e: (e.cik, e.action, e.date))

    return ToleranceMatchResult(
        matched=tuple(matched),
        only_canonical=tuple(only_canonical),
        only_validator=tuple(only_validator),
        tolerance_days=tolerance_days,
    )


def tolerance_impact_curve(
    canonical_events: frozenset[CikEvent],
    validator_events: frozenset[CikEvent],
    *,
    tolerance_range_days: range,
) -> list[dict]:
    """Dla każdej wartości tolerancji w `tolerance_range_days` uruchamia
    `match_cik_events_with_tolerance` i zwraca listę {tolerance_days,
    matched_count, only_canonical_count, only_validator_count} — do
    EMPIRYCZNEGO pokazania krzywej malejących przyrostów (ile dodatkowo
    dopasowań daje każdy kolejny dzień tolerancji) zamiast arbitralnego
    wyboru jednej wartości tolerancji."""
    curve = []
    for t in tolerance_range_days:
        r = match_cik_events_with_tolerance(canonical_events, validator_events, tolerance_days=t)
        curve.append(
            {
                "tolerance_days": t,
                "matched_count": len(r.matched),
                "only_canonical_count": len(r.only_canonical),
                "only_validator_count": len(r.only_validator),
            }
        )
    return curve


def pick_plateau_tolerance(curve: list[dict]) -> int:
    """Wybiera NAJMNIEJSZĄ wartość tolerancji, od której `matched_count`
    już się nie zmienia do końca przetestowanego zakresu (plateau) —
    deterministyczny wybór WYPROWADZONY z krzywej
    `tolerance_impact_curve`, nie arbitralna liczba wybrana z góry.
    Zakłada `curve` posortowane rosnąco po `tolerance_days` (tak jak
    zwraca `tolerance_impact_curve`). Jeśli `matched_count` rośnie aż
    do ostatniego przetestowanego punktu (plateau nie zostało jeszcze
    osiągnięte w testowanym zakresie), zwraca tolerancję z OSTATNIEGO
    punktu krzywej — TO NALEŻY jawnie zaraportować jako "zakres do
    rozszerzenia w kolejnym przebiegu", nie ukrywać milcząco."""
    if not curve:
        raise ValueError("tolerance_impact_curve nie może być pusta")
    final_count = curve[-1]["matched_count"]
    for point in curve:
        if point["matched_count"] == final_count:
            return point["tolerance_days"]
    return curve[-1]["tolerance_days"]  # nieosiągalne przy poprawnym curve, ale bez zgadywania


@dataclass(frozen=True)
class ReconciliationReport:
    tolerance_days: int
    matched_count: int
    only_canonical: tuple[CikEvent, ...]
    only_validator: tuple[CikEvent, ...]
    canonical_dropped_unresolved_tickers: tuple[str, ...]
    validator_dropped_unresolved_tickers: tuple[str, ...]


def build_reconciliation_report(
    canonical_ticker_events: frozenset[ChangeEvent],
    validator_ticker_events: frozenset[ChangeEvent],
    canonical_resolved: dict[str, str],
    validator_resolved: dict[str, str],
    *,
    tolerance_days: int,
) -> ReconciliationReport:
    """Składa `change_events_to_cik_events` + `match_cik_events_with_
    tolerance` w jeden audytowalny raport. fja05680 (`canonical_*`)
    pozostaje kanonicznym źródłem — ta funkcja NIGDY nie zwraca ani nie
    sugeruje zmodyfikowanego membership, wyłącznie listy rozbieżności
    do ręcznej oceny. Wynik jest deterministyczny i w pełni odtwarzalny
    z tych samych wejść (audytowalność: część 2 domknięcia BLOCKER 2)."""
    canonical_conv = change_events_to_cik_events(canonical_ticker_events, canonical_resolved)
    validator_conv = change_events_to_cik_events(validator_ticker_events, validator_resolved)
    match_result = match_cik_events_with_tolerance(
        canonical_conv.events, validator_conv.events, tolerance_days=tolerance_days
    )
    return ReconciliationReport(
        tolerance_days=tolerance_days,
        matched_count=len(match_result.matched),
        only_canonical=match_result.only_canonical,
        only_validator=match_result.only_validator,
        canonical_dropped_unresolved_tickers=canonical_conv.dropped_unresolved_tickers,
        validator_dropped_unresolved_tickers=validator_conv.dropped_unresolved_tickers,
    )

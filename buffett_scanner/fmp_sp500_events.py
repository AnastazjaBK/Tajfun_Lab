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
from dataclasses import dataclass


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
        parsed = None
        for fmt in ("%B %d, %Y", "%b %d, %Y"):
            try:
                parsed = dt.datetime.strptime(e.date_added_raw.strip(), fmt).date().isoformat()
                break
            except (ValueError, AttributeError):
                continue
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

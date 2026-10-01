"""Analiza zero-gap adjacency dla tickerów `CIK_UNRESOLVED` (Faza 5.3,
Proof Run zatwierdzony przez właściciela 2026-09-30, PRZED jakąkolwiek
implementacją produkcyjną). Cel: zmierzyć, ile z obecnych 196
`CIK_UNRESOLVED` tickerów MOŻNA odzyskać przez strukturalny sygnał
"ten ticker kończy się dokładnie tam, gdzie zaczyna się inny,
rozwiązany ticker" (lub odwrotnie) — a ile z nich ma to jednoznacznie,
a ile niejednoznacznie (kilku kandydatów, sprzeczne CIK).

Krytyczne zastrzeżenie właściciela, wprost cytowane w wymaganiach:
sam fakt zero-gap adjacency (jedna spółka opuszcza indeks tego samego
dnia, którego inna wchodzi) NIE jest wystarczającym dowodem tożsamości
spółki — to może być TICKER RENAME SAME COMPANY (prawdziwa zmiana
tickera tej samej spółki) albo INDEX REPLACEMENT DIFFERENT COMPANY
(przypadkowa koincydencja dnia rebalansu indeksu, dwie niepowiązane
spółki). Ten moduł dostarcza WYŁĄCZNIE część A (analiza strukturalna,
`analyze_ticker_adjacency`) — klasyfikuje kandydatów, ale
`UNIQUE_CANDIDATE` oznacza tylko "strukturalnie jednoznaczny", NIGDY
"potwierdzony". Część B (niezależna weryfikacja przez `formerNames`
SEC, `former_name_corroborates_boundary`) dostarcza dodatkowego,
niezależnego od struktury sygnału, ale i ona nie jest ostatecznym
dowodem — tylko sygnałem korroborującym, do jawnego zaraportowania.
Zero I/O w tym module — pobieranie danych dzieje się w warstwie
providerów."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Literal

from buffett_scanner.universe_history import TickerInterval

AdjacencyDirection = Literal["UNRESOLVED_ENDS_RESOLVED_STARTS", "RESOLVED_ENDS_UNRESOLVED_STARTS"]
AdjacencyStatus = Literal["NO_CANDIDATE", "UNIQUE_CANDIDATE", "AMBIGUOUS_CONFLICTING_CIK"]


@dataclass(frozen=True)
class AdjacencyCandidate:
    unresolved_ticker: str
    boundary_date: str
    direction: AdjacencyDirection
    adjacent_ticker: str
    adjacent_cik: str


@dataclass(frozen=True)
class AdjacencyAnalysis:
    unresolved_ticker: str
    candidates: tuple[AdjacencyCandidate, ...]
    distinct_ciks: tuple[str, ...]
    status: AdjacencyStatus


def analyze_ticker_adjacency(
    ticker_intervals: list[TickerInterval],
    resolved: dict[str, str],
    unresolved: tuple[str, ...],
) -> list[AdjacencyAnalysis]:
    """Dla każdego tickera z `unresolved`, sprawdza OBA kierunki
    zero-gap adjacency względem WSZYSTKICH przedziałów tickerów już
    rozwiązanych (`resolved`): (1) przedział nierozwiązanego tickera
    kończy się dokładnie tam, gdzie zaczyna się przedział rozwiązanego
    tickera (nierozwiązany = potencjalnie STARY ticker), (2) przedział
    rozwiązanego tickera kończy się dokładnie tam, gdzie zaczyna się
    przedział nierozwiązanego (nierozwiązany = potencjalnie NOWY
    ticker, rzadszy przypadek, ale sprawdzany symetrycznie na żądanie
    właściciela). Ticker z wieloma własnymi przedziałami (rzadkie, ale
    możliwe — patrz `test_build_cik_membership_intervals_unresolved_is_sorted_and_deduped`)
    jest sprawdzany na KAŻDEJ swojej granicy niezależnie; wszyscy
    znalezieni kandydaci trafiają do jednej listy dla tego tickera.
    Klasyfikacja: 0 kandydatów -> `NO_CANDIDATE`; kandydaci wskazujący
    razem na DOKŁADNIE JEDEN odrębny CIK (niezależnie ile ścieżek/dat
    do niego prowadzi) -> `UNIQUE_CANDIDATE` (WYŁĄCZNIE strukturalnie
    jednoznaczne — patrz zastrzeżenie w docstringu modułu, to NIE jest
    potwierdzenie tożsamości); kandydaci wskazujący na >1 odrębny CIK
    -> `AMBIGUOUS_CONFLICTING_CIK`."""
    intervals_by_ticker: dict[str, list[TickerInterval]] = {}
    for iv in ticker_intervals:
        intervals_by_ticker.setdefault(iv.ticker, []).append(iv)

    resolved_starts: dict[str, list[tuple[str, str]]] = {}
    resolved_ends: dict[str, list[tuple[str, str]]] = {}
    for iv in ticker_intervals:
        cik = resolved.get(iv.ticker)
        if cik is None:
            continue
        resolved_starts.setdefault(iv.start_date, []).append((iv.ticker, cik))
        if iv.end_date is not None:
            resolved_ends.setdefault(iv.end_date, []).append((iv.ticker, cik))

    results: list[AdjacencyAnalysis] = []
    for ticker in sorted(unresolved):
        candidates: set[AdjacencyCandidate] = set()
        for iv in intervals_by_ticker.get(ticker, []):
            if iv.end_date is not None:
                for adj_ticker, adj_cik in resolved_starts.get(iv.end_date, []):
                    candidates.add(
                        AdjacencyCandidate(
                            unresolved_ticker=ticker,
                            boundary_date=iv.end_date,
                            direction="UNRESOLVED_ENDS_RESOLVED_STARTS",
                            adjacent_ticker=adj_ticker,
                            adjacent_cik=adj_cik,
                        )
                    )
            for adj_ticker, adj_cik in resolved_ends.get(iv.start_date, []):
                candidates.add(
                    AdjacencyCandidate(
                        unresolved_ticker=ticker,
                        boundary_date=iv.start_date,
                        direction="RESOLVED_ENDS_UNRESOLVED_STARTS",
                        adjacent_ticker=adj_ticker,
                        adjacent_cik=adj_cik,
                    )
                )

        sorted_candidates = tuple(
            sorted(candidates, key=lambda c: (c.boundary_date, c.direction, c.adjacent_ticker))
        )
        distinct_ciks = tuple(sorted({c.adjacent_cik for c in sorted_candidates}))
        if not sorted_candidates:
            status: AdjacencyStatus = "NO_CANDIDATE"
        elif len(distinct_ciks) == 1:
            status = "UNIQUE_CANDIDATE"
        else:
            status = "AMBIGUOUS_CONFLICTING_CIK"

        results.append(
            AdjacencyAnalysis(
                unresolved_ticker=ticker,
                candidates=sorted_candidates,
                distinct_ciks=distinct_ciks,
                status=status,
            )
        )
    return results


def chronological_order(unresolved_ticker: str, candidate: AdjacencyCandidate) -> tuple[str, str]:
    """Zwraca `(old_ticker, new_ticker)` na podstawie WYŁĄCZNIE
    strukturalnego kierunku przejścia w fja05680 (`candidate.direction`)
    — NIGDY na podstawie tego, który ticker jest `unresolved` wg
    dzisiejszej mapy SEC. To dwie niezależne rzeczy, pomylone w
    pierwszej wersji `ticker_rename_multi_signal_verification.py`
    (błąd znaleziony i zgłoszony przez właścicielkę dla pary FI/FISV,
    2026-10-01: dzisiejsza mapa SEC rozwiązywała `FISV`, mimo że to
    `FISV` jest CHRONOLOGICZNIE STARSZYM tickerem — Fiserv notuje się
    pod `FI` dopiero od 2023-06-07). "Unresolved wg SEC dziś" i
    "chronologicznie starszy w fja05680" to NIE to samo pojęcie i nie
    wolno ich utożsamiać.

    `UNRESOLVED_ENDS_RESOLVED_STARTS`: `unresolved_ticker` kończy się
    (stary), `candidate.adjacent_ticker` zaczyna się (nowy).
    `RESOLVED_ENDS_UNRESOLVED_STARTS`: `candidate.adjacent_ticker`
    kończy się (stary), `unresolved_ticker` zaczyna się (nowy) —
    dokładnie ten przypadek wymaga ZAMIANY miejscami względem tego,
    który ticker jest dziś "unresolved"."""
    if candidate.direction == "UNRESOLVED_ENDS_RESOLVED_STARTS":
        return unresolved_ticker, candidate.adjacent_ticker
    return candidate.adjacent_ticker, unresolved_ticker


@dataclass(frozen=True)
class FormerNameMatch:
    name: str
    from_date: str | None
    to_date: str | None
    day_diff: int


def former_name_corroborates_boundary(
    former_names: list[dict], boundary_date: str, *, tolerance_days: int = 3
) -> FormerNameMatch | None:
    """Sprawdza, czy KTÓRAKOLWIEK dawna nazwa prawna spółki
    (`former_names`, z `SecEdgarClient.get_former_names`) przestała
    obowiązywać (`to_date`) w pobliżu `boundary_date` (data zero-gap
    adjacency z `analyze_ticker_adjacency`) — sygnał niezależny od
    struktury: realna zmiana tickera zwykle towarzyszy realnej zmianie
    nazwy prawnej (rebranding), podczas gdy przypadkowa koincydencja
    dnia rebalansu indeksu (dwie NIEPOWIĄZANE spółki) nie ma powodu
    współwystępować z akurat TĄ zmianą nazwy. Wpis bez parsowalnego
    `to_date` (ISO YYYY-MM-DD) jest pomijany — nigdy nie zgadujemy daty.
    Zwraca kandydata z NAJMNIEJSZĄ różnicą dni (możliwe kilka wpisów w
    tolerancji — wybieramy najbliższy, analogicznie do
    `match_cik_events_with_tolerance`), albo `None`, jeśli żaden wpis
    nie mieści się w tolerancji. To WYŁĄCZNIE sygnał korroborujący, nie
    samodzielny dowód — patrz zastrzeżenie w docstringu modułu."""
    boundary = dt.date.fromisoformat(boundary_date)
    best: FormerNameMatch | None = None
    for entry in former_names:
        to_date = entry.get("to_date")
        if not to_date:
            continue
        try:
            to = dt.date.fromisoformat(to_date)
        except ValueError:
            continue
        diff = (to - boundary).days
        if abs(diff) > tolerance_days:
            continue
        if best is None or abs(diff) < abs(best.day_diff):
            best = FormerNameMatch(
                name=entry.get("name", ""), from_date=entry.get("from_date"), to_date=to_date, day_diff=diff
            )
    return best

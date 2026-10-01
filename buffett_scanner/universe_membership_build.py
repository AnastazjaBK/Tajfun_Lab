"""Budowa finalnego `universe_membership` (Faza 5.2, domknięcie OPEN
BLOCKER 2, v1.35) — projekt zatwierdzony przez właścicielkę. Czyste
transformacje już rozwiązanych (CIK) przedziałów i wyników walidacji na
gotowe do zapisu wiersze; zero I/O, zero decyzji o CIK (to już zrobione
w `universe_history.resolve_tickers_to_cik` / `fmp_sp500_events.
resolve_fmp_tickers`).

Zasada architektoniczna (niezmienna): fja05680 jest JEDYNYM źródłem
`universe_membership` — FMP (przez `universe_cik_reconciliation.
match_cik_events_with_tolerance`) wyłącznie OPISUJE, czy dane zdarzenie
jest niezależnie potwierdzone. Żadna funkcja w tym module nie zmienia
cik/start_date/end_date na podstawie FMP — tylko dopisuje metadane
walidacji."""

from __future__ import annotations

from dataclasses import dataclass, replace

from buffett_scanner.universe_cik_reconciliation import ToleranceMatchResult
from buffett_scanner.universe_history import TickerInterval

NOT_VALIDATED = "NOT_VALIDATED"
MATCHED = "MATCHED"
ONLY_CANONICAL = "ONLY_CANONICAL"
ONLY_VALIDATOR = "ONLY_VALIDATOR"


@dataclass(frozen=True)
class MembershipInterval:
    cik: str
    index_name: str
    start_date: str
    end_date: str | None
    source: str
    source_snapshot_ref: str
    cik_resolution_method: str  # "DIRECT" | "FORMAT_VARIANT" | "CURATED_ALLOWLIST"
    cik_resolution_note: str | None = None  # provenance pełnej allowlisty (Faza 5.3), tylko dla CURATED_ALLOWLIST
    entry_validation_status: str = NOT_VALIDATED
    entry_validation_day_diff: int | None = None
    exit_validation_status: str | None = None
    exit_validation_day_diff: int | None = None
    validation_tolerance_days: int | None = None
    validation_date_field: str | None = None
    validation_rule_version: str | None = None
    validation_run_id: str | None = None


@dataclass(frozen=True)
class ConflictRecord:
    cik: str
    index_name: str
    event_date: str
    action: str  # "ADD" | "REMOVE"
    conflict_type: str  # "ONLY_CANONICAL" | "ONLY_VALIDATOR"
    tolerance_days: int
    date_field: str
    validation_rule_version: str
    validation_run_id: str


def build_cik_membership_intervals(
    ticker_intervals: list[TickerInterval],
    resolved: dict[str, str],
    resolved_via_format_variant: dict[str, str],
    *,
    index_name: str,
    source: str,
    source_snapshot_ref: str,
    resolved_via_curated_allowlist: dict[str, str] | None = None,
) -> tuple[list[MembershipInterval], tuple[str, ...]]:
    """Konwertuje przedziały ticker-poziomu (`universe_history.
    build_ticker_intervals`) na przedziały CIK-poziomu, używając
    WYŁĄCZNIE potwierdzonego mapowania `resolved` — nigdy nie zgaduje
    CIK. Ticker bez CIK jest pomijany (nie generuje wiersza) i trafia
    do drugiego elementu zwracanej krotki (`unresolved_tickers`,
    posortowane, bez duplikatów) — nigdy nie znika bez śladu (dyscyplina
    CIK_UNRESOLVED). NIE scala jeszcze przedziałów tego samego CIK —
    patrz `merge_adjacent_same_cik_intervals`, osobny, jawny krok.

    `resolved_via_curated_allowlist` (Faza 5.3, LIMITED_BUT_HONEST,
    zatwierdzone przez właścicielkę 2026-10-01): ticker -> nota
    provenance (z `universe_ticker_rename_allowlist.
    apply_curated_allowlist`). Ticker w tym mapowaniu dostaje
    `cik_resolution_method="CURATED_ALLOWLIST"` (priorytet nad
    FORMAT_VARIANT/DIRECT — allowlista jest zawsze jawnym, ręcznie
    zatwierdzonym wyjątkiem) i `cik_resolution_note` z pełną
    ścieżką dowodową, zamiast zwykłego DIRECT/FORMAT_VARIANT."""
    curated_notes = resolved_via_curated_allowlist or {}
    intervals: list[MembershipInterval] = []
    unresolved: set[str] = set()
    for iv in ticker_intervals:
        cik = resolved.get(iv.ticker)
        if cik is None:
            unresolved.add(iv.ticker)
            continue
        if iv.ticker in curated_notes:
            method = "CURATED_ALLOWLIST"
        elif iv.ticker in resolved_via_format_variant:
            method = "FORMAT_VARIANT"
        else:
            method = "DIRECT"
        intervals.append(
            MembershipInterval(
                cik=cik,
                index_name=index_name,
                start_date=iv.start_date,
                end_date=iv.end_date,
                source=source,
                source_snapshot_ref=source_snapshot_ref,
                cik_resolution_method=method,
                cik_resolution_note=curated_notes.get(iv.ticker),
            )
        )
    return intervals, tuple(sorted(unresolved))


def merge_adjacent_same_cik_intervals(intervals: list[MembershipInterval]) -> list[MembershipInterval]:
    """Scala przedziały TEGO SAMEGO CIK, gdy `end_date` jednego dokładnie
    równa się `start_date` następnego (zero-dniowa przerwa) — typowy
    ślad zmiany tickera BEZ opuszczenia indeksu (np. FB->META), którą
    `build_ticker_intervals` na poziomie tickera poprawnie widzi jako
    dwa przedziały, ale na poziomie CIK to JEDNO ciągłe członkostwo.
    Rzeczywiste opuszczenie i powrót (niezerowa przerwa) NIE jest
    scalane — zostaje dwoma osobnymi przedziałami (zgodnie z regułą
    zatwierdzoną przez właścicielkę). Provenance (source,
    cik_resolution_method) scalonego przedziału pochodzi z PIERWSZEGO
    (dotyczy wejścia w ciągły okres); `exit_validation_*` z DRUGIEGO
    (dotyczy faktycznego końca, jeśli istnieje). Zakłada brak
    nakładających się przedziałów dla tego samego CIK (to inny problem,
    poza zakresem tej funkcji)."""
    if not intervals:
        return []

    by_cik: dict[str, list[MembershipInterval]] = {}
    for iv in intervals:
        by_cik.setdefault(iv.cik, []).append(iv)

    merged: list[MembershipInterval] = []
    for group in by_cik.values():
        group_sorted = sorted(group, key=lambda iv: iv.start_date)
        current = group_sorted[0]
        for nxt in group_sorted[1:]:
            if current.end_date is not None and current.end_date == nxt.start_date:
                current = replace(
                    current,
                    end_date=nxt.end_date,
                    exit_validation_status=nxt.exit_validation_status,
                    exit_validation_day_diff=nxt.exit_validation_day_diff,
                )
            else:
                merged.append(current)
                current = nxt
        merged.append(current)

    merged.sort(key=lambda iv: (iv.cik, iv.start_date))
    return merged


def attach_validation_status(
    intervals: list[MembershipInterval],
    match_result: ToleranceMatchResult,
    *,
    date_field: str,
    validation_rule_version: str,
    validation_run_id: str,
) -> list[MembershipInterval]:
    """Oznacza każdy przedział statusem walidacji na podstawie wyniku
    `match_cik_events_with_tolerance` (fja05680=kanoniczne wejście,
    FMP=walidator). Zdarzenie wejścia (`start_date`, ADD) i wyjścia
    (`end_date`, REMOVE — jeśli istnieje) są sprawdzane NIEZALEŻNIE:
    przedział może mieć dopasowane wejście przy niedopasowanym wyjściu,
    lub odwrotnie. Brak `end_date` (nadal aktywny) -> `exit_validation_
    status` pozostaje `None` (nie ma zdarzenia do zwalidowania). FMP
    NIGDY nie zmienia cik/start_date/end_date tutaj — wyłącznie opisuje,
    czy niezależne źródło je potwierdza (zasada kanoniczne/walidator)."""
    matched_diff_by_event = {
        (p.canonical.cik, p.canonical.date, p.canonical.action): p.day_diff for p in match_result.matched
    }
    only_canonical_events = {(e.cik, e.date, e.action) for e in match_result.only_canonical}

    def _status_and_diff(cik: str, date: str, action: str) -> tuple[str, int | None]:
        key = (cik, date, action)
        if key in matched_diff_by_event:
            return MATCHED, matched_diff_by_event[key]
        if key in only_canonical_events:
            return ONLY_CANONICAL, None
        return NOT_VALIDATED, None  # zdarzenie spoza zbioru wejściowego walidacji

    result: list[MembershipInterval] = []
    for iv in intervals:
        entry_status, entry_diff = _status_and_diff(iv.cik, iv.start_date, "ADD")
        if iv.end_date is not None:
            exit_status, exit_diff = _status_and_diff(iv.cik, iv.end_date, "REMOVE")
        else:
            exit_status, exit_diff = None, None
        result.append(
            replace(
                iv,
                entry_validation_status=entry_status,
                entry_validation_day_diff=entry_diff,
                exit_validation_status=exit_status,
                exit_validation_day_diff=exit_diff,
                validation_tolerance_days=match_result.tolerance_days,
                validation_date_field=date_field,
                validation_rule_version=validation_rule_version,
                validation_run_id=validation_run_id,
            )
        )
    return result


def build_conflicts(
    match_result: ToleranceMatchResult,
    *,
    index_name: str,
    date_field: str,
    validation_rule_version: str,
    validation_run_id: str,
) -> list[ConflictRecord]:
    """Materializuje `only_canonical`/`only_validator` z wyniku
    dopasowania jako pełny, audytowalny log konfliktów — niezależny od
    `universe_membership` (obejmuje też `only_validator`, dla którego
    NIE istnieje żaden wiersz membership, bo fja05680 nigdy go nie
    potwierdził). Wyłącznie do ręcznego przeglądu — nic tu nie
    modyfikuje kanonicznego składu."""
    records: list[ConflictRecord] = []
    for e in match_result.only_canonical:
        records.append(
            ConflictRecord(
                cik=e.cik, index_name=index_name, event_date=e.date, action=e.action,
                conflict_type=ONLY_CANONICAL, tolerance_days=match_result.tolerance_days,
                date_field=date_field, validation_rule_version=validation_rule_version,
                validation_run_id=validation_run_id,
            )
        )
    for e in match_result.only_validator:
        records.append(
            ConflictRecord(
                cik=e.cik, index_name=index_name, event_date=e.date, action=e.action,
                conflict_type=ONLY_VALIDATOR, tolerance_days=match_result.tolerance_days,
                date_field=date_field, validation_rule_version=validation_rule_version,
                validation_run_id=validation_run_id,
            )
        )
    return records


def membership_as_of(intervals: list[MembershipInterval], as_of_date: str) -> set[str]:
    """Zbiór CIK-ów aktywnych na `as_of_date` — `start_date <= D <
    end_date` (end_date wyłączny, ten sam wzorzec co `tickers_as_of`/
    `value_as_of`). Czysta funkcja pomocnicza do weryfikacji rekonstrukcji
    w pamięci, bez zapytania SQL — używana w testach i w raporcie
    Proof Run przed zapisem do bazy."""
    return {
        iv.cik
        for iv in intervals
        if iv.start_date <= as_of_date and (iv.end_date is None or iv.end_date > as_of_date)
    }

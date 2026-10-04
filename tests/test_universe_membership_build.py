"""Testy budowy finalnego `universe_membership` (Faza 5.2, domknięcie
OPEN BLOCKER 2, v1.35) — wartości referencyjne policzone ręcznie."""

from __future__ import annotations

from buffett_scanner.universe_cik_reconciliation import CikEvent, MatchedPair, ToleranceMatchResult
from buffett_scanner.universe_history import TickerInterval
from buffett_scanner.universe_membership_build import (
    MembershipInterval,
    attach_validation_status,
    build_cik_membership_intervals,
    build_conflicts,
    membership_as_of,
    merge_adjacent_same_cik_intervals,
)


def _mi(cik, start, end=None, **kw) -> MembershipInterval:
    defaults = dict(
        index_name="SP500", source="fja05680", source_snapshot_ref="ref1",
        cik_resolution_method="DIRECT",
    )
    defaults.update(kw)
    return MembershipInterval(cik=cik, start_date=start, end_date=end, **defaults)


# ---------------------------------------------------------------------------
# build_cik_membership_intervals
# ---------------------------------------------------------------------------


def test_build_cik_membership_intervals_resolves_and_tags_method():
    ticker_intervals = [
        TickerInterval(ticker="AAA", start_date="2012-01-01", end_date="2015-01-01"),
        TickerInterval(ticker="BRK.B", start_date="2012-01-01", end_date=None),
    ]
    resolved = {"AAA": "0001", "BRK.B": "0002"}
    resolved_via_variant = {"BRK.B": "BRK-B"}
    intervals, unresolved = build_cik_membership_intervals(
        ticker_intervals, resolved, resolved_via_variant,
        index_name="SP500", source="fja05680", source_snapshot_ref="ref1",
    )
    by_cik = {iv.cik: iv for iv in intervals}
    assert by_cik["0001"].cik_resolution_method == "DIRECT"
    assert by_cik["0001"].start_date == "2012-01-01"
    assert by_cik["0001"].end_date == "2015-01-01"
    assert by_cik["0002"].cik_resolution_method == "FORMAT_VARIANT"
    assert unresolved == ()


def test_build_cik_membership_intervals_never_fabricates_cik_for_unresolved_ticker():
    ticker_intervals = [TickerInterval(ticker="NOPE", start_date="2012-01-01", end_date=None)]
    intervals, unresolved = build_cik_membership_intervals(
        ticker_intervals, {}, {}, index_name="SP500", source="fja05680", source_snapshot_ref="ref1",
    )
    assert intervals == []
    assert unresolved == ("NOPE",)


def test_build_cik_membership_intervals_tags_curated_allowlist_with_note():
    """Faza 5.3 (LIMITED_BUT_HONEST, v1.39): ticker obecny w
    `resolved_via_curated_allowlist` dostaje method='CURATED_ALLOWLIST'
    i pełną notę, zamiast DIRECT — nawet jeśli nie jest w ogóle w
    `resolved_via_format_variant`."""
    ticker_intervals = [
        TickerInterval(ticker="ANTM", start_date="2012-01-01", end_date="2022-06-28"),
        TickerInterval(ticker="ELV", start_date="2022-06-28", end_date=None),
    ]
    resolved = {"ANTM": "1156039", "ELV": "1156039"}
    curated_notes = {"ANTM": "MULTI_SIGNAL_VERIFIED_V1 old=ANTM new=ELV"}
    intervals, unresolved = build_cik_membership_intervals(
        ticker_intervals, resolved, {}, index_name="SP500", source="fja05680",
        source_snapshot_ref="ref1", resolved_via_curated_allowlist=curated_notes,
    )
    by_start = {iv.start_date: iv for iv in intervals}
    assert by_start["2012-01-01"].cik_resolution_method == "CURATED_ALLOWLIST"
    assert by_start["2012-01-01"].cik_resolution_note == "MULTI_SIGNAL_VERIFIED_V1 old=ANTM new=ELV"
    assert by_start["2022-06-28"].cik_resolution_method == "DIRECT"
    assert by_start["2022-06-28"].cik_resolution_note is None
    assert unresolved == ()


def test_build_cik_membership_intervals_curated_allowlist_takes_priority_over_format_variant():
    """Teoretyczny (nierealny w praktyce) przypadek: ticker jest
    jednocześnie w obu mapowaniach — allowlista wygrywa, bo jest zawsze
    jawnym, ręcznie zatwierdzonym wyjątkiem."""
    ticker_intervals = [TickerInterval(ticker="XYZ", start_date="2012-01-01", end_date=None)]
    resolved = {"XYZ": "0001"}
    intervals, _ = build_cik_membership_intervals(
        ticker_intervals, resolved, {"XYZ": "X-Y-Z"}, index_name="SP500", source="fja05680",
        source_snapshot_ref="ref1", resolved_via_curated_allowlist={"XYZ": "nota"},
    )
    assert intervals[0].cik_resolution_method == "CURATED_ALLOWLIST"


def test_build_cik_membership_intervals_unresolved_is_sorted_and_deduped():
    ticker_intervals = [
        TickerInterval(ticker="ZZZ", start_date="2012-01-01", end_date="2013-01-01"),
        TickerInterval(ticker="ZZZ", start_date="2014-01-01", end_date=None),  # ten sam ticker, 2 przedziały
        TickerInterval(ticker="AAA", start_date="2012-01-01", end_date=None),
    ]
    intervals, unresolved = build_cik_membership_intervals(
        ticker_intervals, {}, {}, index_name="SP500", source="fja05680", source_snapshot_ref="ref1",
    )
    assert unresolved == ("AAA", "ZZZ")


# ---------------------------------------------------------------------------
# merge_adjacent_same_cik_intervals
# ---------------------------------------------------------------------------


def test_merge_joins_zero_gap_same_cik_ticker_rename():
    """FB -> META bez opuszczenia indeksu: dwa przedziały tickera, ale
    JEDEN ciągły przedział CIK."""
    intervals = [
        _mi("0001326801", "2012-01-01", "2021-10-28"),
        _mi("0001326801", "2021-10-28", None),
    ]
    merged = merge_adjacent_same_cik_intervals(intervals)
    assert len(merged) == 1
    assert merged[0].start_date == "2012-01-01"
    assert merged[0].end_date is None


def test_merge_does_not_join_real_exit_and_reentry():
    intervals = [
        _mi("0001", "2012-01-01", "2015-01-01"),
        _mi("0001", "2016-01-01", None),  # niezerowa przerwa — realne wyjście/powrót
    ]
    merged = merge_adjacent_same_cik_intervals(intervals)
    assert len(merged) == 2
    assert (merged[0].start_date, merged[0].end_date) == ("2012-01-01", "2015-01-01")
    assert (merged[1].start_date, merged[1].end_date) == ("2016-01-01", None)


def test_merge_keeps_provenance_from_first_and_exit_validation_from_second():
    first = _mi("0001", "2012-01-01", "2021-10-28", cik_resolution_method="DIRECT")
    second = _mi(
        "0001", "2021-10-28", "2023-01-01",
        cik_resolution_method="FORMAT_VARIANT",
        exit_validation_status="MATCHED", exit_validation_day_diff=1,
    )
    merged = merge_adjacent_same_cik_intervals([first, second])
    assert len(merged) == 1
    assert merged[0].cik_resolution_method == "DIRECT"  # z pierwszego (wejście)
    assert merged[0].exit_validation_status == "MATCHED"  # z drugiego (wyjście)
    assert merged[0].exit_validation_day_diff == 1
    assert merged[0].end_date == "2023-01-01"


def test_merge_keeps_curated_allowlist_note_from_first_interval():
    """Faza 5.3 (LIMITED_BUT_HONEST, v1.39): scalony przedział ANTM+ELV
    musi zachować cik_resolution_method='CURATED_ALLOWLIST' i notę z
    PIERWSZEGO (ANTM, wejście w ciągły okres) — to właśnie wejście
    zależało od allowlisty, bez niej CIK zacząłby się dopiero od ELV."""
    first = _mi(
        "1156039", "2012-01-01", "2022-06-28",
        cik_resolution_method="CURATED_ALLOWLIST", cik_resolution_note="old=ANTM new=ELV",
    )
    second = _mi("1156039", "2022-06-28", None, cik_resolution_method="DIRECT")
    merged = merge_adjacent_same_cik_intervals([first, second])
    assert len(merged) == 1
    assert merged[0].cik_resolution_method == "CURATED_ALLOWLIST"
    assert merged[0].cik_resolution_note == "old=ANTM new=ELV"
    assert merged[0].end_date is None


def test_merge_curated_allowlist_wins_even_when_it_is_the_second_interval():
    """Przypadek FISV->FI (realny błąd znaleziony 2026-10-01 przy
    produkcyjnym buildzie): FISV (DIRECT, WCZEŚNIEJSZY) jest kotwicą,
    FI (CURATED_ALLOWLIST, PÓŹNIEJSZY) jest tickerem odzyskanym przez
    allowlistę. Scalony przedział MUSI pokazać CURATED_ALLOWLIST, mimo
    że to drugi (nie pierwszy) przedział — inaczej znika informacja, że
    druga połowa ciągłego członkostwa zależała od allowlisty."""
    first = _mi("798354", "2012-01-01", "2023-06-07", cik_resolution_method="DIRECT")
    second = _mi(
        "798354", "2023-06-07", None,
        cik_resolution_method="CURATED_ALLOWLIST", cik_resolution_note="old=FISV new=FI",
    )
    merged = merge_adjacent_same_cik_intervals([first, second])
    assert len(merged) == 1
    assert merged[0].cik_resolution_method == "CURATED_ALLOWLIST"
    assert merged[0].cik_resolution_note == "old=FISV new=FI"
    assert merged[0].start_date == "2012-01-01"
    assert merged[0].end_date is None


def test_merge_direct_vs_format_variant_precedence_unchanged_without_curated_allowlist():
    """Kontrola nieregresji: reguła "z pierwszego" dla zwykłego
    DIRECT/FORMAT_VARIANT (bez udziału CURATED_ALLOWLIST) pozostaje
    dokładnie taka, jak zatwierdzona w Fazie 5.2 — duplikuje
    `test_merge_keeps_provenance_from_first_and_exit_validation_from_second`
    z odwróconą kolejnością metod, żeby upewnić się, że wyjątek
    CURATED_ALLOWLIST nie zmienił tej ścieżki."""
    first = _mi("0001", "2012-01-01", "2015-01-01", cik_resolution_method="FORMAT_VARIANT")
    second = _mi("0001", "2015-01-01", None, cik_resolution_method="DIRECT")
    merged = merge_adjacent_same_cik_intervals([first, second])
    assert merged[0].cik_resolution_method == "FORMAT_VARIANT"  # z pierwszego, bez zmian


def test_merge_dual_class_overlap_is_one_cik_membership():
    """Przypadek B (Decyzja właścicielki 2026-10-04, realne znalezisko
    przy pełnym 615-CIK walk-forward): Alphabet GOOGL (od 2012-01-01,
    open-ended) + GOOG (od 2014-04-03, powstał przy split na klasę C,
    open-ended) -- DWIE klasy akcji, JEDNA spółka/CIK. Mimo że oba
    przedziały są RÓWNOLEGLE aktywne (nie sąsiadują, naprawdę się
    nakładają), to musi być JEDNO, nie dwa, membership tego CIK."""
    intervals = [
        _mi("1652044", "2012-01-01", None),
        _mi("1652044", "2014-04-03", None),
    ]
    merged = merge_adjacent_same_cik_intervals(intervals)
    assert len(merged) == 1
    assert merged[0].start_date == "2012-01-01"
    assert merged[0].end_date is None
    assert merged[0].overlap_merge_note is not None
    assert "2014-04-03" in merged[0].overlap_merge_note


def test_merge_partial_overlap_unions_to_widest_range():
    """Przypadek C: przedział A 2014-2020, przedział B 2016-2022
    (częściowe nakładanie, różne końce) -> wynik MUSI być 2014-2022 --
    `end_date` to PÓŹNIEJSZY z dwóch, nigdy przypadkowo skrócony do
    końca wcześniej zaczynającego się przedziału."""
    intervals = [
        _mi("0001", "2014-01-01", "2020-01-01"),
        _mi("0001", "2016-01-01", "2022-01-01"),
    ]
    merged = merge_adjacent_same_cik_intervals(intervals)
    assert len(merged) == 1
    assert merged[0].start_date == "2014-01-01"
    assert merged[0].end_date == "2022-01-01"
    assert merged[0].overlap_merge_note is not None


def test_merge_nested_overlap_does_not_shorten_wider_interval():
    """Under Armour UAA/UA (realny przypadek): oba przedziały mają TEN
    SAM `end_date` (2022-06-21), drugi zaczyna się później (2016-04-08)
    -- w pełni zagnieżdżony w pierwszym. Scalony koniec musi zostać
    2022-06-21 (PÓŹNIEJSZY-lub-równy), nie zostać cofnięty."""
    intervals = [
        _mi("1336917", "2014-05-01", "2022-06-21"),
        _mi("1336917", "2016-04-08", "2022-06-21"),
    ]
    merged = merge_adjacent_same_cik_intervals(intervals)
    assert len(merged) == 1
    assert merged[0].start_date == "2014-05-01"
    assert merged[0].end_date == "2022-06-21"
    assert merged[0].overlap_merge_note is not None


def test_merge_open_ended_overlap_both_none_stays_open_ended():
    """Przypadek D: 2013-NULL + 2015-NULL (oba open-ended) -> 2013-NULL.
    News Corp NWSA/NWS ma dokładnie ten kształt."""
    intervals = [
        _mi("0001", "2013-01-01", None),
        _mi("0001", "2015-01-01", None),
    ]
    merged = merge_adjacent_same_cik_intervals(intervals)
    assert len(merged) == 1
    assert merged[0].start_date == "2013-01-01"
    assert merged[0].end_date is None


def test_merge_real_exit_reentry_stays_two_intervals_exact_dates():
    """Przypadek E (dokładne daty ze specyfikacji właścicielki): 2012-
    2015 + 2018-NULL, dodatnia przerwa (3 lata) -> dwa OSOBNE
    membership intervals, zero `overlap_merge_note`."""
    intervals = [
        _mi("0001", "2012-01-01", "2015-01-01"),
        _mi("0001", "2018-01-01", None),
    ]
    merged = merge_adjacent_same_cik_intervals(intervals)
    assert len(merged) == 2
    assert (merged[0].start_date, merged[0].end_date) == ("2012-01-01", "2015-01-01")
    assert (merged[1].start_date, merged[1].end_date) == ("2018-01-01", None)
    assert merged[0].overlap_merge_note is None
    assert merged[1].overlap_merge_note is None


def test_merge_plain_adjacency_rename_does_not_get_overlap_note():
    """Kontrola nieregresji: zwykła zero-gap adjacency (rename, np.
    FB->META) NIE dostaje `overlap_merge_note` -- to nie jest "nowa"
    normalizacja, tylko już wcześniej obsługiwany przypadek."""
    intervals = [
        _mi("0001326801", "2012-01-01", "2021-10-28"),
        _mi("0001326801", "2021-10-28", None),
    ]
    merged = merge_adjacent_same_cik_intervals(intervals)
    assert merged[0].overlap_merge_note is None


def test_merge_different_ciks_are_never_joined():
    intervals = [_mi("0001", "2012-01-01", "2015-01-01"), _mi("0002", "2015-01-01", None)]
    merged = merge_adjacent_same_cik_intervals(intervals)
    assert len(merged) == 2


def test_merge_empty_list_returns_empty():
    assert merge_adjacent_same_cik_intervals([]) == []


# ---------------------------------------------------------------------------
# attach_validation_status
# ---------------------------------------------------------------------------


def test_attach_validation_status_marks_entry_matched_and_exit_only_canonical():
    intervals = [_mi("A", "2012-01-05", "2013-01-05")]
    match_result = ToleranceMatchResult(
        matched=(
            MatchedPair(
                canonical=CikEvent(date="2012-01-05", cik="A", action="ADD"),
                validator=CikEvent(date="2012-01-06", cik="A", action="ADD"),
                day_diff=1,
            ),
        ),
        only_canonical=(CikEvent(date="2013-01-05", cik="A", action="REMOVE"),),
        only_validator=(),
        tolerance_days=6,
    )
    result = attach_validation_status(
        intervals, match_result, date_field="dateAdded",
        validation_rule_version="cik_tolerance_match_v1", validation_run_id="run123",
    )
    assert len(result) == 1
    iv = result[0]
    assert iv.entry_validation_status == "MATCHED"
    assert iv.entry_validation_day_diff == 1
    assert iv.exit_validation_status == "ONLY_CANONICAL"
    assert iv.exit_validation_day_diff is None
    assert iv.validation_tolerance_days == 6
    assert iv.validation_date_field == "dateAdded"
    assert iv.validation_rule_version == "cik_tolerance_match_v1"
    assert iv.validation_run_id == "run123"


def test_attach_validation_status_open_interval_has_no_exit_status():
    intervals = [_mi("A", "2012-01-05", None)]
    match_result = ToleranceMatchResult(matched=(), only_canonical=(), only_validator=(), tolerance_days=6)
    result = attach_validation_status(
        intervals, match_result, date_field="date",
        validation_rule_version="v1", validation_run_id="run1",
    )
    assert result[0].exit_validation_status is None
    assert result[0].exit_validation_day_diff is None
    assert result[0].entry_validation_status == "NOT_VALIDATED"


def test_attach_validation_status_event_outside_match_result_is_not_validated():
    """Zdarzenie spoza zbioru wejściowego walidacji (np. poza oknem
    porównania) -> NOT_VALIDATED, nigdy fałszywie MATCHED/ONLY_CANONICAL."""
    intervals = [_mi("A", "1999-01-01", "1999-06-01")]
    match_result = ToleranceMatchResult(matched=(), only_canonical=(), only_validator=(), tolerance_days=6)
    result = attach_validation_status(
        intervals, match_result, date_field="date",
        validation_rule_version="v1", validation_run_id="run1",
    )
    assert result[0].entry_validation_status == "NOT_VALIDATED"
    assert result[0].exit_validation_status == "NOT_VALIDATED"


# ---------------------------------------------------------------------------
# build_conflicts
# ---------------------------------------------------------------------------


def test_build_conflicts_materializes_only_canonical_and_only_validator():
    match_result = ToleranceMatchResult(
        matched=(),
        only_canonical=(CikEvent(date="2013-01-05", cik="A", action="REMOVE"),),
        only_validator=(CikEvent(date="2014-01-01", cik="B", action="ADD"),),
        tolerance_days=6,
    )
    records = build_conflicts(
        match_result, index_name="SP500", date_field="dateAdded",
        validation_rule_version="cik_tolerance_match_v1", validation_run_id="run123",
    )
    assert len(records) == 2
    by_type = {r.conflict_type: r for r in records}
    assert by_type["ONLY_CANONICAL"].cik == "A"
    assert by_type["ONLY_CANONICAL"].action == "REMOVE"
    assert by_type["ONLY_VALIDATOR"].cik == "B"
    assert by_type["ONLY_VALIDATOR"].action == "ADD"
    assert all(r.tolerance_days == 6 for r in records)
    assert all(r.validation_run_id == "run123" for r in records)


def test_build_conflicts_empty_when_nothing_unmatched():
    match_result = ToleranceMatchResult(matched=(), only_canonical=(), only_validator=(), tolerance_days=6)
    records = build_conflicts(
        match_result, index_name="SP500", date_field="date",
        validation_rule_version="v1", validation_run_id="run1",
    )
    assert records == []


# ---------------------------------------------------------------------------
# membership_as_of
# ---------------------------------------------------------------------------


def test_membership_as_of_end_date_is_exclusive():
    intervals = [_mi("A", "2012-01-01", "2015-01-01"), _mi("B", "2012-06-01", None)]
    assert membership_as_of(intervals, "2013-01-01") == {"A", "B"}
    assert membership_as_of(intervals, "2015-01-01") == {"B"}  # A kończy się TEGO dnia -> już nie liczy się
    assert membership_as_of(intervals, "2011-01-01") == set()

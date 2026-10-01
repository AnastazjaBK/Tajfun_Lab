"""Testy Proof Run zero-gap adjacency dla CIK_UNRESOLVED (Faza 5.3,
przed jakąkolwiek implementacją produkcyjną, v1.0). Wartości
referencyjne policzone ręcznie."""

from __future__ import annotations

from buffett_scanner.universe_history import TickerInterval
from buffett_scanner.universe_ticker_adjacency import (
    AdjacencyCandidate,
    analyze_ticker_adjacency,
    chronological_order,
    former_name_corroborates_boundary,
)

# ---------------------------------------------------------------------------
# analyze_ticker_adjacency
# ---------------------------------------------------------------------------


def test_clean_single_candidate_case_like_antm_elv():
    intervals = [
        TickerInterval(ticker="ANTM", start_date="2012-01-01", end_date="2022-06-28"),
        TickerInterval(ticker="ELV", start_date="2022-06-28", end_date=None),
    ]
    result = analyze_ticker_adjacency(intervals, resolved={"ELV": "1156039"}, unresolved=("ANTM",))
    assert len(result) == 1
    r = result[0]
    assert r.unresolved_ticker == "ANTM"
    assert r.status == "UNIQUE_CANDIDATE"
    assert r.distinct_ciks == ("1156039",)
    assert r.candidates == (
        AdjacencyCandidate(
            unresolved_ticker="ANTM",
            boundary_date="2022-06-28",
            direction="UNRESOLVED_ENDS_RESOLVED_STARTS",
            adjacent_ticker="ELV",
            adjacent_cik="1156039",
        ),
    )


def test_ambiguous_multi_company_reshuffle_day():
    """Dzień realnego rebalansu indeksu: trzy spółki wychodzą, cztery
    wchodzą, wszystkie tego samego dnia — adjacency samo w sobie nie
    może wskazać jednoznacznego następcy dla AABA."""
    intervals = [
        TickerInterval(ticker="AABA", start_date="2012-01-01", end_date="2017-06-19"),
        TickerInterval(ticker="R", start_date="2012-01-01", end_date="2017-06-19"),
        TickerInterval(ticker="TDC", start_date="2012-01-01", end_date="2017-06-19"),
        TickerInterval(ticker="ALGN", start_date="2017-06-19", end_date=None),
        TickerInterval(ticker="ANSS", start_date="2017-06-19", end_date=None),
        TickerInterval(ticker="HLT", start_date="2017-06-19", end_date=None),
        TickerInterval(ticker="RE", start_date="2017-06-19", end_date=None),
    ]
    resolved = {"ALGN": "A", "ANSS": "B", "HLT": "C", "RE": "D"}
    result = analyze_ticker_adjacency(intervals, resolved=resolved, unresolved=("AABA",))
    r = result[0]
    assert r.status == "AMBIGUOUS_CONFLICTING_CIK"
    assert r.distinct_ciks == ("A", "B", "C", "D")
    assert len(r.candidates) == 4


def test_no_candidate_when_no_adjacent_resolved_ticker():
    intervals = [
        TickerInterval(ticker="XYZ", start_date="2012-01-01", end_date="2015-01-01"),
        TickerInterval(ticker="SOMETHING_ELSE", start_date="2018-01-01", end_date=None),
    ]
    result = analyze_ticker_adjacency(
        intervals, resolved={"SOMETHING_ELSE": "999"}, unresolved=("XYZ",)
    )
    r = result[0]
    assert r.status == "NO_CANDIDATE"
    assert r.candidates == ()
    assert r.distinct_ciks == ()


def test_multiple_paths_to_same_cik_still_counts_as_unique():
    """Nierozwiązany ticker ma DWA własne przedziały (rzadkie, ale
    możliwe), oba graniczące z tym samym CIK — wciąż jednoznaczne."""
    intervals = [
        TickerInterval(ticker="ZZZ", start_date="2012-01-01", end_date="2013-01-01"),
        TickerInterval(ticker="ZZZ", start_date="2014-01-01", end_date="2015-01-01"),
        TickerInterval(ticker="NEW1", start_date="2013-01-01", end_date=None),
        TickerInterval(ticker="NEW1B", start_date="2015-01-01", end_date=None),
    ]
    resolved = {"NEW1": "555", "NEW1B": "555"}
    result = analyze_ticker_adjacency(intervals, resolved=resolved, unresolved=("ZZZ",))
    r = result[0]
    assert r.status == "UNIQUE_CANDIDATE"
    assert r.distinct_ciks == ("555",)
    assert len(r.candidates) == 2


def test_resolved_ends_unresolved_starts_direction_detected():
    """Kierunek symetryczny: rozwiązany ticker kończy się dokładnie
    tam, gdzie zaczyna nierozwiązany (nierozwiązany jako potencjalnie
    NOWY ticker)."""
    intervals = [
        TickerInterval(ticker="OLD", start_date="2012-01-01", end_date="2016-03-01"),
        TickerInterval(ticker="NEWUNRES", start_date="2016-03-01", end_date=None),
    ]
    result = analyze_ticker_adjacency(intervals, resolved={"OLD": "777"}, unresolved=("NEWUNRES",))
    r = result[0]
    assert r.status == "UNIQUE_CANDIDATE"
    assert r.candidates == (
        AdjacencyCandidate(
            unresolved_ticker="NEWUNRES",
            boundary_date="2016-03-01",
            direction="RESOLVED_ENDS_UNRESOLVED_STARTS",
            adjacent_ticker="OLD",
            adjacent_cik="777",
        ),
    )


def test_unresolved_ticker_with_no_intervals_at_all_is_no_candidate():
    """Ticker z listy `unresolved`, który z jakiegoś powodu nie ma
    żadnego przedziału w `ticker_intervals` — nigdy nie crashuje,
    zwraca NO_CANDIDATE."""
    result = analyze_ticker_adjacency([], resolved={}, unresolved=("GHOST",))
    assert result[0].status == "NO_CANDIDATE"


def test_results_sorted_by_unresolved_ticker():
    intervals = [
        TickerInterval(ticker="BBB", start_date="2012-01-01", end_date=None),
        TickerInterval(ticker="AAA", start_date="2012-01-01", end_date=None),
    ]
    result = analyze_ticker_adjacency(intervals, resolved={}, unresolved=("BBB", "AAA"))
    assert [r.unresolved_ticker for r in result] == ["AAA", "BBB"]


# ---------------------------------------------------------------------------
# chronological_order
# ---------------------------------------------------------------------------


def test_chronological_order_unresolved_ends_resolved_starts_keeps_unresolved_as_old():
    """Zwykły przypadek (np. ANTM/ELV): nierozwiązany ticker kończy
    się, rozwiązany zaczyna — nierozwiązany jest stary."""
    cand = AdjacencyCandidate(
        unresolved_ticker="ANTM", boundary_date="2022-06-28",
        direction="UNRESOLVED_ENDS_RESOLVED_STARTS", adjacent_ticker="ELV", adjacent_cik="1156039",
    )
    assert chronological_order("ANTM", cand) == ("ANTM", "ELV")


def test_chronological_order_resolved_ends_unresolved_starts_swaps_old_and_new():
    """Przypadek FI/FISV (realny błąd znaleziony przez właścicielkę,
    2026-10-01): dzisiejsza mapa SEC rozwiązuje `FISV` (chronologicznie
    STARSZY ticker), a `FI` (chronologicznie NOWSZY) jest `unresolved`.
    Kierunek strukturalny musi odwrócić etykiety względem tego, który
    ticker jest dziś `unresolved`."""
    cand = AdjacencyCandidate(
        unresolved_ticker="FI", boundary_date="2023-06-07",
        direction="RESOLVED_ENDS_UNRESOLVED_STARTS", adjacent_ticker="FISV", adjacent_cik="798354",
    )
    assert chronological_order("FI", cand) == ("FISV", "FI")


# ---------------------------------------------------------------------------
# former_name_corroborates_boundary
# ---------------------------------------------------------------------------


def test_former_name_corroborates_exact_date_match():
    former_names = [{"name": "ANTHEM INC", "from_date": "2001-01-02", "to_date": "2022-06-28"}]
    match = former_name_corroborates_boundary(former_names, "2022-06-28", tolerance_days=3)
    assert match is not None
    assert match.name == "ANTHEM INC"
    assert match.day_diff == 0


def test_former_name_within_tolerance_but_not_exact():
    former_names = [{"name": "ANTHEM INC", "from_date": "2001-01-02", "to_date": "2022-06-26"}]
    match = former_name_corroborates_boundary(former_names, "2022-06-28", tolerance_days=3)
    assert match is not None
    assert match.day_diff == -2


def test_former_name_outside_tolerance_returns_none():
    former_names = [{"name": "ANTHEM INC", "from_date": "2001-01-02", "to_date": "2022-06-01"}]
    match = former_name_corroborates_boundary(former_names, "2022-06-28", tolerance_days=3)
    assert match is None


def test_former_name_unparseable_to_date_is_skipped_not_fabricated():
    former_names = [{"name": "WEIRD CO", "from_date": None, "to_date": "not-a-date"}]
    match = former_name_corroborates_boundary(former_names, "2022-06-28", tolerance_days=3)
    assert match is None


def test_former_name_missing_to_date_is_skipped():
    former_names = [{"name": "WEIRD CO", "from_date": "2001-01-01", "to_date": None}]
    match = former_name_corroborates_boundary(former_names, "2022-06-28", tolerance_days=3)
    assert match is None


def test_former_name_picks_closest_among_multiple_candidates():
    former_names = [
        {"name": "FAR", "from_date": None, "to_date": "2022-06-25"},
        {"name": "CLOSE", "from_date": None, "to_date": "2022-06-27"},
    ]
    match = former_name_corroborates_boundary(former_names, "2022-06-28", tolerance_days=5)
    assert match.name == "CLOSE"
    assert match.day_diff == -1


def test_former_name_empty_list_returns_none():
    assert former_name_corroborates_boundary([], "2022-06-28", tolerance_days=3) is None

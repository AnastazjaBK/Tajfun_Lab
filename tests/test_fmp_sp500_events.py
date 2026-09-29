"""Testy parsowania/rekonstrukcji logu zdarzeń FMP (Faza 5.2, krok 1/3)
— wartości referencyjne policzone ręcznie na małych przykładach, w
tym scenariusz naśladujący realne znalezisko z v1.31 (rozjazd date
vs dateAdded o 1 dzień dla starych wierszy)."""

from __future__ import annotations

from buffett_scanner.fmp_sp500_events import (
    ChangeEvent,
    compare_change_events,
    find_date_added_mismatches,
    fmp_change_events,
    parse_fmp_events,
    reconstruct_membership_backward,
)

# ---------------------------------------------------------------------------
# parse_fmp_events
# ---------------------------------------------------------------------------


def test_parse_fmp_events_parses_and_sorts_by_date():
    raw = [
        {"date": "2020-03-01", "dateAdded": "March 1, 2020", "symbol": "BBB",
         "addedSecurity": "BBB Inc", "removedTicker": "AAA", "removedSecurity": "AAA Inc", "reason": "X"},
        {"date": "2012-01-15", "dateAdded": "January 15, 2012", "symbol": "CCC",
         "addedSecurity": "CCC Inc", "removedTicker": "", "removedSecurity": "", "reason": ""},
    ]
    events = parse_fmp_events(raw)
    assert len(events) == 2
    assert events[0].date == "2012-01-15"
    assert events[0].added_symbol == "CCC"
    assert events[0].removed_ticker is None  # pusty string -> None
    assert events[1].removed_ticker == "AAA"


def test_parse_fmp_events_skips_rows_missing_date_or_symbol():
    raw = [
        {"date": None, "symbol": "AAA"},
        {"date": "2020-01-01", "symbol": ""},
        {"date": "2020-01-01", "symbol": "BBB"},
    ]
    events = parse_fmp_events(raw)
    assert len(events) == 1
    assert events[0].added_symbol == "BBB"


# ---------------------------------------------------------------------------
# find_date_added_mismatches
# ---------------------------------------------------------------------------


def _event(date: str, date_added_raw: str) -> "object":
    from buffett_scanner.fmp_sp500_events import FmpConstituentEvent
    return FmpConstituentEvent(
        date=date, date_added_raw=date_added_raw, added_symbol="X",
        added_security="X Inc", removed_ticker=None, removed_security=None, reason="",
    )


def test_find_date_added_mismatches_detects_real_v131_scenario():
    """Dokładnie odtwarza realne znalezisko: date='1957-03-03',
    dateAdded='March 04, 1957' -> rozjazd o 1 dzień."""
    events = [_event("1957-03-03", "March 04, 1957")]
    mismatches = find_date_added_mismatches(events)
    assert len(mismatches) == 1
    assert mismatches[0][1] == "1957-03-04"


def test_find_date_added_mismatches_no_mismatch_when_dates_agree():
    events = [_event("2026-09-21", "September 21, 2026")]
    assert find_date_added_mismatches(events) == []


def test_find_date_added_mismatches_flags_unparseable_date_added():
    events = [_event("2020-01-01", "not a date")]
    mismatches = find_date_added_mismatches(events)
    assert len(mismatches) == 1
    assert mismatches[0][1] == "NIEPARSOWALNE"


# ---------------------------------------------------------------------------
# reconstruct_membership_backward — rdzeń logiki, wartości policzone ręcznie
# ---------------------------------------------------------------------------


def _raw_event(date, symbol, removed_ticker=""):
    return {"date": date, "dateAdded": date, "symbol": symbol,
            "addedSecurity": "", "removedTicker": removed_ticker, "removedSecurity": "", "reason": ""}


def test_reconstruct_membership_backward_undoes_events_after_as_of_date():
    """Dzisiejszy skład: {A, D}. Historia zdarzeń (rosnąco):
    2012-03-01: B wchodzi zamiast C (C usunięty)
    2015-06-01: D wchodzi zamiast B (B usunięty)
    Odtworzenie na 2013-01-01 (między zdarzeniami) musi cofnąć TYLKO
    zdarzenie z 2015-06-01 (bo jest PO badanej dacie), zostawiając
    zdarzenie z 2012-03-01 nietknięte (już się wydarzyło)."""
    raw = [
        {"date": "2012-03-01", "dateAdded": "2012-03-01", "symbol": "B",
         "addedSecurity": "", "removedTicker": "C", "removedSecurity": "", "reason": ""},
        {"date": "2015-06-01", "dateAdded": "2015-06-01", "symbol": "D",
         "addedSecurity": "", "removedTicker": "B", "removedSecurity": "", "reason": ""},
    ]
    events = parse_fmp_events(raw)
    current_members = {"A", "D"}

    result = reconstruct_membership_backward(events, current_members, "2013-01-01")
    # Cofamy zdarzenie z 2015-06-01: usuwamy D (dodany wtedy), przywracamy B.
    # Zdarzenie z 2012-03-01 NIE jest cofane (already happened by 2013-01-01).
    assert result == {"A", "B"}


def test_reconstruct_membership_backward_before_any_events_undoes_all():
    raw = [
        {"date": "2012-03-01", "dateAdded": "2012-03-01", "symbol": "B",
         "addedSecurity": "", "removedTicker": "C", "removedSecurity": "", "reason": ""},
    ]
    events = parse_fmp_events(raw)
    result = reconstruct_membership_backward(events, {"A", "B"}, "2011-01-01")
    assert result == {"A", "C"}


def test_reconstruct_membership_backward_today_returns_current_members_unchanged():
    raw = [
        {"date": "2012-03-01", "dateAdded": "2012-03-01", "symbol": "B",
         "addedSecurity": "", "removedTicker": "C", "removedSecurity": "", "reason": ""},
    ]
    events = parse_fmp_events(raw)
    result = reconstruct_membership_backward(events, {"A", "B"}, "2026-01-01")
    assert result == {"A", "B"}


# ---------------------------------------------------------------------------
# fmp_change_events / compare_change_events
# ---------------------------------------------------------------------------


def test_fmp_change_events_filters_by_cutoff_and_emits_add_and_remove():
    raw = [
        {"date": "2011-01-01", "dateAdded": "2011-01-01", "symbol": "OLD",
         "addedSecurity": "", "removedTicker": "", "removedSecurity": "", "reason": ""},
        {"date": "2012-03-01", "dateAdded": "2012-03-01", "symbol": "B",
         "addedSecurity": "", "removedTicker": "C", "removedSecurity": "", "reason": ""},
    ]
    events = parse_fmp_events(raw)
    result = fmp_change_events(events, cutoff_date="2012-01-01")
    assert result == {
        ChangeEvent(date="2012-03-01", ticker="B", action="ADD"),
        ChangeEvent(date="2012-03-01", ticker="C", action="REMOVE"),
    }


def test_compare_change_events_computes_common_and_differences():
    a = frozenset({
        ChangeEvent(date="2012-03-01", ticker="B", action="ADD"),
        ChangeEvent(date="2012-03-01", ticker="C", action="REMOVE"),
    })
    b = frozenset({
        ChangeEvent(date="2012-03-01", ticker="B", action="ADD"),
        ChangeEvent(date="2013-01-01", ticker="Z", action="ADD"),
    })
    cmp = compare_change_events(a, b)
    assert cmp.common == {ChangeEvent(date="2012-03-01", ticker="B", action="ADD")}
    assert cmp.only_a == {ChangeEvent(date="2012-03-01", ticker="C", action="REMOVE")}
    assert cmp.only_b == {ChangeEvent(date="2013-01-01", ticker="Z", action="ADD")}

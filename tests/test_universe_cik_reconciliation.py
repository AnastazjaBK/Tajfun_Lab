"""Testy pogodzenia fja05680 (kanoniczne) vs FMP (walidator) na
poziomie CIK z tolerancją dat (Faza 5.2, domknięcie OPEN BLOCKER 2,
części 2-3, v1.34). Wartości referencyjne policzone ręcznie."""

from __future__ import annotations

from buffett_scanner.fmp_sp500_events import ChangeEvent
import pytest

from buffett_scanner.universe_cik_reconciliation import (
    CikEvent,
    MatchedPair,
    build_reconciliation_report,
    change_events_to_cik_events,
    match_cik_events_with_tolerance,
    pick_plateau_tolerance,
    tolerance_impact_curve,
)

# ---------------------------------------------------------------------------
# change_events_to_cik_events
# ---------------------------------------------------------------------------


def test_change_events_to_cik_events_resolves_and_drops_unresolved():
    ticker_events = frozenset(
        {
            ChangeEvent(date="2012-01-05", ticker="AAA", action="ADD"),
            ChangeEvent(date="2012-02-01", ticker="BBB", action="REMOVE"),
        }
    )
    resolved = {"AAA": "0001"}
    result = change_events_to_cik_events(ticker_events, resolved)
    assert result.events == frozenset({CikEvent(date="2012-01-05", cik="0001", action="ADD")})
    assert result.dropped_unresolved_tickers == ("BBB",)


def test_change_events_to_cik_events_never_fabricates_cik_for_unresolved_ticker():
    ticker_events = frozenset({ChangeEvent(date="2012-01-05", ticker="ZZZ", action="ADD")})
    result = change_events_to_cik_events(ticker_events, {})
    assert result.events == frozenset()
    assert result.dropped_unresolved_tickers == ("ZZZ",)


# ---------------------------------------------------------------------------
# match_cik_events_with_tolerance — rdzeń logiki, wartości ręcznie policzone
# ---------------------------------------------------------------------------


def test_match_picks_closest_validator_candidate_within_tolerance():
    """Kanoniczne 2012-01-05; walidator ma 2012-01-04 (diff=-1) i
    2012-01-07 (diff=+2) — bliższy jest 01-04, więc to on jest
    dopasowany, a 01-07 zostaje bez pary."""
    canonical = frozenset({CikEvent(date="2012-01-05", cik="X", action="ADD")})
    validator = frozenset(
        {
            CikEvent(date="2012-01-07", cik="X", action="ADD"),
            CikEvent(date="2012-01-04", cik="X", action="ADD"),
        }
    )
    result = match_cik_events_with_tolerance(canonical, validator, tolerance_days=3)
    assert result.matched == (
        MatchedPair(
            canonical=CikEvent(date="2012-01-05", cik="X", action="ADD"),
            validator=CikEvent(date="2012-01-04", cik="X", action="ADD"),
            day_diff=-1,
        ),
    )
    assert result.only_canonical == ()
    assert result.only_validator == (CikEvent(date="2012-01-07", cik="X", action="ADD"),)


def test_match_tie_break_prefers_earlier_validator_date():
    """Dwaj kandydaci równoodlegli (2 dni w obie strony) — remis
    rozstrzyga wcześniejsza data walidatora (01-03, nie 01-07)."""
    canonical = frozenset({CikEvent(date="2012-01-05", cik="Y", action="REMOVE")})
    validator = frozenset(
        {
            CikEvent(date="2012-01-03", cik="Y", action="REMOVE"),
            CikEvent(date="2012-01-07", cik="Y", action="REMOVE"),
        }
    )
    result = match_cik_events_with_tolerance(canonical, validator, tolerance_days=2)
    assert result.matched[0].validator == CikEvent(date="2012-01-03", cik="Y", action="REMOVE")
    assert result.matched[0].day_diff == -2
    assert result.only_validator == (CikEvent(date="2012-01-07", cik="Y", action="REMOVE"),)


def test_match_outside_tolerance_is_not_matched():
    canonical = frozenset({CikEvent(date="2012-01-05", cik="Z", action="ADD")})
    validator = frozenset({CikEvent(date="2012-01-10", cik="Z", action="ADD")})
    result = match_cik_events_with_tolerance(canonical, validator, tolerance_days=1)
    assert result.matched == ()
    assert result.only_canonical == (CikEvent(date="2012-01-05", cik="Z", action="ADD"),)
    assert result.only_validator == (CikEvent(date="2012-01-10", cik="Z", action="ADD"),)


def test_match_does_not_cross_cik_or_action_buckets():
    """Ten sam CIK, inna akcja, i inny CIK z tą samą akcją i datą —
    żadne z nich nie może dopasować się do zdarzenia z innego koszyka
    (cik, action), niezależnie od bliskości daty."""
    canonical = frozenset({CikEvent(date="2012-01-05", cik="A", action="ADD")})
    validator = frozenset(
        {
            CikEvent(date="2012-01-05", cik="A", action="REMOVE"),
            CikEvent(date="2012-01-05", cik="B", action="ADD"),
        }
    )
    result = match_cik_events_with_tolerance(canonical, validator, tolerance_days=5)
    assert result.matched == ()
    assert result.only_canonical == (CikEvent(date="2012-01-05", cik="A", action="ADD"),)
    assert result.only_validator == (
        CikEvent(date="2012-01-05", cik="A", action="REMOVE"),
        CikEvent(date="2012-01-05", cik="B", action="ADD"),
    )


def test_match_exact_date_match_has_zero_day_diff():
    canonical = frozenset({CikEvent(date="2012-01-05", cik="X", action="ADD")})
    validator = frozenset({CikEvent(date="2012-01-05", cik="X", action="ADD")})
    result = match_cik_events_with_tolerance(canonical, validator, tolerance_days=0)
    assert result.matched[0].day_diff == 0


# ---------------------------------------------------------------------------
# tolerance_impact_curve
# ---------------------------------------------------------------------------


def test_tolerance_impact_curve_shows_match_appearing_once_tolerance_covers_gap():
    canonical = frozenset({CikEvent(date="2012-01-05", cik="X", action="ADD")})
    validator = frozenset({CikEvent(date="2012-01-07", cik="X", action="ADD")})  # diff = 2 dni
    curve = tolerance_impact_curve(canonical, validator, tolerance_range_days=range(0, 4))
    assert curve == [
        {"tolerance_days": 0, "matched_count": 0, "only_canonical_count": 1, "only_validator_count": 1},
        {"tolerance_days": 1, "matched_count": 0, "only_canonical_count": 1, "only_validator_count": 1},
        {"tolerance_days": 2, "matched_count": 1, "only_canonical_count": 0, "only_validator_count": 0},
        {"tolerance_days": 3, "matched_count": 1, "only_canonical_count": 0, "only_validator_count": 0},
    ]


# ---------------------------------------------------------------------------
# pick_plateau_tolerance
# ---------------------------------------------------------------------------


def test_pick_plateau_tolerance_returns_first_point_reaching_final_count():
    curve = [
        {"tolerance_days": 0, "matched_count": 0, "only_canonical_count": 1, "only_validator_count": 1},
        {"tolerance_days": 1, "matched_count": 0, "only_canonical_count": 1, "only_validator_count": 1},
        {"tolerance_days": 2, "matched_count": 1, "only_canonical_count": 0, "only_validator_count": 0},
        {"tolerance_days": 3, "matched_count": 1, "only_canonical_count": 0, "only_validator_count": 0},
    ]
    assert pick_plateau_tolerance(curve) == 2


def test_pick_plateau_tolerance_still_rising_returns_last_tested_point():
    curve = [
        {"tolerance_days": 0, "matched_count": 0, "only_canonical_count": 2, "only_validator_count": 2},
        {"tolerance_days": 1, "matched_count": 1, "only_canonical_count": 1, "only_validator_count": 1},
    ]
    assert pick_plateau_tolerance(curve) == 1


def test_pick_plateau_tolerance_flat_from_start_returns_zero():
    curve = [
        {"tolerance_days": 0, "matched_count": 5, "only_canonical_count": 0, "only_validator_count": 0},
        {"tolerance_days": 1, "matched_count": 5, "only_canonical_count": 0, "only_validator_count": 0},
    ]
    assert pick_plateau_tolerance(curve) == 0


def test_pick_plateau_tolerance_raises_on_empty_curve():
    with pytest.raises(ValueError):
        pick_plateau_tolerance([])


# ---------------------------------------------------------------------------
# build_reconciliation_report
# ---------------------------------------------------------------------------


def test_build_reconciliation_report_composes_resolution_and_matching():
    canonical_ticker_events = frozenset({ChangeEvent(date="2012-01-05", ticker="AAPL", action="ADD")})
    validator_ticker_events = frozenset(
        {
            ChangeEvent(date="2012-01-06", ticker="AAPL", action="ADD"),
            ChangeEvent(date="2012-01-05", ticker="UNKNOWNTICK", action="ADD"),
        }
    )
    canonical_resolved = {"AAPL": "0000320193"}
    validator_resolved = {"AAPL": "0000320193"}  # UNKNOWNTICK celowo brak -> dropped

    report = build_reconciliation_report(
        canonical_ticker_events, validator_ticker_events,
        canonical_resolved, validator_resolved, tolerance_days=2,
    )
    assert report.tolerance_days == 2
    assert report.matched_count == 1
    assert report.only_canonical == ()
    assert report.only_validator == ()
    assert report.canonical_dropped_unresolved_tickers == ()
    assert report.validator_dropped_unresolved_tickers == ("UNKNOWNTICK",)


def test_build_reconciliation_report_never_produces_membership_only_diagnostics():
    """Kontrola architektoniczna: `ReconciliationReport` nie ma ŻADNEGO
    pola reprezentującego 'ostateczny' skład — tylko diagnostykę.
    fja05680 pozostaje jedynym źródłem membership poza tym modułem."""
    canonical_ticker_events = frozenset({ChangeEvent(date="2012-01-05", ticker="AAPL", action="ADD")})
    validator_ticker_events = frozenset()
    report = build_reconciliation_report(
        canonical_ticker_events, validator_ticker_events, {"AAPL": "1"}, {}, tolerance_days=1,
    )
    field_names = set(report.__dataclass_fields__.keys())
    assert field_names == {
        "tolerance_days", "matched_count", "only_canonical", "only_validator",
        "canonical_dropped_unresolved_tickers", "validator_dropped_unresolved_tickers",
    }

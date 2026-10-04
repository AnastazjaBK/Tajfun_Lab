"""Testy agregacji coverage dla pełnego baseline walk-forward (Faza
5.3c, Decyzja właścicielki 2026-10-04) — wartości referencyjne liczone
ręcznie."""

from __future__ import annotations

from buffett_scanner.walk_forward_coverage import CoverageSnapshot, aggregate_coverage


def _snap(decision_date, *, pit=100, price=90, fund=85, scanned=80, cand=5) -> CoverageSnapshot:
    return CoverageSnapshot(
        decision_date=decision_date,
        pit_universe_count=pit,
        sufficient_price_count=price,
        sufficient_fundamentals_count=fund,
        scanned_count=scanned,
        excluded_missing_price_count=pit - price,
        excluded_missing_fundamentals_count=pit - fund,
        stage_no_decline_signal=scanned - cand - 2,
        stage_excluded_by_prefilter=1,
        stage_hard_gate_failed=1,
        stage_candidate=cand,
    )


def test_coverage_pct_basic():
    s = _snap("2020-01-01", pit=100, scanned=80)
    assert s.coverage_pct == 80.0


def test_coverage_pct_none_when_pit_universe_empty():
    s = _snap("2020-01-01", pit=0, price=0, fund=0, scanned=0, cand=0)
    assert s.coverage_pct is None


def test_aggregate_coverage_empty_list_never_raises():
    agg = aggregate_coverage([])
    assert agg.n_decision_dates == 0
    assert agg.overall_coverage_pct is None
    assert agg.coverage_pct_median is None
    assert agg.worst_decision_dates == ()


def test_aggregate_coverage_overall_pct_weighted_by_observations():
    """Overall coverage to suma scanned / suma universe, NIE średnia
    procentów per-data (ważona obserwacjami, nie datami) -- celowa
    różnica względem median/percentyli (te są PO procentach)."""
    snapshots = [
        _snap("2012-01-01", pit=10, scanned=10),   # 100%
        _snap("2020-01-01", pit=1000, scanned=500),  # 50%
    ]
    agg = aggregate_coverage(snapshots)
    assert agg.total_pit_universe_observations == 1010
    assert agg.total_scanned_observations == 510
    assert agg.overall_coverage_pct == 510 / 1010 * 100.0


def test_aggregate_coverage_median_and_minmax():
    snapshots = [
        _snap("2012-01-01", pit=100, scanned=40),  # 40%
        _snap("2015-01-01", pit=100, scanned=60),  # 60%
        _snap("2020-01-01", pit=100, scanned=80),  # 80%
    ]
    agg = aggregate_coverage(snapshots)
    assert agg.coverage_pct_min == 40.0
    assert agg.coverage_pct_max == 80.0
    assert agg.coverage_pct_median == 60.0


def test_aggregate_coverage_worst_decision_dates_sorted_ascending():
    snapshots = [
        _snap("2012-01-01", pit=100, scanned=90),  # 90%
        _snap("2015-01-01", pit=100, scanned=30),  # 30%  <- najgorszy
        _snap("2020-01-01", pit=100, scanned=60),  # 60%
    ]
    agg = aggregate_coverage(snapshots, worst_n=2)
    assert agg.worst_decision_dates == (("2015-01-01", 30.0), ("2020-01-01", 60.0))


def test_aggregate_coverage_single_snapshot_no_crash_on_quantiles():
    """statistics.quantiles wymaga >= 2 punktów -- pojedynczy snapshot
    nie może rzucić wyjątku, percentyle spadają na tę jedną wartość."""
    agg = aggregate_coverage([_snap("2020-01-01", pit=100, scanned=70)])
    assert agg.coverage_pct_median == 70.0
    assert agg.coverage_pct_p10 == 70.0
    assert agg.coverage_pct_p90 == 70.0


def test_aggregate_coverage_handles_zero_universe_snapshot_mixed_in():
    """Jedna data z pustym PIT universe (coverage_pct=None) nie może
    zepsuć agregacji innych dat -- jest po prostu pomijana w
    percentylach, ale liczy się do total_pit_universe_observations (0)."""
    snapshots = [
        _snap("2012-01-01", pit=0, price=0, fund=0, scanned=0, cand=0),
        _snap("2020-01-01", pit=100, scanned=50),
    ]
    agg = aggregate_coverage(snapshots)
    assert agg.n_decision_dates == 2
    assert agg.coverage_pct_median == 50.0

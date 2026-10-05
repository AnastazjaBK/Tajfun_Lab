"""Testy czystych funkcji agregujących kalibrację (Faza 5.4, protokół
zatwierdzony przez właścicielkę 2026-10-05). Wartości referencyjne
policzone ręcznie, nie odtworzone z kodu pod testem."""

from __future__ import annotations

import pytest

from buffett_scanner.backtest_harness import BacktestCandidate, ForwardReturns
from buffett_scanner.benchmark import BenchmarkSnapshot
from buffett_scanner.calibration import (
    LOW_SAMPLE_THRESHOLD,
    OOS_FOLD_YEARS,
    derive_practical_tie_epsilon,
    evaluate_candidate_configuration,
    practical_tie,
)


def _candidate(decision_date: str, *, return_6m=None, return_1m=None, score_pct=None, cik="1") -> BacktestCandidate:
    return BacktestCandidate(
        run_id="test", decision_date=decision_date, cik=cik, ticker_as_of_date=cik,
        decision_price=10.0, decline_flags={"daily_decline": True},
        pit_fundamentals_period_end=None, pit_fundamentals_filed_date=None,
        financial_quality_breakdown={}, safety_score=5.0, valuation_score=None,
        dividend_score=2.0, full_score=None, deterministic_partial_score=7.0,
        deterministic_score_pct=score_pct, available_components=("safety", "dividend"),
        missing_components=("business_quality", "fear", "valuation"),
        hard_gate_passed=True, hard_gate_triggered=(), margin_of_safety_base_pct=None,
        config_version="test", scoring_version="test", universe_provenance="test",
        forward_returns=ForwardReturns(
            return_1m_pct=return_1m, return_3m_pct=None, return_6m_pct=return_6m, return_12m_pct=None,
        ),
    )


def _benchmark(decision_date: str, *, ew_6m=None, spy_6m=None, ew_1m=None, spy_1m=None) -> BenchmarkSnapshot:
    return BenchmarkSnapshot(
        decision_date=decision_date,
        ew_pit_universe_return_1m_pct=ew_1m, ew_pit_universe_return_3m_pct=None,
        ew_pit_universe_return_6m_pct=ew_6m, ew_pit_universe_return_12m_pct=None,
        ew_pit_universe_n_1m=1, ew_pit_universe_n_3m=0, ew_pit_universe_n_6m=1, ew_pit_universe_n_12m=0,
        spy_return_1m_pct=spy_1m, spy_return_3m_pct=None, spy_return_6m_pct=spy_6m, spy_return_12m_pct=None,
    )


def test_oos_fold_years_excludes_warmup_2012_2015():
    """2012-2015 to rozgrzewka, nigdy rok testowy -- obserwacja z tych
    lat NIE wchodzi do primary metric, nawet z kompletnymi danymi."""
    candidates = [_candidate("2013-06-01", return_6m=50.0)]
    benchmarks = [_benchmark("2013-06-01", ew_6m=0.0)]
    evaluation = evaluate_candidate_configuration(
        candidate_name="x", round=1, description="d", candidates=candidates, benchmark_snapshots=benchmarks,
    )
    assert evaluation.pooled_n == 0
    assert evaluation.pooled_median_excess_return_pct is None


def test_pooled_oos_combines_all_fold_years():
    candidates = [
        _candidate("2016-06-01", return_6m=10.0, cik="1"),
        _candidate("2017-06-01", return_6m=20.0, cik="2"),
    ]
    benchmarks = [_benchmark("2016-06-01", ew_6m=0.0), _benchmark("2017-06-01", ew_6m=0.0)]
    evaluation = evaluate_candidate_configuration(
        candidate_name="x", round=1, description="d", candidates=candidates, benchmark_snapshots=benchmarks,
    )
    assert evaluation.pooled_n == 2
    assert evaluation.pooled_median_excess_return_pct == 15.0  # mediana(10, 20)


def test_fold_metrics_reported_separately_per_year():
    candidates = [
        _candidate("2016-06-01", return_6m=10.0, cik="1"),
        _candidate("2016-07-01", return_6m=30.0, cik="2"),
        _candidate("2017-06-01", return_6m=5.0, cik="3"),
    ]
    benchmarks = [
        _benchmark("2016-06-01", ew_6m=0.0), _benchmark("2016-07-01", ew_6m=0.0), _benchmark("2017-06-01", ew_6m=0.0),
    ]
    evaluation = evaluate_candidate_configuration(
        candidate_name="x", round=1, description="d", candidates=candidates, benchmark_snapshots=benchmarks,
    )
    by_year = {m.fold_year: m for m in evaluation.fold_metrics}
    assert by_year[2016].n == 2
    assert by_year[2016].median_excess_return_pct == 20.0  # mediana(10,30)
    assert by_year[2017].n == 1
    assert by_year[2017].median_excess_return_pct == 5.0
    # lata bez danych nadal obecne w raporcie (0 obs., nie usunięte):
    assert by_year[2018].n == 0
    assert by_year[2018].median_excess_return_pct is None
    assert set(by_year) == set(OOS_FOLD_YEARS)


def test_low_sample_flag_does_not_remove_fold():
    candidates = [_candidate("2016-06-01", return_6m=10.0)]
    benchmarks = [_benchmark("2016-06-01", ew_6m=0.0)]
    evaluation = evaluate_candidate_configuration(
        candidate_name="x", round=1, description="d", candidates=candidates, benchmark_snapshots=benchmarks,
    )
    fold_2016 = next(m for m in evaluation.fold_metrics if m.fold_year == 2016)
    assert fold_2016.n == 1 < LOW_SAMPLE_THRESHOLD
    assert fold_2016.low_sample is True
    assert fold_2016.median_excess_return_pct == 10.0  # nie usunięte, tylko oflagowane
    assert evaluation.pooled_low_sample is True


def test_fold_stability_summary_min_max_median_of_medians():
    candidates = [
        _candidate("2016-06-01", return_6m=-10.0, cik="1"),
        _candidate("2017-06-01", return_6m=10.0, cik="2"),
        _candidate("2018-06-01", return_6m=30.0, cik="3"),
    ]
    benchmarks = [
        _benchmark("2016-06-01", ew_6m=0.0), _benchmark("2017-06-01", ew_6m=0.0), _benchmark("2018-06-01", ew_6m=0.0),
    ]
    evaluation = evaluate_candidate_configuration(
        candidate_name="x", round=1, description="d", candidates=candidates, benchmark_snapshots=benchmarks,
    )
    assert evaluation.n_folds_with_data == 3
    assert evaluation.min_fold_median_pct == -10.0
    assert evaluation.max_fold_median_pct == 30.0
    assert evaluation.median_of_fold_medians_pct == 10.0
    assert evaluation.n_positive_folds == 2  # 2017 i 2018, nie 2016


def test_secondary_metrics_never_used_for_primary_but_computed():
    candidates = [
        _candidate("2016-06-01", return_6m=10.0, return_1m=5.0, score_pct=80.0, cik="1"),
        _candidate("2016-07-01", return_6m=-5.0, return_1m=-2.0, score_pct=20.0, cik="2"),
        _candidate("2016-08-01", return_6m=30.0, return_1m=10.0, score_pct=90.0, cik="3"),
    ]
    benchmarks = [
        _benchmark("2016-06-01", ew_6m=0.0, spy_6m=0.0, ew_1m=0.0, spy_1m=0.0),
        _benchmark("2016-07-01", ew_6m=0.0, spy_6m=0.0, ew_1m=0.0, spy_1m=0.0),
        _benchmark("2016-08-01", ew_6m=0.0, spy_6m=0.0, ew_1m=0.0, spy_1m=0.0),
    ]
    evaluation = evaluate_candidate_configuration(
        candidate_name="x", round=1, description="d", candidates=candidates, benchmark_snapshots=benchmarks,
    )
    sec_6m = next(s for s in evaluation.secondary if s.horizon_months == 6)
    assert sec_6m.hit_rate_vs_ew_pct == pytest.approx(200 / 3)  # 2 z 3 mają excess > 0
    assert sec_6m.hit_rate_vs_spy_pct == pytest.approx(200 / 3)
    assert sec_6m.median_excess_vs_ew_pct == 10.0  # mediana(10, -5, 30)
    # ranking score (20<80<90) == ranking return (-5<10<30) -> korelacja dodatnia pełna
    assert sec_6m.spearman_score_vs_return == pytest.approx(1.0)


def test_candidates_missing_forward_return_or_benchmark_are_excluded_not_zero():
    candidates = [
        _candidate("2016-06-01", return_6m=None, cik="1"),  # brak forward return
        _candidate("2016-07-01", return_6m=10.0, cik="2"),  # OK
    ]
    benchmarks = [_benchmark("2016-06-01", ew_6m=0.0), _benchmark("2016-07-01", ew_6m=None)]  # drugi brak benchmarku
    evaluation = evaluate_candidate_configuration(
        candidate_name="x", round=1, description="d", candidates=candidates, benchmark_snapshots=benchmarks,
    )
    assert evaluation.pooled_n == 0  # oba wykluczone -- żaden nie fabrykuje 0.0


def test_derive_practical_tie_epsilon_is_fold_median_population_stdev():
    candidates = [
        _candidate("2016-06-01", return_6m=0.0, cik="1"),
        _candidate("2017-06-01", return_6m=10.0, cik="2"),
    ]
    benchmarks = [_benchmark("2016-06-01", ew_6m=0.0), _benchmark("2017-06-01", ew_6m=0.0)]
    baseline = evaluate_candidate_configuration(
        candidate_name="baseline", round=1, description="d", candidates=candidates, benchmark_snapshots=benchmarks,
    )
    epsilon = derive_practical_tie_epsilon(baseline)
    # pstdev([0.0, 10.0]) = 5.0
    assert epsilon == 5.0


def test_derive_practical_tie_epsilon_none_with_insufficient_folds():
    candidates = [_candidate("2016-06-01", return_6m=0.0)]
    benchmarks = [_benchmark("2016-06-01", ew_6m=0.0)]
    baseline = evaluate_candidate_configuration(
        candidate_name="baseline", round=1, description="d", candidates=candidates, benchmark_snapshots=benchmarks,
    )
    assert derive_practical_tie_epsilon(baseline) is None


def test_practical_tie_rule():
    assert practical_tie(10.0, 10.5, epsilon=1.0) is True
    assert practical_tie(10.0, 12.0, epsilon=1.0) is False
    assert practical_tie(None, 10.0, epsilon=1.0) is False

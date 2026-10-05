"""Infrastruktura kalibracji (Faza 5.4, protokół zatwierdzony przez
właścicielkę 2026-10-05, z poprawkami — patrz docs/
buffett-scanner-design-review.md, sekcja "Faza 5.4"). Czyste funkcje
agregujące metryki z już policzonych `BacktestCandidate`/
`BenchmarkSnapshot` — zero I/O, zero zmiany total_debt/scoring/
valuation logiki, zero nowej logiki PIT.

Kandydaci konfiguracji (Round 1/2/3) są callable'ami modyfikującymi
GŁĘBOKĄ kopię bazowego `AppConfig` — `config/config.yaml` NIGDY nie jest
modyfikowany na dysku, każdy kandydat jest w pełni odtwarzalny z kodu
(audytowalność, punkt 11 protokołu).

Expanding-window walk-forward (punkt 2 protokołu): operacjonalizowane
jako JEDEN pełny walk-forward na całym `CALIBRATION_WINDOW` per
kandydat (silnik już jest PIT-poprawny z konstrukcji — "okno
rozszerzające się" nie zmienia tego, co widzi silnik, tylko jak dzielimy
WYNIK na foldy raportowania). Lata 2012-2015 nigdy nie są rokiem
testowym żadnego foldu (`OOS_FOLD_YEARS` zaczyna się od 2016) — służą
wyłącznie jako historia/rozgrzewka, nigdy nie wchodzą do primary metric."""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Callable

from buffett_scanner.backtest_harness import BacktestCandidate
from buffett_scanner.benchmark import BenchmarkSnapshot
from buffett_scanner.config import AppConfig

CALIBRATION_WINDOW_START = "2012-01-01"
CALIBRATION_WINDOW_END = "2021-12-01"
HOLDOUT_WINDOW_START = "2022-01-01"
HOLDOUT_WINDOW_END = None  # do dziś, jak reszta backtestu

# Lata, które SĄ rokiem testowym (OOS) jakiegoś foldu expanding-window
# (2012-2015 to wyłącznie historia/rozgrzewka, nigdy OOS -- patrz
# docstring modułu).
OOS_FOLD_YEARS: tuple[int, ...] = (2016, 2017, 2018, 2019, 2020, 2021)

LOW_SAMPLE_THRESHOLD = 30
HORIZONS_MONTHS: tuple[int, ...] = (1, 3, 6, 12)
PRIMARY_HORIZON_MONTHS = 6


@dataclass(frozen=True)
class CandidateConfig:
    """Jeden kandydat konfiguracji do ewaluacji w danej rundzie.
    `apply` dostaje GŁĘBOKĄ kopię configu bazowego i zwraca zmodyfikowaną
    kopię -- nigdy nie mutuje configu bazowego w miejscu."""

    name: str
    round: int
    description: str
    apply: Callable[[AppConfig], AppConfig]


def _year(decision_date: str) -> int:
    return int(decision_date[:4])


def _spearman_rho(xs: list[float], ys: list[float]) -> float | None:
    """Korelacja rang Spearmana bez numpy/scipy (brak w requirements.txt).
    None przy <3 punktach albo zerowej wariancji (nigdy dzielenie przez 0)."""
    n = len(xs)
    if n < 3:
        return None

    def ranks(vals: list[float]) -> list[float]:
        order = sorted(range(len(vals)), key=lambda i: vals[i])
        r = [0.0] * len(vals)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and vals[order[j + 1]] == vals[order[i]]:
                j += 1
            avg_rank = (i + j) / 2.0 + 1.0
            for k in range(i, j + 1):
                r[order[k]] = avg_rank
            i = j + 1
        return r

    rx, ry = ranks(xs), ranks(ys)
    mean_rx, mean_ry = statistics.mean(rx), statistics.mean(ry)
    cov = sum((a - mean_rx) * (b - mean_ry) for a, b in zip(rx, ry))
    var_x = sum((a - mean_rx) ** 2 for a in rx)
    var_y = sum((b - mean_ry) ** 2 for b in ry)
    if var_x == 0 or var_y == 0:
        return None
    return cov / (var_x ** 0.5 * var_y ** 0.5)


def _excess_pairs(
    candidates: list[BacktestCandidate],
    benchmark_by_date: dict[str, BenchmarkSnapshot],
    horizon: int,
    *,
    oos_only: bool,
    vs: str,
) -> list[tuple[int, float]]:
    """(fold_year, excess_return_pct) dla kandydatów z dostępnym forward
    return i dostępnym benchmarkiem na danym horyzoncie. `vs="ew"` ->
    PRIMARY equal_weighted_pit_universe, `vs="spy"` -> SECONDARY SPY."""
    horizon_attr = f"return_{horizon}m_pct"
    bench_attr = f"ew_pit_universe_return_{horizon}m_pct" if vs == "ew" else f"spy_return_{horizon}m_pct"
    out: list[tuple[int, float]] = []
    for c in candidates:
        year = _year(c.decision_date)
        if oos_only and year not in OOS_FOLD_YEARS:
            continue
        if c.forward_returns is None:
            continue
        cand_ret = getattr(c.forward_returns, horizon_attr)
        if cand_ret is None:
            continue
        bench = benchmark_by_date.get(c.decision_date)
        if bench is None:
            continue
        bench_ret = getattr(bench, bench_attr)
        if bench_ret is None:
            continue
        out.append((year, cand_ret - bench_ret))
    return out


@dataclass(frozen=True)
class FoldMetric:
    fold_year: int
    n: int
    low_sample: bool
    median_excess_return_pct: float | None  # PRIMARY_HORIZON_MONTHS, vs EW


@dataclass(frozen=True)
class SecondaryHorizonMetrics:
    horizon_months: int
    n_vs_ew: int
    n_vs_spy: int
    hit_rate_vs_ew_pct: float | None  # % kandydatów z excess_vs_ew > 0
    hit_rate_vs_spy_pct: float | None
    median_excess_vs_ew_pct: float | None
    median_excess_vs_spy_pct: float | None
    spearman_score_vs_return: float | None
    low_sample: bool


@dataclass(frozen=True)
class CalibrationEvaluation:
    candidate_name: str
    round: int
    description: str
    n_total_candidates: int
    # PRIMARY (punkt 4 protokołu): pooled OOS (A) + fold stability (B).
    pooled_n: int
    pooled_median_excess_return_pct: float | None
    pooled_low_sample: bool
    fold_metrics: tuple[FoldMetric, ...]
    median_of_fold_medians_pct: float | None
    min_fold_median_pct: float | None
    max_fold_median_pct: float | None
    n_positive_folds: int
    n_folds_with_data: int
    # SECONDARY (nigdy nie decydują o wyborze konfiguracji) per horyzont.
    secondary: tuple[SecondaryHorizonMetrics, ...]


def evaluate_candidate_configuration(
    *,
    candidate_name: str,
    round: int,
    description: str,
    candidates: list[BacktestCandidate],
    benchmark_snapshots: list[BenchmarkSnapshot],
) -> CalibrationEvaluation:
    """Liczy PRIMARY (pooled OOS + fold stability, horyzont 6m vs EW) i
    SECONDARY (hit rate/excess vs SPY/Spearman/wszystkie horyzonty)
    metryki dla jednego kandydata konfiguracji, na obserwacjach z
    `OOS_FOLD_YEARS` (2016-2021) -- lata 2012-2015 wyłączone z metryk
    (rozgrzewka, nigdy OOS, patrz docstring modułu)."""
    benchmark_by_date = {b.decision_date: b for b in benchmark_snapshots}

    primary_pairs = _excess_pairs(candidates, benchmark_by_date, PRIMARY_HORIZON_MONTHS, oos_only=True, vs="ew")
    pooled_n = len(primary_pairs)
    pooled_values = [v for _, v in primary_pairs]
    pooled_median = statistics.median(pooled_values) if pooled_values else None

    fold_metrics: list[FoldMetric] = []
    fold_medians: list[float] = []
    for year in OOS_FOLD_YEARS:
        year_values = [v for y, v in primary_pairs if y == year]
        n = len(year_values)
        median = statistics.median(year_values) if year_values else None
        if median is not None:
            fold_medians.append(median)
        fold_metrics.append(
            FoldMetric(fold_year=year, n=n, low_sample=n < LOW_SAMPLE_THRESHOLD, median_excess_return_pct=median)
        )

    secondary: list[SecondaryHorizonMetrics] = []
    for horizon in HORIZONS_MONTHS:
        ew_pairs = _excess_pairs(candidates, benchmark_by_date, horizon, oos_only=True, vs="ew")
        spy_pairs = _excess_pairs(candidates, benchmark_by_date, horizon, oos_only=True, vs="spy")
        ew_values = [v for _, v in ew_pairs]
        spy_values = [v for _, v in spy_pairs]

        score_return_pairs = [
            (c.deterministic_score_pct, getattr(c.forward_returns, f"return_{horizon}m_pct"))
            for c in candidates
            if _year(c.decision_date) in OOS_FOLD_YEARS
            and c.deterministic_score_pct is not None
            and c.forward_returns is not None
            and getattr(c.forward_returns, f"return_{horizon}m_pct") is not None
        ]
        rho = (
            _spearman_rho([p[0] for p in score_return_pairs], [p[1] for p in score_return_pairs])
            if score_return_pairs
            else None
        )

        secondary.append(
            SecondaryHorizonMetrics(
                horizon_months=horizon,
                n_vs_ew=len(ew_values),
                n_vs_spy=len(spy_values),
                hit_rate_vs_ew_pct=(sum(1 for v in ew_values if v > 0) / len(ew_values) * 100.0) if ew_values else None,
                hit_rate_vs_spy_pct=(sum(1 for v in spy_values if v > 0) / len(spy_values) * 100.0) if spy_values else None,
                median_excess_vs_ew_pct=statistics.median(ew_values) if ew_values else None,
                median_excess_vs_spy_pct=statistics.median(spy_values) if spy_values else None,
                spearman_score_vs_return=rho,
                low_sample=len(ew_values) < LOW_SAMPLE_THRESHOLD,
            )
        )

    return CalibrationEvaluation(
        candidate_name=candidate_name,
        round=round,
        description=description,
        n_total_candidates=len(candidates),
        pooled_n=pooled_n,
        pooled_median_excess_return_pct=pooled_median,
        pooled_low_sample=pooled_n < LOW_SAMPLE_THRESHOLD,
        fold_metrics=tuple(fold_metrics),
        median_of_fold_medians_pct=statistics.median(fold_medians) if fold_medians else None,
        min_fold_median_pct=min(fold_medians) if fold_medians else None,
        max_fold_median_pct=max(fold_medians) if fold_medians else None,
        n_positive_folds=sum(1 for m in fold_medians if m > 0),
        n_folds_with_data=len(fold_medians),
        secondary=tuple(secondary),
    )


def derive_practical_tie_epsilon(baseline_evaluation: CalibrationEvaluation) -> float | None:
    """Epsilon "practical tie rule" (punkt 9.7 protokołu) -- population
    stdev fold-median-ów BASELINE (nieskalibrowanego configu) na tych
    samych 6 foldach OOS. Mierzy WŁASNY poziom szumu fold-to-fold
    systemu bez żadnej kalibracji -- zmierzony RAZ, PRZED pierwszym
    kandydatem Round 1, i zamrożony (nigdy nie przeliczany po zobaczeniu
    wyników kandydatów, bo to by uczyniło regułę zależną od wyników,
    które ma oceniać). None, jeśli baseline ma <2 foldy z danymi
    (niemożliwe policzyć stdev)."""
    fold_medians = [m.median_excess_return_pct for m in baseline_evaluation.fold_metrics if m.median_excess_return_pct is not None]
    if len(fold_medians) < 2:
        return None
    return statistics.pstdev(fold_medians)


def practical_tie(a: float | None, b: float | None, epsilon: float) -> bool:
    """True, jeśli różnica pooled-OOS primary metric między dwoma
    kandydatami jest mniejsza niż epsilon -- wtedy wygrywa PROSTSZA
    konfiguracja (decyzja poza tą funkcją, to tylko test remisu)."""
    if a is None or b is None:
        return False
    return abs(a - b) < epsilon

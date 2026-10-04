"""Coverage reporting dla pełnego baseline walk-forward (Faza 5.3c,
Decyzja właścicielki 2026-10-04): "Brak danych nie powoduje fabrykowania
kandydatów ani look-ahead bias, ale może powodować selection/coverage
bias, ponieważ missingness nie musi być losowe." Dlatego dla KAŻDEJ
decision_date mierzymy i raportujemy jawnie, ile spółek z PIT universe
w ogóle dało się przeskanować, nie tylko ile zostało kandydatami.

Zero I/O — czysta agregacja już policzonych per-data liczników
(`CoverageSnapshot`, budowanych w orkiestracji `cli.py` na podstawie
`classify_data_sufficiency`/`evaluate_candidate_at_date`)."""

from __future__ import annotations

import statistics
from dataclasses import dataclass


@dataclass(frozen=True)
class CoverageSnapshot:
    """Jeden wiersz coverage per decision_date — DOKŁADNIE siedem miar
    wymaganych przez właścicielkę (2026-10-04), plus rozbicie funnela,
    żeby ten sam wiersz starczył i do coverage, i do raportu funnela."""

    decision_date: str
    pit_universe_count: int
    sufficient_price_count: int
    sufficient_fundamentals_count: int
    scanned_count: int  # sufficient_price AND sufficient_fundamentals -> nakarmione do funnela
    excluded_missing_price_count: int
    excluded_missing_fundamentals_count: int
    # Rozbicie funnela WŚRÓD scanned_count (sumuje się do scanned_count).
    stage_no_decline_signal: int
    stage_excluded_by_prefilter: int
    stage_hard_gate_failed: int
    stage_candidate: int

    @property
    def coverage_pct(self) -> float | None:
        """`scanned_count / pit_universe_count * 100` — None tylko gdy
        PIT universe jest pusty (nie powinno się zdarzyć dla realnego
        indeksu, ale nigdy nie dzielimy przez zero)."""
        if self.pit_universe_count == 0:
            return None
        return self.scanned_count / self.pit_universe_count * 100.0


@dataclass(frozen=True)
class CoverageAggregate:
    """Agregat po WSZYSTKICH decision_date — min/mediana/percentyle
    `coverage_pct` w czasie, żeby było wiadomo, czy starsze lata są
    istotnie słabiej pokryte niż nowsze (Decyzja właścicielki)."""

    n_decision_dates: int
    total_pit_universe_observations: int  # suma pit_universe_count po wszystkich datach
    total_scanned_observations: int
    overall_coverage_pct: float | None  # total_scanned / total_pit_universe * 100
    coverage_pct_min: float | None
    coverage_pct_median: float | None
    coverage_pct_p10: float | None
    coverage_pct_p25: float | None
    coverage_pct_p75: float | None
    coverage_pct_p90: float | None
    coverage_pct_max: float | None
    worst_decision_dates: tuple[tuple[str, float], ...]  # (decision_date, coverage_pct), rosnąco po coverage_pct, max 10


def aggregate_coverage(snapshots: list[CoverageSnapshot], *, worst_n: int = 10) -> CoverageAggregate:
    """Agreguje coverage po całym baseline run. Puste `snapshots` ->
    wszystkie pola agregatu None/0, nigdy wyjątek, nigdy zgadywana
    wartość domyślna."""
    if not snapshots:
        return CoverageAggregate(
            n_decision_dates=0, total_pit_universe_observations=0, total_scanned_observations=0,
            overall_coverage_pct=None, coverage_pct_min=None, coverage_pct_median=None,
            coverage_pct_p10=None, coverage_pct_p25=None, coverage_pct_p75=None,
            coverage_pct_p90=None, coverage_pct_max=None, worst_decision_dates=(),
        )

    total_universe = sum(s.pit_universe_count for s in snapshots)
    total_scanned = sum(s.scanned_count for s in snapshots)
    overall_pct = (total_scanned / total_universe * 100.0) if total_universe > 0 else None

    pct_values = [s.coverage_pct for s in snapshots if s.coverage_pct is not None]
    if pct_values:
        sorted_pct = sorted(pct_values)
        median = statistics.median(sorted_pct)
        # statistics.quantiles wymaga >= 2 punktów danych dla n=100; dla
        # mniejszych prób spadamy na min/max zamiast zgadywać percentyl.
        if len(sorted_pct) >= 2:
            quantiles = statistics.quantiles(sorted_pct, n=100, method="inclusive")
            p10, p25, p75, p90 = quantiles[9], quantiles[24], quantiles[74], quantiles[89]
        else:
            p10 = p25 = p75 = p90 = sorted_pct[0]
        pct_min, pct_max = sorted_pct[0], sorted_pct[-1]
    else:
        median = p10 = p25 = p75 = p90 = pct_min = pct_max = None

    worst = tuple(
        (s.decision_date, s.coverage_pct)
        for s in sorted(
            (s for s in snapshots if s.coverage_pct is not None), key=lambda s: s.coverage_pct
        )[:worst_n]
    )

    return CoverageAggregate(
        n_decision_dates=len(snapshots),
        total_pit_universe_observations=total_universe,
        total_scanned_observations=total_scanned,
        overall_coverage_pct=overall_pct,
        coverage_pct_min=pct_min,
        coverage_pct_median=median,
        coverage_pct_p10=p10,
        coverage_pct_p25=p25,
        coverage_pct_p75=p75,
        coverage_pct_p90=p90,
        coverage_pct_max=pct_max,
        worst_decision_dates=worst,
    )

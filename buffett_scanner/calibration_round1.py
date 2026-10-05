"""ROUND 1 — SELECTION MECHANICS (Faza 5.4, protokół zatwierdzony przez
właścicielkę 2026-10-05). Kalibruje WYŁĄCZNIE `decline_scanner.
thresholds`/`prefilter`/`hard_gates` — wagi scoringu i mechanika
valuation pozostają default/zamrożone przez całą tę rundę (punkt 7
protokołu, `docs/buffett-scanner-design-review.md`). Cel: ustalić, czy
scanner potrafi sensownie zawęzić universe, PRZED jakąkolwiek zmianą wag.

Każdy kandydat jest czystą funkcją `AppConfig -> AppConfig` na GŁĘBOKIEJ
kopii configu bazowego — `config/config.yaml` nigdy nie jest
modyfikowany na dysku. `baseline` (bez zmian) służy JEDNOCZEŚNIE jako
punkt odniesienia tej rundy I jako pomiar szumu fold-to-fold do
`derive_practical_tie_epsilon` (musi być policzony PRZED porównaniem
pozostałych kandydatów)."""

from __future__ import annotations

from buffett_scanner.calibration import CandidateConfig
from buffett_scanner.config import (
    AppConfig,
    DeclineScannerThresholds,
    HardGatesConfig,
    PrefilterConfig,
    PrefilterRule,
)


def _baseline(config: AppConfig) -> AppConfig:
    return config.model_copy(deep=True)


def _stricter_decline(config: AppConfig) -> AppConfig:
    """Progi zaostrzone ~40% względem obecnych (daily -5→-7, week -8→-12,
    month -15→-20, quarter -20→-28, drawdown -25→-32, volume 2.0x→2.5x)
    — wymaga głębszego spadku, zanim `decline_flags` cokolwiek odpali
    (logika OR między 6 kryteriami w `evaluate_decline_flags` bez zmian)."""
    updated = config.model_copy(deep=True)
    updated.decline_scanner.thresholds = DeclineScannerThresholds(
        daily_pct=-7.0, week_pct=-12.0, month_pct=-20.0, quarter_pct=-28.0,
        drawdown_from_52w_high_pct=-32.0, relative_volume_multiple=2.5,
    )
    return updated


def _hard_gate_safety_floor(config: AppConfig) -> AppConfig:
    """`min_financial_safety=7.5` (połowa maksymalnych 15 pkt wagi
    `financial_safety`). `min_margin_of_safety_pct` pozostaje `None`
    celowo w Round 1 — włączenie go efektywnie wyklucza 81,5% kandydatów
    (ci bez policzonego valuation), czyli konfundowałoby "selection
    mechanics" całego GENERAL universe z osobną analizą complete-
    valuation subset (punkt 10 protokołu) — to pytanie należy do
    Round 2/3, nie Round 1."""
    updated = config.model_copy(deep=True)
    updated.hard_gates = HardGatesConfig(
        min_business_quality=None, min_financial_safety=7.5, min_margin_of_safety_pct=None,
    )
    return updated


def _prefilter_excludes(config: AppConfig) -> AppConfig:
    """Promuje DWIE z czterech istniejących FLAG rules do EXCLUDE:
    `net_debt_to_ebitda>4.0` i `current_ratio<1.0`. `fcf_ttm`/
    `revenue_yoy_growth_pct` pozostają FLAG-only — BLOCKER 5 (docs,
    sekcja BLOCKER 5) zakazuje automatycznego EXCLUDE na samym ujemnym
    FCF/malejących przychodach bez połączenia z innym krytycznym
    sygnałem; dźwignia+płynność to inna, bezpieczna kombinacja."""
    updated = config.model_copy(deep=True)
    updated.prefilter = PrefilterConfig(
        flag_rules=updated.prefilter.flag_rules,
        exclude_rules=[
            PrefilterRule(
                metric="net_debt_to_ebitda", condition="above", threshold=4.0,
                reason="Wysoka dźwignia (net debt / EBITDA > 4.0) — Round 1 candidate prefilter_excludes",
            ),
            PrefilterRule(
                metric="current_ratio", condition="below", threshold=1.0,
                reason="Niska płynność bieżąca (current ratio < 1.0) — Round 1 candidate prefilter_excludes",
            ),
        ],
        status="UNCALIBRATED",
    )
    return updated


def _combo_decline_and_prefilter(config: AppConfig) -> AppConfig:
    return _prefilter_excludes(_stricter_decline(config))


ROUND_1_CANDIDATES: tuple[CandidateConfig, ...] = (
    CandidateConfig(
        name="baseline", round=1,
        description="Obecny/default config bez zmian — referencja Round 1 i pomiar szumu fold-to-fold (epsilon).",
        apply=_baseline,
    ),
    CandidateConfig(
        name="stricter_decline", round=1,
        description="decline_scanner.thresholds zaostrzone ~40% (daily -7/week -12/month -20/quarter -28/drawdown -32/volume 2.5x).",
        apply=_stricter_decline,
    ),
    CandidateConfig(
        name="hard_gate_safety_floor", round=1,
        description="hard_gates.min_financial_safety=7.5 (połowa z 15 pkt); min_margin_of_safety_pct pozostaje None.",
        apply=_hard_gate_safety_floor,
    ),
    CandidateConfig(
        name="prefilter_excludes", round=1,
        description="net_debt_to_ebitda>4.0 i current_ratio<1.0 promowane z FLAG do EXCLUDE.",
        apply=_prefilter_excludes,
    ),
    CandidateConfig(
        name="combo_decline_and_prefilter", round=1,
        description="stricter_decline + prefilter_excludes razem.",
        apply=_combo_decline_and_prefilter,
    ),
)

"""ROUND 3 — VALUATION ROBUSTNESS / SENSITIVITY ANALYSIS (nie Round 3
"optimization" — zmiana celu, decyzja właścicielki 2026-10-05, patrz
docs/buffett-scanner-design-review.md, Faza 5.4d). Cel: sprawdzić, czy
zachowanie valuation i ranking kandydatów są STABILNE przy rozsądnych
zmianach `mos_pct_for_full_score`/growth caps — NIE znaleźć wartości
maksymalizujące forward returns. `default` jest punktem odniesienia w
środku siatki; siatka zamrożona PRZED analizą wyników, nie konstruowana
na podstawie forward returns.

Zmieniane WYŁĄCZNIE: `mos_pct_for_full_score`, `max_projected_growth_
rate_pct`/`min_projected_growth_rate_pct` (growth caps, traktowane
razem jako jeden wspólny "pas bezpieczeństwa" — węższy/domyślny/szerszy
— żeby uniknąć kombinatorycznej siatki 3x3 i zachować siatkę małą).
NIGDY nie zmieniane: `discount_rate_pct`/`terminal_growth_rate_pct`/
`historical_growth_multiplier` (założenia inwestora, permanentnie
zamrożone), `projection_years`, DCF structure, total_debt methodology,
PIT, scoring weights (Round 1/2 winner = default, bez zmian), selection
mechanics, hard gates, benchmarki.

Każdy kandydat zmienia WYŁĄCZNIE `config.valuation.dcf_owner_earnings`
(pełna rekonstrukcja tego pod-configu, tak jak w Round 1/2 dla innych
sekcji) na GŁĘBOKIEJ kopii configu bazowego."""

from __future__ import annotations

from buffett_scanner.calibration import CandidateConfig
from buffett_scanner.config import AppConfig, DcfOwnerEarningsConfig, ScenarioFloats

# Wartości domyślne (config/config.yaml) -- powtórzone tu jawnie jako
# stałe referencyjne, żeby każdy kandydat rekonstruował PEŁNY
# DcfOwnerEarningsConfig bez przypadkowego pominięcia pola.
_DEFAULT_DISCOUNT_RATE = ScenarioFloats(bear=11.0, base=9.0, bull=7.0)
_DEFAULT_TERMINAL_GROWTH = ScenarioFloats(bear=1.0, base=2.5, bull=3.5)
_DEFAULT_GROWTH_MULTIPLIER = ScenarioFloats(bear=0.5, base=1.0, bull=1.3)
_DEFAULT_PROJECTION_YEARS = 10
_DEFAULT_MAX_GROWTH_CAP = 20.0
_DEFAULT_MIN_GROWTH_CAP = -5.0
_DEFAULT_MOS_FOR_FULL_SCORE = 50.0


def _dcf_config(
    *, mos_pct_for_full_score: float, max_growth: float, min_growth: float,
) -> DcfOwnerEarningsConfig:
    return DcfOwnerEarningsConfig(
        projection_years=_DEFAULT_PROJECTION_YEARS,
        discount_rate_pct=_DEFAULT_DISCOUNT_RATE,
        terminal_growth_rate_pct=_DEFAULT_TERMINAL_GROWTH,
        historical_growth_multiplier=_DEFAULT_GROWTH_MULTIPLIER,
        max_projected_growth_rate_pct=max_growth,
        min_projected_growth_rate_pct=min_growth,
        mos_pct_for_full_score=mos_pct_for_full_score,
    )


def _apply(config: AppConfig, *, mos_pct_for_full_score: float, max_growth: float, min_growth: float) -> AppConfig:
    updated = config.model_copy(deep=True)
    updated.valuation.dcf_owner_earnings = _dcf_config(
        mos_pct_for_full_score=mos_pct_for_full_score, max_growth=max_growth, min_growth=min_growth,
    )
    return updated


def _default(config: AppConfig) -> AppConfig:
    return _apply(
        config, mos_pct_for_full_score=_DEFAULT_MOS_FOR_FULL_SCORE,
        max_growth=_DEFAULT_MAX_GROWTH_CAP, min_growth=_DEFAULT_MIN_GROWTH_CAP,
    )


def _mos_low(config: AppConfig) -> AppConfig:
    """mos_pct_for_full_score=35 (domyślne 50 minus 15pp) -- łatwiej
    osiągnąć pełny score (niższy wymagany margines bezpieczeństwa)."""
    return _apply(
        config, mos_pct_for_full_score=35.0,
        max_growth=_DEFAULT_MAX_GROWTH_CAP, min_growth=_DEFAULT_MIN_GROWTH_CAP,
    )


def _mos_high(config: AppConfig) -> AppConfig:
    """mos_pct_for_full_score=65 (domyślne 50 plus 15pp) -- trudniej
    osiągnąć pełny score (wyższy wymagany margines bezpieczeństwa)."""
    return _apply(
        config, mos_pct_for_full_score=65.0,
        max_growth=_DEFAULT_MAX_GROWTH_CAP, min_growth=_DEFAULT_MIN_GROWTH_CAP,
    )


def _caps_narrow(config: AppConfig) -> AppConfig:
    """Węższy pas bezpieczeństwa projekcji wzrostu: max 20->15,
    min -5->-3 (ciaśniejsze ograniczenie ekstremalnej historycznej CAGR)."""
    return _apply(
        config, mos_pct_for_full_score=_DEFAULT_MOS_FOR_FULL_SCORE,
        max_growth=15.0, min_growth=-3.0,
    )


def _caps_wide(config: AppConfig) -> AppConfig:
    """Szerszy pas bezpieczeństwa projekcji wzrostu: max 20->25,
    min -5->-7 (luźniejsze ograniczenie ekstremalnej historycznej CAGR)."""
    return _apply(
        config, mos_pct_for_full_score=_DEFAULT_MOS_FOR_FULL_SCORE,
        max_growth=25.0, min_growth=-7.0,
    )


ROUND_3_CANDIDATES: tuple[CandidateConfig, ...] = (
    CandidateConfig(
        name="3_default", round=3,
        description="mos_pct_for_full_score=50/growth caps=20/-5 (obecna/domyślna) -- punkt odniesienia w środku siatki.",
        apply=_default,
    ),
    CandidateConfig(
        name="3_mos_low", round=3,
        description="mos_pct_for_full_score=35 (domyślne-15pp), growth caps bez zmian.",
        apply=_mos_low,
    ),
    CandidateConfig(
        name="3_mos_high", round=3,
        description="mos_pct_for_full_score=65 (domyślne+15pp), growth caps bez zmian.",
        apply=_mos_high,
    ),
    CandidateConfig(
        name="3_caps_narrow", round=3,
        description="growth caps zwężone do 15/-3 (z 20/-5), mos_pct_for_full_score bez zmian.",
        apply=_caps_narrow,
    ),
    CandidateConfig(
        name="3_caps_wide", round=3,
        description="growth caps rozszerzone do 25/-7 (z 20/-5), mos_pct_for_full_score bez zmian.",
        apply=_caps_wide,
    ),
)

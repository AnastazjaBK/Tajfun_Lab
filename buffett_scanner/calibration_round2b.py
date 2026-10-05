"""ROUND 2B — VALUATION WEIGHT (Faza 5.4b, korekta metodologii
zatwierdzona przez właścicielkę 2026-10-05). Osobny eksperyment od
Round 2A — kalibruje WYŁĄCZNIE `valuation`, wyłącznie na
COMPLETE-VALUATION SUBSET (`margin_of_safety_base_pct is not None`,
identyczny zbiór company-date observations dla każdego wariantu wag w
tej podrundzie z konstrukcji — dostępność wyceny jest własnością
danych, nie wagi, zweryfikowane empirycznie przed Round 2A/2B).

`financial_safety`=15/`dividend_shareholder_return`=10/
`fear_opportunity`=10 przypięte do wartości domyślnych przez CAŁĄ tę
podrundę — żeby zmiana wagi valuation nie mieszała się nierozłącznie
ze zmianą znaczenia safety/dividend (wymóg właścicielki). Punkty
oddawane/pobierane WYŁĄCZNIE z `business_quality` — ten komponent jest
inercyjny w trybie deterministycznym/backtest (`business_quality`/
`fear` są zawsze `None` bez LLM, patrz `backtest_harness.py` docstring
modułu — nie wchodzą do `deterministic_score_pct` ani jego mianownika),
więc przesunięcie budżetu tam i z powrotem nie zmienia rankingu w tej
rundzie, tylko zachowuje inwariant `ScoringWeights` (suma=100, wymóg
pydantic walidatora).

PRIMARY metric: Spearman(`deterministic_score_pct`, forward return 6m)
na COMPLETE-VALUATION SUBSET. `2b_default` (waga domyślna=20) służy
JEDNOCZEŚNIE jako punkt odniesienia I jako pomiar szumu fold-to-fold do
`derive_practical_tie_epsilon_spearman` (epsilon_2B, osobny od
epsilon_2A — inna populacja, inny poziom szumu)."""

from __future__ import annotations

from buffett_scanner.calibration import CandidateConfig
from buffett_scanner.config import AppConfig, ScoringWeights


def _weights(valuation: float, business_quality: float) -> ScoringWeights:
    return ScoringWeights(
        business_quality=business_quality,
        financial_safety=15.0,
        valuation=valuation,
        fear_opportunity=10.0,
        dividend_shareholder_return=10.0,
    )


def _valuation_0(config: AppConfig) -> AppConfig:
    """CONTROL — valuation całkowicie wyłączone z composite score
    (waga=0, punkty przesunięte do business_quality: 65)."""
    updated = config.model_copy(deep=True)
    updated.scoring.weights = _weights(0.0, 65.0)
    return updated


def _valuation_low(config: AppConfig) -> AppConfig:
    updated = config.model_copy(deep=True)
    updated.scoring.weights = _weights(10.0, 55.0)
    return updated


def _default(config: AppConfig) -> AppConfig:
    updated = config.model_copy(deep=True)
    updated.scoring.weights = _weights(20.0, 45.0)
    return updated


def _valuation_high(config: AppConfig) -> AppConfig:
    updated = config.model_copy(deep=True)
    updated.scoring.weights = _weights(30.0, 35.0)
    return updated


ROUND_2B_CANDIDATES: tuple[CandidateConfig, ...] = (
    CandidateConfig(
        name="2b_valuation_0", round=2,
        description="CONTROL — valuation=0/business_quality=65 (punkty przesunięte, valuation całkowicie wyłączone z composite score na complete-valuation subset).",
        apply=_valuation_0,
    ),
    CandidateConfig(
        name="2b_valuation_low", round=2,
        description="valuation=10/business_quality=55 (połowa obecnej wagi).",
        apply=_valuation_low,
    ),
    CandidateConfig(
        name="2b_default", round=2,
        description="valuation=20/business_quality=45 (obecna/domyślna) — referencja Round 2B i pomiar szumu fold-to-fold (epsilon_2B).",
        apply=_default,
    ),
    CandidateConfig(
        name="2b_valuation_high", round=2,
        description="valuation=30/business_quality=35 (1,5x obecnej wagi).",
        apply=_valuation_high,
    ),
)

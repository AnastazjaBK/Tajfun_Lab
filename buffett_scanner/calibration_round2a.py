"""ROUND 2A — SAFETY + DIVIDEND/SHAREHOLDER RETURN (Faza 5.4b, korekta
metodologii zatwierdzona przez właścicielkę 2026-10-05). Kalibruje
WYŁĄCZNIE relację `financial_safety`/`dividend_shareholder_return` —
suma tych dwóch wag jest stała (25, obecny budżet obu komponentów),
żeby test dotyczył relatywnej wagi, nie mechanicznej zmiany całkowitej
dostępnej punktacji. `business_quality`/`valuation`/`fear_opportunity`
przypięte do wartości domyślnych (45/20/10) przez CAŁĄ tę rundę — zero
zmiany Round 1 selection mechanics/valuation mechanics/DCF/MoS/growth
caps/PIT/benchmarków.

PRIMARY metric tej podrundy to Spearman(`deterministic_score_pct`,
forward return 6m) — NIE `pooled_median_excess_return_pct` z Round 1
(ta metryka jest matematycznie niezależna od wag scoringu w obecnym
harnessie, patrz docs/buffett-scanner-design-review.md, Faza 5.4b
punkt 0 -- znalezisko zgłoszone i zatwierdzone PRZED napisaniem tego
modułu). `2a_default` służy JEDNOCZEŚNIE jako punkt odniesienia tej
podrundy I jako pomiar szumu fold-to-fold do
`derive_practical_tie_epsilon_spearman` (musi być policzony PRZED
porównaniem pozostałych kandydatów)."""

from __future__ import annotations

from buffett_scanner.calibration import CandidateConfig
from buffett_scanner.config import AppConfig, ScoringWeights


def _weights(financial_safety: float, dividend_shareholder_return: float) -> ScoringWeights:
    return ScoringWeights(
        business_quality=45.0,
        financial_safety=financial_safety,
        valuation=20.0,
        fear_opportunity=10.0,
        dividend_shareholder_return=dividend_shareholder_return,
    )


def _default(config: AppConfig) -> AppConfig:
    updated = config.model_copy(deep=True)
    updated.scoring.weights = _weights(15.0, 10.0)
    return updated


def _safety_heavy(config: AppConfig) -> AppConfig:
    updated = config.model_copy(deep=True)
    updated.scoring.weights = _weights(20.0, 5.0)
    return updated


def _dividend_heavy(config: AppConfig) -> AppConfig:
    updated = config.model_copy(deep=True)
    updated.scoring.weights = _weights(10.0, 15.0)
    return updated


def _balanced(config: AppConfig) -> AppConfig:
    updated = config.model_copy(deep=True)
    updated.scoring.weights = _weights(12.5, 12.5)
    return updated


ROUND_2A_CANDIDATES: tuple[CandidateConfig, ...] = (
    CandidateConfig(
        name="2a_default", round=2,
        description="financial_safety=15/dividend_shareholder_return=10 (obecna/domyślna) — referencja Round 2A i pomiar szumu fold-to-fold (epsilon_2A).",
        apply=_default,
    ),
    CandidateConfig(
        name="2a_safety_heavy", round=2,
        description="financial_safety=20/dividend_shareholder_return=5 (80/20 w ramach 25 pkt) — mocny przechył w stronę bezpieczeństwa finansowego.",
        apply=_safety_heavy,
    ),
    CandidateConfig(
        name="2a_dividend_heavy", round=2,
        description="financial_safety=10/dividend_shareholder_return=15 (40/60 w ramach 25 pkt) — mocny przechył w stronę dywidendy/zwrotu dla akcjonariuszy.",
        apply=_dividend_heavy,
    ),
    CandidateConfig(
        name="2a_balanced", round=2,
        description="financial_safety=12,5/dividend_shareholder_return=12,5 (50/50 w ramach 25 pkt) — punkt środkowy.",
        apply=_balanced,
    ),
)

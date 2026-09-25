"""Silnik scoringu — Faza 4 (sekcja 15, punkty 4.1-4.2 design review).

Łączy: wynik LLM z Fazy 3 (`AnalysisOutput` — business_understandability/
moat/management, wagi już wymuszone jako stałe Literal[7]/[12]/[10] w
sekcji 8), deterministyczny `financial_quality_score` (0-16, liczony
tu — sekcja 8: "LLM dostarcza tylko komentarz"), `valuation.py`
(margin of safety BASE), `shareholder_returns.py`
(dividend_shareholder_return). Wszystkie wagi finalne z
`config.scoring.weights` (suma 100, sekcja 6).

Zasada: brakujący/niepoliczalny komponent (np. wycena
NOT_YET_IMPLEMENTED) daje `None` w odpowiednim polu, a `total_score`
jest wtedy również `None` z `is_partial=True` — nigdy nie sumujemy
częściowych danych w fałszywie kompletną liczbę (IMPORTANT backlog:
"Zachowanie PARTIAL ANALYSIS", sekcja FINAL PRE-IMPLEMENTATION STATUS).

Hard gates (sekcja 8/9): sprawdzane niezależnie od total_score, nie
wpływają na jego wartość — tylko oznaczają `hard_gates_passed`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from buffett_scanner.analysis_schema import AnalysisOutput, FearAnalysis
from buffett_scanner.config import AppConfig
from buffett_scanner.fundamentals import FundamentalsPeriod, compute_metrics
from buffett_scanner.shareholder_returns import (
    DividendShareholderReturnResult,
    evaluate_dividend_shareholder_return,
)
from buffett_scanner.valuation import ValuationResult, compute_valuation

FINANCIAL_QUALITY_MAX = 16.0
FEAR_OPPORTUNITY_MAX = 10.0
DIVIDEND_SHAREHOLDER_RETURN_MAX = 10.0


@dataclass(frozen=True)
class FinancialQualityResult:
    raw_score: float
    raw_max: float = FINANCIAL_QUALITY_MAX
    breakdown: dict[str, bool] = field(default_factory=dict)


def _no_persistent_losses(periods: list[FundamentalsPeriod], lookback: int) -> bool:
    """True TYLKO gdy mamy `lookback` najnowszych okresów, wszystkie ze
    znanym net_income, i NIE wszystkie są ujemne. Brakujące dane -> False
    (brak kredytu) — inny wariant tej samej zasady co
    `shareholder_returns._no_dividend_cut`: nie mylić "nie mamy dowodu
    strat" z "mamy dowód braku strat"."""
    if len(periods) < lookback:
        return False
    window = periods[-lookback:]
    values = [p.net_income for p in window]
    if any(v is None for v in values):
        return False
    return not all(v < 0 for v in values)


def financial_quality_score(
    periods: list[FundamentalsPeriod], config: AppConfig
) -> FinancialQualityResult:
    if not periods:
        raise ValueError("financial_quality_score wymaga co najmniej jednego okresu")

    fq_config = config.financial_quality
    w = fq_config.weights
    metrics = compute_metrics(periods)
    breakdown: dict[str, bool] = {}
    score = 0.0

    fcf = metrics["fcf_ttm"]
    positive_fcf = fcf is not None and fcf > 0
    breakdown["fcf_positive"] = positive_fcf
    if positive_fcf:
        score += w.fcf_positive

    margin = metrics["fcf_margin_pct"]
    healthy_margin = margin is not None and margin >= fq_config.fcf_margin_healthy_threshold_pct
    breakdown["fcf_margin_healthy"] = healthy_margin
    if healthy_margin:
        score += w.fcf_margin_healthy

    leverage = metrics["net_debt_to_ebitda"]
    low_leverage = (
        leverage is not None and leverage <= fq_config.net_debt_to_ebitda_low_leverage_threshold
    )
    breakdown["low_leverage"] = low_leverage
    if low_leverage:
        score += w.low_leverage

    liquidity = metrics["current_ratio"]
    good_liquidity = liquidity is not None and liquidity >= fq_config.current_ratio_good_threshold
    breakdown["good_liquidity"] = good_liquidity
    if good_liquidity:
        score += w.good_liquidity

    growth = metrics["revenue_yoy_growth_pct"]
    positive_growth = growth is not None and growth > 0
    breakdown["positive_revenue_growth"] = positive_growth
    if positive_growth:
        score += w.positive_revenue_growth

    no_losses = _no_persistent_losses(periods, fq_config.persistent_losses_lookback_years)
    breakdown["no_persistent_losses"] = no_losses
    if no_losses:
        score += w.no_persistent_losses

    return FinancialQualityResult(raw_score=score, breakdown=breakdown)


def business_quality_score(analysis: AnalysisOutput, weight: float) -> float:
    """Skaluje liniowo sumę trzech ocen LLM (max zawsze 7+12+10=29,
    wymuszone jako stałe w schemacie Fazy 3) do wagi z configu."""
    raw_sum = (
        analysis.business_understandability.score
        + analysis.moat.score
        + analysis.management_capital_allocation.score
    )
    raw_max = (
        analysis.business_understandability.max_score
        + analysis.moat.max_score
        + analysis.management_capital_allocation.max_score
    )
    return raw_sum / raw_max * weight


def fear_opportunity_raw_points(fear_analysis: FearAnalysis, config: AppConfig) -> float:
    matrix = config.fear_opportunity.points_by_classification_confidence
    return matrix[fear_analysis.classification][fear_analysis.confidence]


def valuation_score(margin_of_safety_base_pct: float | None, config: AppConfig) -> float | None:
    """None gdy wycena niepoliczalna (nie 0 — brak danych to nie to samo
    co "spółka przewartościowana")."""
    if margin_of_safety_base_pct is None:
        return None
    weight = config.scoring.weights.valuation
    full_score_mos = config.valuation.dcf_owner_earnings.mos_pct_for_full_score
    if margin_of_safety_base_pct <= 0:
        return 0.0
    if margin_of_safety_base_pct >= full_score_mos:
        return weight
    return margin_of_safety_base_pct / full_score_mos * weight


@dataclass(frozen=True)
class HardGateResult:
    passed: bool
    triggered: list[str] = field(default_factory=list)


def evaluate_hard_gates(
    *,
    business_quality: float,
    safety: float,
    margin_of_safety_base_pct: float | None,
    config: AppConfig,
) -> HardGateResult:
    gates = config.hard_gates
    triggered: list[str] = []

    if gates.min_business_quality is not None and business_quality < gates.min_business_quality:
        triggered.append(
            f"business_quality ({business_quality:.1f}) < min_business_quality "
            f"({gates.min_business_quality})"
        )
    if gates.min_financial_safety is not None and safety < gates.min_financial_safety:
        triggered.append(
            f"safety ({safety:.1f}) < min_financial_safety ({gates.min_financial_safety})"
        )
    if gates.min_margin_of_safety_pct is not None:
        if margin_of_safety_base_pct is None:
            triggered.append(
                "min_margin_of_safety_pct aktywny, ale margin_of_safety (BASE) niepoliczalny"
            )
        elif margin_of_safety_base_pct < gates.min_margin_of_safety_pct:
            triggered.append(
                f"margin_of_safety BASE ({margin_of_safety_base_pct:.1f}%) < "
                f"min_margin_of_safety_pct ({gates.min_margin_of_safety_pct}%)"
            )

    return HardGateResult(passed=not triggered, triggered=triggered)


@dataclass(frozen=True)
class ScoreResult:
    business_quality_score: float
    moat_score: float
    management_score: float
    financial_quality_score: float
    safety_score: float
    valuation_score: float | None
    fear_score: float
    dividend_score: float
    total_score: float | None
    is_partial: bool
    missing_components: list[str]
    hard_gate_result: HardGateResult
    valuation_result: ValuationResult
    dividend_result: DividendShareholderReturnResult


def compute_score(
    *,
    analysis: AnalysisOutput,
    periods: list[FundamentalsPeriod],
    sector_profile: str,
    current_price: float,
    config: AppConfig,
) -> ScoreResult:
    weights = config.scoring.weights

    fq = financial_quality_score(periods, config)
    safety = fq.raw_score / FINANCIAL_QUALITY_MAX * weights.financial_safety
    bq = business_quality_score(analysis, weights.business_quality)
    fear = fear_opportunity_raw_points(analysis.fear_analysis, config) / FEAR_OPPORTUNITY_MAX * weights.fear_opportunity

    dividend_result = evaluate_dividend_shareholder_return(
        periods, current_price=current_price, config=config.dividend_shareholder_return,
    )
    dividend = dividend_result.raw_score / DIVIDEND_SHAREHOLDER_RETURN_MAX * weights.dividend_shareholder_return

    valuation_result = compute_valuation(
        sector_profile, periods, current_price=current_price, config=config.valuation,
    )
    mos_base = (
        valuation_result.scenarios["base"].margin_of_safety_pct
        if valuation_result.implemented
        else None
    )
    val_score = valuation_score(mos_base, config)

    components = {
        "business_quality": bq, "safety": safety, "fear": fear,
        "dividend": dividend, "valuation": val_score,
    }
    missing = [k for k, v in components.items() if v is None]
    total = None if missing else sum(components.values())

    hard_gate_result = evaluate_hard_gates(
        business_quality=bq, safety=safety, margin_of_safety_base_pct=mos_base, config=config,
    )

    return ScoreResult(
        business_quality_score=bq,
        moat_score=analysis.moat.score,
        management_score=analysis.management_capital_allocation.score,
        financial_quality_score=fq.raw_score,
        safety_score=safety,
        valuation_score=val_score,
        fear_score=fear,
        dividend_score=dividend,
        total_score=total,
        is_partial=bool(missing),
        missing_components=missing,
        hard_gate_result=hard_gate_result,
        valuation_result=valuation_result,
        dividend_result=dividend_result,
    )

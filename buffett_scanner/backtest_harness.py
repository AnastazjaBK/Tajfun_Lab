"""Deterministyczny walk-forward backtest harness — Faza 5.3 (sekcja 13),
zaprojektowany i zatwierdzony przez właścicielkę 2026-10-01.

Zasady, wszystkie wymuszone strukturalnie w tym module, nie tylko opisane:

1. **Bez pełnego LLM.** `compute_score()`/`evaluate_hard_gates()` z
   `scoring.py` NIE są tu używane i NIE są modyfikowane — wymagają
   obowiązkowo `AnalysisOutput` (wynik LLM), którego nie ma dla tysięcy
   historycznych obserwacji 2012+. Ten moduł liczy WYŁĄCZNIE komponenty
   deterministyczne, które już istnieją: `financial_quality_score`
   (safety), `compute_valuation` (valuation), `evaluate_dividend_
   shareholder_return` (dividend). `business_quality`/`fear` są zawsze
   `None`, `full_score` jest zawsze `None` — nigdy nie udajemy pełnego
   wyniku.

2. **`deterministic_score_pct`** — jawna normalizacja TYLKO dostępnych
   komponentów (punkty zdobyte / maksimum dostępnych komponentów * 100),
   nie nowa metodologia, nie zamiennik pełnego Buffett Score. Komponent
   jest "dostępny", gdy dał wartość liczbową (np. `valuation_score` może
   być `None` dla sektorów bez zaimplementowanej metody wyceny — wtedy
   jest wyłączony Z OBU stron ułamka, nie liczony jako 0).

3. **Zero look-ahead.** Funkcje tu NIE pobierają danych — przyjmują
   `bars`/`periods` już obcięte przez wywołującego do `<= decision_date`.
   Forward returns (`compute_forward_returns`) są policzone w OSOBNEJ
   funkcji, wywoływanej PO sfinalizowaniu kandydata, nigdy jako wejście
   do `evaluate_candidate_at_date` — strukturalnie niemożliwe dla
   przyszłych cen wpłynąć na decline scanner/prefilter/score/hard gates,
   bo ta funkcja ich w ogóle nie przyjmuje.

4. **deterministyczne hard gates** (`evaluate_deterministic_hard_gates`)
   to NOWA funkcja, nie modyfikacja `scoring.evaluate_hard_gates` — bo ta
   druga wymaga `business_quality` (float, nie None) do sprawdzenia
   `min_business_quality`, czego nie da się ocenić bez LLM. Reszta
   (`min_financial_safety`, `min_margin_of_safety_pct`) jest identyczna.

Zero I/O w tym module — pobieranie SEC/FMP i obcinanie do daty dzieje
się w warstwie providerów."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, replace
from typing import Literal

from buffett_scanner.config import AppConfig
from buffett_scanner.fundamentals import FundamentalsPeriod, compute_metrics, evaluate_prefilter
from buffett_scanner.fundamentals import PrefilterResult
from buffett_scanner.scanner import PriceBar, compute_price_changes, evaluate_decline_flags
from buffett_scanner.scoring import (
    FINANCIAL_QUALITY_MAX,
    FinancialQualityResult,
    HardGateResult,
    financial_quality_score,
)
from buffett_scanner.shareholder_returns import (
    DividendShareholderReturnResult,
    evaluate_dividend_shareholder_return,
)
from buffett_scanner.valuation import ValuationResult, compute_valuation

# ---------------------------------------------------------------------------
# Daty rebalansu (walk-forward)
# ---------------------------------------------------------------------------

RebalanceFrequency = Literal["MONTHLY", "QUARTERLY"]


def _add_calendar_months(year: int, month: int, months: int) -> tuple[int, int]:
    total = (year * 12 + (month - 1)) + months
    return total // 12, total % 12 + 1


def generate_rebalance_dates(
    window_start: str, window_end: str, frequency: RebalanceFrequency
) -> list[str]:
    """Generuje listę dat rebalansu (pierwszy dzień kalendarzowy
    miesiąca) od `window_start` do `window_end` WŁĄCZNIE, deterministycznie,
    bez odwołania do "dziś" (to odpowiedzialność wywołującego — przekazać
    `window_end` jawnie, np. `config.backtest.window_end` albo dzisiejszą
    datę). `frequency="QUARTERLY"` -> co 3 miesiące od miesiąca
    `window_start`. Pusta lista, jeśli `window_start > window_end`."""
    start = dt.date.fromisoformat(window_start)
    end = dt.date.fromisoformat(window_end)
    if start > end:
        return []
    step = 1 if frequency == "MONTHLY" else 3
    dates: list[str] = []
    year, month = start.year, start.month
    if start.day != 1:
        year, month = _add_calendar_months(year, month, 1)  # pierwsza data >= window_start, nigdy przed
    current = dt.date(year, month, 1)
    while current <= end:
        dates.append(current.isoformat())
        year, month = _add_calendar_months(year, month, step)
        current = dt.date(year, month, 1)
    return dates


def add_months(date_str: str, months: int) -> str:
    """Dodaje `months` kalendarzowych miesięcy do daty ISO, zachowując
    dzień miesiąca tam, gdzie to możliwe (obcina do ostatniego dnia
    krótszego miesiąca, np. 2024-01-31 + 1mc -> 2024-02-29, nie 2024-03-02
    — nigdy nie "przelewa się" do kolejnego miesiąca)."""
    d = dt.date.fromisoformat(date_str)
    year, month = _add_calendar_months(d.year, d.month, months)
    import calendar

    last_day = calendar.monthrange(year, month)[1]
    day = min(d.day, last_day)
    return dt.date(year, month, day).isoformat()


# ---------------------------------------------------------------------------
# Forward returns — WYŁĄCZNIE outcome labels, nigdy wejście do decyzji
# ---------------------------------------------------------------------------

FORWARD_RETURN_HORIZONS_MONTHS = (1, 3, 6, 12)


def forward_return_pct(
    bars: list[PriceBar], decision_date: str, decision_price: float, horizon_months: int
) -> float | None:
    """Zwrot (%) od `decision_price` do ceny zamknięcia pierwszego baru
    z datą >= `decision_date + horizon_months`. `None`, jeśli `bars` nie
    sięga tak daleko w przyszłość (typowe dla niedawnych dat decyzji —
    NIGDY nie ekstrapolujemy brakującej przyszłości) albo `decision_price`
    jest `None`/`<=0`. `bars` tutaj może (i dla tej funkcji MUSI) zawierać
    ceny PO `decision_date` — w przeciwieństwie do `bars` przekazywanych
    do `evaluate_candidate_at_date`, które muszą być obcięte do
    `<= decision_date`. To rozróżnienie jest celowe i strukturalne, nie
    przez nazwę zmiennej."""
    if decision_price is None or decision_price <= 0:
        return None
    target_date = add_months(decision_date, horizon_months)
    future = sorted((b for b in bars if b.date >= target_date), key=lambda b: b.date)
    if not future:
        return None
    return (future[0].close / decision_price - 1) * 100


@dataclass(frozen=True)
class ForwardReturns:
    return_1m_pct: float | None
    return_3m_pct: float | None
    return_6m_pct: float | None
    return_12m_pct: float | None


def compute_forward_returns(
    bars: list[PriceBar], decision_date: str, decision_price: float
) -> ForwardReturns:
    values = {
        h: forward_return_pct(bars, decision_date, decision_price, h)
        for h in FORWARD_RETURN_HORIZONS_MONTHS
    }
    return ForwardReturns(
        return_1m_pct=values[1], return_3m_pct=values[3],
        return_6m_pct=values[6], return_12m_pct=values[12],
    )


# ---------------------------------------------------------------------------
# Deterministyczny (partial) score
# ---------------------------------------------------------------------------

_COMPONENT_NAMES = ("safety", "valuation", "dividend")


@dataclass(frozen=True)
class DeterministicScoreResult:
    safety_score: float
    valuation_score: float | None
    dividend_score: float
    full_score: None  # ZAWSZE None w tym trybie — nigdy nie udajemy pełnego Buffett Score
    deterministic_partial_score: float  # suma DOSTĘPNYCH komponentów, nieznormalizowana
    deterministic_score_pct: float | None  # znormalizowane 0-100 względem DOSTĘPNYCH komponentów
    available_components: tuple[str, ...]
    missing_components: tuple[str, ...]  # zawsze >= {"business_quality", "fear"} + ew. "valuation"
    financial_quality_result: FinancialQualityResult
    valuation_result: ValuationResult
    dividend_result: DividendShareholderReturnResult
    margin_of_safety_base_pct: float | None


def compute_deterministic_score(
    *, periods: list[FundamentalsPeriod], sector_profile: str, current_price: float, config: AppConfig,
) -> DeterministicScoreResult:
    weights = config.scoring.weights

    fq = financial_quality_score(periods, config)
    safety = fq.raw_score / FINANCIAL_QUALITY_MAX * weights.financial_safety

    dividend_result = evaluate_dividend_shareholder_return(
        periods, current_price=current_price, config=config.dividend_shareholder_return,
    )
    dividend = dividend_result.raw_score / 10.0 * weights.dividend_shareholder_return

    valuation_result = compute_valuation(
        sector_profile, periods, current_price=current_price, config=config.valuation,
    )
    mos_base = (
        valuation_result.scenarios["base"].margin_of_safety_pct
        if valuation_result.implemented and "base" in valuation_result.scenarios
        else None
    )
    valuation_pts: float | None
    if mos_base is None:
        valuation_pts = None
    else:
        full_score_mos = config.valuation.dcf_owner_earnings.mos_pct_for_full_score
        if mos_base <= 0:
            valuation_pts = 0.0
        elif mos_base >= full_score_mos:
            valuation_pts = weights.valuation
        else:
            valuation_pts = mos_base / full_score_mos * weights.valuation

    raw_values = {"safety": safety, "valuation": valuation_pts, "dividend": dividend}
    raw_maxes = {
        "safety": weights.financial_safety,
        "valuation": weights.valuation,
        "dividend": weights.dividend_shareholder_return,
    }
    available = tuple(name for name in _COMPONENT_NAMES if raw_values[name] is not None)
    missing = ("business_quality", "fear") + tuple(
        name for name in _COMPONENT_NAMES if raw_values[name] is None
    )

    points_earned = sum(raw_values[name] for name in available)
    max_available = sum(raw_maxes[name] for name in available)
    pct = (points_earned / max_available * 100) if max_available > 0 else None

    return DeterministicScoreResult(
        safety_score=safety,
        valuation_score=valuation_pts,
        dividend_score=dividend,
        full_score=None,
        deterministic_partial_score=points_earned,
        deterministic_score_pct=pct,
        available_components=available,
        missing_components=missing,
        financial_quality_result=fq,
        valuation_result=valuation_result,
        dividend_result=dividend_result,
        margin_of_safety_base_pct=mos_base,
    )


def evaluate_deterministic_hard_gates(
    *, safety: float, margin_of_safety_base_pct: float | None, config: AppConfig,
) -> HardGateResult:
    """Lustrzane odbicie `scoring.evaluate_hard_gates`, ale BEZ bramki
    `min_business_quality` — nie istnieje historyczny LLM output, więc
    nie da się jej ocenić (decyzja właścicielki, 2026-10-01). To NIE
    jest ten sam wynik, co produkcyjne `evaluate_hard_gates` na żywych
    danych z LLM — nigdy nie wolno ich ze sobą mylić ani mieszać w
    jednym raporcie bez jawnego oznaczenia, który tryb to wyprodukował."""
    gates = config.hard_gates
    triggered: list[str] = []

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


# ---------------------------------------------------------------------------
# Kandydat + funnel ewaluacji per (cik, decision_date)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BacktestCandidate:
    run_id: str
    decision_date: str
    cik: str
    ticker_as_of_date: str
    decision_price: float  # cena bazowa (ostatni bar <= decision_date) — baza forward returns
    decline_flags: dict[str, bool]
    pit_fundamentals_period_end: str | None
    pit_fundamentals_filed_date: str | None
    financial_quality_breakdown: dict[str, bool]
    safety_score: float
    valuation_score: float | None
    dividend_score: float
    full_score: None
    deterministic_partial_score: float
    deterministic_score_pct: float | None
    available_components: tuple[str, ...]
    missing_components: tuple[str, ...]
    hard_gate_passed: bool
    hard_gate_triggered: tuple[str, ...]
    margin_of_safety_base_pct: float | None
    config_version: str
    scoring_version: str
    universe_provenance: str
    forward_returns: ForwardReturns | None = None  # dołączane OSOBNO, patrz attach_forward_returns


FunnelStage = Literal[
    "NO_FUNDAMENTALS", "NO_DECLINE_SIGNAL", "EXCLUDED_BY_PREFILTER", "HARD_GATE_FAILED", "CANDIDATE",
]


@dataclass(frozen=True)
class BacktestFunnelResult:
    stage: FunnelStage
    decline_flags: dict[str, bool] | None
    prefilter_result: PrefilterResult | None
    score: DeterministicScoreResult | None
    candidate: BacktestCandidate | None


def evaluate_candidate_at_date(
    *,
    cik: str,
    ticker_as_of_date: str,
    decision_date: str,
    bars: list[PriceBar],
    periods: list[FundamentalsPeriod],
    sector_profile: str,
    config: AppConfig,
    run_id: str,
    config_version: str,
    universe_provenance: str,
) -> BacktestFunnelResult:
    """Pojedynczy krok walk-forward dla jednej spółki na jedną datę
    decyzji. `bars`/`periods` MUSZĄ być już obcięte przez wywołującego
    do `<= decision_date` (ten warunek NIE jest tu sprawdzany — to
    odpowiedzialność warstwy I/O budującej te listy z realnych danych;
    testy tego modułu weryfikują zachowanie funkcji przy już poprawnie
    obciętych danych, nie poprawność samego obcinania)."""
    if not periods or not bars:
        return BacktestFunnelResult(
            stage="NO_FUNDAMENTALS", decline_flags=None, prefilter_result=None, score=None, candidate=None,
        )

    snapshot = compute_price_changes(bars)
    decline_flags = evaluate_decline_flags(snapshot, config.decline_scanner.thresholds)
    if not any(decline_flags.values()):
        return BacktestFunnelResult(
            stage="NO_DECLINE_SIGNAL", decline_flags=decline_flags,
            prefilter_result=None, score=None, candidate=None,
        )

    metrics = compute_metrics(periods)
    prefilter_result = evaluate_prefilter(metrics, config.prefilter)
    if prefilter_result.excludes:
        return BacktestFunnelResult(
            stage="EXCLUDED_BY_PREFILTER", decline_flags=decline_flags,
            prefilter_result=prefilter_result, score=None, candidate=None,
        )

    current_price = bars[-1].close
    score = compute_deterministic_score(
        periods=periods, sector_profile=sector_profile, current_price=current_price, config=config,
    )
    hard_gates = evaluate_deterministic_hard_gates(
        safety=score.safety_score, margin_of_safety_base_pct=score.margin_of_safety_base_pct, config=config,
    )
    if not hard_gates.passed:
        return BacktestFunnelResult(
            stage="HARD_GATE_FAILED", decline_flags=decline_flags,
            prefilter_result=prefilter_result, score=score, candidate=None,
        )

    latest = periods[-1]
    candidate = BacktestCandidate(
        run_id=run_id,
        decision_date=decision_date,
        cik=cik,
        ticker_as_of_date=ticker_as_of_date,
        decision_price=current_price,
        decline_flags=decline_flags,
        pit_fundamentals_period_end=latest.period_end_date,
        pit_fundamentals_filed_date=latest.filed_date,
        financial_quality_breakdown=score.financial_quality_result.breakdown,
        safety_score=score.safety_score,
        valuation_score=score.valuation_score,
        dividend_score=score.dividend_score,
        full_score=None,
        deterministic_partial_score=score.deterministic_partial_score,
        deterministic_score_pct=score.deterministic_score_pct,
        available_components=score.available_components,
        missing_components=score.missing_components,
        hard_gate_passed=hard_gates.passed,
        hard_gate_triggered=tuple(hard_gates.triggered),
        margin_of_safety_base_pct=score.margin_of_safety_base_pct,
        config_version=config_version,
        scoring_version=config.scoring.version,
        universe_provenance=universe_provenance,
    )
    return BacktestFunnelResult(
        stage="CANDIDATE", decline_flags=decline_flags,
        prefilter_result=prefilter_result, score=score, candidate=candidate,
    )


def attach_forward_returns(
    candidate: BacktestCandidate, bars_including_future: list[PriceBar]
) -> BacktestCandidate:
    """JEDYNE miejsce, gdzie przyszłe ceny (po `decision_date`) wchodzą
    do obrazu — wywoływane PO sfinalizowaniu kandydata przez
    `evaluate_candidate_at_date`. `candidate.safety_score`/`valuation_score`/
    `hard_gate_passed`/itd. są już ustalone i NIE są tu przeliczane —
    `replace()` dodaje wyłącznie `forward_returns`, nic więcej. Baza
    zwrotu to `candidate.decision_price`, ustalona WCZEŚNIEJ, w
    `evaluate_candidate_at_date`, z danych `<= decision_date` — tu
    tylko dokładamy przyszłe ceny do porównania, nigdy nie zmieniamy
    bazy."""
    forward = compute_forward_returns(
        bars_including_future, candidate.decision_date, candidate.decision_price,
    )
    return replace(candidate, forward_returns=forward)

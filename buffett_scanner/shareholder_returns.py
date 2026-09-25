"""Dividend/shareholder-return silnik — Faza 4 (zatwierdzony design
2026-09-25). Czyste, deterministyczne funkcje, konwencja identyczna z
`fundamentals.py`: `periods[-1]` to najnowszy okres.

Zasada z §24 (konsekwentnie stosowana): brakująca wartość wejściowa
NIGDY nie jest cicho traktowana jako 0 i NIGDY nie fabrykuje wyniku ani
kredytu punktowego — dotyczy to zarówno pojedynczych None, jak i
sytuacji "nie mamy wystarczających danych, żeby cokolwiek stwierdzić"
(patrz `_no_dividend_cut`/`share_count_trend` — rozróżniają "potwierdzone
dobrze" od "nie wiadomo", zamiast traktować oba jako to samo).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from buffett_scanner.config import DividendShareholderReturnConfig
from buffett_scanner.fundamentals import FundamentalsPeriod, free_cash_flow


def dividend_per_share(period: FundamentalsPeriod) -> float | None:
    if period.dividends_paid is None or period.diluted_shares_outstanding is None:
        return None
    if period.diluted_shares_outstanding == 0:
        return None
    return period.dividends_paid / period.diluted_shares_outstanding


def market_cap(period: FundamentalsPeriod, price: float) -> float | None:
    if period.diluted_shares_outstanding is None:
        return None
    return price * period.diluted_shares_outstanding


def shareholder_yield_pct(period: FundamentalsPeriod, price: float) -> float | None:
    """(dywidendy + buybacki) / kapitalizacja rynkowa × 100."""
    if period.dividends_paid is None or period.share_buybacks is None:
        return None
    cap = market_cap(period, price)
    if cap is None or cap == 0:
        return None
    return (period.dividends_paid + period.share_buybacks) / cap * 100.0


@dataclass(frozen=True)
class PayoutRatioResult:
    value_pct: float | None
    not_meaningful: bool  # True gdy FCF <= 0 — payout ratio nie jest interpretowalny


def payout_ratio(period: FundamentalsPeriod) -> PayoutRatioResult:
    """dividends_paid / FCF × 100 (Decyzja właściciela 2026-09-25: FCF,
    nie zysk netto). Gdy FCF <= 0, wartość procentowa byłaby myląca
    (ujemna albo pozornie "niska" przy topniejącej gotówce) — zwracamy
    jawny `not_meaningful=True` zamiast liczby."""
    fcf = free_cash_flow(period)
    if fcf is None or period.dividends_paid is None:
        return PayoutRatioResult(value_pct=None, not_meaningful=False)
    if fcf <= 0:
        return PayoutRatioResult(value_pct=None, not_meaningful=True)
    return PayoutRatioResult(value_pct=period.dividends_paid / fcf * 100.0, not_meaningful=False)


def _no_dividend_cut(periods: list[FundamentalsPeriod]) -> bool | None:
    """True = potwierdzone, że DPS nie spadł r/r. False = potwierdzone
    cięcie. None = za mało danych, żeby cokolwiek stwierdzić — NIGDY nie
    traktowane jako "brak cięcia" przy przyznawaniu punktów (patrz
    `evaluate_dividend_shareholder_return`)."""
    if len(periods) < 2:
        return None
    latest_dps = dividend_per_share(periods[-1])
    prior_dps = dividend_per_share(periods[-2])
    if latest_dps is None or prior_dps is None:
        return None
    return latest_dps >= prior_dps


def share_count_trend(periods: list[FundamentalsPeriod]) -> Literal["DECREASING", "FLAT", "INCREASING"] | None:
    if len(periods) < 2:
        return None
    latest = periods[-1].diluted_shares_outstanding
    prior = periods[-2].diluted_shares_outstanding
    if latest is None or prior is None:
        return None
    if latest < prior:
        return "DECREASING"
    if latest > prior:
        return "INCREASING"
    return "FLAT"


@dataclass(frozen=True)
class DividendShareholderReturnResult:
    raw_score: float
    raw_max: float = 10.0
    dividend_per_share_latest: float | None = None
    shareholder_yield_pct_latest: float | None = None
    payout_ratio: PayoutRatioResult | None = None
    share_count_trend: Literal["DECREASING", "FLAT", "INCREASING"] | None = None
    no_dividend_cut: bool | None = None
    breakdown: dict[str, bool] | None = None


def evaluate_dividend_shareholder_return(
    periods: list[FundamentalsPeriod],
    *,
    current_price: float,
    config: DividendShareholderReturnConfig,
) -> DividendShareholderReturnResult:
    if not periods:
        raise ValueError("evaluate_dividend_shareholder_return wymaga co najmniej jednego okresu")

    latest = periods[-1]
    w = config.weights
    breakdown: dict[str, bool] = {}
    score = 0.0

    yield_pct = shareholder_yield_pct(latest, current_price)
    positive_yield = yield_pct is not None and yield_pct > config.min_shareholder_yield_pct
    breakdown["positive_shareholder_yield"] = positive_yield
    if positive_yield:
        score += w.positive_shareholder_yield

    cut_status = _no_dividend_cut(periods)
    no_cut = cut_status is True  # None (nieznane) i False (potwierdzone cięcie) -> brak kredytu
    breakdown["no_dividend_cut"] = no_cut
    if no_cut:
        score += w.no_dividend_cut

    payout = payout_ratio(latest)
    sustainable = (
        payout.value_pct is not None
        and not payout.not_meaningful
        and payout.value_pct <= config.max_sustainable_payout_ratio_pct
    )
    breakdown["sustainable_payout_ratio"] = sustainable
    if sustainable:
        score += w.sustainable_payout_ratio

    trend = share_count_trend(periods)
    shrinking_or_flat = trend in ("DECREASING", "FLAT")
    breakdown["shrinking_or_flat_share_count"] = shrinking_or_flat
    if shrinking_or_flat:
        score += w.shrinking_or_flat_share_count

    return DividendShareholderReturnResult(
        raw_score=score,
        dividend_per_share_latest=dividend_per_share(latest),
        shareholder_yield_pct_latest=yield_pct,
        payout_ratio=payout,
        share_count_trend=trend,
        no_dividend_cut=cut_status,
        breakdown=breakdown,
    )

"""Decline scanner — czyste, deterministyczne kalkulacje (Faza 0, punkt 0.4).

Zero LLM, zero I/O. Liczy zmiany cenowe i drawdown dla pojedynczej
spółki na podstawie jej historii cen (posortowanej rosnąco po dacie).
Brak wystarczającej historii dla danego okna -> None, NIGDY 0 (zasada
DATA UNAVAILABLE z design review, §24 spec).

Progi z config.decline_scanner.thresholds są `UNCALIBRATED` do czasu
backtestingu (Faza 5) — evaluate_decline_flags() tylko sprawdza, czy
próg jest przekroczony, nie twierdzi, że to sygnał inwestycyjny.
"""

from __future__ import annotations

from dataclasses import dataclass

from buffett_scanner.config import DeclineScannerThresholds

# Konwencja "trading days" (nie dni kalendarzowych), zgodna z typowym
# ujęciem miesiąc≈21, kwartał≈63, rok≈252 sesji.
TRADING_DAYS_WEEK = 5
TRADING_DAYS_MONTH = 21
TRADING_DAYS_QUARTER = 63
TRADING_DAYS_YEAR = 252
RELATIVE_VOLUME_LOOKBACK = 20


@dataclass(frozen=True)
class PriceBar:
    date: str  # ISO "YYYY-MM-DD"
    open: float | None
    high: float | None
    low: float | None
    close: float
    adj_close: float | None
    volume: int | None


@dataclass(frozen=True)
class PriceChangeSnapshot:
    as_of_date: str
    daily_pct: float | None
    week_pct: float | None
    month_pct: float | None
    quarter_pct: float | None
    ytd_pct: float | None
    year_pct: float | None
    drawdown_from_52w_high_pct: float | None
    relative_volume: float | None


def _pct_change(current: float, base: float) -> float | None:
    if base == 0:
        return None
    return (current - base) / base * 100.0


def _bar_n_sessions_ago(bars: list[PriceBar], n: int) -> PriceBar | None:
    """bars[-1] to "dziś"; n sesji wstecz to bars[-1-n]."""
    idx = len(bars) - 1 - n
    if idx < 0:
        return None
    return bars[idx]


def _ytd_baseline(bars: list[PriceBar]) -> PriceBar | None:
    """Ostatnia sesja przed 1 stycznia roku bieżącej (ostatniej) sesji."""
    if not bars:
        return None
    current_year = bars[-1].date[:4]
    baseline = None
    for bar in bars:
        if bar.date[:4] < current_year:
            baseline = bar
        else:
            break
    return baseline


def compute_price_changes(bars: list[PriceBar]) -> PriceChangeSnapshot:
    if not bars:
        raise ValueError("compute_price_changes wymaga co najmniej jednego bara")

    today = bars[-1]

    daily_base = _bar_n_sessions_ago(bars, 1)
    week_base = _bar_n_sessions_ago(bars, TRADING_DAYS_WEEK)
    month_base = _bar_n_sessions_ago(bars, TRADING_DAYS_MONTH)
    quarter_base = _bar_n_sessions_ago(bars, TRADING_DAYS_QUARTER)
    year_base = _bar_n_sessions_ago(bars, TRADING_DAYS_YEAR)
    ytd_base = _ytd_baseline(bars)

    window_52w = bars[-TRADING_DAYS_YEAR:] if len(bars) >= 1 else bars
    high_52w = max((b.high if b.high is not None else b.close) for b in window_52w)
    drawdown = _pct_change(today.close, high_52w) if high_52w else None

    rel_volume = None
    if today.volume is not None and len(bars) > RELATIVE_VOLUME_LOOKBACK:
        prior = bars[-1 - RELATIVE_VOLUME_LOOKBACK : -1]
        volumes = [b.volume for b in prior if b.volume is not None]
        if volumes:
            avg_volume = sum(volumes) / len(volumes)
            if avg_volume > 0:
                rel_volume = today.volume / avg_volume

    return PriceChangeSnapshot(
        as_of_date=today.date,
        daily_pct=_pct_change(today.close, daily_base.close) if daily_base else None,
        week_pct=_pct_change(today.close, week_base.close) if week_base else None,
        month_pct=_pct_change(today.close, month_base.close) if month_base else None,
        quarter_pct=_pct_change(today.close, quarter_base.close) if quarter_base else None,
        ytd_pct=_pct_change(today.close, ytd_base.close) if ytd_base else None,
        year_pct=_pct_change(today.close, year_base.close) if year_base else None,
        drawdown_from_52w_high_pct=drawdown,
        relative_volume=rel_volume,
    )


def evaluate_decline_flags(
    snapshot: PriceChangeSnapshot, thresholds: DeclineScannerThresholds
) -> dict[str, bool]:
    """Zwraca, które progi zostały przekroczone. UNCALIBRATED — patrz
    docstring modułu; to NIE jest werdykt inwestycyjny."""

    def below(value: float | None, threshold: float) -> bool:
        return value is not None and value <= threshold

    def above(value: float | None, threshold: float) -> bool:
        return value is not None and value >= threshold

    return {
        "daily_decline": below(snapshot.daily_pct, thresholds.daily_pct),
        "week_decline": below(snapshot.week_pct, thresholds.week_pct),
        "month_decline": below(snapshot.month_pct, thresholds.month_pct),
        "quarter_decline": below(snapshot.quarter_pct, thresholds.quarter_pct),
        "drawdown_from_52w_high": below(
            snapshot.drawdown_from_52w_high_pct, thresholds.drawdown_from_52w_high_pct
        ),
        "abnormal_volume": above(
            snapshot.relative_volume, thresholds.relative_volume_multiple
        ),
    }

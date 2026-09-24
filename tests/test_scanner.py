"""Testy jednostkowe decline scanner — wartości referencyjne policzone
ręcznie (formuła (nowa-stara)/stara*100), nie odtworzone z kodu pod testem.

Konwencja: bars[-1] to "dziś". Zero I/O, zero LLM.
"""

import datetime as dt

import pytest

from buffett_scanner.config import DeclineScannerThresholds
from buffett_scanner.scanner import (
    PriceBar,
    compute_price_changes,
    evaluate_decline_flags,
)


def make_bar(date: str, close: float, volume: int | None = 1000) -> PriceBar:
    return PriceBar(date=date, open=close, high=close, low=close, close=close,
                     adj_close=close, volume=volume)


# ---------------------------------------------------------------------------
# Mały, w pełni ręcznie policzony przykład (5 sesji) — dokumentacyjny.
# ---------------------------------------------------------------------------

def test_small_hand_computed_example_insufficient_history_returns_none():
    bars = [
        make_bar("2026-01-01", 100.0),
        make_bar("2026-01-02", 95.0),   # -5% dzień do dnia
        make_bar("2026-01-03", 90.0),   # -5.2631...% dzień do dnia
        make_bar("2026-01-04", 100.0),  # +11.111...% dzień do dnia
        make_bar("2026-01-05", 80.0),   # -20% dzień do dnia
    ]
    snapshot = compute_price_changes(bars)

    assert snapshot.daily_pct == pytest.approx((80.0 - 100.0) / 100.0 * 100.0)  # -20.0
    # za mało sesji na week/month/quarter/year -> None, NIGDY 0
    assert snapshot.week_pct is None
    assert snapshot.month_pct is None
    assert snapshot.quarter_pct is None
    assert snapshot.year_pct is None
    # drawdown liczony z dostępnego okna (max z 5 barów = 100.0)
    assert snapshot.drawdown_from_52w_high_pct == pytest.approx((80.0 - 100.0) / 100.0 * 100.0)


# ---------------------------------------------------------------------------
# Duży przykład (300 sesji, close rosnący liniowo: close[i] = 100 + i) —
# oczekiwane wartości policzone formułą (j - i) / (100 + i) * 100 dla
# konkretnych, wybranych ręcznie indeksów.
# ---------------------------------------------------------------------------

def _build_linear_series(n: int, start_date: dt.date) -> list[PriceBar]:
    bars = []
    for i in range(n):
        date = (start_date + dt.timedelta(days=i)).isoformat()
        volume = 3000 if i == n - 1 else 1000  # dzisiejszy wolumen 3x normalny
        bars.append(make_bar(date, close=100.0 + i, volume=volume))
    return bars


@pytest.fixture
def linear_series():
    return _build_linear_series(300, dt.date(2025, 6, 1))


def test_daily_week_month_quarter_pct_on_linear_series(linear_series):
    snapshot = compute_price_changes(linear_series)
    # dziś: close[299] = 399. pct = diff / base * 100
    assert snapshot.daily_pct == pytest.approx(1.0 / 398.0 * 100.0)      # base close[298]=398
    assert snapshot.week_pct == pytest.approx(5.0 / 394.0 * 100.0)       # base close[294]=394
    assert snapshot.month_pct == pytest.approx(21.0 / 378.0 * 100.0)     # base close[278]=378
    assert snapshot.quarter_pct == pytest.approx(63.0 / 336.0 * 100.0)   # base close[236]=336
    assert snapshot.year_pct == pytest.approx(252.0 / 147.0 * 100.0)     # base close[47]=147


def test_drawdown_is_zero_when_prices_monotonically_rising(linear_series):
    # ceny rosną cały czas -> dzisiejsza cena JEST 52-tygodniowym maksimum
    snapshot = compute_price_changes(linear_series)
    assert snapshot.drawdown_from_52w_high_pct == pytest.approx(0.0)


def test_drawdown_reflects_a_manufactured_dip():
    bars = _build_linear_series(300, dt.date(2025, 6, 1))
    # Podmieniamy DZISIEJSZY bar na spadek -> 52-tyg. maksimum w oknie to
    # teraz poprzedni bar, close[298]=398 (druga najwyższa cena w oknie,
    # bo bar[299] przestał nim być po podmianie).
    peak = 398.0
    dipped_close = 318.4  # dokładnie -20% od peaku: 398 * 0.8 = 318.4
    bars[-1] = make_bar(bars[-1].date, close=dipped_close, volume=bars[-1].volume)
    snapshot = compute_price_changes(bars)
    assert snapshot.drawdown_from_52w_high_pct == pytest.approx((dipped_close - peak) / peak * 100.0)
    assert snapshot.drawdown_from_52w_high_pct == pytest.approx(-20.0)


def test_relative_volume_on_linear_series(linear_series):
    snapshot = compute_price_changes(linear_series)
    # ostatnie 20 sesji przed dziś mają wolumen 1000, dziś 3000 -> 3.0x
    assert snapshot.relative_volume == pytest.approx(3.0)


def test_ytd_uses_last_session_of_prior_calendar_year():
    bars = _build_linear_series(300, dt.date(2025, 6, 1))
    today = bars[-1]
    today_year = today.date[:4]
    # niezależne ustalenie oczekiwanego baseline'u: ostatni bar przed
    # 1 stycznia roku "dziś"
    baseline = None
    for b in bars:
        if b.date[:4] < today_year:
            baseline = b
        else:
            break
    assert baseline is not None, "test wymaga serii przekraczającej granicę roku"

    snapshot = compute_price_changes(bars)
    expected = (today.close - baseline.close) / baseline.close * 100.0
    assert snapshot.ytd_pct == pytest.approx(expected)


def test_ytd_is_none_when_series_does_not_cross_year_boundary():
    bars = _build_linear_series(10, dt.date(2026, 1, 5))  # cały styczeń, brak poprzedniego roku w danych
    snapshot = compute_price_changes(bars)
    assert snapshot.ytd_pct is None


# ---------------------------------------------------------------------------
# evaluate_decline_flags — progi UNCALIBRATED, sama logika porównania
# ---------------------------------------------------------------------------

DEFAULT_THRESHOLDS = DeclineScannerThresholds(
    daily_pct=-5.0,
    week_pct=-8.0,
    month_pct=-15.0,
    quarter_pct=-20.0,
    drawdown_from_52w_high_pct=-25.0,
    relative_volume_multiple=2.0,
)


def test_evaluate_decline_flags_triggers_on_exact_threshold_boundary():
    bars = [make_bar("2026-01-01", 100.0), make_bar("2026-01-02", 95.0)]  # dokładnie -5.0%
    snapshot = compute_price_changes(bars)
    flags = evaluate_decline_flags(snapshot, DEFAULT_THRESHOLDS)
    assert flags["daily_decline"] is True  # <=, nie <


def test_evaluate_decline_flags_does_not_trigger_just_above_threshold():
    bars = [make_bar("2026-01-01", 100.0), make_bar("2026-01-02", 96.0)]  # -4.0%
    snapshot = compute_price_changes(bars)
    flags = evaluate_decline_flags(snapshot, DEFAULT_THRESHOLDS)
    assert flags["daily_decline"] is False


def test_evaluate_decline_flags_none_value_never_triggers_false_positive():
    """Brakujące dane (None) nigdy nie mają być cicho traktowane jako 0
    i nigdy nie mają fałszywie odpalić flagi (§24 design review)."""
    bars = [make_bar("2026-01-01", 100.0)]  # tylko 1 sesja -> same None poza daily
    snapshot = compute_price_changes(bars)
    assert snapshot.week_pct is None
    flags = evaluate_decline_flags(snapshot, DEFAULT_THRESHOLDS)
    assert flags["week_decline"] is False


def test_abnormal_volume_flag():
    bars = _build_linear_series(300, dt.date(2025, 6, 1))
    snapshot = compute_price_changes(bars)
    flags = evaluate_decline_flags(snapshot, DEFAULT_THRESHOLDS)
    assert flags["abnormal_volume"] is True  # rel_volume=3.0 >= próg 2.0


def test_compute_price_changes_requires_at_least_one_bar():
    with pytest.raises(ValueError):
        compute_price_changes([])

"""Faza 11 (P2): zmiany cen 1D-MAX -- N/A zamiast krótszego okresu,
dni bez sesji, ucięta historia, anomalie (CTVA)."""

from __future__ import annotations

import datetime as dt

import pytest

from buffett_scanner.ui.price_changes import (
    compute_period_changes,
    detect_price_anomalies,
    periods_affected,
)


def _daily(start: str, end: str, price_fn):
    out, d = [], dt.date.fromisoformat(start)
    while d <= dt.date.fromisoformat(end):
        if d.weekday() < 5:
            out.append((d.isoformat(), price_fn(d)))
        d += dt.timedelta(days=1)
    return out


def test_periods_use_last_session_on_or_before_target_date():
    series = _daily("2020-01-01", "2026-10-16", lambda d: 100.0 + (d - dt.date(2020, 1, 1)).days * 0.01)
    changes = compute_period_changes(series)
    assert changes["1D"].start_date == "2026-10-15"
    # 2026-10-09 to piątek; 1W = 7 dni przed 2026-10-16
    assert changes["1W"].start_date == "2026-10-09"
    # 2026-07-16 -> czwartek, sesja
    assert changes["3M"].start_date == "2026-07-16"
    # 2021-10-16 to sobota -> ostatnia sesja przed: piątek 2021-10-15
    assert changes["5Y"].start_date == "2021-10-15"
    assert changes["MAX"].start_date == "2020-01-01"
    assert changes["1Y"].pct == pytest.approx((series[-1][1] / dict(series)["2025-10-16"] - 1) * 100)


def test_short_history_gives_na_not_shorter_period():
    series = _daily("2025-10-17", "2026-10-16", lambda d: 50.0)
    changes = compute_period_changes(series, history_complete=False)
    assert changes["1Y"] is None  # historia zaczyna się dzień PO dacie docelowej
    assert changes["5Y"] is None
    assert changes["MAX"] is None  # ucięta historia (np. EODHD Free) -> N/A, nie "MAX"
    assert changes["3M"] is not None


def test_ref_date_uses_prices_as_of_scan_date_only():
    series = _daily("2025-09-01", "2026-10-16", lambda d: 10.0 if d <= dt.date(2026, 10, 5) else 20.0)
    changes = compute_period_changes(series, ref_date="2026-10-05")
    assert changes["1D"].end_date == "2026-10-05"
    assert changes["1D"].pct == pytest.approx(0.0)


def test_month_end_clamping():
    series = [("2026-02-27", 100.0), ("2026-03-31", 110.0)]
    assert compute_period_changes(series)["1M"].start_date == "2026-02-27"


def test_ctva_spin_off_is_flagged_and_marks_spanning_periods():
    rows = [{"date": f"2026-09-{d:02d}", "close": 77.0, "volume": 4_000_000} for d in range(1, 30)]
    rows += [{"date": "2026-09-30", "close": 77.65, "volume": 4_035_252},
             {"date": "2026-10-01", "close": 12.57, "volume": 88_375_542},
             {"date": "2026-10-02", "close": 11.92, "volume": 78_829_324}]
    anomalies = detect_price_anomalies(rows)
    assert [a.date for a in anomalies] == ["2026-10-01"]
    assert anomalies[0].strong is True
    changes = compute_period_changes([(r["date"], r["close"]) for r in rows])
    assert periods_affected(changes, anomalies) == {"1W", "1M", "MAX"}  # 1D (10-01 -> 10-02) nie obejmuje skoku


def test_normal_moves_are_not_flagged():
    rows = [{"date": f"2026-09-{d:02d}", "close": 100 + d, "volume": 1000} for d in range(1, 29)]
    assert detect_price_anomalies(rows) == []

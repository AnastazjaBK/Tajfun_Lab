"""Testy planu pobrania historycznych cen (Faza 5.3, Price Data Proof
Run) — wartości referencyjne policzone ręcznie."""

from __future__ import annotations

from buffett_scanner.price_history_plan import (
    PriceFetchTask,
    build_price_fetch_plan,
    detect_large_day_over_day_moves,
)
from buffett_scanner.universe_history import TickerInterval

CUTOFF = "2012-01-01"
TODAY = "2026-01-01"

# ---------------------------------------------------------------------------
# build_price_fetch_plan
# ---------------------------------------------------------------------------


def test_build_price_fetch_plan_interval_within_window():
    iv = TickerInterval(ticker="AAA", start_date="2012-01-01", end_date="2015-01-01")
    tasks, unresolved = build_price_fetch_plan([iv], {"AAA": "0001"}, cutoff_date=CUTOFF, today=TODAY)
    assert tasks == [PriceFetchTask(cik="0001", ticker="AAA", from_date="2012-01-01", to_date="2015-01-01")]
    assert unresolved == ()


def test_build_price_fetch_plan_clips_start_date_to_cutoff():
    iv = TickerInterval(ticker="BBB", start_date="2005-01-01", end_date="2020-01-01")
    tasks, _ = build_price_fetch_plan([iv], {"BBB": "0002"}, cutoff_date=CUTOFF, today=TODAY)
    assert tasks == [PriceFetchTask(cik="0002", ticker="BBB", from_date="2012-01-01", to_date="2020-01-01")]


def test_build_price_fetch_plan_open_interval_uses_today_as_end():
    iv = TickerInterval(ticker="CCC", start_date="2018-01-01", end_date=None)
    tasks, _ = build_price_fetch_plan([iv], {"CCC": "0003"}, cutoff_date=CUTOFF, today=TODAY)
    assert tasks == [PriceFetchTask(cik="0003", ticker="CCC", from_date="2018-01-01", to_date="2026-01-01")]


def test_build_price_fetch_plan_interval_entirely_before_cutoff_is_excluded():
    iv = TickerInterval(ticker="DDD", start_date="2005-01-01", end_date="2010-01-01")
    tasks, _ = build_price_fetch_plan([iv], {"DDD": "0004"}, cutoff_date=CUTOFF, today=TODAY)
    assert tasks == []


def test_build_price_fetch_plan_unresolved_ticker_produces_no_task_but_is_reported():
    iv = TickerInterval(ticker="NOPE", start_date="2015-01-01", end_date=None)
    tasks, unresolved = build_price_fetch_plan([iv], {}, cutoff_date=CUTOFF, today=TODAY)
    assert tasks == []
    assert unresolved == ("NOPE",)


def test_build_price_fetch_plan_unresolved_is_sorted_and_deduped():
    intervals = [
        TickerInterval(ticker="ZZZ", start_date="2012-01-01", end_date="2013-01-01"),
        TickerInterval(ticker="ZZZ", start_date="2014-01-01", end_date=None),
        TickerInterval(ticker="AAA", start_date="2012-01-01", end_date=None),
    ]
    tasks, unresolved = build_price_fetch_plan(intervals, {}, cutoff_date=CUTOFF, today=TODAY)
    assert tasks == []
    assert unresolved == ("AAA", "ZZZ")


def test_build_price_fetch_plan_multiple_intervals_same_cik_produce_multiple_tasks():
    """Ticker rename bez opuszczenia indeksu (np. FB->META): dwa
    przedziały tickera, dwa osobne zapytania do FMP pod właściwym
    symbolem dla każdego okresu — scalanie do ciągłego CIK dzieje się
    dopiero w price_daily (ten sam klucz (cik, date))."""
    intervals = [
        TickerInterval(ticker="FB", start_date="2012-05-18", end_date="2021-10-28"),
        TickerInterval(ticker="META", start_date="2021-10-28", end_date=None),
    ]
    resolved = {"FB": "0001326801", "META": "0001326801"}
    tasks, _ = build_price_fetch_plan(intervals, resolved, cutoff_date=CUTOFF, today=TODAY)
    assert len(tasks) == 2
    assert {t.ticker for t in tasks} == {"FB", "META"}
    assert all(t.cik == "0001326801" for t in tasks)


# ---------------------------------------------------------------------------
# detect_large_day_over_day_moves
# ---------------------------------------------------------------------------


def test_detect_large_moves_smooth_series_has_no_candidates():
    rows = [{"date": "2020-01-01", "close": 100}, {"date": "2020-01-02", "close": 102}]
    assert detect_large_day_over_day_moves(rows) == []


def test_detect_large_moves_flags_split_like_drop():
    """Symuluje NIEadjustowany split 4:1 (400 -> 100): -75% w jeden dzień."""
    rows = [{"date": "2020-08-28", "close": 400}, {"date": "2020-08-31", "close": 100}]
    assert detect_large_day_over_day_moves(rows) == [("2020-08-28", "2020-08-31", -75.0)]


def test_detect_large_moves_custom_threshold():
    rows = [{"date": "2020-01-01", "close": 100}, {"date": "2020-01-02", "close": 110}]
    assert detect_large_day_over_day_moves(rows, threshold_pct=35.0) == []
    assert detect_large_day_over_day_moves(rows, threshold_pct=5.0) == [("2020-01-01", "2020-01-02", 10.0)]


def test_detect_large_moves_missing_close_breaks_continuity_without_crash():
    rows = [
        {"date": "2020-01-01", "close": 100},
        {"date": "2020-01-02", "close": None},
        {"date": "2020-01-03", "close": 105},
    ]
    assert detect_large_day_over_day_moves(rows) == []


def test_detect_large_moves_zero_close_never_divides_by_zero():
    rows = [
        {"date": "2020-01-01", "close": 100},
        {"date": "2020-01-02", "close": 0},
        {"date": "2020-01-03", "close": 105},
    ]
    assert detect_large_day_over_day_moves(rows) == []


def test_detect_large_moves_sorts_unsorted_input():
    rows = [{"date": "2020-01-02", "close": 102}, {"date": "2020-01-01", "close": 100}]
    assert detect_large_day_over_day_moves(rows) == []

"""Testy dualnego benchmarku (Faza 5.3c, Decyzja właścicielki
2026-10-04): equal_weighted_pit_universe (PRIMARY) i SPY price return
(SECONDARY), obie konwencją forward_return_pct bez zmian."""

from __future__ import annotations

import pytest

from buffett_scanner.benchmark import compute_benchmark_snapshot
from buffett_scanner.scanner import PriceBar


def _bar(date: str, close: float) -> PriceBar:
    return PriceBar(date=date, open=close, high=close, low=close, close=close, adj_close=close, volume=1000)


def _flat_bars_with_return(decision_close: float, future_close: float) -> list[PriceBar]:
    """Bary na dokładnie (lub bezpośrednio po) każdym targecie horyzontu
    (1m/3m/6m/12m od 2013-01-02), ten sam `future_close` na każdym --
    forward_return_pct wybiera NAJWCZEŚNIEJSZY bar >= target_date, więc
    każdy horyzont musi mieć własny bar >= swojego targetu, inaczej
    dalszy bar "podkradnie" wcześniejszy horyzont."""
    return [
        _bar("2013-01-02", decision_close),
        _bar("2013-02-02", future_close),
        _bar("2013-04-02", future_close),
        _bar("2013-07-02", future_close),
        _bar("2014-01-02", future_close),
    ]


def test_equal_weighted_pit_universe_averages_across_constituents():
    # CIK A: +10% na 1m, CIK B: -10% na 1m -> średnia 0%.
    bars_a = _flat_bars_with_return(100.0, 110.0)
    bars_b = _flat_bars_with_return(100.0, 90.0)
    snapshot = compute_benchmark_snapshot(
        decision_date="2013-01-02",
        pit_universe_ciks_with_sufficient_price=["A", "B"],
        price_bars_by_cik={"A": bars_a, "B": bars_b},
        spy_bars=None,
    )
    assert snapshot.ew_pit_universe_return_1m_pct == pytest.approx(0.0)
    assert snapshot.ew_pit_universe_n_1m == 2


def test_equal_weighted_pit_universe_excludes_ciks_without_decision_price():
    bars_a = _flat_bars_with_return(100.0, 110.0)
    snapshot = compute_benchmark_snapshot(
        decision_date="2013-01-02",
        pit_universe_ciks_with_sufficient_price=["A", "MISSING"],
        price_bars_by_cik={"A": bars_a},  # "MISSING" brak kluczu -> brak cen
        spy_bars=None,
    )
    assert snapshot.ew_pit_universe_n_1m == 1
    assert snapshot.ew_pit_universe_return_1m_pct == pytest.approx(10.0)


def test_equal_weighted_pit_universe_none_when_zero_constituents_have_future_data():
    bars_a = [_bar("2013-01-02", 100.0)]  # zero przyszlych barow -> brak 1m return
    snapshot = compute_benchmark_snapshot(
        decision_date="2013-01-02",
        pit_universe_ciks_with_sufficient_price=["A"],
        price_bars_by_cik={"A": bars_a},
        spy_bars=None,
    )
    assert snapshot.ew_pit_universe_n_1m == 0
    assert snapshot.ew_pit_universe_return_1m_pct is None


def test_spy_benchmark_uses_same_forward_return_convention():
    spy_bars = _flat_bars_with_return(400.0, 420.0)  # +5% na 1m
    snapshot = compute_benchmark_snapshot(
        decision_date="2013-01-02",
        pit_universe_ciks_with_sufficient_price=[],
        price_bars_by_cik={},
        spy_bars=spy_bars,
    )
    assert snapshot.spy_return_1m_pct == pytest.approx(5.0)
    assert snapshot.spy_return_3m_pct == pytest.approx(5.0)


def test_spy_benchmark_none_when_no_spy_data_provided():
    snapshot = compute_benchmark_snapshot(
        decision_date="2013-01-02",
        pit_universe_ciks_with_sufficient_price=[],
        price_bars_by_cik={},
        spy_bars=None,
    )
    assert snapshot.spy_return_1m_pct is None
    assert snapshot.spy_return_12m_pct is None


def test_spy_benchmark_none_when_decision_date_before_any_spy_bar():
    spy_bars = [_bar("2013-06-01", 400.0)]
    snapshot = compute_benchmark_snapshot(
        decision_date="2013-01-02",
        pit_universe_ciks_with_sufficient_price=[],
        price_bars_by_cik={},
        spy_bars=spy_bars,
    )
    assert snapshot.spy_return_1m_pct is None


def test_all_horizons_populated_independently():
    bars_a = [
        _bar("2013-01-02", 100.0),
        _bar("2013-02-02", 101.0),
        _bar("2013-04-02", 103.0),
        _bar("2013-07-02", 106.0),
        _bar("2014-01-02", 112.0),
    ]
    snapshot = compute_benchmark_snapshot(
        decision_date="2013-01-02",
        pit_universe_ciks_with_sufficient_price=["A"],
        price_bars_by_cik={"A": bars_a},
        spy_bars=None,
    )
    assert snapshot.ew_pit_universe_return_1m_pct == pytest.approx(1.0)
    assert snapshot.ew_pit_universe_return_3m_pct == pytest.approx(3.0)
    assert snapshot.ew_pit_universe_return_6m_pct == pytest.approx(6.0)
    assert snapshot.ew_pit_universe_return_12m_pct == pytest.approx(12.0)

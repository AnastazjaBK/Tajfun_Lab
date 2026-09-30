"""Testy planu pobrania historycznych cen (Faza 5.3, Price Data Proof
Run) — wartości referencyjne policzone ręcznie."""

from __future__ import annotations

from buffett_scanner.price_history_plan import (
    PriceFetchTask,
    build_price_fetch_plan,
    detect_large_day_over_day_moves,
    diff_price_fields,
    merge_ticker_price_rows,
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


def test_build_price_fetch_plan_ticker_rename_queries_each_ticker_over_full_cik_span():
    """Ticker rename bez opuszczenia indeksu (FB->META, realny przypadek
    z Proof Run 2026-09-30): OBA tickery są odpytywane o PEŁNE okno
    aktywności CIK (nie tylko własny pod-przedział) — empirycznie
    potwierdzone, że FMP może trzymać całą historię wyłącznie pod
    najnowszym tickerem (META), więc zapytanie o FB w jego 'własnym'
    okresie 2013-2021 zwróciłoby 0 wierszy i cicho zgubiło dane."""
    intervals = [
        TickerInterval(ticker="FB", start_date="2013-12-23", end_date="2022-06-09"),
        TickerInterval(ticker="META", start_date="2022-06-09", end_date=None),
    ]
    resolved = {"FB": "0001326801", "META": "0001326801"}
    tasks, _ = build_price_fetch_plan(intervals, resolved, cutoff_date=CUTOFF, today=TODAY)
    assert len(tasks) == 2
    assert {t.ticker for t in tasks} == {"FB", "META"}
    for t in tasks:
        assert t.cik == "0001326801"
        assert t.from_date == "2013-12-23"  # pełne okno CIK, nie własny przedział tickera
        assert t.to_date == TODAY


def test_build_price_fetch_plan_delisted_cik_never_extends_past_its_own_exit():
    """Kontrola ochrony przed recyklingiem tickera (BBBY, realny
    przypadek): spółka opuściła indeks przed 2026, więc nawet jeśli
    ticker został później przypisany innej spółce, okno zapytania
    kończy się na jej rzeczywistym końcu członkostwa, nie sięga w
    przyszłość poza `today`/`end_date`."""
    iv = TickerInterval(ticker="BBBY", start_date="2012-01-01", end_date="2017-07-26")
    tasks, _ = build_price_fetch_plan([iv], {"BBBY": "0000886158"}, cutoff_date=CUTOFF, today=TODAY)
    assert tasks == [PriceFetchTask(cik="0000886158", ticker="BBBY", from_date="2012-01-01", to_date="2017-07-26")]


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


# ---------------------------------------------------------------------------
# merge_ticker_price_rows
# ---------------------------------------------------------------------------


def _price_row(date, close, **kw):
    defaults = {"open": close, "high": close, "low": close, "adj_close": close, "volume": 1000}
    defaults.update(kw)
    return {"date": date, "close": close, **defaults}


def test_merge_single_ticker_no_overlap_passes_through():
    rows_by_ticker = {"AAA": [_price_row("2020-01-01", 100.0), _price_row("2020-01-02", 101.0)]}
    result = merge_ticker_price_rows("0001", rows_by_ticker)
    assert len(result.merged) == 2
    assert result.conflicts == []
    assert result.merged[0].source_tickers == ("AAA",)


def test_merge_two_tickers_agreeing_on_same_date_deduplicates_deterministically():
    """FB i META oba zwracają wiersz dla tej samej daty (nadmiarowa,
    ale zgodna odpowiedź) — jeden scalony wiersz, source_tickers
    zawiera OBA tickery, posortowane alfabetycznie."""
    rows_by_ticker = {
        "FB": [_price_row("2020-01-01", 200.0)],
        "META": [_price_row("2020-01-01", 200.0)],
    }
    result = merge_ticker_price_rows("0001326801", rows_by_ticker)
    assert len(result.merged) == 1
    assert result.merged[0].source_tickers == ("FB", "META")
    assert result.conflicts == []


def test_merge_two_tickers_disagreeing_on_same_date_is_flagged_not_silently_resolved():
    rows_by_ticker = {
        "FB": [_price_row("2020-01-01", 200.0)],
        "META": [_price_row("2020-01-01", 250.0)],
    }
    result = merge_ticker_price_rows("0001326801", rows_by_ticker)
    assert result.merged == []  # niepewna data NIE trafia do wyniku
    assert len(result.conflicts) == 1
    conflict = result.conflicts[0]
    assert conflict.ticker_a == "FB"
    assert conflict.ticker_b == "META"
    assert conflict.row_a["close"] == 200.0
    assert conflict.row_b["close"] == 250.0


def test_merge_non_overlapping_dates_from_different_tickers_both_kept():
    rows_by_ticker = {
        "FB": [_price_row("2020-01-01", 200.0)],
        "META": [_price_row("2020-06-01", 210.0)],
    }
    result = merge_ticker_price_rows("0001326801", rows_by_ticker)
    assert len(result.merged) == 2
    assert result.conflicts == []
    assert {m.source_tickers for m in result.merged} == {("FB",), ("META",)}


def test_merge_small_difference_within_tolerance_is_not_a_conflict():
    rows_by_ticker = {
        "FB": [_price_row("2020-01-01", 200.00)],
        "META": [_price_row("2020-01-01", 200.005)],  # różnica 0.005 < podłoga bezwzględna 0.01
    }
    result = merge_ticker_price_rows("0001326801", rows_by_ticker)
    assert len(result.merged) == 1
    assert result.conflicts == []


def test_merge_relative_tolerance_absorbs_rounding_noise_on_expensive_stock():
    """Realny przypadek z Proof Run (2026-09-30, ANTM/ELV ~$180-260):
    różnica 0.05 na akcji wycenianej ~$726 to 0,007% — szum zaokrąglenia
    dostawcy, nie realna rozbieżność. Stara stała tolerancja 0.01
    błędnie oznaczyłaby to jako konflikt; względna tolerancja (0,1%)
    poprawnie to akceptuje."""
    rows_by_ticker = {
        "FB": [_price_row("2025-06-26", 726.09)],
        "META": [_price_row("2025-06-26", 726.14)],  # różnica 0.05
    }
    result = merge_ticker_price_rows("0001326801", rows_by_ticker)
    assert len(result.merged) == 1
    assert result.conflicts == []


def test_merge_relative_tolerance_still_catches_conflict_on_cheap_stock():
    """Podłoga bezwzględna (0.01) chroni tanie akcje: przy cenie ~$2,00
    różnica 0.02 to 1% — realna rozbieżność, nie szum — wciąż
    wykrywana mimo tolerancji względnej."""
    rows_by_ticker = {
        "FB": [_price_row("2020-01-01", 2.00)],
        "META": [_price_row("2020-01-01", 2.02)],
    }
    result = merge_ticker_price_rows("0001326801", rows_by_ticker)
    assert result.merged == []
    assert len(result.conflicts) == 1


def test_diff_price_fields_reports_only_mismatching_fields():
    """Diagnostyka konfliktu: `close` może być zgodne, podczas gdy
    `open`/`high`/`low`/`adj_close` się różnią — raport musi to pokazać,
    nie tylko `close` (defekt raportowania znaleziony w realnym Proof
    Run: konflikt ANTM/ELV z identycznym `close` był nie do
    zdiagnozowania bez tej funkcji)."""
    row_a = {"date": "2017-10-13", "open": 180.0, "high": 184.0, "low": 179.0, "close": 183.83, "adj_close": 183.83}
    row_b = {"date": "2017-10-13", "open": 181.5, "high": 184.0, "low": 179.0, "close": 183.83, "adj_close": 183.83}
    diff = diff_price_fields(row_a, row_b)
    assert diff == {"open": (180.0, 181.5)}

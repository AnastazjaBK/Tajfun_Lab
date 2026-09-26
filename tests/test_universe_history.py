"""Testy analizy historycznego składu S&P 500 (Faza 5, punkt 5.2) —
wartości referencyjne policzone ręcznie na małych, syntetycznych
przykładach (ten sam duch co `test_point_in_time.py`)."""

from __future__ import annotations

from buffett_scanner.universe_history import (
    ComponentsRow,
    build_ticker_intervals,
    compare_ticker_sets,
    distinct_tickers,
    parse_components_csv,
    resolve_tickers_to_cik,
    tickers_as_of,
    window_from_cutoff,
)

# ---------------------------------------------------------------------------
# parse_components_csv
# ---------------------------------------------------------------------------


def test_parse_components_csv_parses_and_sorts_by_date():
    # Prawdziwe źródło cytuje pole tickers (bo zawiera przecinki) —
    # dokładnie tak, jak potwierdzone bezpośrednim pobraniem w tej sesji.
    csv_text = (
        'date,tickers\n'
        '2012-03-01,"AAA,BBB"\n'
        '2012-01-01,"AAA,BBB,CCC"\n'
    )
    rows = parse_components_csv(csv_text)
    assert len(rows) == 2
    assert rows[0].date == "2012-01-01"
    assert rows[0].tickers == ("AAA", "BBB", "CCC")
    assert rows[1].date == "2012-03-01"


def test_parse_components_csv_skips_rows_missing_date_or_tickers():
    csv_text = 'date,tickers\n' ',"AAA,BBB"\n' '2012-01-01,\n' '2012-02-01,AAA\n'
    rows = parse_components_csv(csv_text)
    assert len(rows) == 1
    assert rows[0].date == "2012-02-01"


def test_parse_components_csv_strips_whitespace_around_tickers():
    csv_text = 'date,tickers\n2012-01-01," AAA , BBB "\n'
    rows = parse_components_csv(csv_text)
    assert rows[0].tickers == ("AAA", "BBB")


# ---------------------------------------------------------------------------
# window_from_cutoff
# ---------------------------------------------------------------------------


def _row(date: str, *tickers: str) -> ComponentsRow:
    return ComponentsRow(date=date, tickers=tuple(tickers))


def test_window_from_cutoff_includes_baseline_and_later_rows():
    rows = [
        _row("2011-06-01", "A", "B"),
        _row("2011-12-30", "A", "B", "C"),
        _row("2012-03-01", "A", "C", "D"),
        _row("2013-01-01", "A", "D"),
    ]
    window = window_from_cutoff(rows, "2012-01-01")
    assert [r.date for r in window] == ["2011-12-30", "2012-03-01", "2013-01-01"]


def test_window_from_cutoff_returns_empty_when_no_row_before_cutoff():
    rows = [_row("2015-01-01", "A")]
    assert window_from_cutoff(rows, "2012-01-01") == []


def test_window_from_cutoff_exact_cutoff_date_is_the_baseline():
    rows = [_row("2012-01-01", "A", "B"), _row("2012-06-01", "A")]
    window = window_from_cutoff(rows, "2012-01-01")
    assert window[0].date == "2012-01-01"


# ---------------------------------------------------------------------------
# distinct_tickers
# ---------------------------------------------------------------------------


def test_distinct_tickers_union_across_all_rows():
    window = [_row("2012-01-01", "A", "B"), _row("2012-06-01", "B", "C")]
    assert distinct_tickers(window) == {"A", "B", "C"}


# ---------------------------------------------------------------------------
# tickers_as_of — dla walidacji krzyżowej z niezależnymi źródłami (IVV)
# ---------------------------------------------------------------------------


def test_tickers_as_of_returns_latest_row_on_or_before_date():
    rows = [_row("2012-01-01", "A", "B"), _row("2012-06-01", "A", "C")]
    assert tickers_as_of(rows, "2012-12-31") == {"A", "C"}


def test_tickers_as_of_exact_date_is_inclusive():
    rows = [_row("2012-06-01", "A", "C")]
    assert tickers_as_of(rows, "2012-06-01") == {"A", "C"}


def test_tickers_as_of_none_when_nothing_before_date():
    rows = [_row("2012-06-01", "A")]
    assert tickers_as_of(rows, "2012-01-01") is None


# ---------------------------------------------------------------------------
# compare_ticker_sets
# ---------------------------------------------------------------------------


def test_compare_ticker_sets_computes_counts_and_differences():
    a = {"AAPL", "MSFT", "KO"}
    b = {"AAPL", "MSFT", "IBM"}
    result = compare_ticker_sets(a, b)
    assert result.count_a == 3
    assert result.count_b == 3
    assert result.intersection_count == 2
    assert result.only_in_a == ("KO",)
    assert result.only_in_b == ("IBM",)


# ---------------------------------------------------------------------------
# build_ticker_intervals — rdzeń logiki diff, wartości policzone ręcznie
# ---------------------------------------------------------------------------


def test_build_ticker_intervals_handles_entries_exits_and_still_open():
    window = [
        _row("2012-01-01", "A", "B", "C"),  # baseline
        _row("2012-03-01", "A", "C", "D"),  # B wypada, D wchodzi
        _row("2012-06-01", "A", "D"),  # C wypada
        _row("2012-09-01", "A", "D", "E"),  # E wchodzi
    ]
    intervals = build_ticker_intervals(window, cutoff_date="2012-01-01")
    by_ticker = {iv.ticker: iv for iv in intervals}

    assert by_ticker["A"].start_date == "2012-01-01"
    assert by_ticker["A"].end_date is None  # obecny do końca źródła

    assert by_ticker["B"].start_date == "2012-01-01"
    assert by_ticker["B"].end_date == "2012-03-01"  # data wiersza, w którym już go nie ma

    assert by_ticker["C"].start_date == "2012-01-01"
    assert by_ticker["C"].end_date == "2012-06-01"

    assert by_ticker["D"].start_date == "2012-03-01"  # wszedł dopiero tutaj
    assert by_ticker["D"].end_date is None

    assert by_ticker["E"].start_date == "2012-09-01"
    assert by_ticker["E"].end_date is None

    assert len(intervals) == 5  # każdy ticker dokładnie jeden przedział w tym scenariuszu


def test_build_ticker_intervals_reentry_produces_two_separate_intervals():
    """Ticker, który wypada i wraca później, to DWA osobne przedziały
    członkostwa, nie jeden ciągły — istotne dla poprawnego liczenia
    ekspozycji w backteście."""
    window = [
        _row("2012-01-01", "A", "B"),
        _row("2012-03-01", "A"),  # B wypada
        _row("2012-06-01", "A", "B"),  # B wraca
    ]
    intervals = build_ticker_intervals(window, cutoff_date="2012-01-01")
    b_intervals = sorted((iv.start_date, iv.end_date) for iv in intervals if iv.ticker == "B")
    assert b_intervals == [("2012-01-01", "2012-03-01"), ("2012-06-01", None)]


def test_build_ticker_intervals_empty_window_returns_empty():
    assert build_ticker_intervals([], cutoff_date="2012-01-01") == []


# ---------------------------------------------------------------------------
# resolve_tickers_to_cik — nigdy nie zgadujemy, CIK_UNRESOLVED jest jawny
# ---------------------------------------------------------------------------


def test_resolve_tickers_to_cik_splits_resolved_and_unresolved():
    sec_map = {"AAPL": "0000320193", "MSFT": "0000789019"}
    result = resolve_tickers_to_cik({"AAPL", "MSFT", "DELISTEDCO"}, sec_map)
    assert result.resolved == {"AAPL": "0000320193", "MSFT": "0000789019"}
    assert result.unresolved == ("DELISTEDCO",)
    assert result.resolved_via_format_variant == {}


def test_resolve_tickers_to_cik_never_fabricates_a_cik_for_unknown_ticker():
    result = resolve_tickers_to_cik({"NOPE"}, {})
    assert result.resolved == {}
    assert result.unresolved == ("NOPE",)


def test_resolve_tickers_to_cik_falls_back_to_dash_variant_of_dotted_ticker():
    """Realny przypadek z Fazy 5.2: BRK.B (Berkshire Hathaway Class B)
    nie trafia bezpośrednio, ale mapowanie SEC ma go pod BRK-B."""
    sec_map = {"BRK-B": "0001067983"}
    result = resolve_tickers_to_cik({"BRK.B"}, sec_map)
    assert result.resolved == {"BRK.B": "0001067983"}
    assert result.resolved_via_format_variant == {"BRK.B": "BRK-B"}
    assert result.unresolved == ()


def test_resolve_tickers_to_cik_falls_back_to_dot_variant_of_dashed_ticker():
    sec_map = {"FOO.A": "0000000001"}
    result = resolve_tickers_to_cik({"FOO-A"}, sec_map)
    assert result.resolved == {"FOO-A": "0000000001"}
    assert result.resolved_via_format_variant == {"FOO-A": "FOO.A"}


def test_resolve_tickers_to_cik_direct_match_takes_priority_over_variant():
    sec_map = {"BRK.B": "0001111111", "BRK-B": "0002222222"}
    result = resolve_tickers_to_cik({"BRK.B"}, sec_map)
    assert result.resolved == {"BRK.B": "0001111111"}
    assert result.resolved_via_format_variant == {}


def test_resolve_tickers_to_cik_ticker_rename_is_not_recovered_by_format_variant():
    """FB -> META to zmiana nazwy/tickera, nie formatu zapisu — nie
    powinna być (i nie jest) naprawiana przez normalizację kropka/myślnik,
    bo to inny problem (wymaga crosswalka historycznego)."""
    sec_map = {"META": "0001326801"}
    result = resolve_tickers_to_cik({"FB"}, sec_map)
    assert result.resolved == {}
    assert result.unresolved == ("FB",)


def test_resolve_tickers_to_cik_unresolved_is_sorted():
    result = resolve_tickers_to_cik({"ZZZ", "AAA", "MMM"}, {})
    assert result.unresolved == ("AAA", "MMM", "ZZZ")

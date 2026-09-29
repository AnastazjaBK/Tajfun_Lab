"""Testy parsowania/rekonstrukcji logu zdarzeń FMP (Faza 5.2, krok 1/3)
— wartości referencyjne policzone ręcznie na małych przykładach, w
tym scenariusz naśladujący realne znalezisko z v1.31 (rozjazd date
vs dateAdded o 1 dzień dla starych wierszy)."""

from __future__ import annotations

from buffett_scanner.fmp_sp500_events import (
    ChangeEvent,
    collect_fmp_ticker_names,
    compare_change_events,
    find_date_added_mismatches,
    find_tickers_with_multiple_names,
    fmp_change_events,
    fmp_change_events_by_date_added,
    names_plausibly_match,
    normalize_company_name_tokens,
    parse_fmp_events,
    reconstruct_membership_backward,
    resolve_fmp_tickers,
)

# ---------------------------------------------------------------------------
# parse_fmp_events
# ---------------------------------------------------------------------------


def test_parse_fmp_events_parses_and_sorts_by_date():
    raw = [
        {"date": "2020-03-01", "dateAdded": "March 1, 2020", "symbol": "BBB",
         "addedSecurity": "BBB Inc", "removedTicker": "AAA", "removedSecurity": "AAA Inc", "reason": "X"},
        {"date": "2012-01-15", "dateAdded": "January 15, 2012", "symbol": "CCC",
         "addedSecurity": "CCC Inc", "removedTicker": "", "removedSecurity": "", "reason": ""},
    ]
    events = parse_fmp_events(raw)
    assert len(events) == 2
    assert events[0].date == "2012-01-15"
    assert events[0].added_symbol == "CCC"
    assert events[0].removed_ticker is None  # pusty string -> None
    assert events[1].removed_ticker == "AAA"


def test_parse_fmp_events_skips_rows_missing_date_or_symbol():
    raw = [
        {"date": None, "symbol": "AAA"},
        {"date": "2020-01-01", "symbol": ""},
        {"date": "2020-01-01", "symbol": "BBB"},
    ]
    events = parse_fmp_events(raw)
    assert len(events) == 1
    assert events[0].added_symbol == "BBB"


# ---------------------------------------------------------------------------
# find_date_added_mismatches
# ---------------------------------------------------------------------------


def _event(date: str, date_added_raw: str) -> "object":
    from buffett_scanner.fmp_sp500_events import FmpConstituentEvent
    return FmpConstituentEvent(
        date=date, date_added_raw=date_added_raw, added_symbol="X",
        added_security="X Inc", removed_ticker=None, removed_security=None, reason="",
    )


def test_find_date_added_mismatches_detects_real_v131_scenario():
    """Dokładnie odtwarza realne znalezisko: date='1957-03-03',
    dateAdded='March 04, 1957' -> rozjazd o 1 dzień."""
    events = [_event("1957-03-03", "March 04, 1957")]
    mismatches = find_date_added_mismatches(events)
    assert len(mismatches) == 1
    assert mismatches[0][1] == "1957-03-04"


def test_find_date_added_mismatches_no_mismatch_when_dates_agree():
    events = [_event("2026-09-21", "September 21, 2026")]
    assert find_date_added_mismatches(events) == []


def test_find_date_added_mismatches_flags_unparseable_date_added():
    events = [_event("2020-01-01", "not a date")]
    mismatches = find_date_added_mismatches(events)
    assert len(mismatches) == 1
    assert mismatches[0][1] == "NIEPARSOWALNE"


# ---------------------------------------------------------------------------
# reconstruct_membership_backward — rdzeń logiki, wartości policzone ręcznie
# ---------------------------------------------------------------------------


def _raw_event(date, symbol, removed_ticker=""):
    return {"date": date, "dateAdded": date, "symbol": symbol,
            "addedSecurity": "", "removedTicker": removed_ticker, "removedSecurity": "", "reason": ""}


def test_reconstruct_membership_backward_undoes_events_after_as_of_date():
    """Dzisiejszy skład: {A, D}. Historia zdarzeń (rosnąco):
    2012-03-01: B wchodzi zamiast C (C usunięty)
    2015-06-01: D wchodzi zamiast B (B usunięty)
    Odtworzenie na 2013-01-01 (między zdarzeniami) musi cofnąć TYLKO
    zdarzenie z 2015-06-01 (bo jest PO badanej dacie), zostawiając
    zdarzenie z 2012-03-01 nietknięte (już się wydarzyło)."""
    raw = [
        {"date": "2012-03-01", "dateAdded": "2012-03-01", "symbol": "B",
         "addedSecurity": "", "removedTicker": "C", "removedSecurity": "", "reason": ""},
        {"date": "2015-06-01", "dateAdded": "2015-06-01", "symbol": "D",
         "addedSecurity": "", "removedTicker": "B", "removedSecurity": "", "reason": ""},
    ]
    events = parse_fmp_events(raw)
    current_members = {"A", "D"}

    result = reconstruct_membership_backward(events, current_members, "2013-01-01")
    # Cofamy zdarzenie z 2015-06-01: usuwamy D (dodany wtedy), przywracamy B.
    # Zdarzenie z 2012-03-01 NIE jest cofane (already happened by 2013-01-01).
    assert result == {"A", "B"}


def test_reconstruct_membership_backward_before_any_events_undoes_all():
    raw = [
        {"date": "2012-03-01", "dateAdded": "2012-03-01", "symbol": "B",
         "addedSecurity": "", "removedTicker": "C", "removedSecurity": "", "reason": ""},
    ]
    events = parse_fmp_events(raw)
    result = reconstruct_membership_backward(events, {"A", "B"}, "2011-01-01")
    assert result == {"A", "C"}


def test_reconstruct_membership_backward_today_returns_current_members_unchanged():
    raw = [
        {"date": "2012-03-01", "dateAdded": "2012-03-01", "symbol": "B",
         "addedSecurity": "", "removedTicker": "C", "removedSecurity": "", "reason": ""},
    ]
    events = parse_fmp_events(raw)
    result = reconstruct_membership_backward(events, {"A", "B"}, "2026-01-01")
    assert result == {"A", "B"}


# ---------------------------------------------------------------------------
# fmp_change_events / compare_change_events
# ---------------------------------------------------------------------------


def test_fmp_change_events_filters_by_cutoff_and_emits_add_and_remove():
    raw = [
        {"date": "2011-01-01", "dateAdded": "2011-01-01", "symbol": "OLD",
         "addedSecurity": "", "removedTicker": "", "removedSecurity": "", "reason": ""},
        {"date": "2012-03-01", "dateAdded": "2012-03-01", "symbol": "B",
         "addedSecurity": "", "removedTicker": "C", "removedSecurity": "", "reason": ""},
    ]
    events = parse_fmp_events(raw)
    result = fmp_change_events(events, cutoff_date="2012-01-01")
    assert result == {
        ChangeEvent(date="2012-03-01", ticker="B", action="ADD"),
        ChangeEvent(date="2012-03-01", ticker="C", action="REMOVE"),
    }


def test_fmp_change_events_by_date_added_uses_parsed_date_added_as_event_date():
    raw = [
        {"date": "2020-06-01", "dateAdded": "June 03, 2020", "symbol": "X",
         "addedSecurity": "", "removedTicker": "", "removedSecurity": "", "reason": ""},
    ]
    events = parse_fmp_events(raw)
    result, unparseable = fmp_change_events_by_date_added(events, cutoff_date="2012-01-01")
    assert result == {ChangeEvent(date="2020-06-03", ticker="X", action="ADD")}
    assert unparseable == ()


def test_fmp_change_events_by_date_added_falls_back_to_date_when_unparseable():
    raw = [
        {"date": "2020-06-01", "dateAdded": "bogus", "symbol": "Y",
         "addedSecurity": "", "removedTicker": "Z", "removedSecurity": "", "reason": ""},
    ]
    events = parse_fmp_events(raw)
    result, unparseable = fmp_change_events_by_date_added(events, cutoff_date="2012-01-01")
    assert result == {
        ChangeEvent(date="2020-06-01", ticker="Y", action="ADD"),
        ChangeEvent(date="2020-06-01", ticker="Z", action="REMOVE"),
    }
    assert unparseable == ("Y",)


def test_fmp_change_events_by_date_added_cutoff_filters_by_original_date_field():
    """Filtr `cutoff_date` musi działać na oryginalnym `date` (jedynym
    gwarantowanym ISO), nawet jeśli sparsowany `dateAdded` przesunąłby
    zdarzenie na drugą stronę progu."""
    raw = [
        {"date": "2011-12-31", "dateAdded": "January 02, 2012", "symbol": "W",
         "addedSecurity": "", "removedTicker": "", "removedSecurity": "", "reason": ""},
    ]
    events = parse_fmp_events(raw)
    result, unparseable = fmp_change_events_by_date_added(events, cutoff_date="2012-01-01")
    assert result == frozenset()
    assert unparseable == ()


def test_compare_change_events_computes_common_and_differences():
    a = frozenset({
        ChangeEvent(date="2012-03-01", ticker="B", action="ADD"),
        ChangeEvent(date="2012-03-01", ticker="C", action="REMOVE"),
    })
    b = frozenset({
        ChangeEvent(date="2012-03-01", ticker="B", action="ADD"),
        ChangeEvent(date="2013-01-01", ticker="Z", action="ADD"),
    })
    cmp = compare_change_events(a, b)
    assert cmp.common == {ChangeEvent(date="2012-03-01", ticker="B", action="ADD")}
    assert cmp.only_a == {ChangeEvent(date="2012-03-01", ticker="C", action="REMOVE")}
    assert cmp.only_b == {ChangeEvent(date="2013-01-01", ticker="Z", action="ADD")}


# ---------------------------------------------------------------------------
# normalize_company_name_tokens / names_plausibly_match — reguła v1,
# wartości ręcznie wyprowadzone z definicji (2 * overlap > shorter_len)
# ---------------------------------------------------------------------------


def test_normalize_company_name_tokens_strips_punctuation_and_legal_suffixes():
    assert normalize_company_name_tokens("Apple Inc.") == frozenset({"apple"})
    assert normalize_company_name_tokens("The Coca-Cola Company") == frozenset({"coca", "cola"})


def test_normalize_company_name_tokens_empty_or_pure_noise_name_is_empty_set():
    assert normalize_company_name_tokens("") == frozenset()
    assert normalize_company_name_tokens("The Inc. Co.") == frozenset()


def test_names_plausibly_match_minor_formatting_difference_matches():
    """{"apple"} vs {"apple"}: overlap=1, shorter=1 -> 2*1=2 > 1 -> True."""
    assert names_plausibly_match("Apple Inc.", "Apple Inc") is True


def test_names_plausibly_match_single_shared_word_among_two_is_not_enough():
    """Realny przypadek graniczny reguły v1: General Electric i General
    Dynamics dzielą tylko "general" (overlap=1, shorter=2) ->
    2*1=2 > 2 jest False -> to MUSZĄ pozostać różne spółki."""
    assert names_plausibly_match("General Electric", "General Dynamics") is False


def test_names_plausibly_match_completely_different_names_do_not_match():
    assert names_plausibly_match("Meta Platforms, Inc.", "Facebook, Inc.") is False


def test_names_plausibly_match_empty_name_never_matches():
    assert names_plausibly_match("", "Apple Inc.") is False
    assert names_plausibly_match("Apple Inc.", "") is False


# ---------------------------------------------------------------------------
# collect_fmp_ticker_names
# ---------------------------------------------------------------------------


def test_collect_fmp_ticker_names_keeps_latest_name_per_ticker():
    raw = [
        {"date": "2012-01-01", "dateAdded": "2012-01-01", "symbol": "AAA",
         "addedSecurity": "Old Name Inc", "removedTicker": "", "removedSecurity": "", "reason": ""},
        {"date": "2020-01-01", "dateAdded": "2020-01-01", "symbol": "ZZZ",
         "addedSecurity": "", "removedTicker": "AAA", "removedSecurity": "New Name Inc", "reason": ""},
    ]
    events = parse_fmp_events(raw)
    names = collect_fmp_ticker_names(events)
    # AAA pojawia się w obu zdarzeniach — wygrywa nazwa z późniejszej daty.
    assert names["AAA"] == "New Name Inc"
    assert "ZZZ" not in names  # brak addedSecurity w tym wierszu -> nie wpisane wcale


def test_collect_fmp_ticker_names_ignores_events_without_a_name():
    raw = [
        {"date": "2012-01-01", "dateAdded": "2012-01-01", "symbol": "BBB",
         "addedSecurity": "", "removedTicker": "", "removedSecurity": "", "reason": ""},
    ]
    events = parse_fmp_events(raw)
    assert collect_fmp_ticker_names(events) == {}


# ---------------------------------------------------------------------------
# find_tickers_with_multiple_names — wewnętrzna spójność logu FMP
# ---------------------------------------------------------------------------


def test_find_tickers_with_multiple_names_flags_mutually_inconsistent_names():
    raw = [
        {"date": "2000-01-01", "dateAdded": "2000-01-01", "symbol": "AAA",
         "addedSecurity": "Alpha Corp", "removedTicker": "", "removedSecurity": "", "reason": ""},
        {"date": "2015-01-01", "dateAdded": "2015-01-01", "symbol": "XXX",
         "addedSecurity": "", "removedTicker": "AAA", "removedSecurity": "Beta Inc", "reason": ""},
    ]
    events = parse_fmp_events(raw)
    result = find_tickers_with_multiple_names(events)
    assert result == {"AAA": frozenset({"Alpha Corp", "Beta Inc"})}


def test_find_tickers_with_multiple_names_does_not_flag_consistent_spelling_variants():
    raw = [
        {"date": "2000-01-01", "dateAdded": "2000-01-01", "symbol": "BBB",
         "addedSecurity": "Beta Co", "removedTicker": "", "removedSecurity": "", "reason": ""},
        {"date": "2015-01-01", "dateAdded": "2015-01-01", "symbol": "XXX",
         "addedSecurity": "", "removedTicker": "BBB", "removedSecurity": "Beta Co.", "reason": ""},
    ]
    events = parse_fmp_events(raw)
    assert find_tickers_with_multiple_names(events) == {}


def test_find_tickers_with_multiple_names_single_name_ticker_not_flagged():
    raw = [
        {"date": "2000-01-01", "dateAdded": "2000-01-01", "symbol": "CCC",
         "addedSecurity": "Gamma Inc", "removedTicker": "", "removedSecurity": "", "reason": ""},
    ]
    events = parse_fmp_events(raw)
    assert find_tickers_with_multiple_names(events) == {}


# ---------------------------------------------------------------------------
# resolve_fmp_tickers — nigdy nie zgadujemy CIK; niezgodność nazwy jest
# jawnie oznaczana, nie usuwa wyniku z resolved
# ---------------------------------------------------------------------------


def test_resolve_fmp_tickers_direct_match_with_consistent_name():
    names = {"AAPL": "Apple Inc."}
    sec_map = {"AAPL": "0000320193"}
    sec_titles = {"AAPL": "Apple Inc."}
    result = resolve_fmp_tickers(names, sec_map, sec_titles)
    assert result.resolved == {"AAPL": "0000320193"}
    assert result.resolved_via_format_variant == {}
    assert result.unresolved == ()
    assert result.name_mismatch_suspicious == {}


def test_resolve_fmp_tickers_falls_back_to_format_variant_and_checks_name_under_that_variant():
    names = {"BRK.B": "Berkshire Hathaway Inc."}
    sec_map = {"BRK-B": "0001067983"}
    sec_titles = {"BRK-B": "Berkshire Hathaway Inc"}
    result = resolve_fmp_tickers(names, sec_map, sec_titles)
    assert result.resolved == {"BRK.B": "0001067983"}
    assert result.resolved_via_format_variant == {"BRK.B": "BRK-B"}
    assert result.name_mismatch_suspicious == {}


def test_resolve_fmp_tickers_unresolved_ticker_never_gets_a_fabricated_cik():
    names = {"DELISTEDCO": "Some Old Company"}
    result = resolve_fmp_tickers(names, {}, {})
    assert result.resolved == {}
    assert result.unresolved == ("DELISTEDCO",)


def test_resolve_fmp_tickers_flags_name_mismatch_but_keeps_cik_in_resolved():
    """Symuluje recykling tickera: SEC dziś mapuje 'XYZ' na zupełnie inną
    spółkę niż ta, pod którą FMP historycznie znało ten ticker. CIK
    pozostaje w `resolved` (to jedyny potwierdzony fakt przez ticker),
    ale przypadek trafia jawnie do `name_mismatch_suspicious`."""
    names = {"XYZ": "Old Historical Company"}
    sec_map = {"XYZ": "0009999999"}
    sec_titles = {"XYZ": "Brand New Unrelated Corp"}
    result = resolve_fmp_tickers(names, sec_map, sec_titles)
    assert result.resolved == {"XYZ": "0009999999"}
    assert result.name_mismatch_suspicious == {
        "XYZ": {
            "cik": "0009999999",
            "sec_title": "Brand New Unrelated Corp",
            "fmp_name": "Old Historical Company",
        }
    }


def test_resolve_fmp_tickers_missing_sec_title_does_not_produce_mismatch():
    """Brak tytułu SEC dla danego tickera (np. luka w danych) nie może
    być interpretowany jako niezgodność — po prostu nie da się
    sprawdzić, więc nie zgadujemy w żadną stronę."""
    names = {"AAA": "Alpha Corp"}
    sec_map = {"AAA": "0000000001"}
    result = resolve_fmp_tickers(names, sec_map, sec_titles={})
    assert result.resolved == {"AAA": "0000000001"}
    assert result.name_mismatch_suspicious == {}


def test_resolve_fmp_tickers_unresolved_is_sorted():
    names = {"ZZZ": "Z Corp", "AAA": "A Corp"}
    result = resolve_fmp_tickers(names, {}, {})
    assert result.unresolved == ("AAA", "ZZZ")

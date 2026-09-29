"""Proof Run: domknięcie OPEN BLOCKER 2, ponowna walidacja po CIK i po
zastosowaniu reguły tolerancji dat (Faza 5.2, v1.34, części 1+5 zadania
zleconego po zatwierdzeniu wyników kroku 3). WYŁĄCZNIE DIAGNOSTYCZNE —
nie zapisuje nic do bazy, nie buduje finalnego `universe_membership`.

    python -m buffett_scanner.providers.universe_cik_revalidation_smoketest

Wymaga FMP_API_KEY (plan Premium) i SEC_EDGAR_USER_AGENT (dane
kontaktowe wymagane przez SEC). fja05680/sp500 darmowe, bez klucza.

Raportuje (5 punktów zleconych po v1.33):
1. Rozwiązanie CIK dla tickerów obu źródeł (fja05680 i FMP) — coverage,
   unresolved (jawnie, nigdy nie zgadywane), oraz `name_mismatch_
   suspicious` dla FMP (możliwy recykling tickera).
2. fja05680 pozostaje kanoniczne — raport rozbieżności z FMP jest
   wyłącznie diagnostyczny, NIC tu nie nadpisuje kanonicznego składu.
3. Krzywą wpływu tolerancji dat (0-5 dni) na liczbę dopasowań — reguła
   dopasowania jest wersjonowana i jej wpływ jest MIERZONY, nie
   zakładany.
4. Empiryczne porównanie pola `date` vs `dateAdded` jako klucza daty
   zdarzenia FMP — wybór pola wynika z krzywych, nie z góry.
5. Finalny raport po CIK + tolerancji: rzeczywiste konflikty po
   odfiltrowaniu różnic tickerów i przesunięć dat, oraz wpływ na
   rekonstrukcję membership (ticker-poziom vs CIK-poziom) na
   reprezentatywnych datach 2012-2026 (Decyzja D14 — NIE rozszerzamy
   zakresu przed 2012).
"""

from __future__ import annotations

import sys

from buffett_scanner.config import load_config
from buffett_scanner.fmp_sp500_events import (
    ChangeEvent,
    collect_fmp_ticker_names,
    find_tickers_with_multiple_names,
    fmp_change_events,
    fmp_change_events_by_date_added,
    parse_fmp_events,
    reconstruct_membership_backward,
    resolve_fmp_tickers,
)
from buffett_scanner.providers.fmp import FMPClient, FMPError
from buffett_scanner.providers.sec_edgar import SecEdgarClient, SecEdgarError
from buffett_scanner.providers.sp500_history import Sp500HistoryError, fetch_components_csv
from buffett_scanner.universe_cik_reconciliation import (
    change_events_to_cik_events,
    match_cik_events_with_tolerance,
    pick_plateau_tolerance,
    tolerance_impact_curve,
)
from buffett_scanner.universe_history import (
    build_ticker_intervals,
    compare_ticker_sets,
    distinct_tickers,
    parse_components_csv,
    resolve_tickers_to_cik,
    tickers_as_of,
    window_from_cutoff,
)

CUTOFF = "2012-01-01"  # Decyzja D14 — nie rozszerzamy zakresu przed 2012
SAMPLE_DATES = ["2012-01-31", "2018-12-31", "2026-09-01"]
TOLERANCE_RANGE = range(0, 6)  # 0..5 dni, do empirycznego wyboru progu (plateau)


def _print_curve(label: str, curve: list[dict]) -> None:
    print(f"  {label}:")
    for p in curve:
        print(
            f"    tolerancja={p['tolerance_days']}d  dopasowane={p['matched_count']}  "
            f"tylko_kanoniczne={p['only_canonical_count']}  tylko_walidator={p['only_validator_count']}"
        )


def _field_dominance(curve_a: list[dict], curve_b: list[dict]) -> str | None:
    """Zwraca nazwę pola, którego krzywa ma matched_count >= drugiej
    PRZY KAŻDEJ testowanej tolerancji (jednoznaczna dominacja), albo
    `None`, jeśli żadne pole nie dominuje jednoznacznie w całym
    zakresie — wtedy wybór NIE jest podejmowany automatycznie."""
    a_dominates = all(a["matched_count"] >= b["matched_count"] for a, b in zip(curve_a, curve_b))
    b_dominates = all(b["matched_count"] >= a["matched_count"] for a, b in zip(curve_a, curve_b))
    if a_dominates and not b_dominates:
        return "date"
    if b_dominates and not a_dominates:
        return "dateAdded"
    return None


def main() -> int:
    config = load_config()
    try:
        api_key = config.data_provider.resolve_api_key()
        user_agent = config.sources.sec_edgar.resolve_user_agent()
    except RuntimeError as exc:
        print(f"BŁĄD: {exc}", file=sys.stderr)
        return 1

    print("== Krok 1: SEC company_tickers_full (ticker -> cik + title) ==")
    with SecEdgarClient(user_agent) as sec_client:
        try:
            sec_full = sec_client.get_company_tickers_full()
        except SecEdgarError as exc:
            print(f"BŁĄD pobierania SEC company_tickers.json: {exc}")
            return 1
    sec_ticker_map = {t: info["cik"] for t, info in sec_full.items()}
    sec_titles = {t: info["title"] for t, info in sec_full.items()}
    print(f"SEC: {len(sec_full)} tickerów z CIK i tytułem.")

    print("\n== Krok 2: fja05680/sp500 (KANONICZNE) — pobranie + rozwiązanie CIK ==")
    try:
        fja_csv = fetch_components_csv()
    except Sp500HistoryError as exc:
        print(f"BŁĄD pobierania fja05680/sp500: {exc}")
        return 1
    fja_rows = parse_components_csv(fja_csv)
    fja_window = window_from_cutoff(fja_rows, CUTOFF)
    if not fja_window:
        print(f"BŁĄD: fja05680 nie ma żadnego wiersza <= {CUTOFF}.")
        return 1
    fja_intervals = build_ticker_intervals(fja_window, cutoff_date=CUTOFF)
    fja_all_tickers = distinct_tickers(fja_window)
    fja_resolution = resolve_tickers_to_cik(fja_all_tickers, sec_ticker_map)
    print(
        f"fja05680: {len(fja_all_tickers)} unikalnych tickerów w oknie {CUTOFF}+, "
        f"rozwiązanych={len(fja_resolution.resolved)} "
        f"(w tym via wariant formatu={len(fja_resolution.resolved_via_format_variant)}), "
        f"UNRESOLVED={len(fja_resolution.unresolved)}"
    )
    if fja_resolution.unresolved:
        print(f"  fja05680 UNRESOLVED (max 30): {', '.join(fja_resolution.unresolved[:30])}")

    print("\n== Krok 3: FMP — bieżący skład + historical-sp500-constituent + rozwiązanie CIK ==")
    with FMPClient(api_key) as fmp_client:
        try:
            current_rows = fmp_client.get_sp500_constituents()
        except FMPError as exc:
            print(f"BŁĄD pobierania bieżącego składu FMP: {exc}")
            return 1
        current_members = {r["symbol"] for r in current_rows if r.get("symbol")}

        path, raw_rows, attempts = fmp_client.get_historical_sp500_constituents()
        for candidate_path, outcome in attempts:
            print(f"  próba {candidate_path}: {outcome}")
        if path is None or not raw_rows:
            print("BŁĄD: historical-sp500-constituent niedostępny lub pusty — przerywam.")
            return 1

    fmp_events_all = parse_fmp_events(raw_rows)
    fmp_names_by_ticker = collect_fmp_ticker_names(fmp_events_all)
    fmp_resolution = resolve_fmp_tickers(fmp_names_by_ticker, sec_ticker_map, sec_titles)
    print(
        f"FMP: {len(fmp_names_by_ticker)} unikalnych tickerów w logu zdarzeń, "
        f"rozwiązanych={len(fmp_resolution.resolved)} "
        f"(w tym via wariant formatu={len(fmp_resolution.resolved_via_format_variant)}), "
        f"UNRESOLVED={len(fmp_resolution.unresolved)}"
    )
    if fmp_resolution.unresolved:
        print(f"  FMP UNRESOLVED (max 30): {', '.join(fmp_resolution.unresolved[:30])}")
    print(f"  FMP name_mismatch_suspicious (możliwy recykling tickera, max 20):")
    for ticker, info in list(fmp_resolution.name_mismatch_suspicious.items())[:20]:
        print(f"    {ticker}: cik={info['cik']} sec_title={info['sec_title']!r} fmp_name={info['fmp_name']!r}")
    print(f"    (razem: {len(fmp_resolution.name_mismatch_suspicious)})")

    internal_multi_name = find_tickers_with_multiple_names(fmp_events_all)
    print(f"  FMP wewnętrzna niespójność nazw (ten sam ticker, >=2 niezgodne nazwy w logu FMP, max 20):")
    for ticker, names in list(internal_multi_name.items())[:20]:
        print(f"    {ticker}: {sorted(names)}")
    print(f"    (razem: {len(internal_multi_name)})")

    print(f"\n== Krok 4: zdarzenia CIK-poziomu w oknie {CUTOFF}+ (oba pola daty FMP) ==")
    fja_events_set: set[ChangeEvent] = set()
    for iv in fja_intervals:
        if iv.start_date > CUTOFF:
            fja_events_set.add(ChangeEvent(date=iv.start_date, ticker=iv.ticker, action="ADD"))
        if iv.end_date is not None:
            fja_events_set.add(ChangeEvent(date=iv.end_date, ticker=iv.ticker, action="REMOVE"))
    fja_events_window = frozenset(fja_events_set)
    fja_cik_conv = change_events_to_cik_events(fja_events_window, fja_resolution.resolved)
    print(
        f"fja05680: {len(fja_events_window)} zdarzeń ticker-poziom -> "
        f"{len(fja_cik_conv.events)} zdarzeń CIK-poziom "
        f"(pominięto brak CIK dla {len(fja_cik_conv.dropped_unresolved_tickers)} tickerów)"
    )

    fmp_events_window_date = fmp_change_events(fmp_events_all, cutoff_date=CUTOFF)
    fmp_events_window_date_added, unparseable_da = fmp_change_events_by_date_added(
        fmp_events_all, cutoff_date=CUTOFF
    )
    fmp_cik_conv_date = change_events_to_cik_events(fmp_events_window_date, fmp_resolution.resolved)
    fmp_cik_conv_date_added = change_events_to_cik_events(
        fmp_events_window_date_added, fmp_resolution.resolved
    )
    print(
        f"FMP (pole date): {len(fmp_events_window_date)} zdarzeń ticker-poziom -> "
        f"{len(fmp_cik_conv_date.events)} CIK-poziom "
        f"(pominięto brak CIK dla {len(fmp_cik_conv_date.dropped_unresolved_tickers)} tickerów)"
    )
    print(
        f"FMP (pole dateAdded): {len(fmp_events_window_date_added)} zdarzeń ticker-poziom -> "
        f"{len(fmp_cik_conv_date_added.events)} CIK-poziom "
        f"(pominięto brak CIK dla {len(fmp_cik_conv_date_added.dropped_unresolved_tickers)} tickerów; "
        f"{len(unparseable_da)} zdarzeń miało niesparsowalny dateAdded i użyło oryginalnego date jako fallback)"
    )

    print(f"\n== Krok 5: krzywa wpływu tolerancji dat (0-5 dni), 'date' vs 'dateAdded' ==")
    curve_date = tolerance_impact_curve(
        fja_cik_conv.events, fmp_cik_conv_date.events, tolerance_range_days=TOLERANCE_RANGE
    )
    curve_date_added = tolerance_impact_curve(
        fja_cik_conv.events, fmp_cik_conv_date_added.events, tolerance_range_days=TOLERANCE_RANGE
    )
    _print_curve("pole 'date'", curve_date)
    _print_curve("pole 'dateAdded'", curve_date_added)

    dominant_field = _field_dominance(curve_date, curve_date_added)
    print(
        f"\nPole z jednoznaczną dominacją (>= liczba dopasowań PRZY KAŻDEJ testowanej tolerancji): "
        f"{dominant_field or 'BRAK — żadne pole nie dominuje w całym zakresie, wymaga ręcznej oceny krzywych wyżej'}"
    )

    print(f"\n== Krok 6: finalny raport pogodzenia (fja05680 kanoniczne, FMP walidator) na progu plateau ==")
    for field_name, curve, fmp_conv in (
        ("date", curve_date, fmp_cik_conv_date),
        ("dateAdded", curve_date_added, fmp_cik_conv_date_added),
    ):
        chosen_t = pick_plateau_tolerance(curve)
        result = match_cik_events_with_tolerance(fja_cik_conv.events, fmp_conv.events, tolerance_days=chosen_t)
        print(f"\n-- pole={field_name}, tolerancja (plateau)={chosen_t}d --")
        print(f"  Dopasowane: {len(result.matched)}")
        print(f"  Tylko fja05680 (kandydaci na lukę walidatora, max 15):")
        for e in result.only_canonical[:15]:
            print(f"    cik={e.cik} date={e.date} action={e.action}")
        print(f"    (razem: {len(result.only_canonical)})")
        print(f"  Tylko FMP (kandydaci na lukę kanonicznego źródła, max 15):")
        for e in result.only_validator[:15]:
            print(f"    cik={e.cik} date={e.date} action={e.action}")
        print(f"    (razem: {len(result.only_validator)})")

    print(f"\n== Krok 7: wpływ na rekonstrukcję membership (ticker vs CIK) na datach {CUTOFF}-2026 ==")
    for date in SAMPLE_DATES:
        fmp_snapshot = reconstruct_membership_backward(fmp_events_all, current_members, date)
        fja_snapshot = tickers_as_of(fja_rows, date)
        print(f"\n-- {date} --")
        if fja_snapshot is None:
            print("  fja05680: brak danych sprzed/na tę datę.")
            continue
        ticker_cmp = compare_ticker_sets(fmp_snapshot, fja_snapshot)
        print(
            f"  Ticker-poziom: FMP={ticker_cmp.count_a} fja05680={ticker_cmp.count_b} "
            f"wspólne={ticker_cmp.intersection_count} tylko_FMP={len(ticker_cmp.only_in_a)} "
            f"tylko_fja05680={len(ticker_cmp.only_in_b)}"
        )
        fmp_cik_snapshot = {fmp_resolution.resolved[t] for t in fmp_snapshot if t in fmp_resolution.resolved}
        fja_cik_snapshot = {fja_resolution.resolved[t] for t in fja_snapshot if t in fja_resolution.resolved}
        cik_cmp = compare_ticker_sets(fmp_cik_snapshot, fja_cik_snapshot)
        print(
            f"  CIK-poziom:    FMP={cik_cmp.count_a} fja05680={cik_cmp.count_b} "
            f"wspólne={cik_cmp.intersection_count} tylko_FMP={len(cik_cmp.only_in_a)} "
            f"tylko_fja05680={len(cik_cmp.only_in_b)}"
        )
        print(
            f"  (nierozwiązany CIK pominięty z tego porównania: "
            f"FMP {len(fmp_snapshot) - sum(1 for t in fmp_snapshot if t in fmp_resolution.resolved)}, "
            f"fja05680 {len(fja_snapshot) - sum(1 for t in fja_snapshot if t in fja_resolution.resolved)})"
        )
        if cik_cmp.only_in_a:
            print(f"    tylko FMP (CIK, max 15): {', '.join(sorted(cik_cmp.only_in_a)[:15])}")
        if cik_cmp.only_in_b:
            print(f"    tylko fja05680 (CIK, max 15): {', '.join(sorted(cik_cmp.only_in_b)[:15])}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

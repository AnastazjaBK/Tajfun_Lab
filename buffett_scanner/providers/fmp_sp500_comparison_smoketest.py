"""Proof Run: krok 3 Fazy 5.2 (OPEN BLOCKER 2) — walidacja krzyżowa
FMP `historical-sp500-constituent` vs `fja05680/sp500` dla okna 2012+.
WYŁĄCZNIE DIAGNOSTYCZNE — nie zapisuje nic do bazy, nie buduje
finalnego `universe_membership`.

    python -m buffett_scanner.providers.fmp_sp500_comparison_smoketest

Wymaga FMP_API_KEY (plan Premium — potwierdzone w v1.31, że endpoint
jest teraz dostępny). fja05680/sp500 darmowe, bez klucza.

Raportuje (design review v1.31, krok 3):
- anomalie w samych danych FMP (date vs dateAdded, duplikaty — patrz
  też rozszerzony fmp_smoketest.py),
- zgodne zmiany składu / tylko-FMP / tylko-fja05680 (dokładne
  dopasowanie date+ticker+ADD/REMOVE),
- rekonstrukcję składu na kilku datach obiema metodami i ich zgodność,
- ocenę wpływu rozbieżności na rekonstrukcję point-in-time.
"""

from __future__ import annotations

import sys

from buffett_scanner.config import load_config
from buffett_scanner.fmp_sp500_events import (
    ChangeEvent,
    compare_change_events,
    find_date_added_mismatches,
    fmp_change_events,
    parse_fmp_events,
    reconstruct_membership_backward,
)
from buffett_scanner.providers.fmp import FMPClient, FMPError
from buffett_scanner.providers.sp500_history import Sp500HistoryError, fetch_components_csv
from buffett_scanner.universe_history import (
    build_ticker_intervals,
    compare_ticker_sets,
    parse_components_csv,
    tickers_as_of,
    window_from_cutoff,
)

CUTOFF = "2012-01-01"
SAMPLE_DATES = ["2012-01-31", "2018-12-31", "2026-09-01"]


def main() -> int:
    config = load_config()
    try:
        api_key = config.data_provider.resolve_api_key()
    except RuntimeError as exc:
        print(f"BŁĄD: {exc}", file=sys.stderr)
        return 1

    print("== Krok 1: pobranie FMP historical-sp500-constituent + sp500-constituent (bieżący skład) ==")
    with FMPClient(api_key) as client:
        try:
            current_rows = client.get_sp500_constituents()
        except FMPError as exc:
            print(f"BŁĄD pobierania bieżącego składu FMP: {exc}")
            return 1
        current_members = {r["symbol"] for r in current_rows if r.get("symbol")}
        print(f"Bieżący skład FMP (sp500-constituent): {len(current_members)} tickerów")

        path, raw_rows, attempts = client.get_historical_sp500_constituents()
        for candidate_path, outcome in attempts:
            print(f"  próba {candidate_path}: {outcome}")
        if path is None or not raw_rows:
            print("BŁĄD: historical-sp500-constituent niedostępny lub pusty — przerywam.")
            return 1
        print(f"FMP: {len(raw_rows)} surowych wierszy zdarzeń (ścieżka: {path})")

    fmp_events_all = parse_fmp_events(raw_rows)
    print(f"FMP: {len(fmp_events_all)} sparsowanych zdarzeń (po odrzuceniu wierszy bez date/symbol)")

    print("\n== Krok 2: anomalie w danych FMP (nie zakładamy poprawności) ==")
    mismatches = find_date_added_mismatches(fmp_events_all)
    print(f"Rozbieżności date vs dateAdded (lub NIEPARSOWALNE): {len(mismatches)} z {len(fmp_events_all)}")
    if mismatches:
        print("Przykłady (max 10):")
        for event, parsed in mismatches[:10]:
            print(f"  date={event.date} dateAdded={event.date_added_raw!r} sparsowane_jako={parsed}")
        in_window = sum(1 for e, _ in mismatches if e.date >= CUTOFF)
        print(f"Z tego w oknie {CUTOFF}+: {in_window}")

    print("\n== Krok 3: fja05680/sp500 (do porównania) ==")
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
    print(f"fja05680: baseline={fja_window[0].date}, {len(fja_window)} wierszy w oknie, {len(fja_intervals)} przedziałów")

    print(f"\n== Krok 4: porównanie zdarzeń zmiany składu w oknie {CUTOFF}+ (dokładne dopasowanie date+ticker+action) ==")
    fmp_events_window = fmp_change_events(fmp_events_all, cutoff_date=CUTOFF)

    # Budujemy zdarzenia z fja05680 bezpośrednio (ADD = start_date > cutoff, REMOVE = end_date obecny).
    fja_events_set = set()
    for iv in fja_intervals:
        if iv.start_date > CUTOFF:
            fja_events_set.add(ChangeEvent(date=iv.start_date, ticker=iv.ticker, action="ADD"))
        if iv.end_date is not None:
            fja_events_set.add(ChangeEvent(date=iv.end_date, ticker=iv.ticker, action="REMOVE"))
    fja_events_window = frozenset(fja_events_set)

    print(f"FMP: {len(fmp_events_window)} zdarzeń w oknie, fja05680: {len(fja_events_window)} zdarzeń w oknie")
    cmp = compare_change_events(fmp_events_window, fja_events_window)
    print(f"Zgodne (dokładne date+ticker+action): {len(cmp.common)}")
    print(f"Tylko w FMP: {len(cmp.only_a)}")
    print(f"Tylko w fja05680: {len(cmp.only_b)}")

    # Uzupełniające, mniej rygorystyczne porównanie: same tickery dotknięte
    # zdarzeniem w oknie, bez wymogu zgodnej daty/akcji — mniej wrażliwe na
    # rozbieżności formatu daty czy klasyfikacji ADD/REMOVE.
    fmp_tickers_touched = {e.ticker for e in fmp_events_window}
    fja_tickers_touched = {e.ticker for e in fja_events_window}
    loose_cmp = compare_ticker_sets(fmp_tickers_touched, fja_tickers_touched)
    print(f"\nPorównanie luźniejsze (tylko tickery dotknięte zdarzeniem w oknie, bez daty/akcji):")
    print(f"  FMP: {loose_cmp.count_a}, fja05680: {loose_cmp.count_b}, wspólne: {loose_cmp.intersection_count}")
    print(f"  Tylko w FMP ({len(loose_cmp.only_in_a)}): {', '.join(loose_cmp.only_in_a[:40])}"
          f"{' ...' if len(loose_cmp.only_in_a) > 40 else ''}")
    print(f"  Tylko w fja05680 ({len(loose_cmp.only_in_b)}): {', '.join(loose_cmp.only_in_b[:40])}"
          f"{' ...' if len(loose_cmp.only_in_b) > 40 else ''}")

    print(f"\nPrzykłady zdarzeń 'tylko w FMP' (max 10, do ręcznej oceny czy to timing/nazewnictwo czy realna luka):")
    for ev in sorted(cmp.only_a, key=lambda e: e.date)[:10]:
        print(f"  {ev.date} {ev.action} {ev.ticker}")
    print(f"Przykłady zdarzeń 'tylko w fja05680' (max 10):")
    for ev in sorted(cmp.only_b, key=lambda e: e.date)[:10]:
        print(f"  {ev.date} {ev.action} {ev.ticker}")

    print(f"\n== Krok 5: rekonstrukcja składu na próbnych datach obiema metodami ==")
    for date in SAMPLE_DATES:
        fmp_snapshot = reconstruct_membership_backward(fmp_events_all, current_members, date)
        fja_snapshot = tickers_as_of(fja_rows, date)
        print(f"\n-- {date} --")
        print(f"  FMP (rekonstrukcja wsteczna): {len(fmp_snapshot)} tickerów")
        if fja_snapshot is None:
            print(f"  fja05680: brak danych sprzed/na tę datę.")
            continue
        print(f"  fja05680: {len(fja_snapshot)} tickerów")
        snap_cmp = compare_ticker_sets(fmp_snapshot, fja_snapshot)
        print(f"  Wspólne: {snap_cmp.intersection_count}, tylko FMP: {len(snap_cmp.only_in_a)}, tylko fja05680: {len(snap_cmp.only_in_b)}")
        if snap_cmp.only_in_a:
            print(f"    tylko FMP: {', '.join(snap_cmp.only_in_a[:20])}{' ...' if len(snap_cmp.only_in_a) > 20 else ''}")
        if snap_cmp.only_in_b:
            print(f"    tylko fja05680: {', '.join(snap_cmp.only_in_b[:20])}{' ...' if len(snap_cmp.only_in_b) > 20 else ''}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

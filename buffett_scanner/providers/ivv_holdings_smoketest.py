"""Proof Run: holdingi IVV jako niezależne źródło walidacji
`universe_membership` 2012+ (Faza 5.2, research v1.27) — MINIMALNY,
DIAGNOSTYCZNY. Nie buduje finalnego adaptera, nie zapisuje nic do bazy.

    python -m buffett_scanner.providers.ivv_holdings_smoketest

Sprawdza empirycznie (design review v1.27, sekcja "Alternatywne
źródła"):
1. czy historyczne holdingi IVV faktycznie dają się pobrać dla dat 2012+,
2. jaki jest realny kształt odpowiedzi (surowe linie do inspekcji),
3. czy `asOfDate` faktycznie zmienia zwracane dane (nie zwraca zawsze
   bieżącego pliku) — porównanie metadanych "as of" i zbiorów tickerów
   między różnymi datami,
4. porównanie z `fja05680/sp500` dla tych samych dat: liczebności,
   część wspólna, różnice.

Żadnego klucza API — ishares.com i fja05680/sp500 są oba darmowe, bez
autoryzacji.
"""

from __future__ import annotations

from buffett_scanner.ivv_holdings_parse import parse_ivv_holdings_csv
from buffett_scanner.providers.ivv_holdings import IvvHoldingsError, fetch_ivv_holdings_csv
from buffett_scanner.providers.sp500_history import Sp500HistoryError, fetch_components_csv
from buffett_scanner.universe_history import compare_ticker_sets, parse_components_csv, tickers_as_of

# Celowo wybrane daty z różnych okresów (właściciel, 2026-09-25):
# blisko początku okna 2012+ (koniec miesiąca, większa szansa na
# trafienie przy nieznanej granularności), okres środkowy, data
# współczesna.
TEST_DATES = ["2012-01-31", "2018-12-31", "2026-09-22"]

RAW_PREVIEW_LINES = 15


def main() -> int:
    print("== Krok A: fja05680/sp500 (do porównania) ==")
    try:
        fja_csv = fetch_components_csv()
    except Sp500HistoryError as exc:
        print(f"BŁĄD pobierania fja05680/sp500: {exc}")
        return 1
    fja_rows = parse_components_csv(fja_csv)
    print(f"fja05680/sp500: {len(fja_rows)} wierszy, zakres {fja_rows[0].date}..{fja_rows[-1].date}")

    as_of_lines: dict[str, str | None] = {}
    ticker_sets: dict[str, set[str] | None] = {}

    for date in TEST_DATES:
        print(f"\n{'=' * 70}\n== Krok B: IVV holdings, asOfDate={date} ==\n{'=' * 70}")
        try:
            raw = fetch_ivv_holdings_csv(date)
        except IvvHoldingsError as exc:
            print(f"BŁĄD pobierania IVV holdings dla {date}: {exc}")
            ticker_sets[date] = None
            continue

        print(f"Długość surowej odpowiedzi: {len(raw)} znaków")
        print(f"Pierwsze {RAW_PREVIEW_LINES} linii surowej odpowiedzi (do ręcznej inspekcji kształtu):")
        for line in raw.splitlines()[:RAW_PREVIEW_LINES]:
            print(f"  {line}")

        as_of_line = next((l for l in raw.splitlines() if "as of" in l.lower()), None)
        as_of_lines[date] = as_of_line
        print(f"\nLinia zawierająca 'as of' (sprawdzenie punktu 3 — czy asOfDate realnie działa): {as_of_line!r}")

        result = parse_ivv_holdings_csv(raw)
        if result.header_row_index is None:
            print("NIEROZPOZNANA STRUKTURA — brak wiersza z kolumną 'Ticker'. Sprawdź podgląd wyżej ręcznie.")
            ticker_sets[date] = None
            continue

        print(f"Nagłówek znaleziony w wierszu {result.header_row_index}, kolumny: {result.columns}")
        print(f"Liczba wierszy danych (z wypełnionym Ticker): {len(result.rows)}")
        tickers = result.tickers
        ticker_sets[date] = tickers
        print(f"Dystynktywnych tickerów: {len(tickers)}")

        fja_tickers = tickers_as_of(fja_rows, date)
        if fja_tickers is None:
            print(f"fja05680/sp500: brak danych sprzed/na {date} — porównanie niemożliwe.")
            continue
        cmp = compare_ticker_sets(tickers, fja_tickers)
        print(f"\nPorównanie IVV vs fja05680/sp500 na {date}:")
        print(f"  IVV: {cmp.count_a}, fja05680: {cmp.count_b}, część wspólna: {cmp.intersection_count}")
        print(f"  Tylko w IVV ({len(cmp.only_in_a)}): {', '.join(cmp.only_in_a)}")
        print(f"  Tylko w fja05680 ({len(cmp.only_in_b)}): {', '.join(cmp.only_in_b)}")

    print(f"\n{'=' * 70}\n== Krok C: czy asOfDate realnie różnicuje wynik (punkt 3) ==\n{'=' * 70}")
    print("Linie 'as of' per data:")
    for date, line in as_of_lines.items():
        print(f"  {date}: {line!r}")
    distinct_sets = {frozenset(s) for s in ticker_sets.values() if s is not None}
    print(f"Liczba RÓŻNYCH zbiorów tickerów wśród {len(ticker_sets)} zapytanych dat: {len(distinct_sets)}")
    if len(distinct_sets) <= 1 and len([s for s in ticker_sets.values() if s is not None]) > 1:
        print("UWAGA: wszystkie zapytane daty dały IDENTYCZNY zbiór tickerów — możliwe, że asOfDate jest ignorowany.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Proof Run: dane cenowe FMP dla pełnego backfillu 2012+ (Faza 5.3,
przed budową deterministic walk-forward harness). WYŁĄCZNIE
DIAGNOSTYCZNE — nie zapisuje nic do bazy, nie wykonuje pełnego
backfillu.

    python -m buffett_scanner.providers.price_data_proof_run

Wymaga FMP_API_KEY i SEC_EDGAR_USER_AGENT (oba już istnieją jako
sekrety). Sprawdza empirycznie (zlecone przez właścicielkę, 2026-09-30):

1. Czy `adjClose`/`close` z `historical-price-eod/full` jest faktycznie
   adjustowane pod splity, czy nie — KRYTYCZNE dla poprawności
   backtestu (fmp.py dotąd zakładał `close` jako fallback bez
   potwierdzenia w żadną stronę). Test na realnych, znanych datach
   splitów (AAPL 2014-06-09 7:1, AAPL 2020-08-31 4:1, NVDA 2021-07-20
   4:1, NVDA 2024-06-10 10:1).
2. Dostępność danych dla delistowanych/wygasłych tickerów (AABA, BBBY).
3. Zachowanie przy zmianie tickera (FB vs META dla tego samego CIK,
   zapytanie o okres SPRZED zmiany pod obydwoma symbolami).
4. Zachowanie limitów żądań przy serii kolejnych zapytań.
5. Liczbę zapytań potrzebnych do pełnego backfillu historycznego
   uniwersum 2012+ (na podstawie realnych przedziałów tickerów
   fja05680 + rozwiązania CIK — ta sama logika co Faza 5.2).

Jeśli którykolwiek z punktów 1-3 ujawni problem grożący look-ahead
bias, błędnym zwrotom, albo cichą utratą danych — ZATRZYMAĆ SIĘ przed
pełnym backfillem (instrukcja właścicielki, 2026-09-30)."""

from __future__ import annotations

import sys

from buffett_scanner.config import load_config
from buffett_scanner.price_history_plan import build_price_fetch_plan, detect_large_day_over_day_moves
from buffett_scanner.providers.fmp import FMPClient, FMPError
from buffett_scanner.providers.sec_edgar import SecEdgarClient, SecEdgarError
from buffett_scanner.providers.sp500_history import Sp500HistoryError, fetch_components_csv
from buffett_scanner.universe_history import (
    build_ticker_intervals,
    distinct_tickers,
    parse_components_csv,
    resolve_tickers_to_cik,
    window_from_cutoff,
)

# Znane, realne daty splitów — źródło: publiczne ogłoszenia korporacyjne
# (nie zgadywane). Używane WYŁĄCZNIE jako punkt odniesienia do sprawdzenia,
# czy seria FMP jest adjustowana — nie jako założenie o wyniku.
KNOWN_SPLITS = [
    ("AAPL", "2014-06-09", "7:1"),
    ("AAPL", "2020-08-31", "4:1"),
    ("NVDA", "2021-07-20", "4:1"),
    ("NVDA", "2024-06-10", "10:1"),
]
DELISTED_TICKERS = ["AABA", "BBBY"]  # Altaba (rozwiązana 2019), Bed Bath & Beyond (bankructwo 2023)
RENAME_CHECK = ("FB", "META")  # ten sam CIK, zmiana tickera 2021-10-28


def main() -> int:
    config = load_config()
    try:
        api_key = config.data_provider.resolve_api_key()
        user_agent = config.sources.sec_edgar.resolve_user_agent()
    except RuntimeError as exc:
        print(f"BŁĄD: {exc}", file=sys.stderr)
        return 1

    cutoff = config.backtest.window_start

    print("== Krok 1: adjClose vs close — czy seria jest adjustowana pod splity? ==")
    with FMPClient(api_key) as client:
        for symbol, split_date, ratio in KNOWN_SPLITS:
            try:
                rows = client.get_historical_prices(symbol, from_date=cutoff, to_date="2026-09-30")
            except FMPError as exc:
                print(f"  {symbol}: BŁĄD pobierania: {exc}")
                continue
            around = [r for r in rows if abs((_to_date(r["date"]) - _to_date(split_date)).days) <= 3]
            print(f"  {symbol} split {split_date} ({ratio}): {len(rows)} wierszy ogółem, wiersze w okolicy splitu:")
            for r in sorted(around, key=lambda r: r["date"]):
                print(f"    {r['date']}: close={r['close']} adj_close={r['adj_close']}")
            moves = detect_large_day_over_day_moves(rows, threshold_pct=15.0)
            move_at_split = [m for m in moves if abs((_to_date(m[1]) - _to_date(split_date)).days) <= 3]
            if move_at_split:
                print(f"    -> WYKRYTO skok >=15% w okolicy splitu: {move_at_split} "
                      f"(seria PRAWDOPODOBNIE NIE jest adjustowana pod splity)")
            else:
                print(f"    -> BRAK skoku >=15% w okolicy splitu (seria PRAWDOPODOBNIE jest adjustowana)")

        print("\n== Krok 2: dostępność danych dla delistowanych tickerów ==")
        for symbol in DELISTED_TICKERS:
            try:
                rows = client.get_historical_prices(symbol, from_date=cutoff, to_date="2026-09-30")
            except FMPError as exc:
                print(f"  {symbol}: BŁĄD: {exc}")
                continue
            if not rows:
                print(f"  {symbol}: 0 wierszy — BRAK danych historycznych (do ręcznej oceny).")
            else:
                print(f"  {symbol}: {len(rows)} wierszy, zakres {rows[0]['date']}..{rows[-1]['date']}")

        print("\n== Krok 3: zmiana tickera (FB vs META) — czy stary symbol wciąż zwraca historię? ==")
        old_symbol, new_symbol = RENAME_CHECK
        for symbol in (old_symbol, new_symbol):
            try:
                rows = client.get_historical_prices(symbol, from_date=cutoff, to_date="2021-10-28")
            except FMPError as exc:
                print(f"  {symbol}: BŁĄD: {exc}")
                continue
            print(f"  {symbol} (zapytanie o okres SPRZED zmiany tickera): {len(rows)} wierszy"
                  + (f", zakres {rows[0]['date']}..{rows[-1]['date']}" if rows else " — BRAK danych"))

        print("\n== Krok 4: zachowanie limitu żądań (seria 20 zapytań) ==")
        burst_tickers = ["AAPL", "MSFT", "KO", "JNJ", "PG", "XOM", "CVX", "JPM", "V", "HD",
                          "PEP", "MRK", "ABBV", "AVGO", "COST", "WMT", "MA", "UNH", "DIS", "BA"]
        errors = 0
        for symbol in burst_tickers:
            try:
                client.get_historical_prices(symbol, from_date="2026-09-01", to_date="2026-09-30")
            except FMPError as exc:
                errors += 1
                print(f"  {symbol}: BŁĄD: {exc}")
        print(f"  {len(burst_tickers)} zapytań, błędów: {errors}")

    print("\n== Krok 5: pełny inwentarz zadań backfillu dla uniwersum 2012+ ==")
    with SecEdgarClient(user_agent) as sec_client:
        try:
            sec_map = sec_client.get_company_tickers()
        except SecEdgarError as exc:
            print(f"BŁĄD pobierania mapowania SEC: {exc}", file=sys.stderr)
            return 1
    try:
        fja_csv = fetch_components_csv()
    except Sp500HistoryError as exc:
        print(f"BŁĄD pobierania fja05680/sp500: {exc}", file=sys.stderr)
        return 1
    fja_rows = parse_components_csv(fja_csv)
    fja_window = window_from_cutoff(fja_rows, cutoff)
    if not fja_window:
        print(f"BŁĄD: fja05680 nie ma żadnego wiersza <= {cutoff}.", file=sys.stderr)
        return 1
    fja_intervals = build_ticker_intervals(fja_window, cutoff_date=cutoff)
    fja_all_tickers = distinct_tickers(fja_window)
    resolution = resolve_tickers_to_cik(fja_all_tickers, sec_map)

    today = "2026-09-30"
    tasks, unresolved = build_price_fetch_plan(fja_intervals, resolution.resolved, cutoff_date=cutoff, today=today)
    unique_ciks = {t.cik for t in tasks}
    total_days_span = sum(
        (_to_date(t.to_date) - _to_date(t.from_date)).days for t in tasks
    )
    print(f"Przedziałów tickera w oknie {cutoff}+: {len(fja_intervals)}")
    print(f"Zadań pobrania cen: {len(tasks)} (dla {len(unique_ciks)} unikalnych CIK)")
    print(f"Tickery bez CIK (nie generują zadania): {len(unresolved)}")
    print(f"Łączna rozpiętość dni we wszystkich zadaniach (nie liczba requestów): {total_days_span}")
    print(f"Przy throttlingu 0.05s/request: ok. {len(tasks) * 0.05 / 60:.1f} minut samego throttlingu "
          f"(bez czasu odpowiedzi sieci) dla {len(tasks)} requestów.")

    return 0


def _to_date(iso: str):
    import datetime as dt
    return dt.date.fromisoformat(iso)


if __name__ == "__main__":
    raise SystemExit(main())

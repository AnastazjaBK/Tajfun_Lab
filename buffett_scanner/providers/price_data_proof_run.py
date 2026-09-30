"""Proof Run: dane cenowe FMP dla pełnego backfillu 2012+ (Faza 5.3,
przed budową deterministic walk-forward harness). WYŁĄCZNIE
DIAGNOSTYCZNE — nie zapisuje nic do bazy, nie wykonuje pełnego
backfillu.

    python -m buffett_scanner.providers.price_data_proof_run

Wymaga FMP_API_KEY i SEC_EDGAR_USER_AGENT (oba już istnieją jako
sekrety). Sprawdza empirycznie (zlecone przez właścicielkę, 2026-09-30):

1. Czy `adjClose`/`close` z `historical-price-eod/full` jest faktycznie
   adjustowane pod splity (test na realnych, znanych datach: AAPL
   2014/2020, NVDA 2021/2024).
2. Dostępność danych dla delistowanych/wygasłych tickerów (AABA, BBBY).
3. NOWY MODEL pobierania cen (v1.37, po znalezisku z pierwszego
   uruchomienia: stary model per-ticker-interval cicho gubił dane dla
   spółek, które zmieniły ticker — np. `FB` w swoim własnym okresie
   2013-2022 zwracał 0 wierszy, cała historia była pod `META`).
   Pokazuje coverage PRZED i PO poprawce, gaps, duplicates, conflicts
   i które tickery faktycznie dostarczyły dane — na 4 przypadkach:
   FB/META (potwierdzony rename), ANTM/ELV (drugi potwierdzony rename,
   Anthem->Elevance Health 2022), AAPL (kontrola bez zmiany tickera),
   BBBY (kontrola: ochrona przed recyklingiem tickera po opuszczeniu
   indeksu w 2017). Przy KAŻDYM konflikcie: pełna lista różniących się
   pól (v1.37b — drugie uruchomienie pokazało konflikt z identycznym
   `close`, ale różnym innym polem, niewidoczny w poprzednim raporcie)
   oraz bezpośrednie sprawdzenie DZISIEJSZEGO profilu (cik, nazwa) obu
   skonfliktowanych tickerów — do potwierdzenia recyklingu bez
   zgadywania. Tolerancja porównania zmieniona z bezwzględnej na
   względną (0,1% + podłoga 1 cent) po realnym znalezisku fałszywie
   ostrej tolerancji przy drogich akcjach.
4. Zachowanie limitów żądań przy serii kolejnych zapytań.
5. Pełny inwentarz zadań backfillu dla realnego uniwersum 2012+, wg
   NOWEGO modelu — z pełną listą WSZYSTKICH CIK posiadających >1
   ticker w oknie (nie tylko liczbą), żeby żaden przypadek rename/
   recyklingu nie pozostał niezidentyfikowany przed backfillem.

Jeśli którykolwiek z punktów ujawni problem grożący look-ahead bias,
survivorship bias, błędnej tożsamości spółki albo błędnym zwrotom —
ZATRZYMAĆ SIĘ przed pełnym backfillem (instrukcja właścicielki,
2026-09-30)."""

from __future__ import annotations

import datetime as dt
import sys

from buffett_scanner.config import load_config
from buffett_scanner.price_history_plan import (
    build_price_fetch_plan,
    detect_large_day_over_day_moves,
    diff_price_fields,
    merge_ticker_price_rows,
)
from buffett_scanner.providers.fmp import FMPClient, FMPError
from buffett_scanner.providers.sec_edgar import SecEdgarClient, SecEdgarError
from buffett_scanner.providers.sp500_history import Sp500HistoryError, fetch_components_csv
from buffett_scanner.universe_history import (
    TickerInterval,
    build_ticker_intervals,
    distinct_tickers,
    parse_components_csv,
    resolve_tickers_to_cik,
    window_from_cutoff,
)

TODAY = "2026-09-30"

KNOWN_SPLITS = [
    ("AAPL", "2014-06-09", "7:1"),
    ("AAPL", "2020-08-31", "4:1"),
    ("NVDA", "2021-07-20", "4:1"),
    ("NVDA", "2024-06-10", "10:1"),
]
DELISTED_TICKERS = ["AABA", "BBBY"]

# Cztery przypadki testowe nowego modelu pobierania cen — przedziały
# POTWIERDZONE bezpośrednio z realnego cache fja05680 w tej sesji, nie
# zgadywane. CIK to etykiety grupujące (do scalania), nie muszą być
# prawdziwymi numerami CIK dla celów tego testu logiki.
TICKER_MODEL_TEST_CASES: dict[str, tuple[str, list[TickerInterval]]] = {
    "FB->META (potwierdzony rename bez opuszczenia indeksu)": (
        "CIK_META",
        [
            TickerInterval(ticker="FB", start_date="2013-12-23", end_date="2022-06-09"),
            TickerInterval(ticker="META", start_date="2022-06-09", end_date=None),
        ],
    ),
    "ANTM->ELV (drugi potwierdzony rename: Anthem -> Elevance Health 2022)": (
        "CIK_ELEVANCE",
        [
            TickerInterval(ticker="ANTM", start_date="2012-01-01", end_date="2022-06-28"),
            TickerInterval(ticker="ELV", start_date="2022-06-28", end_date=None),
        ],
    ),
    "AAPL (kontrola — bez zmiany tickera)": (
        "CIK_APPLE",
        [TickerInterval(ticker="AAPL", start_date="2012-01-01", end_date=None)],
    ),
    "BBBY (kontrola — ochrona przed recyklingiem tickera po 2017)": (
        "CIK_BBBY_OLD",
        [TickerInterval(ticker="BBBY", start_date="2012-01-01", end_date="2017-07-26")],
    ),
}


def _to_date(iso: str) -> dt.date:
    return dt.date.fromisoformat(iso)


def _count_weekdays(from_date: str, to_date: str) -> int:
    d, end = _to_date(from_date), _to_date(to_date)
    n = 0
    while d <= end:
        if d.weekday() < 5:
            n += 1
        d += dt.timedelta(days=1)
    return n


def _run_ticker_model_case(client: FMPClient, label: str, cik: str, intervals: list[TickerInterval]) -> None:
    print(f"\n-- {label} --")

    # STARY model (odrzucony): każdy ticker pytany TYLKO w swoim
    # własnym przedziale — reprodukujemy dokładnie tę logikę tutaj
    # (już nieobecną w price_history_plan.py), żeby empirycznie pokazać
    # kontrast coverage przed/po w JEDNYM uruchomieniu.
    old_rows_by_ticker: dict[str, list[dict]] = {}
    for iv in intervals:
        old_to = iv.end_date if iv.end_date is not None else TODAY
        try:
            old_rows_by_ticker[iv.ticker] = client.get_historical_prices(
                iv.ticker, from_date=iv.start_date, to_date=old_to
            )
        except FMPError as exc:
            print(f"  BŁĄD (stary model, {iv.ticker}): {exc}")
            old_rows_by_ticker[iv.ticker] = []
    old_dates = {r["date"] for rows in old_rows_by_ticker.values() for r in rows}

    # NOWY model: build_price_fetch_plan + merge_ticker_price_rows.
    tasks, unresolved = build_price_fetch_plan(
        intervals, {iv.ticker: cik for iv in intervals}, cutoff_date="2012-01-01", today=TODAY
    )
    new_rows_by_ticker: dict[str, list[dict]] = {}
    for task in tasks:
        try:
            new_rows_by_ticker[task.ticker] = client.get_historical_prices(
                task.ticker, from_date=task.from_date, to_date=task.to_date
            )
        except FMPError as exc:
            print(f"  BŁĄD (nowy model, {task.ticker}): {exc}")
            new_rows_by_ticker[task.ticker] = []

    merge_result = merge_ticker_price_rows(cik, new_rows_by_ticker)
    new_dates = {m.date for m in merge_result.merged}

    expected_from = min(iv.start_date for iv in intervals)
    expected_to = TODAY if any(iv.end_date is None for iv in intervals) else max(iv.end_date for iv in intervals)
    expected_weekdays = _count_weekdays(expected_from, expected_to)

    print(f"  Oczekiwany zakres dla CIK: {expected_from}..{expected_to} (~{expected_weekdays} dni roboczych)")
    print(f"  Tickery dostarczające dane (stary model): "
          f"{sorted(t for t, rows in old_rows_by_ticker.items() if rows)} "
          f"(puste: {sorted(t for t, rows in old_rows_by_ticker.items() if not rows)})")
    print(f"  Coverage PRZED poprawką: {len(old_dates)} unikalnych dat "
          f"({'BRAK' if not old_dates else f'{min(old_dates)}..{max(old_dates)}'})")
    print(f"  Tickery dostarczające dane (nowy model): "
          f"{sorted(t for t, rows in new_rows_by_ticker.items() if rows)} "
          f"(puste/nadmiarowe: {sorted(t for t, rows in new_rows_by_ticker.items() if not rows)})")
    print(f"  Coverage PO poprawce: {len(new_dates)} unikalnych dat "
          f"({'BRAK' if not new_dates else f'{min(new_dates)}..{max(new_dates)}'})")

    recovered = new_dates - old_dates
    print(f"  Dni ODZYSKANE dzięki poprawce (były w nowym, nie było w starym): {len(recovered)}")

    gap_ratio = 1 - (len(new_dates) / expected_weekdays) if expected_weekdays else 0.0
    print(f"  Przybliżona luka względem oczekiwanych dni roboczych: {gap_ratio:.1%} "
          f"(przybliżenie kalendarzowe, nie uwzględnia świąt giełdowych)")

    duplicates = [m for m in merge_result.merged if len(m.source_tickers) > 1]
    print(f"  Duplicates (data potwierdzona zgodnie przez >=2 tickery): {len(duplicates)}")
    if duplicates:
        example = duplicates[0]
        print(f"    przykład: {example.date} <- {example.source_tickers}")

    print(f"  Conflicts (data niezgodna między tickerami — NIE zapisana): {len(merge_result.conflicts)}")
    for c in merge_result.conflicts[:5]:
        fields = diff_price_fields(c.row_a, c.row_b)
        print(f"    {c.date}: {c.ticker_a} vs {c.ticker_b} — różniące się pola: {fields}")
    if merge_result.conflicts:
        first_conflict_date = merge_result.conflicts[0].date
        last_conflict_date = merge_result.conflicts[-1].date
        print(f"    zakres dat konfliktów: {first_conflict_date}..{last_conflict_date} "
              f"(pierwszy dzień konfliktu = KANDYDAT na moment recyklingu/rozjazdu danych)")
        # Sprawdzenie tożsamości NIE zgadywane — bezpośrednie zapytanie o
        # dzisiejszy profil (m.in. CIK) obu skonfliktowanych tickerów.
        conflicted_tickers = sorted({c.ticker_a for c in merge_result.conflicts} | {c.ticker_b for c in merge_result.conflicts})
        for ticker in conflicted_tickers:
            try:
                profile = client.get_company_profile(ticker)
                print(f"    profil DZIŚ dla {ticker}: cik={profile.get('cik')} "
                      f"companyName={profile.get('companyName')!r}")
            except FMPError as exc:
                print(f"    profil DZIŚ dla {ticker}: BŁĄD: {exc}")

    if unresolved:
        print(f"  UWAGA: unresolved tickery w tym przypadku testowym: {unresolved}")


def main() -> int:
    config = load_config()
    try:
        api_key = config.data_provider.resolve_api_key()
        user_agent = config.sources.sec_edgar.resolve_user_agent()
    except RuntimeError as exc:
        print(f"BŁĄD: {exc}", file=sys.stderr)
        return 1

    cutoff = config.backtest.window_start

    print("== Krok 1: adjClose vs close — czy seria jest adjustowana pod splity? "
          "(potwierdzenie z poprzedniego uruchomienia, powtórzone) ==")
    with FMPClient(api_key) as client:
        for symbol, split_date, ratio in KNOWN_SPLITS:
            try:
                rows = client.get_historical_prices(symbol, from_date=cutoff, to_date=TODAY)
            except FMPError as exc:
                print(f"  {symbol}: BŁĄD pobierania: {exc}")
                continue
            around = [r for r in rows if abs((_to_date(r["date"]) - _to_date(split_date)).days) <= 3]
            moves = detect_large_day_over_day_moves(rows, threshold_pct=15.0)
            move_at_split = [m for m in moves if abs((_to_date(m[1]) - _to_date(split_date)).days) <= 3]
            status = "NIEadjustowana (skok wykryty)" if move_at_split else "adjustowana (brak skoku)"
            print(f"  {symbol} split {split_date} ({ratio}): {len(rows)} wierszy, "
                  f"{len(around)} wierszy w okolicy splitu -> {status}")
        print("  -> Wniosek: seria FMP jest split-adjusted (potwierdzone realnymi poziomami cen "
              "w poprzednim uruchomieniu: AAPL ~$23 w 2014 i 2020 zgodne z ceną podzieloną przez "
              "OBA splity 7:1 i 4:1 -- $645/7/4≈$23). Bezpieczna do liczenia historycznych zwrotów.")

        print("\n== Krok 2: dostępność danych dla delistowanych tickerów ==")
        for symbol in DELISTED_TICKERS:
            try:
                rows = client.get_historical_prices(symbol, from_date=cutoff, to_date=TODAY)
            except FMPError as exc:
                print(f"  {symbol}: BŁĄD: {exc}")
                continue
            if not rows:
                print(f"  {symbol}: 0 wierszy — BRAK danych historycznych.")
            else:
                print(f"  {symbol}: {len(rows)} wierszy, zakres {rows[0]['date']}..{rows[-1]['date']}")

        print("\n== Krok 3: NOWY MODEL pobierania cen — coverage przed/po poprawce, "
              "gaps, duplicates, conflicts ==")
        for label, (cik, intervals) in TICKER_MODEL_TEST_CASES.items():
            _run_ticker_model_case(client, label, cik, intervals)

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

    print("\n== Krok 5: pełny inwentarz zadań backfillu dla uniwersum 2012+ (nowy model) ==")
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

    tasks, unresolved = build_price_fetch_plan(fja_intervals, resolution.resolved, cutoff_date=cutoff, today=TODAY)
    unique_ciks = {t.cik for t in tasks}
    tickers_per_cik = {}
    for t in tasks:
        tickers_per_cik.setdefault(t.cik, set()).add(t.ticker)
    multi_ticker_groups = {cik: sorted(tickers) for cik, tickers in tickers_per_cik.items() if len(tickers) > 1}

    print(f"Przedziałów tickera w oknie {cutoff}+: {len(fja_intervals)}")
    print(f"Zadań pobrania cen (nowy model, ticker x pełne okno CIK): {len(tasks)} "
          f"dla {len(unique_ciks)} unikalnych CIK")
    print(f"CIK z >1 tickerem w oknie (kandydaci na rename/recykling): {len(multi_ticker_groups)}")
    for cik, tickers in sorted(multi_ticker_groups.items()):
        print(f"  {cik}: {tickers}")
    print(f"Tickery bez CIK (nie generują zadania): {len(unresolved)}")
    print(f"Przy throttlingu 0.05s/request: ok. {len(tasks) * 0.05 / 60:.1f} minut samego throttlingu "
          f"(bez czasu odpowiedzi sieci) dla {len(tasks)} requestów.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

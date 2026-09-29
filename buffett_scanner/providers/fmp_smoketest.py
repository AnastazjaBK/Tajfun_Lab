"""Ręczny smoke-test klienta FMP — uruchom z prawdziwym FMP_API_KEY.

    python -m buffett_scanner.providers.fmp_smoketest

Wykonuje po jednym, tanim wywołaniu na każdy endpoint i wypisuje
surowy kształt odpowiedzi, żeby potwierdzić (albo obalić) założenia
opisane na górze fmp.py. Nie zapisuje nic do bazy. Nie wypisuje klucza.
"""

from __future__ import annotations

import sys

from buffett_scanner.config import load_config
from buffett_scanner.providers.fmp import FMPClient, FMPError


def main() -> int:
    config = load_config()
    try:
        api_key = config.data_provider.resolve_api_key()
    except RuntimeError as exc:
        print(f"BŁĄD: {exc}", file=sys.stderr)
        return 1

    with FMPClient(api_key) as client:
        print("== sp500_constituent (pierwsze 2 wpisy) ==")
        try:
            constituents = client.get_sp500_constituents()
            print(f"Liczba spółek: {len(constituents)}")
            for row in constituents[:2]:
                print(row)
        except FMPError as exc:
            print(f"NIEZGODNE ZAŁOŻENIE: {exc}")

        print("\n== profile/AAPL ==")
        try:
            profile = client.get_company_profile("AAPL")
            print(profile)
        except FMPError as exc:
            print(f"NIEZGODNE ZAŁOŻENIE: {exc}")

        print("\n== historical-price-full/AAPL (ostatnie 3 sesje) ==")
        try:
            prices = client.get_historical_prices(
                "AAPL", from_date="2026-08-01", to_date="2026-09-20"
            )
            for row in prices[-3:]:
                print(row)
        except FMPError as exc:
            print(f"NIEZGODNE ZAŁOŻENIE: {exc}")

        print("\n== income-statement/AAPL (najnowszy wpis) ==")
        try:
            income = client.get_income_statement("AAPL", limit=2)
            print(f"Liczba okresów: {len(income)}")
            if income:
                print(income[0])
        except FMPError as exc:
            print(f"NIEZGODNE ZAŁOŻENIE: {exc}")

        print("\n== balance-sheet-statement/AAPL (najnowszy wpis) ==")
        try:
            balance = client.get_balance_sheet_statement("AAPL", limit=2)
            print(f"Liczba okresów: {len(balance)}")
            if balance:
                print(balance[0])
        except FMPError as exc:
            print(f"NIEZGODNE ZAŁOŻENIE: {exc}")

        print("\n== cash-flow-statement/AAPL (najnowszy wpis) ==")
        try:
            cashflow = client.get_cash_flow_statement("AAPL", limit=2)
            print(f"Liczba okresów: {len(cashflow)}")
            if cashflow:
                print(cashflow[0])
        except FMPError as exc:
            print(f"NIEZGODNE ZAŁOŻENIE: {exc}")

        print("\n== historical-sp500-constituent (Faza 5.2, krok 1, OPEN BLOCKER 2) ==")
        path, rows, attempts = client.get_historical_sp500_constituents()
        print("Próby per kandydat (KAŻDY osobno, żeby odróżnić 402 'wymaga planu' od 404 'zła ścieżka'):")
        for candidate_path, outcome in attempts:
            print(f"  {candidate_path}: {outcome}")
        if path is None:
            print("ŻADEN kandydat nie zadziałał na obecnym planie/kluczu.")
        elif not rows:
            print(f"\nZadziałała ścieżka: {path}, ale odpowiedź jest pustą listą — brak danych do analizy.")
        else:
            print(f"\nZadziałała ścieżka: {path}")
            print(f"Liczba wierszy: {len(rows)}")
            print(f"Pierwszy wiersz (kształt pól): {rows[0]}")
            print(f"Ostatni wiersz (kształt pól): {rows[-1]}")

            all_keys: set[str] = set()
            for r in rows:
                all_keys.update(r.keys())
            print(f"Wszystkie klucze widziane w CAŁYM zbiorze (nie tylko 1. wiersz): {sorted(all_keys)}")

            dates = sorted(r.get("date") for r in rows if r.get("date"))
            if dates:
                print(f"Zakres dat w polu 'date': {dates[0]} .. {dates[-1]}")
                print(f"Sięga do 2012-01-01 lub wcześniej: {dates[0] <= '2012-01-01'}")
            else:
                print("BRAK pola 'date' w żadnym wierszu.")

            no_date = sum(1 for r in rows if not r.get("date"))
            print(f"Wierszy BEZ pola 'date' (anomalia): {no_date}")

            for ticker_field in ("symbol", "removedTicker"):
                values = [r.get(ticker_field) for r in rows if r.get(ticker_field)]
                distinct = set(values)
                print(f"Pole '{ticker_field}': {len(values)} niepustych wartości, {len(distinct)} unikalnych")

            symbols = {r.get("symbol") for r in rows if r.get("symbol")}
            removed = {r.get("removedTicker") for r in rows if r.get("removedTicker")}
            print(f"Suma unikalnych tickerów (symbol ∪ removedTicker): {len(symbols | removed)}")

            no_ticker_at_all = sum(
                1 for r in rows if not r.get("symbol") and not r.get("removedTicker")
            )
            print(f"Wierszy bez ŻADNEGO tickera (ani symbol, ani removedTicker) — anomalia: {no_ticker_at_all}")

            seen = {}
            dup_count = 0
            for r in rows:
                key = (r.get("date"), r.get("symbol"), r.get("removedTicker"))
                if key in seen:
                    dup_count += 1
                seen[key] = seen.get(key, 0) + 1
            print(f"Dokładne duplikaty (date, symbol, removedTicker) — anomalia: {dup_count}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

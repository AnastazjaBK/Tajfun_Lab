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

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

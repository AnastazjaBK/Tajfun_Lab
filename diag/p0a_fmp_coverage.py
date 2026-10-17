"""DIAG P0a (jednorazowy, Decyzja właścicielki 2026-10-17): pokrycie FMP
dla instrumentów europejskich, ETF/ETC, dywidend, krypto, metali oraz
weryfikacja zdarzenia korporacyjnego CTVA. Wyłącznie odczyt, zero zapisu,
zero Claude API, zero live scanu. max_retries=0 -- każde zapytanie
liczone dokładnie raz. Klucz API nigdy nie jest drukowany."""

from __future__ import annotations

import datetime as dt
import json
import os

from buffett_scanner.providers.fmp import FMPClient, FMPError
from buffett_scanner.providers.sec_edgar import SecEdgarClient, SecEdgarError

TODAY = dt.date.today().isoformat()
CALLS = 0


def show(label: str, data) -> None:
    print(f"\n=== {label} ===")
    if isinstance(data, list):
        print(f"type=list len={len(data)}")
        if data and isinstance(data[0], dict):
            print("keys:", sorted(data[0].keys()))
            print("first:", json.dumps(data[0], ensure_ascii=False)[:600])
            if len(data) > 1:
                print("last:", json.dumps(data[-1], ensure_ascii=False)[:600])
    elif isinstance(data, dict):
        print("type=dict keys:", sorted(data.keys()))
        print(json.dumps(data, ensure_ascii=False)[:1200])
    else:
        print(repr(data)[:600])


def fmp(client: FMPClient, label: str, path: str, **params) -> None:
    global CALLS
    CALLS += 1
    try:
        show(label, client._get(path, **params))
    except FMPError as exc:
        print(f"\n=== {label} ===\nFMPError: {exc}")


def history(client: FMPClient, label: str, symbol: str, from_date: str, to_date: str = TODAY) -> None:
    global CALLS
    CALLS += 1
    try:
        rows = client._get("historical-price-eod/full", symbol=symbol, **{"from": from_date, "to": to_date})
    except FMPError as exc:
        print(f"\n=== {label} ===\nFMPError: {exc}")
        return
    if isinstance(rows, dict) and "historical" in rows:
        rows = rows["historical"]
    print(f"\n=== {label} ===")
    if not isinstance(rows, list) or not rows:
        print("brak danych:", repr(rows)[:300])
        return
    rows = sorted(rows, key=lambda r: r["date"])
    print(f"rows={len(rows)} min={rows[0]['date']} max={rows[-1]['date']}")
    print("keys:", sorted(rows[0].keys()))
    print("oldest:", json.dumps(rows[0])[:300])
    for r in rows[-6:]:
        print("recent:", r.get("date"), "close=", r.get("close"), "adjClose=", r.get("adjClose"), "vol=", r.get("volume"))


def main() -> None:
    with FMPClient(os.environ["FMP_API_KEY"], max_retries=0) as c:
        # --- Europa: akcje ---
        fmp(c, "profile SU.PA", "profile", symbol="SU.PA")
        fmp(c, "quote SU.PA", "quote", symbol="SU.PA")
        history(c, "history SU.PA (MAX)", "SU.PA", "1980-01-01")
        fmp(c, "profile GSK.L", "profile", symbol="GSK.L")
        history(c, "history GSK.L (MAX)", "GSK.L", "1980-01-01")
        # --- Europa: ETF / ETC (Xetra) ---
        fmp(c, "profile EUNL.DE (iShares Core MSCI World, ETF)", "profile", symbol="EUNL.DE")
        fmp(c, "profile 4GLD.DE (Xetra-Gold, ETC)", "profile", symbol="4GLD.DE")
        history(c, "history 4GLD.DE (10 dni)", "4GLD.DE", (dt.date.today() - dt.timedelta(days=14)).isoformat())
        # --- USA: głębokość historii (5Y/MAX) ---
        history(c, "history AAPL (MAX)", "AAPL", "1980-01-01")
        # --- Dywidendy ---
        fmp(c, "dividends AAPL", "dividends", symbol="AAPL")
        fmp(c, "dividends SU.PA", "dividends", symbol="SU.PA")
        fmp(c, "dividends GSK.L", "dividends", symbol="GSK.L")
        # --- Krypto / metale ---
        fmp(c, "quote BTCUSD", "quote", symbol="BTCUSD")
        fmp(c, "quote GCUSD (złoto)", "quote", symbol="GCUSD")
        fmp(c, "quote SIUSD (srebro)", "quote", symbol="SIUSD")
        # --- CTVA / Vylor ---
        fmp(c, "profile CTVA", "profile", symbol="CTVA")
        history(c, "history CTVA wokół 2026-10-01 (czy FMP koryguje wstecz?)", "CTVA", "2026-09-22")
        fmp(c, "splits CTVA", "splits", symbol="CTVA")
        fmp(c, "profile VYLR", "profile", symbol="VYLR")
    print(f"\nFMP calls total: {CALLS}")

    try:
        with SecEdgarClient(os.environ["SEC_EDGAR_USER_AGENT"], max_retries=0) as sec:
            filings = sec.get_filings("1755672")
        print("\n=== SEC CTVA filings 2026-09-01..dziś ===")
        for f in filings:
            if f["filing_date"] >= "2026-09-01":
                print(f["filing_date"], f["form"], f["primary_document"])
    except (SecEdgarError, KeyError) as exc:
        print(f"SEC error: {exc}")


if __name__ == "__main__":
    main()

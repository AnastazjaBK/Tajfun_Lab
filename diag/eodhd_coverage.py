"""DIAG EODHD (jednorazowy, Decyzja właścicielki 2026-10-17): pokrycie
darmowego klucza EODHD dla instrumentów europejskich (ceny, waluta
notowania, historia 1D-1Y, dywidendy). Wyłącznie odczyt. Maks. 17
zapytań (limit Free: 20/dzień). Token nigdy nie jest drukowany ani
umieszczany w komunikatach błędów (drukujemy wyłącznie ścieżkę)."""

from __future__ import annotations

import datetime as dt
import json
import os

import httpx

BASE = "https://eodhd.com/api"
TOKEN = os.environ["EODHD_API_KEY"]
TODAY = dt.date.today()
ONE_YEAR_AGO = (TODAY - dt.timedelta(days=372)).isoformat()
CALLS = 0


def get(label: str, path: str, **params):
    global CALLS
    CALLS += 1
    print(f"\n=== {label} ===  [{path}]")
    try:
        resp = httpx.get(f"{BASE}/{path}", params={**params, "api_token": TOKEN, "fmt": "json"}, timeout=30)
    except httpx.HTTPError as exc:
        print("network error:", type(exc).__name__)
        return None
    print("status:", resp.status_code)
    if resp.status_code != 200:
        print("body:", resp.text[:300].replace(TOKEN, "***"))
        return None
    try:
        return resp.json()
    except ValueError:
        print("non-JSON body:", resp.text[:300].replace(TOKEN, "***"))
        return None


def show_rows(data, date_key="date") -> None:
    if isinstance(data, list):
        print(f"rows={len(data)}")
        if data and isinstance(data[0], dict):
            rows = sorted(data, key=lambda r: r.get(date_key) or "")
            print("keys:", sorted(rows[0].keys()))
            print("oldest:", json.dumps(rows[0])[:400])
            for r in rows[-3:]:
                print("recent:", json.dumps(r)[:400])
    elif data is not None:
        print(json.dumps(data, ensure_ascii=False)[:1200])


def main() -> None:
    user = get("user (plan i licznik zapytań, start)", "user")
    if isinstance(user, dict):
        print({k: user.get(k) for k in ("subscriptionType", "paymentMethod", "apiRequests", "dailyRateLimit", "apiRequestsDate")})

    for sym in ("SU.PA", "GSK.LSE", "EUNL.XETRA", "4GLD.XETRA"):
        show_rows(get(f"search {sym} (waluta, ISIN, typ)", f"search/{sym}"), date_key="Code")
    for sym in ("SU.PA", "GSK.LSE", "EUNL.XETRA", "4GLD.XETRA"):
        show_rows(get(f"eod {sym} ostatni rok", f"eod/{sym}", **{"from": ONE_YEAR_AGO, "to": TODAY.isoformat()}))
    show_rows(get("eod SU.PA od 2015 (czy Free ogranicza do 1 roku?)", "eod/SU.PA", **{"from": "2015-01-01", "to": TODAY.isoformat()}))
    for sym in ("SU.PA", "GSK.LSE", "VGWL.XETRA"):
        show_rows(get(f"dividends {sym}", f"div/{sym}", **{"from": "2020-01-01"}))
    for sym in ("SU.PA", "GSK.LSE"):
        show_rows(get(f"real-time {sym}", f"real-time/{sym}"))

    user = get("user (licznik zapytań, koniec)", "user")
    if isinstance(user, dict):
        print({k: user.get(k) for k in ("apiRequests", "dailyRateLimit", "apiRequestsDate")})
    print(f"\nEODHD HTTP calls total: {CALLS}")


if __name__ == "__main__":
    main()

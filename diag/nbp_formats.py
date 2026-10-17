"""DIAG NBP (jednorazowy): faktyczny format API NBP (tabela A, kursy
historyczne, ceny złota) -- publiczne, darmowe, bez klucza."""

import json

import httpx

URLS = [
    ("tabela A bieżąca", "https://api.nbp.pl/api/exchangerates/tables/a/?format=json"),
    ("USD zakres 2026-09-25..2026-10-06", "https://api.nbp.pl/api/exchangerates/rates/a/usd/2026-09-25/2026-10-06/?format=json"),
    ("EUR zakres weekend 2026-10-10..2026-10-12", "https://api.nbp.pl/api/exchangerates/rates/a/eur/2026-10-10/2026-10-12/?format=json"),
    ("tabela B bieżąca (lista walut)", "https://api.nbp.pl/api/exchangerates/tables/b/?format=json"),
    ("cena złota bieżąca", "https://api.nbp.pl/api/cenyzlota/?format=json"),
    ("cena złota zakres", "https://api.nbp.pl/api/cenyzlota/2026-10-01/2026-10-16/?format=json"),
]

for label, url in URLS:
    print(f"\n=== {label} ===")
    try:
        r = httpx.get(url, timeout=20, headers={"Accept": "application/json"})
    except httpx.HTTPError as exc:
        print("network error:", type(exc).__name__, exc)
        continue
    print("status:", r.status_code)
    try:
        data = r.json()
    except ValueError:
        print("body:", r.text[:300])
        continue
    if isinstance(data, list) and data and isinstance(data[0], dict) and "rates" in data[0]:
        t = data[0]
        print("table keys:", sorted(t.keys()), "effectiveDate:", t.get("effectiveDate"), "no:", t.get("no"))
        print("codes:", [x.get("code") for x in t["rates"]])
        print("first rate:", t["rates"][0])
    else:
        print(json.dumps(data, ensure_ascii=False)[:900])

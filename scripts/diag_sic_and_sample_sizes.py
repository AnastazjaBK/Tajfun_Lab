"""Diagnostyka SIC i liczebności prób (decyzje właścicielki 2026-10-24).

NARZĘDZIE DIAGNOSTYCZNE, nie kod produkcyjny. Tylko odczyt:
- SEC EDGAR (bezpłatne; throttling poniżej limitu 10 zapytań/s),
- FMP w ramach abonamentu (aktualny skład indeksu, surowe pola cash flow),
- artefakt kalibracji Round 1 `baseline` (calibration_result.db),
- snapshot skanu 22.10 (live_scan_result.db).
Bez Claude. Niczego nie zapisuje do baz wejściowych (otwierane
read-only). Nie liczy żadnych stóp zwrotu ani metryk wyników -- jedynie
liczebności obserwacji i spółek.

Sprawdza:
1. brakujące kody SIC (przyszły profil NIEZNANY) i błędy SEC, osobno dla:
   615 CIK uniwersum backtestu, 500 spółek uniwersum skanu 22.10 i
   aktualnego składu indeksu z FMP (zbiory nie są zastępowane jeden drugim);
2. historyczne zmiany SIC z nagłówków raportów 10-K (point-in-time) i ich
   wiarygodność (zgodność najnowszego nagłówka z bieżącym SIC);
3. liczebności per rok 2016-2021 (obserwacje i unikalne spółki), pełna
   próba i podzbiór z wyceną, oraz wpływ profilu NIEZNANY i SIC
   point-in-time na te liczebności;
4. dostępność pól SEC XBRL do oceny alokacji kapitału i zgodność dywidend
   na akcje zwykłe FMP vs SEC (z cache faktów w artefakcie, bez nowych zapytań).

Użycie: python scripts/diag_sic_and_sample_sizes.py --calibration-db X --snapshot-db Y --out Z.json
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from buffett_scanner.providers.fmp import FMPClient, FMPError  # noqa: E402
from buffett_scanner.providers.sec_edgar import ARCHIVES_BASE_URL, SecEdgarClient, SecEdgarError  # noqa: E402
from buffett_scanner.sector_classification import classify_sic_to_sector_profile  # noqa: E402

SUBMISSIONS_BASE = "https://data.sec.gov/submissions/"
ANNUAL_FORMS = ("10-K", "10-K405", "10-KT")
OOS_YEARS = (2016, 2017, 2018, 2019, 2020, 2021)
# Liczebności opublikowane w design review (5.4a, 5.4c) -- kontrola zgodności.
DOCUMENTED_FULL = {2016: 879, 2017: 481, 2018: 741, 2019: 1042, 2020: 2113, 2021: 578}
DOCUMENTED_VALUATION = {2016: 177, 2017: 108, 2018: 138, 2019: 229, 2020: 365, 2021: 94}
UNKNOWN = "NIEZNANY"

_CIK_RE = re.compile(r"(?:<CIK>|CENTRAL INDEX KEY:)\s*0*(\d+)")
_SIC_RE = re.compile(r"(?:<ASSIGNED-SIC>\s*(\d{3,4})|STANDARD INDUSTRIAL CLASSIFICATION:[^\n\[]*\[(\d{3,4})\])")


def norm_cik(cik) -> str:
    return str(int(str(cik)))


def profile_of(sic: str | None) -> str:
    """Reguła zatwierdzona 2026-10-24: brak kodu SIC -> NIEZNANY (nie GENERAL)."""
    return UNKNOWN if not sic else classify_sic_to_sector_profile(sic)


def parse_header_sic(text: str, cik: str) -> tuple[str | None, str]:
    """SIC filera o danym CIK z nagłówka zgłoszenia (format SGML .hdr.sgml
    albo tekstowy). Każdy kod SIC przypisany do najbliższego wcześniejszego
    CIK w nagłówku. Zwraca (sic, status)."""
    text = html.unescape(text)
    ciks = [(m.start(), m.group(1)) for m in _CIK_RE.finditer(text)]
    sics = [(m.start(), m.group(1) or m.group(2)) for m in _SIC_RE.finditer(text)]
    if not sics:
        return None, "BRAK_SIC_W_NAGLOWKU"
    target = norm_cik(cik)
    for pos, sic in sics:
        owner = None
        for cpos, c in ciks:
            if cpos < pos:
                owner = c
        if owner == target:
            return sic, "OK"
    return None, "BRAK_DOPASOWANIA_CIK"


def pit_sic(headers: list[dict], decision_date: str) -> str | None | bool:
    """SIC z najnowszego nagłówka 10-K złożonego najpóźniej w dniu decyzji.
    False = brak takiego nagłówka (nie da się ustalić point-in-time)."""
    best = None
    for h in headers:
        if h["filing_date"] <= decision_date and h["status"] == "OK":
            if best is None or h["filing_date"] > best["filing_date"]:
                best = h
    return False if best is None else best["sic"]


def annual_filings(submissions_pages: list[dict]) -> list[dict]:
    out, seen = [], set()
    for page in submissions_pages:
        cols = page.get("filings", {}).get("recent", page)
        forms = cols.get("form", [])
        for i, form in enumerate(forms):
            if form not in ANNUAL_FORMS:
                continue
            acc = cols["accessionNumber"][i]
            if acc in seen:
                continue
            seen.add(acc)
            out.append({"form": form, "accession": acc, "filing_date": cols["filingDate"][i]})
    return sorted(out, key=lambda f: f["filing_date"])


class SecFetcher:
    def __init__(self, client):
        self.c = client
        self.requests = 0

    def get(self, url: str):
        self.requests += 1
        return self.c._get(url)

    def submissions(self, cik: str) -> tuple[dict | None, list[dict], str | None]:
        resp = self.get(f"{SUBMISSIONS_BASE}CIK{norm_cik(cik).zfill(10)}.json")
        if resp.status_code != 200:
            return None, [], f"HTTP {resp.status_code}"
        data = resp.json()
        return data, [data], None

    def older_pages(self, data: dict, date_from: str) -> tuple[list[dict], list[str]]:
        pages, errors = [], []
        for f in data.get("filings", {}).get("files", []):
            if f.get("filingTo", "9999") < date_from:
                continue
            resp = self.get(SUBMISSIONS_BASE + f["name"])
            if resp.status_code != 200:
                errors.append(f"{f['name']}: HTTP {resp.status_code}")
                continue
            pages.append(resp.json())
        return pages, errors

    def header(self, cik: str, accession: str) -> tuple[str | None, str]:
        base = f"{ARCHIVES_BASE_URL}/{norm_cik(cik)}/{accession.replace('-', '')}/{accession}"
        for suffix in (".hdr.sgml", "-index-headers.html"):
            resp = self.get(base + suffix)
            if resp.status_code == 200:
                return resp.text, suffix
        return None, f"HTTP {resp.status_code}"


def collect_sec(fetcher, ciks_backtest: set[str], ciks_all: set[str], date_from: str, date_to: str) -> dict:
    out = {}
    for i, cik in enumerate(sorted(ciks_all, key=int), 1):
        rec = {"cik": cik, "error": None, "sic": None, "sic_description": None, "name": None, "headers": []}
        try:
            data, pages, err = fetcher.submissions(cik)
            if err:
                rec["error"] = err
            else:
                rec["sic"] = data.get("sic") or None
                rec["sic_description"] = data.get("sicDescription") or None
                rec["name"] = data.get("name")
                if cik in ciks_backtest:
                    older, page_errors = fetcher.older_pages(data, date_from)
                    rec["page_errors"] = page_errors
                    filings = annual_filings(pages + older)
                    window = [f for f in filings if date_from <= f["filing_date"] <= date_to]
                    after = [f for f in filings if f["filing_date"] > date_to]
                    targets = window + after[-1:]  # okno + najnowszy 10-K (test zgodności z bieżącym SIC)
                    for f in targets:
                        text, how = fetcher.header(cik, f["accession"])
                        sic, status = (None, "BRAK_NAGLOWKA " + how) if text is None else parse_header_sic(text, cik)
                        rec["headers"].append({**f, "sic": sic, "status": status, "in_window": f in window})
        except SecEdgarError as exc:
            rec["error"] = str(exc)
        out[cik] = rec
        if i % 50 == 0:
            print(f"  [{i}/{len(ciks_all)}] zapytań SEC: {fetcher.requests}", flush=True)
    return out


def load_backtest(conn) -> tuple[str, list[sqlite3.Row], dict]:
    runs = [r[0] for r in conn.execute("SELECT DISTINCT run_id FROM backtest_candidates")]
    if len(runs) != 1:
        raise SystemExit(f"STOP: oczekiwano jednego run_id w backtest_candidates, jest {runs}")
    run_id = runs[0]
    rows = conn.execute(
        "SELECT decision_date, cik, deterministic_score_pct, margin_of_safety_base_pct, return_6m_pct "
        "FROM backtest_candidates WHERE run_id = ?", (run_id,)).fetchall()
    bench = {r[0]: r[1] for r in conn.execute(
        "SELECT decision_date, ew_pit_universe_return_6m_pct FROM backtest_benchmark WHERE run_id = ?", (run_id,))}
    return run_id, rows, bench


def sample_sets(rows, bench) -> tuple[list[tuple], list[tuple]]:
    """Definicje identyczne z calibration._excess_pairs (pełna próba, 6 m vs EW)
    i calibration._score_return_triples(require_valuation=True)."""
    full, val = [], []
    for decision_date, cik, score, mos, ret6 in rows:
        year = int(decision_date[:4])
        if year not in OOS_YEARS or ret6 is None:
            continue
        if bench.get(decision_date) is not None:
            full.append((year, norm_cik(cik), decision_date))
        if mos is not None and score is not None:
            val.append((year, norm_cik(cik), decision_date))
    return full, val


def per_year(obs, pred=lambda o: True) -> dict[int, tuple[int, int]]:
    out = {}
    for y in OOS_YEARS:
        sel = [o for o in obs if o[0] == y and pred(o)]
        out[y] = (len(sel), len({o[1] for o in sel}))
    return out


def analyse(sec: dict, ciks_backtest: set[str], ciks_current: set[str], ranked: list[tuple[str, str]],
            rows, bench, ciks_fmp: set[str] = frozenset()) -> dict:
    rep: dict = {}
    sets = [("backtest_615", ciks_backtest), ("uniwersum_skanu_22_10", ciks_current),
            ("rankowane_22_10", {c for c, _ in ranked})]
    if ciks_fmp:
        sets.append(("aktualny_sklad_fmp", ciks_fmp))
    for label, cset in sets:
        recs = [sec[c] for c in cset]
        rep[label] = {
            "n": len(recs),
            "bledy_sec": sorted((r["cik"], r["error"]) for r in recs if r["error"]),
            "brak_sic": sorted((r["cik"], r["name"]) for r in recs if not r["error"] and not r["sic"]),
            "profile": dict(Counter(profile_of(r["sic"]) if not r["error"] else "BLAD_SEC" for r in recs)),
        }
    rep["rankowane_22_10_sic"] = [(t, c, sec[c]["sic"], profile_of(sec[c]["sic"]), sec[c]["sic_description"])
                                  for c, t in ranked]

    # --- nagłówki point-in-time -------------------------------------------------
    status = Counter()
    changes, profile_changes, latest_vs_current = [], [], Counter()
    no_window_headers = []
    for c in sorted(ciks_backtest, key=int):
        r = sec[c]
        hs = r["headers"]
        for h in hs:
            status[h["status"].split(" ")[0]] += 1
        ok = [h for h in hs if h["status"] == "OK"]
        if not [h for h in ok if h["in_window"]]:
            no_window_headers.append(c)
        seq = []
        for h in sorted(ok, key=lambda h: h["filing_date"]):
            if not seq or seq[-1][1] != h["sic"]:
                seq.append((h["filing_date"], h["sic"]))
        if len(seq) > 1:
            changes.append((c, r["name"], seq, r["sic"]))
            if len({profile_of(s) for _, s in seq} | {profile_of(r["sic"])}) > 1:
                profile_changes.append((c, r["name"], seq, r["sic"]))
        if ok and r["sic"]:
            latest = max(ok, key=lambda h: h["filing_date"])
            latest_vs_current["zgodny" if latest["sic"] == r["sic"] else "rozny"] += 1
        window_ok = [h for h in ok if h["in_window"]]
        if window_ok and r["sic"]:
            last_in_window = max(window_ok, key=lambda h: h["filing_date"])
            latest_vs_current["okno_" + ("zgodny" if last_in_window["sic"] == r["sic"] else "rozny")] += 1
    rep["naglowki"] = {
        "statusy": dict(status),
        "cik_bez_naglowka_w_oknie": len(no_window_headers),
        "cik_bez_naglowka_w_oknie_lista": no_window_headers,
        "zmiany_sic": changes,
        "zmiany_profilu": profile_changes,
        "najnowszy_naglowek_vs_biezacy_sic": dict(latest_vs_current),
    }

    # --- liczebności i wpływ ------------------------------------------------------
    full, val = sample_sets(rows, bench)
    cur_profile = {c: (profile_of(sec[c]["sic"]) if c in sec and not sec[c]["error"] else "BLAD_SEC") for c in ciks_backtest}
    headers = {c: sec[c]["headers"] for c in ciks_backtest}

    def pit_profile(o):
        s = pit_sic(headers.get(o[1], []), o[2])
        return "BRAK_PIT" if s is False else profile_of(s)

    sizes = {}
    for name, obs, doc in (("pelna", full, DOCUMENTED_FULL), ("z_wycena", val, DOCUMENTED_VALUATION)):
        base = per_year(obs)
        sizes[name] = {
            "per_rok": {y: {"obserwacje": n, "unikalne_spolki": u, "dokumentacja": doc[y], "zgodne": n == doc[y]}
                        for y, (n, u) in base.items()},
            "razem": {"obserwacje": len(obs), "unikalne_spolki": len({o[1] for o in obs})},
            "nieznany": per_year(obs, lambda o: cur_profile.get(o[1]) == UNKNOWN),
            "blad_sec": per_year(obs, lambda o: cur_profile.get(o[1]) == "BLAD_SEC"),
            "pit_inny_profil": per_year(obs, lambda o: pit_profile(o) not in ("BRAK_PIT", cur_profile.get(o[1]))),
            "pit_brak": per_year(obs, lambda o: pit_profile(o) == "BRAK_PIT"),
            "pit_przejscia": dict(Counter(f"{cur_profile.get(o[1])}->{pit_profile(o)}" for o in obs
                                          if pit_profile(o) not in ("BRAK_PIT", cur_profile.get(o[1])))),
        }
    rep["liczebnosci"] = sizes
    return rep


# --- 4. Pola SEC XBRL potrzebne do oceny alokacji kapitału (cache z artefaktu) ---
CAPITAL_TAGS = (
    "PaymentsOfDividendsCommonStock", "PaymentsOfDividends", "PaymentsOfDividendsPreferredStockAndPreferenceStock",
    "DividendsPreferredStock", "DividendsCommonStockCash", "CommonStockDividendsPerShareDeclared",
    "CommonStockDividendsPerShareCashPaid", "PaymentsForRepurchaseOfCommonStock", "ProceedsFromIssuanceOfCommonStock",
    "ProceedsFromStockOptionsExercised", "ShareBasedCompensation", "StockIssuedDuringPeriodSharesAcquisitions",
    "StockIssuedDuringPeriodValueAcquisitions", "StockRepurchasedDuringPeriodShares",
    "PaymentsToAcquireBusinessesNetOfCashAcquired", "ProceedsFromIssuanceOfLongTermDebt", "RepaymentsOfLongTermDebt",
)


def annual_facts(cf: dict, tag: str) -> dict[str, float]:
    """{koniec okresu: wartość} rocznych faktów (>= 330 dni, formularz 10-K),
    najpóźniej złożona wersja dla danego końca okresu."""
    import datetime as dt
    units = cf.get("facts", {}).get("us-gaap", {}).get(tag, {}).get("units", {})
    best: dict[str, tuple[str, float]] = {}
    for entries in units.values():
        for f in entries:
            if not f.get("start") or not str(f.get("form", "")).startswith("10-K"):
                continue
            if (dt.date.fromisoformat(f["end"]) - dt.date.fromisoformat(f["start"])).days < 330:
                continue
            if f["end"] not in best or f["filed"] > best[f["end"]][0]:
                best[f["end"]] = (f["filed"], f["val"])
    return {e: v for e, (_, v) in best.items()}


def capital_fields(cal, snap, ranked: list[tuple[str, str]]) -> dict:
    cache = {norm_cik(r[0]): r[1] for r in cal.execute("SELECT cik, raw_json FROM sec_company_facts_cache")}
    coverage = {t: {"2016_2021": 0, "FY2025": 0} for t in CAPITAL_TAGS}
    for raw in cache.values():
        cf = json.loads(raw)
        for t in CAPITAL_TAGS:
            ends = annual_facts(cf, t)
            if any("2016" <= e[:4] <= "2021" for e in ends):
                coverage[t]["2016_2021"] += 1
            if any(e[:4] in ("2025", "2026") for e in ends):
                coverage[t]["FY2025"] += 1
    # FMP `dividends_paid` (commonDividendsPaid) ze snapshotu vs SEC: dywidendy na akcje zwykłe.
    cmp_rows, by_ticker = [], {}
    for cik, ticker in ranked:
        if cik not in cache:
            continue
        cf = json.loads(cache[cik])
        common = annual_facts(cf, "PaymentsOfDividendsCommonStock")
        total = annual_facts(cf, "PaymentsOfDividends")
        pref = {**annual_facts(cf, "DividendsPreferredStock"),
                **annual_facts(cf, "PaymentsOfDividendsPreferredStockAndPreferenceStock")}
        dps = annual_facts(cf, "CommonStockDividendsPerShareDeclared")
        for end, fmp_val in snap.execute(
                "SELECT period_end_date, value FROM fundamentals_raw f JOIN companies c ON c.cik = f.cik "
                "WHERE f.line_item = 'dividends_paid' AND CAST(c.cik AS INTEGER) = ? ORDER BY period_end_date",
                (int(cik),)):
            def near(d):
                import datetime as dt
                e0 = dt.date.fromisoformat(end[:10])
                hits = [v for k, v in d.items() if abs((dt.date.fromisoformat(k) - e0).days) <= 7]
                return hits[0] if hits else None
            row = (ticker, end, fmp_val, near(common), near(total), near(pref), near(dps))
            cmp_rows.append(row)
            by_ticker.setdefault(ticker, []).append(row)
    mism = []
    for t, end, fmp_val, com, tot, pref, dps in cmp_rows:
        sec_val = com if com is not None else tot
        if fmp_val and sec_val is None:
            mism.append((t, end, fmp_val, None, "brak w SEC"))
        elif fmp_val is not None and sec_val is not None and abs(abs(fmp_val) - abs(sec_val)) > 0.05 * max(abs(sec_val), 1e6):
            mism.append((t, end, fmp_val, sec_val, "różnica > 5%"))
    return {"pokrycie_tagow_cik_z_615": coverage, "cache_cik": len(cache),
            "dywidendy_fmp_vs_sec_niezgodne": mism, "dywidendy_porownane_okresy": len(cmp_rows),
            "BA": by_ticker.get("BA", []), "przyklady": {t: by_ticker.get(t, []) for t in ("MRK", "TPR", "F", "AVGO")}}


# --- 6. FMP: aktualny skład indeksu i surowe pola cash flow ----------------------
FMP_KEY_HINTS = ("issu", "dividend", "stockbased", "acquisition", "repurchas", "debt")


def fmp_part(fmp, sec_tickers: dict[str, str], scan_universe: set[str], ranked: list[tuple[str, str]]) -> dict:
    out: dict = {}
    cons = fmp.get_sp500_constituents()
    cur = {}
    unmapped = []
    for row in cons:
        sym = row.get("symbol")
        cik = row.get("cik") or sec_tickers.get(str(sym).upper().replace(".", "-"))
        if cik:
            cur[norm_cik(cik)] = sym
        else:
            unmapped.append(sym)
    out["sklad_fmp"] = {"n": len(cons), "cik_zmapowane": len(cur), "bez_cik": unmapped,
                        "pola_rekordu": sorted(cons[0].keys()) if cons else []}
    out["sklad_fmp_vs_uniwersum_skanu_22_10"] = {
        "tylko_w_skladzie_fmp": sorted((c, cur[c]) for c in set(cur) - scan_universe),
        "tylko_w_uniwersum_skanu": sorted(scan_universe - set(cur)),
    }
    keys, nonzero, ba_rows, errors = Counter(), Counter(), [], []
    for cik, ticker in ranked:
        try:
            rows = fmp.get_cash_flow_statement(ticker)
        except FMPError as exc:
            errors.append((ticker, str(exc)[:120]))
            continue
        for r in rows:
            for k, v in r.items():
                if any(h in k.lower() for h in FMP_KEY_HINTS):
                    keys[k] += 1
                    if isinstance(v, (int, float)) and v != 0:
                        nonzero[k] += 1
        if ticker == "BA":
            ba_rows = [{k: v for k, v in r.items() if k in ("date", "fiscalYear") or any(
                h in k.lower() for h in FMP_KEY_HINTS)} for r in rows]
    out["cash_flow_pola"] = {k: {"wiersze": keys[k], "niezerowe": nonzero[k]} for k in sorted(keys)}
    out["cash_flow_bledy"] = errors
    out["BA_cash_flow"] = ba_rows
    return out, cur


def print_report(rep: dict) -> None:
    print("\n== 1. Brakujące SIC i błędy SEC ==")
    for label in ("backtest_615", "uniwersum_skanu_22_10", "rankowane_22_10", "aktualny_sklad_fmp"):
        if label not in rep:
            continue
        r = rep[label]
        print(f"{label}: n={r['n']} | profile={r['profile']} | błędy SEC={len(r['bledy_sec'])} | brak SIC={len(r['brak_sic'])}")
        for cik, name in r["brak_sic"]:
            print(f"   brak SIC: CIK={cik} {name}")
        for cik, err in r["bledy_sec"]:
            print(f"   błąd SEC: CIK={cik} {err}")
    print("\n== 2. Nagłówki 10-K (point-in-time) ==")
    n = rep["naglowki"]
    print(f"statusy nagłówków: {n['statusy']}")
    print(f"CIK backtestu bez żadnego odczytanego nagłówka w oknie: {n['cik_bez_naglowka_w_oknie']}")
    print(f"zgodność z bieżącym SIC: {n['najnowszy_naglowek_vs_biezacy_sic']}")
    print(f"CIK ze zmianą SIC w nagłówkach: {len(n['zmiany_sic'])}; ze zmianą profilu: {len(n['zmiany_profilu'])}")
    for cik, name, seq, cur in n["zmiany_sic"]:
        flag = " [PROFIL]" if any(x[0] == cik for x in n["zmiany_profilu"]) else ""
        print(f"   CIK={cik} {name}: {' -> '.join(f'{s}({d})' for d, s in seq)} | bieżący {cur}{flag}")
    print("\n== 3. Liczebności 2016-2021 (obserwacje / unikalne spółki) ==")
    for name, s in rep["liczebnosci"].items():
        print(f"-- próba: {name} | razem {s['razem']}")
        for y, v in s["per_rok"].items():
            print(f"   {y}: {v['obserwacje']} obs. / {v['unikalne_spolki']} spółek | dokumentacja {v['dokumentacja']} "
                  f"| {'ZGODNE' if v['zgodne'] else 'NIEZGODNE'}")
        for key in ("nieznany", "blad_sec", "pit_inny_profil", "pit_brak"):
            print(f"   {key}: " + ", ".join(f"{y}: {o}/{u}" for y, (o, u) in s[key].items()))
        print(f"   przejścia profilu (bieżący->PIT): {s['pit_przejscia']}")
    if "fmp" in rep:
        f = rep["fmp"]
        print("\n== 6. FMP: aktualny skład indeksu (osobny zbiór, NIE uniwersum skanu 22.10) ==")
        print(f"   rekordów {f['sklad_fmp']['n']}, z CIK {f['sklad_fmp']['cik_zmapowane']}, bez CIK {f['sklad_fmp']['bez_cik']}")
        print(f"   pola rekordu: {f['sklad_fmp']['pola_rekordu']}")
        d_ = f["sklad_fmp_vs_uniwersum_skanu_22_10"]
        print(f"   tylko w aktualnym składzie FMP: {d_['tylko_w_skladzie_fmp']}")
        print(f"   tylko w uniwersum skanu 22.10: {d_['tylko_w_uniwersum_skanu']}")
        print("   surowe pola cash flow FMP (wiersze / niezerowe), spółki rankowane 22.10:")
        for k, v in f["cash_flow_pola"].items():
            print(f"     {k}: {v['wiersze']} / {v['niezerowe']}")
        print(f"   błędy FMP: {f['cash_flow_bledy']}")
        for r in f["BA_cash_flow"]:
            print(f"   BA: {r}")
    if "kapital" in rep:
        k = rep["kapital"]
        print(f"\n== 5. Pola SEC XBRL do alokacji kapitału (cache: {k['cache_cik']} CIK) ==")
        for t, v in k["pokrycie_tagow_cik_z_615"].items():
            print(f"   {t}: CIK z danymi 2016-2021 {v['2016_2021']} | FY2025 {v['FY2025']}")
        print(f"   dywidendy FMP vs SEC: porównane okresy {k['dywidendy_porownane_okresy']}, "
              f"niezgodne {len(k['dywidendy_fmp_vs_sec_niezgodne'])}")
        for row in k["dywidendy_fmp_vs_sec_niezgodne"]:
            print(f"   niezgodne: {row}")
        print("   BA (koniec okresu, FMP, SEC common, SEC razem, SEC uprzyw., DPS zadekl.):")
        for row in k["BA"]:
            print(f"     {row[1:]}")
        for t, rows in k["przyklady"].items():
            for row in rows:
                print(f"   {t}: {row[1:]}")
    print("\n== 4. SIC spółek rankowanych 22.10 (ticker, CIK, SIC, profil) ==")
    for t, c, sic, prof, desc in rep["rankowane_22_10_sic"]:
        print(f"   {t};{c};{sic};{prof};{desc}")


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--calibration-db", required=True)
    p.add_argument("--snapshot-db", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--header-from", default="2011-01-01")
    p.add_argument("--header-to", default="2021-12-31")
    p.add_argument("--max-ciks", type=int, default=0, help="test na małej próbie (0 = wszystkie)")
    a = p.parse_args(argv)
    if os.environ.get("ANTHROPIC_API_KEY"):
        print("STOP: ANTHROPIC_API_KEY ustawiony -- diagnostyka nie może wywoływać Claude.")
        return 2
    cal = sqlite3.connect(f"file:{a.calibration_db}?mode=ro", uri=True)
    snap = sqlite3.connect(f"file:{a.snapshot_db}?mode=ro", uri=True)
    ciks_backtest = {norm_cik(r[0]) for r in cal.execute("SELECT DISTINCT cik FROM universe_membership")}
    ciks_current = {norm_cik(r[0]) for r in snap.execute("SELECT cik FROM companies")}
    ranked = [(norm_cik(c), t) for c, t in snap.execute("SELECT cik, ticker FROM live_scan_candidates ORDER BY ticker")]
    run_id, rows, bench = load_backtest(cal)
    fmp_rep, ciks_fmp = None, set()
    fmp_key = os.environ.get("FMP_API_KEY")
    if fmp_key:
        ua0 = os.environ.get("SEC_EDGAR_USER_AGENT", "")
        with SecEdgarClient(ua0, min_interval_s=0.15) as sc0:
            sec_tickers = {t.upper(): norm_cik(c) for t, c in sc0.get_company_tickers().items()}
        with FMPClient(fmp_key, min_interval_s=0.2) as fmp:
            fmp_rep, cur_map = fmp_part(fmp, sec_tickers, ciks_current, ranked)
        ciks_fmp = set(cur_map)
        print(f"Aktualny skład indeksu z FMP: {len(ciks_fmp)} CIK (osobny zbiór od uniwersum skanu 22.10)")
    print(f"backtest run_id={run_id} | kandydaci={len(rows)} | CIK backtestu={len(ciks_backtest)} "
          f"| obecny skład={len(ciks_current)} | rankowane 22.10={len(ranked)}")
    ciks_all = ciks_backtest | ciks_current | ciks_fmp
    if a.max_ciks:
        keep = sorted(ciks_backtest, key=int)[: a.max_ciks] + sorted(ciks_current - ciks_backtest, key=int)[: a.max_ciks]
        ciks_all = set(keep) | {c for c, _ in ranked if c in ciks_backtest}
        ciks_backtest &= ciks_all
        ciks_current &= ciks_all
        ciks_fmp &= ciks_all
        ranked = [r for r in ranked if r[0] in ciks_all]
        print(f"TRYB TESTOWY: {len(ciks_all)} CIK")
    ua = os.environ.get("SEC_EDGAR_USER_AGENT", "")
    with SecEdgarClient(ua, min_interval_s=0.15) as client:
        fetcher = SecFetcher(client)
        sec = collect_sec(fetcher, ciks_backtest, ciks_all, a.header_from, a.header_to)
    print(f"Zapytań SEC łącznie: {fetcher.requests}")
    if a.max_ciks:
        rows = [r for r in rows if norm_cik(r[1]) in ciks_backtest]
    rep = analyse(sec, ciks_backtest, ciks_current, ranked, rows, bench, ciks_fmp)
    if fmp_rep is not None:
        rep["fmp"] = fmp_rep
    rep["kapital"] = capital_fields(cal, snap, ranked)
    rep["meta"] = {"run_id": run_id, "sec_requests": fetcher.requests, "test_mode": bool(a.max_ciks)}
    Path(a.out).write_text(json.dumps({"report": rep, "sec": sec}, ensure_ascii=False, indent=1, default=str))
    print_report(rep)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Użycie: python -I <ten plik> <snapshot 22.10.db> docs/analysis/diag_2026_10_24/sic_ranked_22_10.csv
(APO_CAPEX_NULL=1: wariant, w którym SEC nie potwierdza CAPEX = 0 dla APO).
Ranking 22.10 offline: zapisany (kod f931c38, mechanizm 6.10) vs obecny kod
(a) profile jak 6.10 (wszystkie GENERAL) -- izoluje poprawkę dźwigni;
(b) profile z SIC (SEC, diagnostyka 24.10) -- obecny skan na żywo.
CAPEX/dywidendy: bez weryfikacji SEC (brak faktów w snapshocie) -- lista spółek, których dotyczy."""
import csv, shutil, sqlite3, sys, tempfile
sys.path.insert(0, "/home/user/Tajfun_Lab")
from buffett_scanner.backtest_harness import compute_deterministic_score
from buffett_scanner.config import load_config
from buffett_scanner.db import connect, get_fundamentals_periods
from buffett_scanner.sector_classification import classify_sic_to_sector_profile, UNKNOWN_PROFILE

snap, csv_path = sys.argv[1], sys.argv[2]
tmp = tempfile.mkdtemp() + "/s.db"; shutil.copy(snap, tmp)
conn = connect(tmp)
import os
if os.environ.get("APO_CAPEX_NULL"):
    conn.execute("update fundamentals_raw set value=NULL where line_item='capital_expenditure' and value=0 and cik=(select cik from live_scan_candidates where ticker='APO')")
config = load_config("/home/user/Tajfun_Lab/config/config.yaml")
sic = {r[0]: r[2] for r in csv.reader(open(csv_path), delimiter=";")}
rows = conn.execute("select ticker,cik,current_price,deterministic_score_pct,rank,in_shortlist from live_scan_candidates").fetchall()

def rank(scores):
    s = sorted([(v, t) for t, v in scores.items() if v is not None], key=lambda x: (-x[0], x[1]))
    out, prev, r = {}, None, 0
    for i, (v, t) in enumerate(s, 1):
        if v != prev: r, prev = i, v
        out[t] = r
    return out, s

def shortlist(s, limit=20):
    if len(s) <= limit: return [t for _, t in s]
    b = s[limit - 1][0]
    return [t for v, t in s if v >= b]

stored = {r["ticker"]: r["deterministic_score_pct"] for r in rows}
gen, sicp, prof = {}, {}, {}
for r in rows:
    periods = get_fundamentals_periods(conn, r["cik"])
    gen[r["ticker"]] = compute_deterministic_score(periods=periods, sector_profile="GENERAL",
        current_price=r["current_price"], config=config).deterministic_score_pct
    p = classify_sic_to_sector_profile(sic.get(r["ticker"]))
    prof[r["ticker"]] = p
    sicp[r["ticker"]] = None if p == UNKNOWN_PROFILE else compute_deterministic_score(
        periods=periods, sector_profile=p, current_price=r["current_price"], config=config).deterministic_score_pct

for name, sc in [("zapisany 22.10 (mechanizm 6.10)", stored), ("obecny kod, profile GENERAL", gen), ("obecny kod, profile SIC", sicp)]:
    rk, s = rank(sc)
    sl = shortlist(s)
    print(f"== {name}: rankingowanych {len(s)}, shortlista {len(sl)}")
    print("   " + ", ".join(f"{t}({rk[t]}{'=' if list(rk.values()).count(rk[t])>1 else ''}:{sc[t]:.1f})" for t in sl))
base = shortlist(rank(stored)[1])
for name, sc in [("dźwignia (GENERAL)", gen), ("dźwignia + SIC", sicp)]:
    sl = shortlist(rank(sc)[1])
    print(f"-- {name}: wypadają {sorted(set(base)-set(sl))}, wchodzą {sorted(set(sl)-set(base))}")
diff = {t: (stored[t], gen[t]) for t in stored if stored[t] is not None and abs((gen[t] or 0) - stored[t]) > 1e-9}
print("Zmiana wyniku przez samą dźwignię:", {t: (round(a,1), round(b,1)) for t, (a, b) in diff.items()})
print("Profile inne niż GENERAL:", {t: p for t, p in prof.items() if p != "GENERAL"})
rk, s = rank(sicp)
print("Pozycje spółek z profilem innym niż GENERAL (SIC):", {t: (rk.get(t), None if sicp[t] is None else round(sicp[t],1)) for t, p in prof.items() if p != "GENERAL"})
capex0 = sorted({conn.execute("select ticker from live_scan_candidates where cik=?", (c,)).fetchone()[0] for (c,) in conn.execute(
    "select distinct cik from fundamentals_raw where line_item='capital_expenditure' and value=0") if conn.execute("select 1 from live_scan_candidates where cik=?", (c,)).fetchone()})
print("CAPEX = 0 w danych FMP (weryfikacja SEC w skanie):", capex0)
sl_sic = shortlist(rank(sicp)[1])
print("  w tym na shortliście (SIC):", [t for t in capex0 if t in sl_sic])

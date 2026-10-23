"""(Narzędzie analityczne, NIE kod produkcyjny. Użycie: python <ten plik> <snapshot.db>)
Symulacje decyzji (NIC nie jest wdrażane): wybór do Claude z dwóch list,
grupa niekompletnych danych, statystyki dywidend/buybacków -- dane 22.10."""
import sqlite3, sys, math, dataclasses
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2]))
from buffett_scanner.config import load_config
from buffett_scanner.db import get_fundamentals_periods
from buffett_scanner.backtest_harness import compute_deterministic_score
from buffett_scanner.scoring import financial_quality_score
from buffett_scanner.fundamentals import free_cash_flow, net_debt
from buffett_scanner.shareholder_returns import evaluate_dividend_shareholder_return, share_count_trend
from buffett_scanner.data_quality import input_gaps, dcf_absence_kind

DB = sys.argv[1]
c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True); c.row_factory = sqlite3.Row
cfg = load_config()
PROFILE = {"GL": "INSURER", "ARE": "REIT", "WY": "REIT"}
SUSPICIOUS_CAPEX = {"APO", "COIN"}   # scenariusz B: CAPEX=0 bez potwierdzenia u spółek GENERAL
N = 20
C = []
for r in c.execute("select * from live_scan_candidates order by ticker"):
    periods = get_fundamentals_periods(c, r["cik"])
    if r["ticker"] in SUSPICIOUS_CAPEX:
        periods = [dataclasses.replace(p, capital_expenditure=None) for p in periods]
    prof = PROFILE.get(r["ticker"], "GENERAL")
    s = compute_deterministic_score(periods=periods, sector_profile=prof, current_price=r["current_price"], config=cfg)
    gaps = input_gaps(periods) if prof == "GENERAL" else [g for g in input_gaps(periods) if not g.startswith("capital_expenditure")]
    kind = dcf_absence_kind(gaps, s.valuation_result)
    group = "NIEKOMPLETNE" if (gaps and prof == "GENERAL") or kind == "BRAK_DANYCH" else ("Z_DCF" if s.valuation_score is not None else "BEZ_DCF")
    C.append(dict(t=r["ticker"], prof=prof, pct=s.deterministic_score_pct, group=group, gaps=gaps, s=s, periods=periods,
                  price=r["current_price"], prod_short=bool(r["in_shortlist"]), prod_rank=r["rank"]))

groups = {g: sorted([x for x in C if x["group"] == g], key=lambda x: (-x["pct"], x["t"])) for g in ("Z_DCF", "BEZ_DCF", "NIEKOMPLETNE")}
print("Grupy:", {g: len(v) for g, v in groups.items()})
print("NIEKOMPLETNE:", [(x["t"], x["gaps"][:2]) for x in groups["NIEKOMPLETNE"]])
print("BEZ_DCF wg profilu:", {p: [x["t"] for x in groups["BEZ_DCF"] if x["prof"] == p][:8] for p in ("INSURER", "REIT")})

def top_with_ties(lst, k):
    if k <= 0: return []
    if len(lst) <= k: return [x["t"] for x in lst]
    b = lst[k - 1]["pct"]
    return [x["t"] for x in lst if x["pct"] >= b - 1e-9]

prod = [x["t"] for x in sorted(C, key=lambda x: x["prod_rank"]) if x["prod_short"]]
ranked_pool = len(groups["Z_DCF"]) + len(groups["BEZ_DCF"])

# S1 -- ta sama selektywność w obu listach (metoda największych reszt)
frac = N / ranked_pool
quota = {g: len(groups[g]) * frac for g in ("Z_DCF", "BEZ_DCF")}
alloc = {g: math.floor(q) for g, q in quota.items()}
for g in sorted(quota, key=lambda g: -(quota[g] - alloc[g]))[: N - sum(alloc.values())]:
    alloc[g] += 1
s1 = {g: top_with_ties(groups[g], alloc[g]) for g in alloc}
print(f"\nS1 ta sama selektywność ({frac*100:.1f}% każdej listy): przydział {quota} -> {alloc}")
for g, v in s1.items(): print(f"  {g}: {v}")

# S2 -- percentyl w obrębie własnej listy, wspólne cięcie
def pctl(lst):
    n = len(lst); out = {}
    for x in lst:
        better = sum(1 for y in lst if y["pct"] > x["pct"] + 1e-9)
        out[x["t"]] = 1 - better / n   # odsetek spółek z wynikiem nie wyższym
    return out
P = {**pctl(groups["Z_DCF"]), **pctl(groups["BEZ_DCF"])}
order = sorted(P.items(), key=lambda kv: (-kv[1], kv[0]))
b = order[N - 1][1]
s2 = [t for t, p in order if p >= b - 1e-9]
print(f"\nS2 percentyl we własnej liście, wspólny próg (>= {b:.3f}): {len(s2)} spółek")
print("  z DCF:", [t for t in s2 if t in {x['t'] for x in groups['Z_DCF']}])
print("  bez DCF:", [t for t in s2 if t in {x['t'] for x in groups['BEZ_DCF']}])

# S3 -- jedna kolejność na wspólnych komponentach (safety+dywidendy /25) jako bramka,
#        potem wycena porządkuje tylko w liście z DCF (informacyjnie)
common = sorted([x for g in ("Z_DCF", "BEZ_DCF") for x in groups[g]], key=lambda x: (-(x["s"].safety_score + x["s"].dividend_score), x["t"]))
bb = common[N - 1]["s"].safety_score + common[N - 1]["s"].dividend_score
s3 = [x["t"] for x in common if x["s"].safety_score + x["s"].dividend_score >= bb - 1e-9]
print(f"\nS3 wspólna baza 25 pkt jako bramka: {len(s3)} spółek (remisy); bez DCF wśród nich: {[t for t in s3 if t in {x['t'] for x in groups['BEZ_DCF']}]}")

def cmp(label, sel):
    sel = set(sel)
    print(f"{label}: {len(sel)} | wypadają vs produkcja: {sorted(set(prod) - sel)} | wchodzą: {sorted(sel - set(prod))}")
print()
cmp("S1", [t for v in s1.values() for t in v]); cmp("S2", s2); cmp("S3", s3)

# GL / profile finansowe -- czy kryteria bezpieczeństwa mają sens
print("\nBezpieczeństwo (kryteria) dla profili niefinansowych metod:")
for x in C:
    if x["prof"] != "GENERAL":
        fq = financial_quality_score(x["periods"], cfg)
        print(" ", x["t"], x["prof"], f"safety={x['s'].safety_score:.1f}", fq.breakdown)

# Dywidendy / buyback -- statystyki danych
print("\n== Dywidendy i buyback (najnowszy okres, 162 spółki) ==")
rows = []
for x in C:
    p = x["periods"]; L, Pr = p[-1], (p[-2] if len(p) > 1 else None)
    d = evaluate_dividend_shareholder_return(p, current_price=x["price"], config=cfg.dividend_shareholder_return)
    fcf = free_cash_flow(L); nd, ndp = net_debt(L), (net_debt(Pr) if Pr else None)
    rows.append(dict(t=x["t"], dps=d.dividend_per_share_latest, div=L.dividends_paid, bb=L.share_buybacks, fcf=fcf,
                     nd_up=(nd is not None and ndp is not None and nd > ndp), trend=share_count_trend(p)))
nonpay = [r for r in rows if r["div"] == 0]
print("dividends_paid brak danych:", sum(r["div"] is None for r in rows), "| share_buybacks brak:", sum(r["bb"] is None for r in rows),
      "| liczba akcji (trend) brak:", sum(r["trend"] is None for r in rows))
print("bez dywidendy:", len(nonpay), "| w tym z buybackiem > 0:", sum(1 for r in nonpay if r["bb"]), "| bez dywidendy i bez buybacku (czysta reinwestycja):", sum(1 for r in nonpay if not r["bb"]))
ret = [r for r in rows if (r["div"] or 0) + (r["bb"] or 0) > 0]
unc = [r for r in ret if r["fcf"] is None or (r["div"] or 0) + (r["bb"] or 0) > r["fcf"]]
print("zwracające kapitał:", len(ret), "| zwrot > FCF (niepokryty FCF):", len(unc), "| z tego dług netto wzrósł r/r:", sum(1 for r in unc if r["nd_up"]))
print("  przykłady niepokryte i dług wzrósł:", [r["t"] for r in unc if r["nd_up"]][:12])
inc = [r for r in rows if r["bb"] and r["trend"] == "INCREASING"]
print("buyback > 0, a liczba akcji rośnie (emisja/SBC > skup):", len(inc), [r["t"] for r in inc][:12])

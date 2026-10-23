"""(Narzędzie analityczne, NIE kod produkcyjny. Użycie: python <ten plik> <snapshot.db>)
Runda 3 -- symulacje do decyzji, NIC nie jest wdrażane (dane skanu 22.10):
  A. kwalifikacja do Claude według kryteriów w każdej grupie (bez kwot miejsc),
  B. doprecyzowany P-D3 (zwrot kapitału, 10 pkt) z przykładami spółek.
Założenia jak w selection_rules_2026_10_23.py: GL = INSURER, ARE i WY = REIT
(źródła wtórne), CAPEX = 0 bez potwierdzenia u APO i COIN -> brak danych."""
import dataclasses
import sqlite3
import statistics
import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2]))
from buffett_scanner.backtest_harness import compute_deterministic_score  # noqa: E402
from buffett_scanner.config import load_config  # noqa: E402
from buffett_scanner.data_quality import dcf_absence_kind, input_gaps  # noqa: E402
from buffett_scanner.db import get_fundamentals_periods  # noqa: E402
from buffett_scanner.fundamentals import free_cash_flow, net_debt  # noqa: E402
from buffett_scanner.scoring import financial_quality_score  # noqa: E402

DB = sys.argv[1]
c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
c.row_factory = sqlite3.Row
cfg = load_config()
PROFILE = {"GL": "INSURER", "ARE": "REIT", "WY": "REIT"}
SUSPICIOUS_CAPEX = {"APO", "COIN"}
EPS = 1e-9

C = []
for r in c.execute("select * from live_scan_candidates order by ticker"):
    periods = get_fundamentals_periods(c, r["cik"])
    if r["ticker"] in SUSPICIOUS_CAPEX:
        periods = [dataclasses.replace(p, capital_expenditure=None) for p in periods]
    prof = PROFILE.get(r["ticker"], "GENERAL")
    s = compute_deterministic_score(periods=periods, sector_profile=prof, current_price=r["current_price"], config=cfg)
    gaps = input_gaps(periods)
    if prof != "GENERAL":
        group = "BEZ_METODY"
    elif gaps or dcf_absence_kind(gaps, s.valuation_result) == "BRAK_DANYCH":
        group = "NIEKOMPLETNE"
    else:
        group = "Z_DCF" if s.valuation_score is not None else "BEZ_DCF"
    mos = s.valuation_result.scenarios["base"].margin_of_safety_pct if s.valuation_score is not None else None
    fq = financial_quality_score(periods, cfg)
    C.append(dict(t=r["ticker"], prof=prof, group=group, pct=s.deterministic_score_pct, s=s, mos=mos, fq=fq.raw_score,
                  fq_bd=fq.breakdown, periods=periods, price=r["current_price"], prod_short=bool(r["in_shortlist"])))
BY = {x["t"]: x for x in C}
GROUPS = ("Z_DCF", "BEZ_DCF", "BEZ_METODY", "NIEKOMPLETNE")
print("Grupy:", {g: len([x for x in C if x["group"] == g]) for g in GROUPS})
print("BEZ_METODY:", [x["t"] for x in C if x["group"] == "BEZ_METODY"],
      "| NIEKOMPLETNE:", [x["t"] for x in C if x["group"] == "NIEKOMPLETNE"])
prod = sorted(x["t"] for x in C if x["prod_short"])

# ============ A. Kwalifikacja według kryteriów =====================================
# Kryterium bezpieczeństwa: istniejący financial_quality_score (0-16 pkt surowych,
# te same 6 kryteriów co dziś). Kryterium wyceny: MoS BASE z istniejącego DCF.
# To są dokładnie istniejące, dziś wyłączone hard gates (min_financial_safety,
# min_margin_of_safety_pct). Progi poniżej to SIATKA DO DECYZJI, nie wybór.
print("\n== A. Kwalifikacja: siatka progów (liczebność wynika z kryteriów) ==")
print("Rozkład bezpieczeństwa (pkt surowe /16) w grupach operacyjnych:")
for g in ("Z_DCF", "BEZ_DCF"):
    vals = sorted(x["fq"] for x in C if x["group"] == g)
    print(f"  {g}: n={len(vals)} | " + ", ".join(f">={k}: {sum(v >= k for v in vals)}" for k in (8, 10, 12, 14, 16)))
mos_vals = [x["mos"] for x in C if x["group"] == "Z_DCF"]
print("  Z_DCF MoS BASE: " + ", ".join(f">={k}%: {sum(m >= k for m in mos_vals)}" for k in (0, 25, 50)))

print("\n| min bezp. (/16) | min MoS (Z_DCF) | Q z DCF | Q bez DCF | razem | max wywołań (x3) | wspólne z produkcją |")
grid = {}
for fq_min in (8, 10, 12, 14):
    for mos_min in (0, 25, 50):
        qz = sorted(x["t"] for x in C if x["group"] == "Z_DCF" and x["fq"] >= fq_min - EPS and x["mos"] >= mos_min - EPS)
        qb = sorted(x["t"] for x in C if x["group"] == "BEZ_DCF" and x["fq"] >= fq_min - EPS)
        grid[(fq_min, mos_min)] = (qz, qb)
        print(f"| {fq_min} | {mos_min}% | {len(qz)} | {len(qb)} | {len(qz) + len(qb)} | {3 * (len(qz) + len(qb))} "
              f"| {len(set(qz + qb) & set(prod))}/{len(prod)} |")
for key in ((14, 50), (14, 25), (12, 50)):
    qz, qb = grid[key]
    print(f"\nProgi {key}: z DCF {qz}\n  bez DCF {qb}\n  produkcja poza Q: {sorted(set(prod) - set(qz + qb))}"
          f"\n  Q poza produkcją: {sorted(set(qz + qb) - set(prod))}")

print("\nBEZ_DCF -- przyczyna braku DCF i bezpieczeństwo:")
for x in sorted((x for x in C if x["group"] == "BEZ_DCF"), key=lambda x: -x["fq"])[:12]:
    reason = (x["s"].valuation_result.reason or "")[:90]
    print(f"  {x['t']}: fq={x['fq']:.0f} | {reason}")

# ============ B. P-D3 doprecyzowany (10 pkt) ========================================
# Okno 3 lat obrachunkowych t-2..t (przepływy) i zmiana liczby akcji S_t vs S_{t-3}.
# A. zwrot netto (0-4): NSY3 = średnia roczna dywidenda / kapitalizacja
#    + roczne tempo spadku liczby akcji (ujemne przy rozwodnieniu). Liniowo 0 -> 4 pkt przy T.
# B. źródło finansowania (0-4): tylko gdy spółka zwracała kapitał (D3 + B3 > 0):
#    (D3 + B3) <= FCF3 przy FCF3 > 0 -> 4; nadwyżka ponad FCF3, ale dług brutto
#    nie wzrósł w oknie -> 2; nadwyżka przy rosnącym długu brutto albo FCF3 <= 0 -> 0.
#    Dług BRUTTO, nie netto: wypłata z gotówki też podnosi dług netto.
# C. ciągłość (0-2): zwrot w każdym z 3 lat (D_t > 0 lub B_t > 0) i brak cięcia DPS
#    (t vs t-1, reguła jak dziś) u płacących. Spółka bez zwrotu kapitału: 0.
# Brak danych wejściowych kryterium -> 0 pkt i oznaczenie NIEZNANE.
T_GRID = (4.0, 6.0)


def pd3(x, T=4.0):
    p = x["periods"]
    out = dict(flags=[])
    if len(p) < 4:
        out["flags"].append(f"okno skrócone ({len(p)} okresy)")
    w = p[-3:] if len(p) >= 3 else p
    s_now = p[-1].diluted_shares_outstanding
    s_old = p[-4].diluted_shares_outstanding if len(p) >= 4 else p[0].diluted_shares_outstanding
    years = 3 if len(p) >= 4 else len(p) - 1
    D = [q.dividends_paid for q in w]
    B = [q.share_buybacks for q in w]
    F = [free_cash_flow(q) for q in w]
    if None in D or None in B or not s_now or not s_old or years < 1:
        out.update(A=0, B=0, C=0, total=0)
        out["flags"].append("NIEZNANE: brak D/B/S")
        return out
    mcap = x["price"] * s_now
    div_yield = sum(D) / len(D) / mcap * 100
    share_rate = (1 - (s_now / s_old) ** (1 / years)) * 100  # >0 = ubywa akcji
    nsy = div_yield + share_rate
    out.update(div_yield=div_yield, share_rate=share_rate, nsy=nsy)
    out["A"] = 0.0 if nsy <= 0 else 4.0 * min(nsy / T, 1.0)
    paid = sum(D) + sum(B)
    out["paid"] = paid
    debt_old, debt_new = (p[-4] if len(p) >= 4 else p[0]).total_debt, p[-1].total_debt
    if paid <= 0:
        out["B"] = 0.0
        out["flags"].append("bez zwrotu kapitału")
    elif None in F:
        out["B"] = 0.0
        out["flags"].append("NIEZNANE: brak FCF w oknie")
    else:
        fcf3 = sum(F)
        out["cover"] = paid / fcf3 * 100 if fcf3 > 0 else None
        if fcf3 > 0 and paid <= fcf3 + EPS:
            out["B"] = 4.0
        elif debt_old is None or debt_new is None:
            out["B"] = 0.0
            out["flags"].append("NIEZNANE: brak długu w oknie")
        elif fcf3 > 0 and debt_new <= debt_old:
            out["B"] = 2.0
            out["flags"].append("nadwyżka ponad FCF bez wzrostu długu")
        else:
            out["B"] = 0.0
            out["flags"].append("nadwyżka ponad FCF przy rosnącym długu" if fcf3 > 0 else "FCF3 <= 0")
    every_year = all((d or 0) + (b or 0) > 0 for d, b in zip(D, B))
    payer = any(d > 0 for d in D)
    dps = [q.dividends_paid / q.diluted_shares_outstanding if q.diluted_shares_outstanding else None for q in w]
    cut = payer and (None in dps[-2:] or dps[-1] < dps[-2] - EPS)
    out["C"] = 2.0 if every_year and not cut else 0.0
    if cut:
        out["flags"].append("cięcie DPS r/r")
    out["total"] = out["A"] + out["B"] + out["C"]
    return out


for x in C:
    x["pd3"] = pd3(x)
    x["pd3_T6"] = pd3(x, 6.0)
    x["div_now"] = x["s"].dividend_score

ops = [x for x in C if x["group"] in ("Z_DCF", "BEZ_DCF", "NIEKOMPLETNE")]
nsy = [x["pd3"]["nsy"] for x in ops if "nsy" in x["pd3"]]
print("\n== B. P-D3 doprecyzowany ==")
print(f"NSY3 (spółki operacyjne, n={len(nsy)}): mediana {statistics.median(nsy):.2f}%, "
      f"kwartyle {statistics.quantiles(nsy, n=4)[0]:.2f} / {statistics.quantiles(nsy, n=4)[2]:.2f}%, "
      f"<=0: {sum(v <= 0 for v in nsy)}")
for T in T_GRID:
    key = "pd3" if T == 4.0 else "pd3_T6"
    tot = [x[key]["total"] for x in ops]
    print(f"T={T}%: rozkład punktów: mediana {statistics.median(tot):.1f}, 10/10: {sum(t >= 10 - EPS for t in tot)}, "
          f"0: {sum(t <= EPS for t in tot)}")
nonpay = [x for x in ops if all((q.dividends_paid or 0) == 0 for q in x["periods"][-3:])]
reinv = [x for x in nonpay if all((q.share_buybacks or 0) == 0 for q in x["periods"][-3:])]
print(f"bez dywidendy w oknie: {len(nonpay)} | dziś 10/10: {sum(x['div_now'] >= 10 - EPS for x in nonpay)} "
      f"| P-D3 10/10: {sum(x['pd3']['total'] >= 10 - EPS for x in nonpay)}")
print(f"czysta reinwestycja (bez D i B przez 3 lata): {len(reinv)} {[x['t'] for x in reinv]}")
print("  ich punkty dziś -> P-D3:", [(x["t"], x["div_now"], round(x["pd3"]["total"], 1)) for x in reinv])
debt = [x["t"] for x in ops if "nadwyżka ponad FCF przy rosnącym długu" in x["pd3"]["flags"]]
uncov = [x["t"] for x in ops if x["pd3"].get("paid", 0) > 0 and x["pd3"]["B"] < 4]
print("cięcie DPS r/r:", [x["t"] for x in ops if "cięcie DPS r/r" in x["pd3"]["flags"]])
print("dziś 'brak cięcia' przyznany spółkom bez dywidendy:",
      sum(1 for x in ops if x["s"].dividend_result.breakdown["no_dividend_cut"] and not x["periods"][-1].dividends_paid))
dil = [x["t"] for x in ops if x["pd3"].get("share_rate", 0) < 0 and sum((q.share_buybacks or 0) for q in x["periods"][-3:]) > 0]
print(f"zwrot niepokryty z 3-letniego FCF: {len(uncov)}; w tym przy rosnącym długu brutto: {len(debt)} {debt[:15]}")
print(f"buyback w oknie, a liczba akcji wzrosła w 3 latach: {len(dil)} {dil[:15]}")
print(f"okno skrócone: {[x['t'] for x in ops if any(f.startswith('okno') for f in x['pd3']['flags'])]}")

EXAMPLES = ["MRK", "SNA", "ADBE", "CHTR", "AVGO", "APP", "NFLX", "UBER", "DECK", "TPR", "QCOM", "BA"] + [x["t"] for x in reinv[:3]]
print("\n| Spółka | dziś | DY3 % | tempo akcji %/r | NSY3 % | A | pokrycie % FCF3 | B | C | P-D3 | T=6% | flagi |")
for t in EXAMPLES:
    if t not in BY:
        continue
    x, d = BY[t], BY[t]["pd3"]
    cov = d.get("cover")
    print(f"| {t} | {x['div_now']:.0f} | {d.get('div_yield', float('nan')):.2f} | {d.get('share_rate', float('nan')):+.2f} "
          f"| {d.get('nsy', float('nan')):.2f} | {d['A']:.1f} | {'—' if cov is None else f'{cov:.0f}'} | {d['B']:.0f} "
          f"| {d['C']:.0f} | {d['total']:.1f} | {x['pd3_T6']['total']:.1f} | {'; '.join(d['flags'])} |")

# Wpływ na wynik deterministyczny i TOP20 rankingu (informacyjnie; przy kwalifikacji
# progowej dywidendy nie decydują o skierowaniu do Claude -- patrz dokument).
W = cfg.scoring.weights


def pct_with(x, div):
    s = x["s"]
    pts = s.safety_score + div + (s.valuation_score or 0)
    base = W.financial_safety + W.dividend_shareholder_return + (W.valuation if s.valuation_score is not None else 0)
    return pts / base * 100


def top(key):
    lst = sorted((x for x in C if x["group"] in ("Z_DCF", "BEZ_DCF")), key=lambda x: (-x[key], x["t"]))
    b = lst[19][key]
    return {x["t"] for x in lst if x[key] >= b - EPS}


for x in C:
    x["p_now"] = pct_with(x, x["div_now"])
    x["p_pd3"] = pct_with(x, x["pd3"]["total"])
a, b = top("p_now"), top("p_pd3")
print(f"\nTOP20+remisy (Z_DCF + BEZ_DCF, renormalizacja jak dziś): dziś {len(a)}, P-D3 {len(b)}; "
      f"wypadają {sorted(a - b)}, wchodzą {sorted(b - a)}")
print("B = 2 (nadwyżka ponad FCF3 bez wzrostu długu brutto):",
      [x["t"] for x in ops if "nadwyżka ponad FCF bez wzrostu długu" in x["pd3"]["flags"]])
print("P-D3 = 10:", [x["t"] for x in ops if x["pd3"]["total"] >= 10 - EPS])
print("dziś 10/10 i P-D3 <= 4:", [(x["t"], round(x["pd3"]["total"], 1)) for x in ops
                                   if x["div_now"] >= 10 - EPS and x["pd3"]["total"] <= 4 + EPS])

# Wariant kryterium bezpieczeństwa oparty na warunkach, nie na sumie punktów:
# "rdzeń wypłacalności" = FCF > 0 i dług netto/EBITDA <= 2 i brak trwałych strat.
print("\n== A2. Rdzeń wypłacalności (3 warunki z istniejących kryteriów) ==")
CORE = ("fcf_positive", "low_leverage", "no_persistent_losses")
for mos_min in (0, 25, 50):
    qz = sorted(x["t"] for x in C if x["group"] == "Z_DCF" and all(x["fq_bd"][k] for k in CORE) and x["mos"] >= mos_min - EPS)
    qb = sorted(x["t"] for x in C if x["group"] == "BEZ_DCF" and all(x["fq_bd"][k] for k in CORE))
    print(f"MoS >= {mos_min}%: z DCF {len(qz)}, bez DCF {len(qb)}, razem {len(qz) + len(qb)}, "
          f"wspólne z produkcją {len(set(qz + qb) & set(prod))}/{len(prod)}")
    if mos_min == 0:
        print("  bez DCF:", qb)
    if mos_min == 50:
        print("  z DCF:", qz)

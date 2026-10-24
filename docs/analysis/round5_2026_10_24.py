"""(Narzędzie analityczne, NIE kod produkcyjny.
Użycie: python <ten plik> <snapshot.db> <sic_ranked_22_10.csv>)

Runda 5 -- symulacja kwalifikacji do Claude na zapisanych danych skanu 22.10,
KODEM PRODUKCYJNYM PO POPRAWKACH (commit 6cef41d i późniejsze):
- poprawka 6 (dźwignia przy EBITDA <= 0) -- w scoringu;
- poprawka 8 (SIC 6500 -> GENERAL z oznaczeniem) -- kody SIC z diagnostyki SEC
  (run 40098265387), profil liczony bieżącą regułą `classify_sic_to_sector_profile`;
- kwalifikacja: `buffett_scanner.qualification` (decyzje 1, 3, 4, 5).
Poprawka 7 (dywidendy uprzywilejowane) wymaga faktów SEC, których snapshot nie ma
-- nie wpływa na kwalifikację (kryteria nie używają dywidend), opisana w raporcie.
Bez sieci, bez Claude. Niczego nie zapisuje."""
import dataclasses
import sqlite3
import statistics
import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2]))
from buffett_scanner import qualification as q  # noqa: E402
from buffett_scanner.backtest_harness import compute_deterministic_score  # noqa: E402
from buffett_scanner.cli import MAX_REPAIR_ATTEMPTS  # noqa: E402
from buffett_scanner.config import load_config  # noqa: E402
from buffett_scanner.data_quality import dcf_absence_kind, input_gaps  # noqa: E402
from buffett_scanner.db import get_fundamentals_periods  # noqa: E402
from buffett_scanner.fundamentals import free_cash_flow  # noqa: E402
from buffett_scanner.sector_classification import classify_sic_to_sector_profile  # noqa: E402

DB, SIC_CSV = sys.argv[1], sys.argv[2]
cfg = load_config()
LEV = cfg.financial_quality.net_debt_to_ebitda_low_leverage_threshold
SUSPICIOUS_CAPEX = {"APO", "COIN"}  # jak w rundach 3-4: CAPEX = 0 bez potwierdzenia w SEC
# Cennik claude-sonnet-5 (model z config/config.yaml), dokumentacja Claude API,
# stan 2026-10-06: 2 USD / 1 mln tokenów wejścia, 10 USD / 1 mln tokenów wyjścia.
PRICE_IN, PRICE_OUT = 2.0 / 1e6, 10.0 / 1e6

sic = {}
for line in open(SIC_CSV, encoding="utf-8"):
    t, _cik, code, _old_profile = line.strip().split(";")[:4]
    sic[t] = None if code in ("", "None") else code

c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
c.row_factory = sqlite3.Row
rows = []
for r in c.execute("select * from live_scan_candidates order by ticker"):
    periods = get_fundamentals_periods(c, r["cik"])
    if r["ticker"] in SUSPICIOUS_CAPEX:
        periods = [dataclasses.replace(p, capital_expenditure=None) for p in periods]
    profile = classify_sic_to_sector_profile(sic.get(r["ticker"]))
    s = compute_deterministic_score(periods=periods, sector_profile=profile if profile != "NIEZNANY" else "GENERAL",
                                    current_price=r["current_price"], config=cfg)
    gaps = input_gaps(periods)
    if profile == "NIEZNANY":
        group = "NIEKOMPLETNE"
    elif profile != "GENERAL":
        group = "BEZ_METODY"
    elif gaps or dcf_absence_kind(gaps, s.valuation_result) == "BRAK_DANYCH":
        group = "NIEKOMPLETNE"
    else:
        group = "Z_DCF" if s.valuation_score is not None else "BEZ_DCF"
    vr = s.valuation_result
    base = vr.scenarios.get("base") if vr.implemented else None
    mos = base.margin_of_safety_pct if base else None
    fcf = [free_cash_flow(p) for p in periods]
    rows.append(dict(
        t=r["ticker"], group=group, profile=profile, sic=sic.get(r["ticker"]), periods=periods, mos=mos,
        growth=base.projected_growth_rate_pct if base else None, cagr=vr.historical_growth_cagr_pct,
        fcf_last=fcf[-1], fcf_prev=[v for v in fcf[-4:-1] if v is not None],
        safety_new=s.safety_score, safety_old=r["safety_score"], pct_new=s.deterministic_score_pct,
        pct_old=r["deterministic_score_pct"], prod=bool(r["in_shortlist"]),
        q0=q.qualify(group=group, periods=periods, margin_of_safety_base_pct=mos, sic=sic.get(r["ticker"]),
                     leverage_threshold=LEV, min_margin_of_safety_pct=0.0),
        q50=q.qualify(group=group, periods=periods, margin_of_safety_base_pct=mos, sic=sic.get(r["ticker"]),
                      leverage_threshold=LEV, min_margin_of_safety_pct=50.0),
    ))
by = {x["t"]: x for x in rows}

print("== 0. Wpływ poprawek na dane 22.10 ==")
print("Grupy:", {g: sum(x["group"] == g for x in rows) for g in ("Z_DCF", "BEZ_DCF", "BEZ_METODY", "NIEKOMPLETNE")})
print("BEZ_METODY:", sorted(x["t"] for x in rows if x["group"] == "BEZ_METODY"),
      "| NIEKOMPLETNE:", sorted(x["t"] for x in rows if x["group"] == "NIEKOMPLETNE"))
changed = [(x["t"], round(x["safety_old"], 2), round(x["safety_new"], 2)) for x in rows
           if abs(x["safety_old"] - x["safety_new"]) > 1e-6]
print("Bezpieczeństwo zmienione (stare -> nowe, skala 15):", changed)
print("  uwaga: stare wartości z bazy liczone były bez profilu SIC (wszystkie GENERAL); różnice mogą wynikać "
      "też z poprawki 1 (profile), nie tylko 6")

for label, key in (("MoS >= 0 (preferencja)", "q0"), ("MoS >= 50 (porównanie)", "q50")):
    print(f"\n== 1. Kwalifikacja: {label} ==")
    st = {}
    for x in rows:
        st.setdefault(x[key].status, []).append(x["t"])
    for status in (q.QUALIFIED, q.QUALIFIED_NO_PRICE, q.MANUAL_REVIEW, q.NOT_QUALIFIED, q.NO_METHOD, q.INCOMPLETE):
        print(f"  {status}: {len(st.get(status, []))} {sorted(st.get(status, []))}")
    n = len(st.get(q.QUALIFIED, [])) + len(st.get(q.QUALIFIED_NO_PRICE, []))
    print(f"  do Claude: {n} spółek | wywołania: minimum {n}, najgorszy przypadek "
          f"{q.worst_case_calls(n, MAX_REPAIR_ATTEMPTS)} | mieści się w 75: "
          f"{q.within_call_limit(n, max_calls=75, max_repair_attempts=MAX_REPAIR_ATTEMPTS)}")
    prod = {x["t"] for x in rows if x["prod"]}
    qset = set(st.get(q.QUALIFIED, []) + st.get(q.QUALIFIED_NO_PRICE, []))
    print(f"  obecna shortlista (24) poza kwalifikacją: {sorted(prod - qset)}; nowe względem shortlisty: "
          f"{sorted(qset - prod)}")

print("\n== 2. Ręczny przegląd -- przyczyny ==")
for x in sorted(rows, key=lambda x: x["t"]):
    if x["q0"].status == q.MANUAL_REVIEW:
        mos = "—" if x["mos"] is None else f"{x['mos']:.1f}%"
        print(f"  {x['t']} ({x['group']}, SIC {x['sic']}, MoS {mos}): " + "; ".join(x["q0"].reasons))

print("\n== 3. Powody braku kwalifikacji (MoS >= 0) ==")
reasons = {}
for x in rows:
    if x["q0"].status == q.NOT_QUALIFIED:
        for r in x["q0"].reasons:
            key = r.split(" ")[0] + " " + r.split(" ")[1] if r.startswith(("FCF", "MoS", "zysk")) else r.split(" ")[0]
            reasons.setdefault(r.split(" ")[0] if not r.startswith("dług netto/EBITDA") else "dźwignia > próg", []).append(x["t"])
for k, v in sorted(reasons.items(), key=lambda kv: -len(kv[1])):
    print(f"  {k}: {len(v)}")

print("\n== 4. MoS >= 0 a ograniczenia DCF (spółki zakwalifikowane z DCF) ==")
qd = [x for x in rows if x["q0"].status == q.QUALIFIED]
print(f"| Spółka | MoS BASE | CAGR FCF (2 punkty) | wzrost w projekcji | FCF ost. / śr. 3 wcześn. | uwagi |")
cap = cfg.valuation.dcf_owner_earnings.max_projected_growth_rate_pct
flags_count = {"sufit": 0, "szczyt": 0, "0-50": 0, ">=50": 0}
for x in sorted(qd, key=lambda x: -x["mos"]):
    prev = statistics.mean(x["fcf_prev"]) if x["fcf_prev"] else None
    ratio = x["fcf_last"] / prev if prev and prev > 0 else None
    notes = []
    if x["growth"] is not None and x["growth"] >= cap - 1e-9:
        notes.append(f"wzrost przycięty do sufitu {cap:g}%")
        flags_count["sufit"] += 1
    if ratio is not None and ratio >= 2.0:
        notes.append("baza FCF >= 2x średniej wcześniejszych lat")
        flags_count["szczyt"] += 1
    if x["mos"] >= 50:
        notes.append("pełne punkty za wycenę (nasycenie)")
        flags_count[">=50"] += 1
    else:
        flags_count["0-50"] += 1
    print(f"| {x['t']} | {x['mos']:.1f}% | {('—' if x['cagr'] is None else f'{x[chr(99)+chr(97)+chr(103)+chr(114)]:.1f}%')} "
          f"| {x['growth']:.1f}% | {('—' if ratio is None else f'{ratio:.2f}')} | {'; '.join(notes)} |")
print("Podsumowanie:", flags_count)

print("\n== 5. Spółki bez DCF zakwalifikowane (N1: jakość bez potwierdzonej ceny) -- przyczyna braku DCF ==")
for x in rows:
    if x["q0"].status == q.QUALIFIED_NO_PRICE:
        fcf = [free_cash_flow(p) for p in x["periods"]]
        print(f"  {x['t']}: FCF okna {[round(v / 1e9, 2) for v in fcf if v is not None]} mld")

print("\n== 6. Koszt (rzeczywiste zużycie tokenów 24 analiz z 22.10) ==")
usage = c.execute("select llm_input_tokens i, llm_output_tokens o from live_scan_candidates "
                  "where llm_input_tokens is not null").fetchall()
inp = [u["i"] for u in usage]
out = [u["o"] for u in usage]
per_call = [i * PRICE_IN + o * PRICE_OUT for i, o in zip(inp, out)]
print(f"wywołań z danymi: {len(usage)} | wejście śr. {statistics.mean(inp):.0f}, wyjście śr. {statistics.mean(out):.0f} "
      f"(min {min(out)}, max {max(out)}) tokenów | koszt wywołania śr. {statistics.mean(per_call):.4f} USD, "
      f"max {max(per_call):.4f} USD")
for label, key in (("MoS >= 0", "q0"), ("MoS >= 50", "q50")):
    n = sum(1 for x in rows if x[key].status in (q.QUALIFIED, q.QUALIFIED_NO_PRICE))
    worst = q.worst_case_calls(n, MAX_REPAIR_ATTEMPTS)
    print(f"{label}: {n} spółek -> bez napraw {n} wywołań ≈ {n * statistics.mean(per_call):.2f} USD "
          f"(przy maks. zużyciu {n * max(per_call):.2f}); najgorszy przypadek {worst} wywołań ≈ "
          f"{worst * max(per_call):.2f} USD (każda naprawa liczona jak pełne wywołanie -- górne oszacowanie)")

# ---------- 7. K2 -- ilustracja proponowanej punktacji (NIE wdrożona) ----------------
# A (0-7): realny zwrot dla właściciela = roczne tempo zmiany FCF na akcję (średnia
#   2 ostatnich lat vs średnia 2 lat sprzed 3 lat) + średnia stopa dywidendy z 3 lat.
#   Liniowo 0 przy <= 0 do 7 przy >= stopie dyskontowej BASE z configu (9%).
#   W docelowej wersji FCF pomniejszony o SBC -- snapshot 22.10 nie ma pola SBC.
#   Niepoliczalne (ujemny/zerowy start, brak danych) -> 3,5 pkt (neutralnie) + oznaczenie.
# B (0-2): liczba akcji w oknie nie wzrosła -> 2; wzrosła -> 0. Docelowo z wyłączeniem
#   lat z oznaczoną emisją przy przejęciu (snapshot nie ma danych o przejęciach).
# C (0-1): dźwignia na końcu okna <= próg z configu albo gotówka netto, albo nie wzrosła
#   w oknie -> 1; inaczej 0.
from buffett_scanner.fundamentals import net_debt  # noqa: E402

R_BASE = cfg.valuation.dcf_owner_earnings.discount_rate_pct.base


def lev(p):
    nd = net_debt(p)
    if nd is None or p.ebitda is None:
        return None
    if nd <= 0:
        return 0.0
    return nd / p.ebitda if p.ebitda > 0 else float("inf")


def k2(x, price):
    p = x["periods"]
    out = {"flags": []}
    if len(p) < 5:
        out["flags"].append("okno < 5 lat")
    fps = [(free_cash_flow(q_) / q_.diluted_shares_outstanding) if free_cash_flow(q_) is not None
           and q_.diluted_shares_outstanding else None for q_ in p]
    start, end = fps[-5:-3] if len(p) >= 5 else fps[:2], fps[-2:]
    dy = [(q_.dividends_paid or 0) / q_.diluted_shares_outstanding / price * 100 for q_ in p[-3:]
          if q_.diluted_shares_outstanding]
    div_yield = statistics.mean(dy) if dy else 0.0
    if None in start or None in end or not start or statistics.mean(start) <= 0 or statistics.mean(end) <= 0:
        out["A"], out["g"] = 3.5, None
        out["flags"].append("A niepoliczalne (ujemny/zerowy start lub brak danych) -- neutralnie")
    else:
        years = max(len(p) - 2, 1) if len(p) < 5 else 3
        g = ((statistics.mean(end) / statistics.mean(start)) ** (1 / years) - 1) * 100
        total = g + div_yield
        out["g"] = g
        out["A"] = 0.0 if total <= 0 else 7.0 * min(total / R_BASE, 1.0)
    out["dy"] = div_yield
    s0, s1 = p[-4].diluted_shares_outstanding if len(p) >= 4 else None, p[-1].diluted_shares_outstanding
    out["shares"] = None if not s0 or not s1 else (s1 / s0 - 1) * 100
    out["B"] = 2.0 if out["shares"] is not None and out["shares"] <= 0 else 0.0
    l0, l1 = lev(p[-4]) if len(p) >= 4 else None, lev(p[-1])
    out["C"] = 1.0 if l1 is not None and (l1 <= LEV or (l0 is not None and l1 <= l0)) else 0.0
    out["total"] = out["A"] + out["B"] + out["C"]
    return out


print("\n== 7. K2 -- ilustracja (FCF bez SBC; bez wyłączenia przejęć) ==")
prices = {r["ticker"]: r["current_price"] for r in c.execute("select ticker, current_price from live_scan_candidates")}
ops = [x for x in rows if x["group"] in ("Z_DCF", "BEZ_DCF")]
for x in ops:
    x["k2"] = k2(x, prices[x["t"]])
    x["div_now"] = compute_deterministic_score(periods=x["periods"], sector_profile="GENERAL",
                                               current_price=prices[x["t"]], config=cfg).dividend_score
tot = [x["k2"]["total"] for x in ops]
print(f"rozkład K2 (n={len(tot)}): mediana {statistics.median(tot):.1f}, 10/10: {sum(t >= 10 - 1e-9 for t in tot)}, "
      f"<= 2: {sum(t <= 2 for t in tot)}, A neutralne: {sum(1 for x in ops if x['k2']['g'] is None)}")
reinv = [x for x in ops if all((q_.dividends_paid or 0) == 0 and (q_.share_buybacks or 0) == 0
                               for q_ in x["periods"][-3:])]
payers = [x for x in ops if all((q_.dividends_paid or 0) > 0 for q_ in x["periods"][-3:])]
print(f"bez wypłat w 3 latach (n={len(reinv)}): mediana dziś {statistics.median([x['div_now'] for x in reinv]):.1f} "
      f"-> K2 {statistics.median([x['k2']['total'] for x in reinv]):.1f}; płacący dywidendę co roku (n={len(payers)}): "
      f"dziś {statistics.median([x['div_now'] for x in payers]):.1f} -> K2 {statistics.median([x['k2']['total'] for x in payers]):.1f}")
EX = ["MRK", "SNA", "QCOM", "CHTR", "ADBE", "AVGO", "TPR", "DECK", "APP", "NFLX", "UBER", "BA",
      "AXON", "BSX", "TYL", "DDOG", "RDDT", "CVNA", "MU", "FSLR"]
print("| Spółka | dziś (10) | wzrost FCF/akcję %/r | dyw. yield % | A | liczba akcji 3 l. % | B | C | K2 | uwagi |")
for t in EX:
    x = by.get(t)
    if x is None or "k2" not in x:
        continue
    k = x["k2"]
    g = "—" if k["g"] is None else f"{k['g']:.1f}"
    sh = "—" if k["shares"] is None else f"{k['shares']:+.1f}"
    print(f"| {t} | {x['div_now']:.0f} | {g} | {k['dy']:.2f} | {k['A']:.1f} | {sh} | {k['B']:.0f} | {k['C']:.0f} "
          f"| {k['total']:.1f} | {'; '.join(k['flags'])} |")

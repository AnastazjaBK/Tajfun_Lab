"""(Narzędzie analityczne, NIE kod produkcyjny. Użycie: python <ten plik> <snapshot.db> [profile.csv])
Runda 4 -- kwalifikacja do Claude: ograniczenia „rdzenia wypłacalności”
i porównanie reguł na spółkach z 22.10. Nic nie jest wdrażane.

profile.csv (opcjonalnie): ticker;cik;sic;profil -- kody SIC z diagnostyki SEC
(workflow diag-sic-sample-sizes). Bez pliku: założenia z rundy 3."""
import dataclasses
import sqlite3
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
EPS = 1e-9
PROFILE = {"GL": "INSURER", "ARE": "REIT", "WY": "REIT"}
if len(sys.argv) > 2:
    PROFILE = {}
    for line in open(sys.argv[2], encoding="utf-8"):
        t, _cik, _sic, prof = line.strip().split(";")[:4]
        PROFILE[t] = prof
SUSPICIOUS_CAPEX = {"APO", "COIN"}

C = []
for r in c.execute("select * from live_scan_candidates order by ticker"):
    periods = get_fundamentals_periods(c, r["cik"])
    if r["ticker"] in SUSPICIOUS_CAPEX:
        periods = [dataclasses.replace(p, capital_expenditure=None) for p in periods]
    prof = PROFILE.get(r["ticker"], "GENERAL")
    s = compute_deterministic_score(periods=periods, sector_profile=prof if prof != "NIEZNANY" else "GENERAL",
                                    current_price=r["current_price"], config=cfg)
    gaps = input_gaps(periods)
    if prof == "NIEZNANY":
        group = "NIEKOMPLETNE"
    elif prof != "GENERAL":
        group = "BEZ_METODY"
    elif gaps or dcf_absence_kind(gaps, s.valuation_result) == "BRAK_DANYCH":
        group = "NIEKOMPLETNE"
    else:
        group = "Z_DCF" if s.valuation_score is not None else "BEZ_DCF"
    L = periods[-1]
    fcf = [free_cash_flow(p) for p in periods]
    ni = [p.net_income for p in periods]
    nd = net_debt(L)
    fq = financial_quality_score(periods, cfg)
    C.append(dict(
        t=r["ticker"], group=group, prof=prof, prod_short=bool(r["in_shortlist"]), fq=fq.raw_score, bd=fq.breakdown,
        mos=s.valuation_result.scenarios["base"].margin_of_safety_pct if s.valuation_score is not None else None,
        fcf_last=fcf[-1], fcf3=sum(fcf[-3:]) if None not in fcf[-3:] else None,
        nd=nd, ebitda=L.ebitda, lev=(nd / L.ebitda if nd is not None and L.ebitda else None),
        ni3=ni[-3:], rev=L.revenue))
BY = {x["t"]: x for x in C}
OPS = [x for x in C if x["group"] in ("Z_DCF", "BEZ_DCF")]
print("Grupy:", {g: sum(x["group"] == g for x in C) for g in ("Z_DCF", "BEZ_DCF", "BEZ_METODY", "NIEKOMPLETNE")})
print("BEZ_METODY:", sorted(x["t"] for x in C if x["group"] == "BEZ_METODY"),
      "| NIEKOMPLETNE:", sorted(x["t"] for x in C if x["group"] == "NIEKOMPLETNE"))


def bn(v):
    return "—" if v is None else f"{v / 1e9:,.2f}"


# ---------- 1. Ograniczenia trzech warunków (fakty z danych) --------------------
print("\n== 1. Ograniczenia warunków rdzenia ==")
neg_ebitda = [x for x in OPS if x["ebitda"] is not None and x["ebitda"] <= 0]
print("EBITDA <= 0:", [(x["t"], bn(x["ebitda"]), bn(x["nd"]), x["bd"]["low_leverage"]) for x in neg_ebitda])
false_pass = [x["t"] for x in neg_ebitda if x["bd"]["low_leverage"]]
print("  'niska dźwignia' zaliczona mimo EBITDA <= 0 (dług netto/EBITDA ujemny przez znak):", false_pass)
lev_none = [x["t"] for x in OPS if x["lev"] is None]
print("dźwignia niepoliczalna (brak danych/EBITDA=0):", lev_none)
fcf_flip = [(x["t"], bn(x["fcf_last"]), bn(x["fcf3"])) for x in OPS
            if x["fcf_last"] is not None and x["fcf_last"] <= 0 and x["fcf3"] is not None and x["fcf3"] > 0]
print("FCF ostatniego roku <= 0, ale suma 3 lat > 0:", fcf_flip)
fcf_flip2 = [(x["t"], bn(x["fcf_last"]), bn(x["fcf3"])) for x in OPS
             if x["fcf_last"] is not None and x["fcf_last"] > 0 and x["fcf3"] is not None and x["fcf3"] <= 0]
print("FCF ostatniego roku > 0, ale suma 3 lat <= 0:", fcf_flip2)
weak_loss = [(x["t"], [bn(v) for v in x["ni3"]]) for x in OPS
             if x["bd"]["no_persistent_losses"] and sum(1 for v in x["ni3"] if v is not None and v < 0) >= 1]
print("„brak trwałych strat” zaliczony mimo straty w 1-2 z 3 lat:", weak_loss)
lev_band = sorted(((x["t"], round(x["lev"], 2)) for x in OPS if x["lev"] is not None and 2 < x["lev"] <= 3),
                  key=lambda v: v[1])
print("dług netto/EBITDA w przedziale (2; 3] (wypadają przez próg 2):", lev_band)

# ---------- 2. Reguły i wyniki ------------------------------------------------------
CORE = ("fcf_positive", "low_leverage", "no_persistent_losses")


def core_now(x):
    return all(x["bd"][k] for k in CORE)


def core_fixed(x):
    """Rdzeń z poprawionymi ograniczeniami (propozycja): FCF z 3 lat > 0;
    dźwignia liczona tylko przy EBITDA > 0 (EBITDA <= 0 przy długu netto > 0 = nie
    spełnia; gotówka netto = spełnia); zysk netto > 0 w co najmniej 2 z 3 lat."""
    fcf_ok = x["fcf3"] is not None and x["fcf3"] > 0
    if x["nd"] is None:
        lev_ok = False
    elif x["nd"] <= 0:
        lev_ok = True
    else:
        lev_ok = x["ebitda"] is not None and x["ebitda"] > 0 and x["nd"] / x["ebitda"] <= 2 + EPS
    ni = x["ni3"]
    ni_ok = len(ni) == 3 and None not in ni and sum(v > 0 for v in ni) >= 2
    return fcf_ok and lev_ok and ni_ok


def why_fixed(x):
    out = []
    if not (x["fcf3"] is not None and x["fcf3"] > 0):
        out.append(f"FCF 3 l. {bn(x['fcf3'])} mld")
    if x["nd"] is None:
        out.append("brak długu netto")
    elif x["nd"] > 0 and not (x["ebitda"] and x["ebitda"] > 0 and x["nd"] / x["ebitda"] <= 2 + EPS):
        out.append(f"dług netto/EBITDA {x['lev']:.2f}" if x["ebitda"] and x["ebitda"] > 0 else "dług netto przy EBITDA <= 0")
    ni = x["ni3"]
    if not (len(ni) == 3 and None not in ni and sum(v > 0 for v in ni) >= 2):
        out.append("zysk netto > 0 w mniej niż 2 z 3 lat")
    return ", ".join(out)


RULES = {
    "P12": lambda x: x["fq"] >= 12 - EPS,
    "RDZEN": core_now,
    "RDZEN_POPR": core_fixed,
}
VAL = {"MoS>=0": 0.0, "MoS>=50": 50.0}
print("\n== 2. Reguły kwalifikacji (bezpieczeństwo x wycena dla grupy z DCF) ==")
print("| Reguła bezp. | Wycena | Q z DCF | Q bez DCF | razem | maks. wywołań |")
Q = {}
for rn, rule in RULES.items():
    for vn, vmin in VAL.items():
        qz = sorted(x["t"] for x in OPS if x["group"] == "Z_DCF" and rule(x) and x["mos"] >= vmin - EPS)
        qb = sorted(x["t"] for x in OPS if x["group"] == "BEZ_DCF" and rule(x))
        Q[(rn, vn)] = (qz, qb)
        print(f"| {rn} | {vn} | {len(qz)} | {len(qb)} | {len(qz) + len(qb)} | {3 * (len(qz) + len(qb))} |")

print("\nRóżnice RDZEN -> RDZEN_POPR (bezpieczeństwo, wszystkie spółki operacyjne):")
a = {x["t"] for x in OPS if core_now(x)}
b = {x["t"] for x in OPS if core_fixed(x)}
print("  odpadają:", [(t, why_fixed(BY[t])) for t in sorted(a - b)])
print("  wchodzą:", sorted(b - a))

print("\nRDZEN_POPR + MoS>=0 -- skład:")
qz, qb = Q[("RDZEN_POPR", "MoS>=0")]
print("  z DCF:", qz)
print("  bez DCF:", qb)
qz50, _ = Q[("RDZEN_POPR", "MoS>=50")]
print("  z DCF przy MoS>=50:", qz50)

print("\nObecna shortlista (24) wobec RDZEN_POPR + MoS>=0 -- kto odpada i dlaczego:")
for x in sorted((x for x in C if x["prod_short"]), key=lambda x: x["t"]):
    if x["group"] not in ("Z_DCF", "BEZ_DCF"):
        print(f"  {x['t']}: grupa {x['group']}")
    elif not core_fixed(x):
        print(f"  {x['t']}: {why_fixed(x)}")
    elif x["group"] == "Z_DCF" and x["mos"] < 0:
        print(f"  {x['t']}: MoS BASE {x['mos']:.1f}%")

print("\nWysokie bezpieczeństwo punktowe (>=12/16), a odpadają w RDZEN_POPR:")
print("  ", [(x["t"], x["fq"], why_fixed(x)) for x in OPS if x["fq"] >= 12 and not core_fixed(x)])

print("\nBEZ_DCF -- przyczyny braku DCF wśród zakwalifikowanych (RDZEN_POPR):")
for t in qb:
    x = BY[t]
    print(f"  {t}: FCF ost. {bn(x['fcf_last'])} mld, FCF 3 l. {bn(x['fcf3'])} mld, dług netto/EBITDA "
          f"{'—' if x['lev'] is None else f'{x[chr(108)+chr(101)+chr(118)]:.2f}'}")

print("\nPełna tabela (ticker;grupa;fq;rdzeń;rdzeń_popr;MoS;FCF ost.;FCF 3 l.;dług netto/EBITDA;przyczyna):")
for x in sorted(OPS, key=lambda x: x["t"]):
    lev = "—" if x["lev"] is None else f"{x['lev']:.2f}"
    mos = "—" if x["mos"] is None else f"{x['mos']:.1f}"
    print(f"  {x['t']};{x['group']};{x['fq']:.0f};{int(core_now(x))};{int(core_fixed(x))};{mos};"
          f"{bn(x['fcf_last'])};{bn(x['fcf3'])};{lev};{why_fixed(x)}")

# ---------- 3. Alokacja kapitału: wzrost FCF na akcję (ilustracja koncepcji) ------
# Miara neutralna względem formy alokacji: dobra reinwestycja, buyback po dobrej
# cenie i brak rozwodnienia podnoszą FCF na akcję; rozwodnienie i nietrafione
# inwestycje go obniżają. Okno: 3 lata (średnia FCF z lat t-2..t na akcję t wobec
# średniej z lat t-4..t-2 na akcję t-2 -- średnie ograniczają wrażliwość na rok startu).
print("\n== 3. FCF na akcję -- ilustracja ==")
fps_rows = []
for r in c.execute("select ticker, cik from live_scan_candidates order by ticker"):
    x = BY[r["ticker"]]
    if x["group"] not in ("Z_DCF", "BEZ_DCF"):
        continue
    p = get_fundamentals_periods(c, r["cik"])
    if len(p) < 5:
        continue
    f = [free_cash_flow(q) for q in p]
    s = [q.diluted_shares_outstanding for q in p]
    if None in f or None in s:
        continue
    start = sum(f[-5:-2]) / 3 / s[-3]
    end = sum(f[-3:]) / 3 / s[-1]
    d = [q.dividends_paid or 0 for q in p[-3:]]
    b = [q.share_buybacks or 0 for q in p[-3:]]
    payout = (sum(d) + sum(b)) / sum(f[-3:]) * 100 if sum(f[-3:]) > 0 else None
    g = (end / start) ** (1 / 2) - 1 if start > 0 and end > 0 else None
    fps_rows.append((r["ticker"], start, end, g, payout, s[-1] / s[-3] - 1))
vals = sorted(v[3] for v in fps_rows if v[3] is not None)
print(f"spółki z policzalnym wzrostem: {len(vals)} z {len(fps_rows)}; mediana {vals[len(vals) // 2] * 100:.1f}%/rok; "
      f"ujemny lub niepoliczalny start: {sum(1 for v in fps_rows if v[1] <= 0)}")
EX = ["AXON", "BSX", "TYL", "DDOG", "RDDT", "CVNA", "MRK", "SNA", "QCOM", "CHTR", "ADBE", "AVGO", "TPR", "DECK", "APP", "BA", "UBER", "NFLX"]
print("| Spółka | FCF/akcję start | FCF/akcję koniec | wzrost r/r | wypłaty / FCF 3 l. | zmiana liczby akcji 2 l. |")
for t, st, en, g, po, ds in fps_rows:
    if t in EX:
        print(f"| {t} | {st:.2f} | {en:.2f} | {'—' if g is None else f'{g * 100:.1f}%'} | "
              f"{'—' if po is None else f'{po:.0f}%'} | {ds * 100:+.1f}% |")
reinvest = [v for v in fps_rows if v[4] is not None and v[4] < 10]
returners = [v for v in fps_rows if v[4] is not None and v[4] >= 75]
med = lambda xs: sorted(xs)[len(xs) // 2] if xs else None  # noqa: E731
print(f"mediana wzrostu FCF/akcję: wypłaty < 10% FCF (n={len(reinvest)}): "
      f"{med([v[3] for v in reinvest if v[3] is not None]) * 100:.1f}%; "
      f"wypłaty >= 75% FCF (n={len(returners)}): {med([v[3] for v in returners if v[3] is not None]) * 100:.1f}%")

# ---------- 4. Finansowanie wypłat: test wynikowy zamiast „wzrost długu brutto” ----
# Wypłaty (D + B) z 3 lat wobec FCF z 3 lat; dźwignia (dług netto/EBITDA) na
# początku i na końcu okna. Próg 2,0 = istniejący próg bezpieczeństwa z configu
# (spójność, nie kalibracja).
print("\n== 4. Wypłaty ponad FCF: dźwignia na początku i końcu okna ==")
LEV_T = cfg.financial_quality.net_debt_to_ebitda_low_leverage_threshold


def lev(q):
    nd_ = net_debt(q)
    if nd_ is None or q.ebitda is None:
        return None
    if nd_ <= 0:
        return 0.0 if q.ebitda > 0 else None
    return nd_ / q.ebitda if q.ebitda > 0 else float("inf")


over = []
for r in c.execute("select ticker, cik from live_scan_candidates order by ticker"):
    x = BY[r["ticker"]]
    if x["group"] not in ("Z_DCF", "BEZ_DCF"):
        continue
    p = get_fundamentals_periods(c, r["cik"])
    if len(p) < 4:
        continue
    f = [free_cash_flow(q) for q in p[-3:]]
    if None in f:
        continue
    paid = sum((q.dividends_paid or 0) + (q.share_buybacks or 0) for q in p[-3:])
    if paid <= 0 or paid <= sum(f):
        continue
    l0, l1 = lev(p[-4]), lev(p[-1])
    dd = (p[-1].total_debt or 0) - (p[-4].total_debt or 0)
    over.append((r["ticker"], paid / sum(f) * 100 if sum(f) > 0 else None, l0, l1, dd))
ok = [o for o in over if o[3] is not None and o[3] <= LEV_T]
bad = [o for o in over if o[3] is None or o[3] > LEV_T]
print(f"wypłaty > FCF 3 l.: {len(over)}; dźwignia na końcu <= {LEV_T}: {len(ok)}; > {LEV_T} lub EBITDA <= 0: {len(bad)}")
fmt = lambda v: "—" if v is None else ("EBITDA<=0" if v == float("inf") else f"{v:.2f}")  # noqa: E731
for t, cov, l0, l1, dd in sorted(over):
    print(f"  {t}: wypłaty/FCF {('—' if cov is None else f'{cov:.0f}%')}, dźwignia {fmt(l0)} -> {fmt(l1)}, "
          f"dług brutto {dd / 1e9:+.2f} mld")

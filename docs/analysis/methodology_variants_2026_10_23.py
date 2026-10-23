"""Analiza wrażliwości rankingu na reguły metodologii -- dane skanu 22.10.2026
(narzędzie analityczne, NIE kod produkcyjny; niczego nie zapisuje do bazy).

TYLKO ANALIZA: produkcyjny kod/config nie są zmieniane ani importowane do
zapisu. Każdy wariant zmienia JEDNĄ regułę, reszta = produkcja. Najpierw
weryfikacja, że odtworzenie produkcji daje identyczne MoS i ranking.
"""
from __future__ import annotations

import math
import sqlite3
import statistics
import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2]))
from buffett_scanner.config import load_config  # noqa: E402
from buffett_scanner.db import get_fundamentals_periods  # noqa: E402
from buffett_scanner.fundamentals import free_cash_flow, net_debt  # noqa: E402
from buffett_scanner.scoring import valuation_score  # noqa: E402
from buffett_scanner.shareholder_returns import evaluate_dividend_shareholder_return  # noqa: E402
from buffett_scanner.valuation import compute_valuation  # noqa: E402

# Użycie: python docs/analysis/methodology_variants_2026_10_23.py <snapshot.db> <wynik.md>
# (snapshot skanu 22.10: GitHub Release scanner-snapshot, sha256 69e6785d...)
DB, OUT = sys.argv[1], sys.argv[2]
CFG = load_config()
DCF = CFG.valuation.dcf_owner_earnings
R, TG, N = DCF.discount_rate_pct.base / 100, DCF.terminal_growth_rate_pct.base / 100, DCF.projection_years
GMIN, GMAX = DCF.min_projected_growth_rate_pct / 100, DCF.max_projected_growth_rate_pct / 100
W = CFG.scoring.weights
LIMIT = 20

conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
conn.row_factory = sqlite3.Row
C = []
for r in conn.execute("SELECT * FROM live_scan_candidates ORDER BY rank"):
    periods = get_fundamentals_periods(conn, r["cik"])
    C.append(dict(t=r["ticker"], rank=r["rank"], price=r["current_price"], periods=periods,
                  fcf=[free_cash_flow(p) for p in periods], safety=r["safety_score"],
                  div_db=r["dividend_score"], val_db=r["valuation_score"], pct_db=r["deterministic_score_pct"],
                  short=bool(r["in_shortlist"])))

# ---------- odtworzenie produkcji ----------------------------------------------


def endpoint_cagr(fcf):
    if len(fcf) < 2 or fcf[0] is None or fcf[-1] is None or fcf[0] <= 0 or fcf[-1] <= 0:
        return None
    return (fcf[-1] / fcf[0]) ** (1 / (len(fcf) - 1)) - 1


def dcf_mos(c, base_fcf, path):
    latest = c["periods"][-1]
    nd, shares = net_debt(latest), latest.diluted_shares_outstanding
    if base_fcf is None or base_fcf <= 0 or nd is None or not shares or shares <= 0:
        return None
    oe, pv = base_fcf, 0.0
    for t, g in enumerate(path, start=1):
        oe *= 1 + g
        pv += oe / (1 + R) ** t
    tv = oe * (1 + TG) / (R - TG) / (1 + R) ** N
    iv = (pv + tv - nd) / shares
    return (iv - c["price"]) / iv * 100 if iv > 0 else None


def const(g):
    return [g] * N


def clamp(g, hi=GMAX):
    return max(GMIN, min(hi, g))


def fade(g0):
    """Liniowe wygaszanie od g0 (rok 1) do wzrostu rezydualnego (rok 10)."""
    return [g0 + (TG - g0) * (t - 1) / (N - 1) for t in range(1, N + 1)]


def prod_mos(c):
    g = endpoint_cagr(c["fcf"])
    if g is None or c["fcf"][-1] is None or c["fcf"][-1] <= 0:
        return None, None
    return dcf_mos(c, c["fcf"][-1], const(clamp(g))), clamp(g)


mismatch = 0
for c in C:
    v = compute_valuation("GENERAL", c["periods"], current_price=c["price"], config=CFG.valuation)
    mine, g = prod_mos(c)
    theirs = v.scenarios["base"].margin_of_safety_pct if v.implemented else None
    c["mos0"], c["g0"], c["cagr0"] = mine, g, endpoint_cagr(c["fcf"])
    if (mine is None) != (theirs is None) or (mine is not None and abs(mine - theirs) > 1e-6):
        mismatch += 1
    d = evaluate_dividend_shareholder_return(c["periods"], current_price=c["price"],
                                             config=CFG.dividend_shareholder_return)
    c["div_bd"], c["dps"], c["div0"] = d.breakdown, d.dividend_per_share_latest, d.raw_score
    assert abs(d.raw_score - c["div_db"]) < 1e-9, c["t"]


def pct(c, val_pts=None, div=None, mode="renorm"):
    """Wynik deterministyczny %. mode: renorm (produkcja), zero (brak=0/45),
    half (brak=10/20), none (bez wyceny: safety+div /25)."""
    div = c["div0"] if div is None else div
    pts = c["safety"] + div
    if mode == "none":
        return pts / (W.financial_safety + W.dividend_shareholder_return) * 100
    if val_pts is None:
        if mode == "renorm":
            return pts / (W.financial_safety + W.dividend_shareholder_return) * 100
        if mode == "zero":
            return pts / 45 * 100
        if mode == "half":
            return (pts + W.valuation / 2) / 45 * 100
    return (pts + val_pts) / 45 * 100


def vpts(mos):
    return valuation_score(mos, CFG)


for c in C:
    c["pct0"] = pct(c, vpts(c["mos0"]))
    assert abs(c["pct0"] - c["pct_db"]) < 1e-6, (c["t"], c["pct0"], c["pct_db"])

ALPHA = sorted(C, key=lambda c: c["t"])  # kolejność przetwarzania (remisy)


def ranking(key):
    order = sorted(ALPHA, key=lambda c: -key(c))  # sort stabilny jak produkcja
    boundary = key(order[LIMIT - 1])
    short = [c["t"] for c in order if key(c) >= boundary - 1e-12]
    return [c["t"] for c in order], short


base_order, base_short = ranking(lambda c: c["pct0"])
assert base_order == [c["t"] for c in C], "ranking produkcyjny nie odtworzony"
assert set(base_short) == {c["t"] for c in C if c["short"]}

# ---------- narzędzia raportu ----------------------------------------------------


def avg_ranks(values):
    order = sorted(range(len(values)), key=lambda i: -values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return ranks


def spearman(a, b):
    ra, rb = avg_ranks(a), avg_ranks(b)
    ma, mb = statistics.mean(ra), statistics.mean(rb)
    cov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    return cov / math.sqrt(sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb))


lines = []


def fmt(v, d=1):
    return "—" if v is None else f"{v:.{d}f}"


def report(title, desc, key, mos_key=None, limits=""):
    order, short = ranking(key)
    pos = {t: i + 1 for i, t in enumerate(order)}
    pos0 = {t: i + 1 for i, t in enumerate(base_order)}
    by = {c["t"]: c for c in C}
    top0, top = set(base_order[:LIMIT]), set(order[:LIMIT])
    rho = spearman([c["pct0"] for c in C], [key(c) for c in C])
    lines.append(f"\n## {title}\n\n{desc}\n")
    lines.append(f"- Spearman (cały ranking 162 spółek, produkcja vs wariant): **{rho:.3f}**")
    lines.append(f"- TOP20: wypadają {', '.join(sorted(top0 - top)) or 'brak'}; "
                 f"wchodzą {', '.join(sorted(top - top0)) or 'brak'}")
    lines.append(f"- Shortlista: {len(base_short)} -> {len(short)} spółek; wypadają "
                 f"{', '.join(t for t in base_short if t not in short) or 'brak'}; wchodzą "
                 f"{', '.join(t for t in short if t not in base_short) or 'brak'}")
    if mos_key:
        dcf0 = [c for c in C if c["mos0"] is not None]
        dcf1 = [c for c in C if mos_key(c) is not None]
        lines.append(f"- DCF policzony: {len(dcf0)} -> {len(dcf1)} spółek; MoS>=50%: "
                     f"{sum(c['mos0'] >= 50 for c in dcf0)} -> {sum(mos_key(c) >= 50 for c in dcf1)}; "
                     f"mediana MoS: {fmt(statistics.median(c['mos0'] for c in dcf0))} -> "
                     f"{fmt(statistics.median(mos_key(c) for c in dcf1))}")
    union = [t for t in base_order if t in set(base_short) | set(short)]
    union += [t for t in order if t in set(short) and t not in union]
    hdr = "| Spółka | Pozycja | Wynik % | " + ("MoS BASE % | " if mos_key else "") + "Shortlista |"
    lines.append("\n" + hdr)
    lines.append("|" + "---|" * (hdr.count("|") - 1))
    for t in union:
        c = by[t]
        status = ("=" if t in base_short and t in short else "wypada" if t in base_short else "wchodzi")
        mos = f"{fmt(c['mos0'], 0)} -> {fmt(mos_key(c), 0)} | " if mos_key else ""
        lines.append(f"| {t} | {pos0[t]} -> {pos[t]} | {c['pct0']:.1f} -> {key(c):.1f} | {mos}{status} |")
    lines.append(f"\n**Ograniczenia i ryzyko:** {limits}")


lines.append("# Analiza wrażliwości rankingu — dane skanu 22.10.2026\n")
lines.append(f"Weryfikacja odtworzenia produkcji: MoS niezgodnych: {mismatch}/162; ranking i shortlista "
             f"identyczne z bazą: TAK. Shortlista produkcyjna ({len(base_short)}): {', '.join(base_short)}.")
lines.append("\nKażdy wariant zmienia JEDNĄ regułę; pozostałe = produkcja. Spearman 1,0 = identyczna kolejność. "
             "Warianty nie są oceniane jako lepsze/gorsze -- na danych jednego dnia nie da się tego stwierdzić.")

# ---------- 1. DCF: wzrost --------------------------------------------------------
grow = {
    "G1. Sufit wzrostu 15%": lambda c: dcf_mos(c, c["fcf"][-1], const(clamp(c["cagr0"], 0.15))) if c["mos0"] is not None else None,
    "G2. Sufit wzrostu 10%": lambda c: dcf_mos(c, c["fcf"][-1], const(clamp(c["cagr0"], 0.10))) if c["mos0"] is not None else None,
    "G3. Wygaszanie: start od obecnego wzrostu (max 20%), liniowo do 2,5% w roku 10":
        lambda c: dcf_mos(c, c["fcf"][-1], fade(c["g0"])) if c["mos0"] is not None else None,
    "G4. Wygaszanie od max 10%": lambda c: dcf_mos(c, c["fcf"][-1], fade(clamp(c["cagr0"], 0.10))) if c["mos0"] is not None else None,
}
lim_g = {
    "G1. Sufit wzrostu 15%": "Nadal 10 lat stałego wzrostu; 15% to wartość z siatki Round 3, nie wynik walidacji.",
    "G2. Sufit wzrostu 10%": "Zaniża spółki o trwałym wysokim wzroście; liczba arbitralna.",
    "G3. Wygaszanie: start od obecnego wzrostu (max 20%), liniowo do 2,5% w roku 10":
        "Profil liniowy to założenie; nadal startuje od CAGR z dwóch punktów i od najnowszego FCF.",
    "G4. Wygaszanie od max 10%": "Najbardziej konserwatywny wzrost; łączy dwie zmiany (sufit + profil).",
}
for name, mk in grow.items():
    for c in C:
        c["_m"] = mk(c)
    report(name, "Zmienia tylko ścieżkę wzrostu w DCF (baza FCF = najnowszy rok, CAGR jak w produkcji).",
           lambda c: pct(c, vpts(c["_m"])), lambda c: c["_m"], lim_g[name])

# ---------- 2. FCF: baza ----------------------------------------------------------


def valid(c):
    return [x for x in c["fcf"] if x is not None]


fbase = {
    "F1. Baza FCF = średnia z okna": lambda c: statistics.mean(valid(c)),
    "F2. Baza FCF = mediana z okna": lambda c: statistics.median(valid(c)),
    "F3. Baza FCF = mniejsza z: najnowszy, średnia": lambda c: min(c["fcf"][-1], statistics.mean(valid(c))),
}
lim_f = {
    "F1. Baza FCF = średnia z okna": "Zaniża spółki z trwałą poprawą (np. wzrost skali); okno 5 lat może nie obejmować pełnego cyklu.",
    "F2. Baza FCF = mediana z okna": "Jak F1; przy 5 punktach mediana bywa skokowa.",
    "F3. Baza FCF = mniejsza z: najnowszy, średnia": "Systematycznie konserwatywne; asymetrycznie karze spółki rosnące.",
}
for name, base in fbase.items():
    for c in C:
        c["_m"] = dcf_mos(c, base(c), const(c["g0"])) if c["mos0"] is not None else None
    report(name, "Zmienia tylko bazę FCF w DCF; wzrost i CAGR jak w produkcji (DCF tylko tam, gdzie produkcja go liczy).",
           lambda c: pct(c, vpts(c["_m"])), lambda c: c["_m"], lim_f[name])

# ---------- 3. Dywidendy ----------------------------------------------------------


def div_zero(c):
    if c["dps"] == 0:  # wypłaca 0 (nie: brak danych)
        b = c["div_bd"]
        return c["div0"] - 3 * b["no_dividend_cut"] - 2 * b["sustainable_payout_ratio"]
    return c["div0"]


def div_na(c):
    if c["dps"] == 0:
        b = c["div_bd"]
        return (3 * b["positive_shareholder_yield"] + 2 * b["shrinking_or_flat_share_count"]) / 5 * 10
    return c["div0"]


report("D1. Bez punktów za 'brak cięcia' i 'bezpieczny payout' przy zerowej dywidendzie",
       "Spółka z DPS = 0 traci 3 + 2 pkt, jeśli je dostawała.",
       lambda c: pct(c, vpts(c["mos0"]), div=div_zero(c)), None,
       "Karze spółki wzrostowe zwracające gotówkę wyłącznie buybackiem; DPS = 0 z FMP może też być brakiem danych.")
report("D2. Kryteria dywidendowe 'nie dotyczy' przy zerowej dywidendzie (komponent liczony z 5 pkt i skalowany do 10)",
       "Yield (3) + liczba akcji (2) przeskalowane do 10.",
       lambda c: pct(c, vpts(c["mos0"]), div=div_na(c)), None,
       "Ten sam problem mieszania baz co w punkcie 4, tylko wewnątrz komponentu; spółka z buybackiem i malejącą liczbą akcji nadal 10/10.")

# ---------- 4. Bazy punktowe -------------------------------------------------------
report("B1. Brak wyceny = 0 z 20 pkt (wynik z 45)", "Brak DCF traktowany jak najgorsza wycena.",
       lambda c: pct(c, vpts(c["mos0"]), mode="zero"), None,
       "Karze uzasadniony brak DCF (np. spółki odbudowujące FCF) tak samo jak przewartościowanie.")
report("B2. Brak wyceny = połowa punktów (10 z 20)", "Neutralne uzupełnienie.",
       lambda c: pct(c, vpts(c["mos0"]), mode="half"), None, "Wartość 10/20 jest arbitralna.")
report("B3. Najpierw spółki z pełną bazą (z DCF), potem bez DCF",
       "Ta sama zasada co w finalnym rankingu (complete przed partial).",
       lambda c: (1000 if c["mos0"] is not None else 0) + c["pct0"], None,
       "Spółki bez DCF praktycznie nie trafiają na shortlistę, dopóki jest >=20 spółek z DCF.")
report("B4. Bez komponentu wyceny (bezpieczeństwo + dywidendy, z 25 pkt)",
       "Odpowiednik modelu 'BEZ wyceny' z testu historycznego.",
       lambda c: pct(c, mode="none"), None,
       "Porzuca wycenę -- sprzeczne z filozofią Buffetta; sam test historyczny ma ograniczenia (sekcja walidacji).")

# ---------- 5. CAGR ----------------------------------------------------------------


def cagr_first_positive(fcf):
    if fcf[-1] is None or fcf[-1] <= 0:
        return None
    idx = [i for i, x in enumerate(fcf) if x is not None and x > 0]
    i0 = idx[0]
    span = len(fcf) - 1 - i0
    if span < 2:
        return None
    return (fcf[-1] / fcf[i0]) ** (1 / span) - 1


def cagr_loglinear(fcf):
    pts = [(i, math.log(x)) for i, x in enumerate(fcf) if x is not None and x > 0]
    if len(pts) < 3 or fcf[-1] is None or fcf[-1] <= 0:
        return None
    mx = statistics.mean(i for i, _ in pts)
    my = statistics.mean(y for _, y in pts)
    slope = sum((i - mx) * (y - my) for i, y in pts) / sum((i - mx) ** 2 for i, _ in pts)
    return math.exp(slope) - 1


def cagr_median_yoy(fcf):
    pairs = [(a, b) for a, b in zip(fcf, fcf[1:]) if a and b and a > 0 and b > 0]
    if len(pairs) < 2 or fcf[-1] is None or fcf[-1] <= 0:
        return None
    return statistics.median(b / a - 1 for a, b in pairs)


cg = {
    "C1. CAGR od pierwszego dodatniego roku (min. 2 lata)": cagr_first_positive,
    "C2. Trend log-liniowy z lat dodatnich (min. 3 lata)": cagr_loglinear,
    "C3. Mediana wzrostu r/r z par dodatnich lat (min. 2 pary)": cagr_median_yoy,
}
lim_c = {
    "C1. CAGR od pierwszego dodatniego roku (min. 2 lata)": "Nadal dwa punkty końcowe; start z niskiej bazy daje bardzo wysoki CAGR (sufit 20% to tłumi).",
    "C2. Trend log-liniowy z lat dodatnich (min. 3 lata)": "Pomija lata ujemne (optymistyczne); 3-5 punktów to mała próbka.",
    "C3. Mediana wzrostu r/r z par dodatnich lat (min. 2 pary)": "Niestabilna przy małej liczbie par; ignoruje lata ujemne.",
}
for name, fn in cg.items():
    for c in C:
        g = fn(c["fcf"])
        c["_m"] = dcf_mos(c, c["fcf"][-1], const(clamp(g))) if g is not None else None
        c["_g"] = g
    report(name, "Zmienia tylko sposób liczenia wzrostu historycznego (sufit 20% i baza FCF jak w produkcji).",
           lambda c: pct(c, vpts(c["_m"])), lambda c: c["_m"], lim_c[name])

# ---------- MU / SNDK --------------------------------------------------------------
lines.append("\n## MU i SNDK — MoS BASE w każdym wariancie DCF\n")
lines.append("| Wariant | MU | SNDK |\n|---|---|---|")
by = {c["t"]: c for c in C}
rows = [("Produkcja", lambda c: c["mos0"])]
rows += [(n, (lambda f: lambda c: f(c))(f)) for n, f in grow.items()]
rows += [(n, (lambda b: lambda c: dcf_mos(c, b(c), const(c["g0"])))(b)) for n, b in fbase.items()]
for n, f in rows:
    lines.append(f"| {n} | {fmt(f(by['MU']), 0)} | {fmt(f(by['SNDK']), 0)} |")

open(OUT, "w", encoding="utf-8").write("\n".join(lines) + "\n")
print(f"zapisano {OUT}; niezgodności MoS: {mismatch}")

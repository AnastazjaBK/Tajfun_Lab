"""Raport POST-DEBT / PARTIAL-VALUATION baseline (Faza 5.3f, Decyzja
wlascicielki 2026-10-05, punkty 7/8/9). Jednorazowy skrypt diagnostyczny
-- ZERO zmian w total_debt.py/scoring.py/backtest_harness.py, czyta
WYLACZNIE z lokalnej kopii bazy (artefakt nowego baseline run, po
wpieciu total_debt Tier 1/Tier 2). Do usuniecia po wykorzystaniu.

Czesc 1: realny total_debt coverage (overall/per rok/rozklad
debt_resolution_method/confidence_tier/per-CIK) -- rekomputacja
build_annual_fundamentals_periods_as_of na PELNYM PIT universe x
decision_date (ta sama populacja 76 292 obs. co diagnostyka coverage
gap 2026-10-05), NIEZALEZNIE od decline scanera (bo total_debt jest
liczony dla KAZDEGO scanned obs., nie tylko kandydatow).

Czesc 2: valuation coverage + bottleneck (sekcja 9) -- z
backtest_candidates (valuation jest liczony WYLACZNIE dla kandydatow,
bo decline scanner odcina reszte przed policzeniem score). Dla
kandydatow z valuation=None, rekomputacja compute_valuation (czysta
funkcja, deterministyczna) zeby odczytac .reason i zbuczetowac przyczyny.

Czesc 3: PAIRED porownanie WITH vs WITHOUT valuation na dokladnie tym
samym subsecie (complete-valuation subset) -- hit rate/forward
returns/excess returns vs oba benchmarki/korelacja score-vs-forward-return,
zgodnie z instrukcja "nie porownuj calego universe z nowym subsetem,
bo roznica moglaby wynikac z selection/coverage bias"."""

from __future__ import annotations

import sqlite3
import statistics
import sys
from collections import Counter, defaultdict

sys.path.insert(0, ".")

from buffett_scanner.config import load_config
from buffett_scanner.db import (
    get_backtest_benchmark,
    get_backtest_candidates,
    get_companies_sector_profiles,
    get_sec_company_facts_cache,
)
from buffett_scanner.pit_fundamentals import build_annual_fundamentals_periods_as_of
from buffett_scanner.valuation import compute_valuation

DB_PATH = "baseline_walk_forward_result.db"
INDEX_NAME = "SP500"


def spearman_rho(xs: list[float], ys: list[float]) -> float | None:
    """Korelacja rang Spearmana, bez numpy/scipy (brak w requirements.txt)
    -- ranguje obie listy, liczy Pearsona na rangach. None przy <3 punktach
    danych albo zerowej wariancji (nigdy nie dzieli przez zero)."""
    n = len(xs)
    if n < 3:
        return None

    def ranks(vals: list[float]) -> list[float]:
        order = sorted(range(len(vals)), key=lambda i: vals[i])
        r = [0.0] * len(vals)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and vals[order[j + 1]] == vals[order[i]]:
                j += 1
            avg_rank = (i + j) / 2.0 + 1.0
            for k in range(i, j + 1):
                r[order[k]] = avg_rank
            i = j + 1
        return r

    rx, ry = ranks(xs), ranks(ys)
    mean_rx, mean_ry = statistics.mean(rx), statistics.mean(ry)
    cov = sum((a - mean_rx) * (b - mean_ry) for a, b in zip(rx, ry))
    var_x = sum((a - mean_rx) ** 2 for a in rx)
    var_y = sum((b - mean_ry) ** 2 for b in ry)
    if var_x == 0 or var_y == 0:
        return None
    return cov / (var_x ** 0.5 * var_y ** 0.5)


def main() -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    config = load_config()
    weights = config.scoring.weights

    run_id = conn.execute(
        "SELECT run_id FROM backtest_coverage ORDER BY decision_date DESC LIMIT 1"
    ).fetchone()["run_id"]
    print(f"run_id (najnowszy w tej bazie) = {run_id}")

    decision_dates = [
        r["decision_date"] for r in conn.execute(
            "SELECT DISTINCT decision_date FROM backtest_coverage WHERE run_id = ? ORDER BY decision_date", (run_id,)
        ).fetchall()
    ]
    all_ciks = [
        r["cik"] for r in conn.execute(
            "SELECT DISTINCT cik FROM universe_membership WHERE index_name = ?", (INDEX_NAME,)
        ).fetchall()
    ]
    membership_rows = conn.execute(
        "SELECT cik, start_date, end_date FROM universe_membership WHERE index_name = ?", (INDEX_NAME,)
    ).fetchall()

    def pit_universe_at(d: str) -> list[str]:
        return [
            r["cik"] for r in membership_rows
            if r["start_date"] <= d and (r["end_date"] is None or r["end_date"] > d)
        ]

    company_facts_by_cik: dict[str, dict] = {}
    for cik in all_ciks:
        cf = get_sec_company_facts_cache(conn, cik)
        if cf is not None:
            company_facts_by_cik[cik] = cf

    print(f"Decision dates: {len(decision_dates)}, CIK w universe_membership: {len(all_ciks)}, "
          f"CIK z SEC cache: {len(company_facts_by_cik)}")

    # ==================================================================
    # CZĘŚĆ 1 -- realny total_debt coverage (pełna PIT universe populacja,
    # niezależnie od decline scanera -- total_debt liczony dla każdego
    # scanned obs., nie tylko kandydatów).
    # ==================================================================
    print("\n" + "=" * 70)
    print("CZĘŚĆ 1 -- total_debt coverage (realny, po implementacji Tier 1/Tier 2)")
    print("=" * 70)

    total_obs = 0
    with_debt = 0
    method_counts: Counter[str] = Counter()
    tier_counts: Counter[str | None] = Counter()
    by_year: dict[str, list[int]] = {}
    cik_ever_observed: set[str] = set()
    cik_ever_has_debt: set[str] = set()
    periods_cache: dict[tuple[str, str], list] = {}  # (cik, decision_date) -> periods, reused w Części 2

    for d in decision_dates:
        year = d[:4]
        by_year.setdefault(year, [0, 0])
        for cik in pit_universe_at(d):
            facts = company_facts_by_cik.get(cik)
            if facts is None:
                continue
            total_obs += 1
            cik_ever_observed.add(cik)
            by_year[year][0] += 1
            periods = build_annual_fundamentals_periods_as_of(facts, d)
            periods_cache[(cik, d)] = periods
            if not periods:
                method_counts["NO_ANNUAL_PERIOD"] += 1
                continue
            latest = periods[-1]
            method_counts[latest.total_debt_resolution_method or "NONE"] += 1
            tier_counts[latest.total_debt_confidence_tier] += 1
            if latest.total_debt is not None:
                with_debt += 1
                by_year[year][1] += 1
                cik_ever_has_debt.add(cik)

    print(f"Suma obserwacji (PIT universe x decision_date, z SEC cache): {total_obs}")
    print(f"Z total_debt != None: {with_debt} ({with_debt/total_obs*100:.2f}%)")
    print("\nPer rok:")
    for year in sorted(by_year):
        obs, withval = by_year[year]
        pct = withval / obs * 100 if obs else 0
        print(f"  {year}: {withval}/{obs} ({pct:.1f}%)")
    print("\nRozkład debt_resolution_method:")
    for method, cnt in method_counts.most_common():
        print(f"  {method}: {cnt} ({cnt/total_obs*100:.1f}%)")
    print("\nRozkład confidence_tier:")
    for tier, cnt in tier_counts.most_common():
        print(f"  {tier}: {cnt} ({cnt/total_obs*100:.1f}%)")
    print(f"\nPer-CIK: {len(cik_ever_has_debt)}/{len(cik_ever_observed)} "
          f"({len(cik_ever_has_debt)/len(cik_ever_observed)*100:.1f}%) CIK z total_debt != None choć raz")

    # ==================================================================
    # CZĘŚĆ 2 -- valuation coverage (z backtest_candidates -- valuation
    # liczony WYŁĄCZNIE dla kandydatów, decline scanner odcina reszte
    # przed policzeniem score) + bottleneck (sekcja 9).
    # ==================================================================
    print("\n" + "=" * 70)
    print("CZĘŚĆ 2 -- valuation coverage + bottleneck (wśród kandydatów)")
    print("=" * 70)

    candidates = get_backtest_candidates(conn, run_id)
    print(f"Kandydaci (CANDIDATE stage) w tym run: {len(candidates)}")

    sector_profiles = get_companies_sector_profiles(conn)

    val_implemented = 0
    val_none = 0
    reason_counts: Counter[str] = Counter()
    debt_tier_among_candidates: Counter[str | None] = Counter()
    val_none_but_debt_high_confidence = 0

    for c in candidates:
        periods = periods_cache.get((c["cik"], c["decision_date"]))
        if periods is None:
            facts = company_facts_by_cik.get(c["cik"])
            periods = build_annual_fundamentals_periods_as_of(facts, c["decision_date"]) if facts else []
        debt_tier = periods[-1].total_debt_confidence_tier if periods else None
        debt_tier_among_candidates[debt_tier] += 1

        if c["valuation_score"] is not None:
            val_implemented += 1
            continue
        val_none += 1
        sector_profile = sector_profiles.get(c["cik"], "GENERAL")
        vresult = compute_valuation(
            sector_profile, periods, current_price=c["decision_price"], config=config.valuation,
        )
        reason_counts[vresult.reason or "N/A"] += 1
        if debt_tier is not None:
            val_none_but_debt_high_confidence += 1

    print(f"\nvaluation_score != None: {val_implemented} ({val_implemented/len(candidates)*100:.1f}% kandydatów)")
    print(f"valuation_score == None: {val_none} ({val_none/len(candidates)*100:.1f}% kandydatów)")
    print(f"\nconfidence_tier total_debt WŚRÓD kandydatów:")
    for tier, cnt in debt_tier_among_candidates.most_common():
        print(f"  {tier}: {cnt} ({cnt/len(candidates)*100:.1f}%)")
    print(f"\nKandydaci z high-confidence total_debt (TIER_1/TIER_2), ale valuation=None mimo to "
          f"(bottleneck NIE jest total_debt): {val_none_but_debt_high_confidence} "
          f"({val_none_but_debt_high_confidence/val_none*100:.1f}% z valuation=None)" if val_none else "")
    print("\nPrzyczyny valuation=None (rozbicie reason z compute_valuation, rekomputacja):")
    for reason, cnt in reason_counts.most_common(15):
        print(f"  [{cnt}] {reason}")

    # ==================================================================
    # CZĘŚĆ 3 -- PAIRED porównanie WITH vs WITHOUT valuation, DOKŁADNIE
    # ten sam subset (complete-valuation subset): kandydaci z
    # valuation_score != None.
    # ==================================================================
    print("\n" + "=" * 70)
    print("CZĘŚĆ 3 -- PAIRED WITH vs WITHOUT valuation (complete-valuation subset)")
    print("=" * 70)

    subset = [c for c in candidates if c["valuation_score"] is not None]
    print(f"Complete-valuation subset: {len(subset)} obserwacji ({len(subset)/len(candidates)*100:.1f}% kandydatów)")

    max_without = weights.financial_safety + weights.dividend_shareholder_return
    rows = []
    for c in subset:
        pct_with = c["deterministic_score_pct"]
        pct_without = (c["safety_score"] + c["dividend_score"]) / max_without * 100.0 if max_without > 0 else None
        rows.append({
            "cik": c["cik"], "decision_date": c["decision_date"],
            "pct_with": pct_with, "pct_without": pct_without,
            "r1": c["return_1m_pct"], "r3": c["return_3m_pct"], "r6": c["return_6m_pct"], "r12": c["return_12m_pct"],
        })

    benchmark_rows = {r["decision_date"]: r for r in get_backtest_benchmark(conn, run_id)}
    bench_col = {1: "ew_pit_universe_return_1m_pct", 3: "ew_pit_universe_return_3m_pct",
                 6: "ew_pit_universe_return_6m_pct", 12: "ew_pit_universe_return_12m_pct"}
    spy_col = {1: "spy_return_1m_pct", 3: "spy_return_3m_pct", 6: "spy_return_6m_pct", 12: "spy_return_12m_pct"}

    def summarize(label: str, score_key: str) -> None:
        print(f"\n  -- {label} --")
        for h, ret_key in ((1, "r1"), (3, "r3"), (6, "r6"), (12, "r12")):
            pairs = [(r[score_key], r[ret_key]) for r in rows if r[score_key] is not None and r[ret_key] is not None]
            n = len(pairs)
            if n == 0:
                print(f"    {h}m: n=0")
                continue
            scores = [p[0] for p in pairs]
            rets = [p[1] for p in pairs]
            mean_ret = statistics.mean(rets)
            median_ret = statistics.median(rets)
            hit_rate = sum(1 for r in rets if r > 0) / n * 100.0
            rho = spearman_rho(scores, rets)

            excess_ew, excess_spy = [], []
            for r in rows:
                if r[score_key] is None or r[ret_key] is None:
                    continue
                brow = benchmark_rows.get(r["decision_date"])
                if brow is None:
                    continue
                ew = brow[bench_col[h]]
                spy = brow[spy_col[h]]
                if ew is not None:
                    excess_ew.append(r[ret_key] - ew)
                if spy is not None:
                    excess_spy.append(r[ret_key] - spy)

            median_score = statistics.median(scores)
            top = [ret for score, ret in pairs if score >= median_score]
            bottom = [ret for score, ret in pairs if score < median_score]
            top_mean = statistics.mean(top) if top else None
            bottom_mean = statistics.mean(bottom) if bottom else None
            top_hit = sum(1 for r in top if r > 0) / len(top) * 100.0 if top else None

            print(
                f"    {h}m: n={n} mean={mean_ret:.2f}% median={median_ret:.2f}% hit_rate={hit_rate:.1f}% "
                f"spearman_rho(score,return)={rho if rho is None else round(rho, 3)}"
            )
            print(
                f"         excess_vs_EW: n={len(excess_ew)} mean={statistics.mean(excess_ew):.2f}% | "
                f"excess_vs_SPY: n={len(excess_spy)} mean={statistics.mean(excess_spy):.2f}%"
                if excess_ew and excess_spy else f"         excess: niewystarczające dane benchmarku"
            )
            print(
                f"         top-half (score>=median {median_score:.1f}): n={len(top)} mean_return={top_mean:.2f}% "
                f"hit_rate={top_hit:.1f}% | bottom-half: n={len(bottom)} mean_return={bottom_mean:.2f}%"
                if top and bottom else "         top/bottom split: niewystarczające dane"
            )

    summarize("WITH valuation (pct_with -- już policzony deterministic_score_pct)", "pct_with")
    summarize("WITHOUT valuation (pct_without -- tylko safety+dividend, przeliczone)", "pct_without")


if __name__ == "__main__":
    main()

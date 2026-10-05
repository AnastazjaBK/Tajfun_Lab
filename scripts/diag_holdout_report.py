"""ONE-OFF analysis -- Faza 5.6, FINAL HOLDOUT EVALUATION (2022-2026).

Czyta WYŁĄCZNIE już istniejące, persystowane wyniki jednorazowego
holdout runu (`run-baseline-walk-forward --window-start 2022-01-01`,
GitHub Actions run 37346815021, run_id=walk-forward-baseline-
2026-10-05T171553Z) -- NIE uruchamia żadnego nowego backtestu, NIE
wybiera konfiguracji, NIE zmienia configu. Czysta agregacja/analiza
opisowa na DANYCH, które już istnieją w `backtest_candidates`/
`backtest_coverage`/`backtest_benchmark`.

Do usunięcia z obu branchy po wyciągnięciu wyników (ten sam wzorzec co
wcześniejsze diag_*.py w tym projekcie)."""

from __future__ import annotations

import argparse
import sqlite3
import statistics

from buffett_scanner.calibration import _spearman_rho

PRIMARY_HORIZON = 6
HORIZONS = (1, 3, 6, 12)
WITHOUT_VALUATION_MAX = 25.0  # financial_safety(15) + dividend_shareholder_return(10)


def year_of(d: str) -> int:
    return int(d[:4])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row

    run_ids = [r["run_id"] for r in conn.execute("SELECT DISTINCT run_id FROM backtest_candidates")]
    if len(run_ids) != 1:
        raise RuntimeError(f"Oczekiwano dokładnie 1 run_id w backtest_candidates, znaleziono: {run_ids}")
    run_id = run_ids[0]
    print(f"run_id={run_id}")

    candidates = conn.execute("SELECT * FROM backtest_candidates WHERE run_id=?", (run_id,)).fetchall()
    coverage = conn.execute("SELECT * FROM backtest_coverage WHERE run_id=? ORDER BY decision_date", (run_id,)).fetchall()
    benchmarks = {r["decision_date"]: r for r in conn.execute("SELECT * FROM backtest_benchmark WHERE run_id=?", (run_id,))}

    print(f"\n== 1. DATA / INTEGRITY ==")
    print(f"n_candidates={len(candidates)}")
    print(f"n_decision_dates(coverage)={len(coverage)}")
    dates = sorted({r["decision_date"] for r in coverage})
    print(f"date_range={dates[0]}..{dates[-1]}")
    total_pit = sum(r["pit_universe_count"] for r in coverage)
    total_scanned = sum(r["scanned_count"] for r in coverage)
    print(f"pit_universe_total={total_pit} scanned_total={total_scanned} coverage_pct={total_scanned/total_pit*100:.2f}%")
    total_candidate_stage = sum(r["stage_candidate"] for r in coverage)
    print(f"funnel CANDIDATE total (coverage table) = {total_candidate_stage} (backtest_candidates rows = {len(candidates)})")

    print(f"\n== 7. ZERO-CANDIDATE DECISION DATES ==")
    zero_dates = [r["decision_date"] for r in coverage if r["stage_candidate"] == 0]
    print(f"zero_candidate_dates n={len(zero_dates)} / {len(coverage)} ({len(zero_dates)/len(coverage)*100:.2f}%)")
    print(f"dates: {zero_dates}")

    def excess_pairs(rows, horizon, vs):
        attr = f"return_{horizon}m_pct"
        bench_attr = f"ew_pit_universe_return_{horizon}m_pct" if vs == "ew" else f"spy_return_{horizon}m_pct"
        out = []
        for c in rows:
            ret = c[attr]
            if ret is None:
                continue
            bench = benchmarks.get(c["decision_date"])
            if bench is None:
                continue
            bench_ret = bench[bench_attr]
            if bench_ret is None:
                continue
            out.append((year_of(c["decision_date"]), ret - bench_ret, c["deterministic_score_pct"]))
        return out

    def report_population(label, rows):
        print(f"\n== {label} (n_candidates={len(rows)}) ==")
        for horizon in HORIZONS:
            ew_pairs = excess_pairs(rows, horizon, "ew")
            spy_pairs = excess_pairs(rows, horizon, "spy")
            ew_vals = [v for _, v, _ in ew_pairs]
            spy_vals = [v for _, v, _ in spy_pairs]
            hit_ew = (sum(1 for v in ew_vals if v > 0) / len(ew_vals) * 100.0) if ew_vals else None
            hit_spy = (sum(1 for v in spy_vals if v > 0) / len(spy_vals) * 100.0) if spy_vals else None
            med_ew = statistics.median(ew_vals) if ew_vals else None
            med_spy = statistics.median(spy_vals) if spy_vals else None
            score_pairs = [(s, v) for _, v, s in ew_pairs if s is not None]
            rho = _spearman_rho([p[0] for p in score_pairs], [p[1] for p in score_pairs]) if len(score_pairs) >= 3 else None
            print(f"  {horizon}m: n_ew={len(ew_vals)} n_spy={len(spy_vals)} median_excess_vs_ew={med_ew} "
                  f"median_excess_vs_spy={med_spy} hit_rate_vs_ew={hit_ew} hit_rate_vs_spy={hit_spy} "
                  f"spearman(score,excess_vs_ew)={rho} n_score_pairs={len(score_pairs)}")

            if horizon == PRIMARY_HORIZON:
                by_year = {}
                for y, v, s in ew_pairs:
                    by_year.setdefault(y, []).append((v, s))
                print(f"    per-year (horizon={horizon}m, vs EW):")
                for y in sorted(by_year):
                    vals = [v for v, s in by_year[y]]
                    pairs_y = [(s, v) for v, s in by_year[y] if s is not None]
                    rho_y = _spearman_rho([p[0] for p in pairs_y], [p[1] for p in pairs_y]) if len(pairs_y) >= 3 else None
                    print(f"      {y}: n={len(vals)} median_excess={statistics.median(vals) if vals else None} "
                          f"hit_rate={(sum(1 for v in vals if v>0)/len(vals)*100.0) if vals else None} spearman={rho_y}")

    report_population("2. FULL/PARTIAL POPULATION -- FINAL FROZEN MODEL", candidates)

    cv_subset = [c for c in candidates if c["margin_of_safety_base_pct"] is not None]
    report_population("3. COMPLETE-VALUATION SUBSET -- B) final score WITH valuation", cv_subset)

    print(f"\n== 3. COMPLETE-VALUATION SUBSET -- A) score WITHOUT valuation (paired, same n={len(cv_subset)} observations) ==")
    without_rows = []
    for c in cv_subset:
        without_pct = (c["safety_score"] + c["dividend_score"]) / WITHOUT_VALUATION_MAX * 100.0
        without_rows.append(dict(c, deterministic_score_pct_without=without_pct))

    def excess_pairs_without(rows, horizon, vs):
        attr = f"return_{horizon}m_pct"
        bench_attr = f"ew_pit_universe_return_{horizon}m_pct" if vs == "ew" else f"spy_return_{horizon}m_pct"
        out = []
        for c in rows:
            ret = c[attr]
            if ret is None:
                continue
            bench = benchmarks.get(c["decision_date"])
            if bench is None:
                continue
            bench_ret = bench[bench_attr]
            if bench_ret is None:
                continue
            out.append((year_of(c["decision_date"]), ret - bench_ret, c["deterministic_score_pct_without"]))
        return out

    for horizon in HORIZONS:
        ew_pairs = excess_pairs_without(without_rows, horizon, "ew")
        score_pairs = [(s, v) for _, v, s in ew_pairs if s is not None]
        rho = _spearman_rho([p[0] for p in score_pairs], [p[1] for p in score_pairs]) if len(score_pairs) >= 3 else None
        print(f"  {horizon}m: n={len(score_pairs)} spearman(score_WITHOUT_valuation, excess_vs_ew)={rho}")
        if horizon == PRIMARY_HORIZON:
            by_year = {}
            for y, v, s in ew_pairs:
                by_year.setdefault(y, []).append((v, s))
            for y in sorted(by_year):
                pairs_y = [(s, v) for v, s in by_year[y] if s is not None]
                rho_y = _spearman_rho([p[0] for p in pairs_y], [p[1] for p in pairs_y]) if len(pairs_y) >= 3 else None
                print(f"    {y}: n={len(pairs_y)} spearman_without={rho_y}")

    print("\n== KONIEC HOLDOUT DIAGNOSTIC ==")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

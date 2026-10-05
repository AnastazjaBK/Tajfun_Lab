"""ONE-OFF diagnostic — Faza 5.4d, ROUND 3: VALUATION ROBUSTNESS / SENSITIVITY
ANALYSIS (decyzja właścicielki 2026-10-05: zmiana celu Round 3 z parameter
optimization na robustness check). NIE jest to candidate search ani wybór
"zwycięzcy" po forward returns — cel to sprawdzić, czy silnik wyceny i
ranking kandydatów są STABILNE przy rozsądnych zmianach `mos_pct_for_
full_score`/growth caps (`buffett_scanner.calibration_round3.
ROUND_3_CANDIDATES`, siatka zamrożona PRZED tym runem).

Do usunięcia z obu branchy po wyciągnięciu wyników (ten sam wzorzec co
wcześniejsze diag_*.py w tym projekcie) -- `calibration_round3.py`
(zamrożona siatka) zostaje jako trwały zapis audytowy, ten skrypt nie.

Metodologia:
- Funnel (decline scanner / prefilter / hard gates) liczony RAZ pod
  `3_default` -- niezależny od valuation sub-configu z konstrukcji
  (zweryfikowane już w Faza 5.4b/5.4c dla wag scoringu; to samo dotyczy
  `dcf_owner_earnings`, bo decline/prefilter/hard_gates nigdy go nie
  czytają). Dla każdej obserwacji na etapie CANDIDATE, pozostałe 4
  warianty liczone WYŁĄCZNIE przez `compute_deterministic_score` na
  TYCH SAMYCH periods/cenie -- jedna ścieżka kanoniczna, zero
  duplikowania logiki.
- SCORE/RANK/CLASSIFICATION/VALUATION-OUTPUT stability: liczone na
  PEŁNYM oknie kalibracyjnym 2012-2021 (nie tylko OOS 2016-2021) --
  to diagnostyka silnika wyceny, nie wybór konfiguracji po forward
  returns, więc większa próbka jest właściwsza. FORWARD-RETURN
  diagnostics (sekcja 5) pozostają restricted do OOS 2016-2021, zgodnie
  z konwencją reszty projektu (rozgrzewka 2012-2015 nigdy nie wchodzi
  do oceny).
- "Duża zmiana" valuation_score zdefiniowana jako |Δ| > 2.0 pkt (10%
  budżetu wagi valuation=20) -- próg opisowy/raportowy, NIE decyzyjny.
"""

from __future__ import annotations

import argparse
import statistics

from buffett_scanner.backtest_harness import (
    BacktestCandidate,
    compute_deterministic_score,
    compute_forward_returns,
    evaluate_candidate_at_date,
    generate_rebalance_dates,
)
from buffett_scanner.benchmark import compute_benchmark_snapshot
from buffett_scanner.calibration import (
    CALIBRATION_WINDOW_END,
    CALIBRATION_WINDOW_START,
    OOS_FOLD_YEARS,
    _spearman_rho,
    evaluate_candidate_configuration,
    evaluate_candidate_configuration_spearman,
)
from buffett_scanner.calibration_round3 import ROUND_3_CANDIDATES
from buffett_scanner.config import load_config
from buffett_scanner.db import (
    connect,
    get_cik_for_active_ticker,
    get_companies_sector_profiles,
    get_price_series,
    get_sec_company_facts_cache,
    get_universe_membership_as_of,
    list_universe_membership_ciks,
)
from buffett_scanner.pit_fundamentals import build_annual_fundamentals_periods_as_of
from buffett_scanner.scanner import PriceBar

UNIVERSE_MEMBERSHIP_INDEX_NAME = "SP500"
LARGE_SCORE_CHANGE_THRESHOLD = 2.0  # 10% budzetu wagi valuation (20 pkt)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--sample", default=None)
    args = parser.parse_args()

    base_config = load_config()
    variant_configs = {c.name: c.apply(base_config) for c in ROUND_3_CANDIDATES}
    variant_names = [c.name for c in ROUND_3_CANDIDATES]
    non_default_names = [n for n in variant_names if n != "3_default"]

    conn = connect(args.db)
    all_ciks = list_universe_membership_ciks(conn, UNIVERSE_MEMBERSHIP_INDEX_NAME)
    sample_set = None
    if args.sample:
        sample_set = {c.strip() for c in args.sample.split(",") if c.strip()}
        all_ciks = [c for c in all_ciks if c in sample_set]
    print(f"CIK w zakresie: {len(all_ciks)}")

    sector_profiles = get_companies_sector_profiles(conn)
    price_bars_by_cik: dict[str, list[PriceBar]] = {}
    company_facts_by_cik: dict[str, dict] = {}
    for cik in all_ciks:
        rows = get_price_series(conn, cik)
        price_bars_by_cik[cik] = [
            PriceBar(date=r["date"], open=r["open"], high=r["high"], low=r["low"],
                      close=r["close"], adj_close=r["adj_close"], volume=r["volume"])
            for r in rows
        ]
        cf = get_sec_company_facts_cache(conn, cik)
        if cf is not None:
            company_facts_by_cik[cik] = cf

    spy_cik = get_cik_for_active_ticker(conn, "SPY")
    spy_bars: list[PriceBar] | None = None
    if spy_cik is not None:
        spy_rows = get_price_series(conn, spy_cik)
        spy_bars = [
            PriceBar(date=r["date"], open=r["open"], high=r["high"], low=r["low"],
                      close=r["close"], adj_close=r["adj_close"], volume=r["volume"])
            for r in spy_rows
        ]

    decision_dates = generate_rebalance_dates(CALIBRATION_WINDOW_START, CALIBRATION_WINDOW_END, "MONTHLY")
    print(f"Okno kalibracyjne: {CALIBRATION_WINDOW_START}..{CALIBRATION_WINDOW_END}, {len(decision_dates)} decision dates.")
    print(f"Kandydaci Round 3 (zamrożona siatka): {variant_names}")

    # obs[(cik, decision_date)] = {variant_name: DeterministicScoreResult, "decision_price":..., "forward_returns":..., "decline_flags":...}
    observations: dict[tuple[str, str], dict] = {}
    benchmark_snapshots = []

    for d_idx, decision_date in enumerate(decision_dates, 1):
        pit_ciks = get_universe_membership_as_of(conn, UNIVERSE_MEMBERSHIP_INDEX_NAME, decision_date)
        if len(pit_ciks) != len(set(pit_ciks)):
            dupes = sorted({c for c in pit_ciks if pit_ciks.count(c) > 1})
            raise RuntimeError(f"FAIL FAST: duplikat CIK {dupes} w universe_membership_as_of({decision_date!r})")
        if sample_set is not None:
            pit_ciks = [c for c in pit_ciks if c in sample_set]

        pit_ciks_with_sufficient_price: list[str] = []
        for cik in pit_ciks:
            full_bars = price_bars_by_cik.get(cik, [])
            bars = [b for b in full_bars if b.date <= decision_date]
            cf = company_facts_by_cik.get(cik)
            periods = build_annual_fundamentals_periods_as_of(cf, decision_date) if cf is not None else []
            if bars:
                pit_ciks_with_sufficient_price.append(cik)
            if not bars or not periods:
                continue

            sector_profile = sector_profiles.get(cik, "GENERAL")
            default_result = evaluate_candidate_at_date(
                cik=cik, ticker_as_of_date=cik, decision_date=decision_date,
                bars=bars, periods=periods, sector_profile=sector_profile,
                config=variant_configs["3_default"], run_id="round3-diag",
                config_version="3_default", universe_provenance="round3-diag",
            )
            if default_result.stage != "CANDIDATE":
                continue

            current_price = bars[-1].close
            per_variant = {"3_default": default_result.score}
            for name in non_default_names:
                per_variant[name] = compute_deterministic_score(
                    periods=periods, sector_profile=sector_profile,
                    current_price=current_price, config=variant_configs[name],
                )

            forward_returns = compute_forward_returns(full_bars, decision_date, current_price)
            observations[(cik, decision_date)] = {
                "scores": per_variant,
                "decision_price": current_price,
                "decline_flags": default_result.decline_flags,
                "forward_returns": forward_returns,
            }

        benchmark_snapshots.append(
            compute_benchmark_snapshot(
                decision_date=decision_date,
                pit_universe_ciks_with_sufficient_price=pit_ciks_with_sufficient_price,
                price_bars_by_cik=price_bars_by_cik, spy_bars=spy_bars,
            )
        )
        if d_idx % 24 == 0 or d_idx == len(decision_dates):
            print(f"  [{d_idx}/{len(decision_dates)}] {decision_date}: obserwacji dotychczas={len(observations)}")

    print(f"\nLacznie obserwacji (CANDIDATE stage, wszystkie warianty policzone): {len(observations)}")

    def year_of(d: str) -> int:
        return int(d[:4])

    # Complete-valuation subset wedlug DEFAULT (margin_of_safety_base_pct not None).
    cv_subset = {
        key: obs for key, obs in observations.items()
        if obs["scores"]["3_default"].margin_of_safety_base_pct is not None
    }
    print(f"Complete-valuation subset (wg 3_default, pelne okno 2012-2021): {len(cv_subset)}")

    # ------------------------------------------------------------------
    # A. SCORE STABILITY (valuation_score vs 3_default), pelne okno.
    # ------------------------------------------------------------------
    print("\n== A. SCORE STABILITY (valuation_score vs 3_default, complete-valuation subset, pelne okno 2012-2021) ==")
    for name in non_default_names:
        pairs = [
            (obs["scores"]["3_default"].valuation_score, obs["scores"][name].valuation_score)
            for obs in cv_subset.values()
        ]
        default_vals = [p[0] for p in pairs]
        variant_vals = [p[1] for p in pairs]
        deltas = [abs(v - d) for d, v in pairs]
        rho = _spearman_rho(default_vals, variant_vals)
        deltas_sorted = sorted(deltas)
        n = len(deltas_sorted)
        def pct(p):
            if n == 0:
                return None
            idx = min(n - 1, int(p * n))
            return deltas_sorted[idx]
        large_share = (sum(1 for d in deltas if d > LARGE_SCORE_CHANGE_THRESHOLD) / n * 100.0) if n else None
        print(f"  {name}: n={n} spearman(default,variant)={rho} median_abs_delta={statistics.median(deltas) if deltas else None}")
        print(f"    delta percentyle p50/p75/p90/p95/max = {pct(0.50)}/{pct(0.75)}/{pct(0.90)}/{pct(0.95)}/{(deltas_sorted[-1] if deltas_sorted else None)}")
        print(f"    udzial obserwacji z |delta|>{LARGE_SCORE_CHANGE_THRESHOLD} pkt: {large_share}%")

    # ------------------------------------------------------------------
    # B. RANK STABILITY per decision_date (pelna populacja CANDIDATE, pelne okno).
    # ------------------------------------------------------------------
    print("\n== B. RANK STABILITY (deterministic_score_pct ranking per decision_date vs 3_default, pelne okno) ==")
    by_date: dict[str, list[tuple[str, str]]] = {}
    for (cik, decision_date) in observations:
        by_date.setdefault(decision_date, []).append((cik, decision_date))

    for name in non_default_names:
        date_rhos: list[tuple[str, float]] = []
        for decision_date, keys in by_date.items():
            default_scores = [observations[k]["scores"]["3_default"].deterministic_score_pct for k in keys]
            variant_scores = [observations[k]["scores"][name].deterministic_score_pct for k in keys]
            pairs = [(d, v) for d, v in zip(default_scores, variant_scores) if d is not None and v is not None]
            if len(pairs) < 3:
                continue
            rho = _spearman_rho([p[0] for p in pairs], [p[1] for p in pairs])
            if rho is not None:
                date_rhos.append((decision_date, rho))
        if date_rhos:
            rhos_only = [r for _, r in date_rhos]
            worst = sorted(date_rhos, key=lambda x: x[1])[:3]
            print(f"  {name}: n_dates={len(date_rhos)} median={statistics.median(rhos_only)} min={min(rhos_only)} max={max(rhos_only)}")
            print(f"    3 najbardziej niestabilne daty: {worst}")
        else:
            print(f"  {name}: brak dat z >=3 kandydatami.")

    # ------------------------------------------------------------------
    # C. CLASSIFICATION STABILITY -- MoS<=0 floor crossing vs 3_default.
    # ------------------------------------------------------------------
    print("\n== C. CLASSIFICATION STABILITY (MoS<=0 valuation_score floor crossing vs 3_default, complete-valuation subset) ==")
    print("  Uwaga: hard_gates.min_margin_of_safety_pct=None (nieaktywny) w produkcyjnym configu -- jedyny ZYWY prog to floor MoS<=0 w valuation_score.")
    for name in non_default_names:
        crossed = 0
        for obs in cv_subset.values():
            d_mos = obs["scores"]["3_default"].margin_of_safety_base_pct
            v_mos = obs["scores"][name].margin_of_safety_base_pct
            if v_mos is None:
                continue
            d_side = d_mos <= 0
            v_side = v_mos <= 0
            if d_side != v_side:
                crossed += 1
        pct_crossed = (crossed / len(cv_subset) * 100.0) if cv_subset else None
        print(f"  {name}: crossed={crossed}/{len(cv_subset)} ({pct_crossed}%)")

    # ------------------------------------------------------------------
    # D. VALUATION OUTPUT STABILITY -- bear/base/bull intrinsic value + MoS.
    # ------------------------------------------------------------------
    print("\n== D. VALUATION OUTPUT STABILITY (bear/base/bull, complete-valuation subset, pelne okno) ==")
    for name in non_default_names:
        print(f"  -- {name} --")
        for scenario in ("bear", "base", "bull"):
            iv_pct_changes = []
            mos_pp_changes = []
            excluded_nonpositive_default_iv = 0
            for obs in cv_subset.values():
                d_result = obs["scores"]["3_default"].valuation_result
                v_result = obs["scores"][name].valuation_result
                if scenario not in d_result.scenarios or scenario not in v_result.scenarios:
                    continue
                d_scn = d_result.scenarios[scenario]
                v_scn = v_result.scenarios[scenario]
                if d_scn.intrinsic_value_per_share > 0:
                    iv_pct_changes.append(
                        abs(v_scn.intrinsic_value_per_share - d_scn.intrinsic_value_per_share)
                        / d_scn.intrinsic_value_per_share * 100.0
                    )
                else:
                    excluded_nonpositive_default_iv += 1
                if d_scn.margin_of_safety_pct is not None and v_scn.margin_of_safety_pct is not None:
                    mos_pp_changes.append(abs(v_scn.margin_of_safety_pct - d_scn.margin_of_safety_pct))
            med_iv = statistics.median(iv_pct_changes) if iv_pct_changes else None
            med_mos = statistics.median(mos_pp_changes) if mos_pp_changes else None
            print(f"    {scenario}: n_iv_pct={len(iv_pct_changes)} median_|delta_intrinsic_value|%={med_iv} "
                  f"(wykluczonych non-positive default IV: {excluded_nonpositive_default_iv}); "
                  f"n_mos={len(mos_pp_changes)} median_|delta_MoS|_pp={med_mos}")

    # ------------------------------------------------------------------
    # 5. FORWARD-RETURN DIAGNOSTICS -- TYLKO DIAGNOSTIC, nigdy decyzyjne.
    # ------------------------------------------------------------------
    print("\n== 5. FORWARD-RETURN DIAGNOSTICS (TYLKO diagnostyczne -- NIE uzyte do wyboru parametrow, OOS 2016-2021) ==")
    for name in variant_names:
        candidates: list[BacktestCandidate] = []
        for (cik, decision_date), obs in observations.items():
            score = obs["scores"][name]
            candidates.append(
                BacktestCandidate(
                    run_id="round3-diag", decision_date=decision_date, cik=cik, ticker_as_of_date=cik,
                    decision_price=obs["decision_price"], decline_flags=obs["decline_flags"],
                    pit_fundamentals_period_end=None, pit_fundamentals_filed_date=None,
                    financial_quality_breakdown=score.financial_quality_result.breakdown,
                    safety_score=score.safety_score, valuation_score=score.valuation_score,
                    dividend_score=score.dividend_score, full_score=None,
                    deterministic_partial_score=score.deterministic_partial_score,
                    deterministic_score_pct=score.deterministic_score_pct,
                    available_components=score.available_components, missing_components=score.missing_components,
                    hard_gate_passed=True, hard_gate_triggered=(),
                    margin_of_safety_base_pct=score.margin_of_safety_base_pct,
                    config_version=name, scoring_version=variant_configs[name].scoring.version,
                    universe_provenance="round3-diag", forward_returns=obs["forward_returns"],
                )
            )
        spearman_full = evaluate_candidate_configuration_spearman(
            candidate_name=name, round=3, subround="3", description="round3-diag",
            candidates=candidates, require_valuation=False,
        )
        spearman_cv = evaluate_candidate_configuration_spearman(
            candidate_name=name, round=3, subround="3", description="round3-diag",
            candidates=candidates, require_valuation=True,
        )
        median_excess = evaluate_candidate_configuration(
            candidate_name=name, round=3, description="round3-diag",
            candidates=candidates, benchmark_snapshots=benchmark_snapshots,
        )
        print(f"  {name}:")
        print(f"    [full population]            pooled_spearman(n={spearman_full.pooled_n})={spearman_full.pooled_spearman} "
              f"median_of_fold={spearman_full.median_of_fold_spearman} n_positive_folds={spearman_full.n_positive_folds}/{spearman_full.n_folds_with_data}")
        print(f"    [complete-valuation subset]  pooled_spearman(n={spearman_cv.pooled_n})={spearman_cv.pooled_spearman} "
              f"median_of_fold={spearman_cv.median_of_fold_spearman} n_positive_folds={spearman_cv.n_positive_folds}/{spearman_cv.n_folds_with_data}")
        print(f"    [diagnostic] pooled_median_excess_return_pct(n={median_excess.pooled_n})={median_excess.pooled_median_excess_return_pct}")

    print("\n== KONIEC ROUND 3 ROBUSTNESS DIAGNOSTIC ==")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

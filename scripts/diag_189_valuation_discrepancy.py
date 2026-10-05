"""Diagnostyka rozbieznosci 189 kandydatow (Faza 5.3g, zlecenie
wlascicielki 2026-10-05): dlaczego PERSISTED production valuation_score
jest None, a POMOCNICZA rekomputacja compute_valuation(...) daje
implemented=True, na pozornie tych samych wejsciach.

ZERO zmian w total_debt.py/pit_fundamentals.py/fundamentals.py/
valuation.py/scoring.py/backtest_harness.py/config.yaml. Jedyny cel:
ustalic, KTO ma racje (oryginalny production run, czy recompute) i
DLACZEGO sie rozchodza -- nie zakladam z gory, ze to wina skryptu
pomocniczego.

Dla kazdego z 189 przypadkow:
1. Rekonstruuje WSZYSTKIE wejscia (periods/FCF/CAGR/total_debt/cash/
   net_debt/diluted_shares/current_price/sector_profile/config_version).
2. PONOWNIE URUCHAMIA cala produkcyjna sciezke
   (evaluate_candidate_at_date -- DOKLADNIE ta sama funkcja, co
   oryginalny walk-forward) na tych samych wejsciach z tego samego
   artefaktu, i porownuje jej wynik z (a) persisted backtest_candidates,
   (b) wczesniejsza rekompozycja compute_valuation() wprost.
3. Jesli produkcyjna sciezka PONOWNIE URUCHOMIONA zgadza sie z
   persisted (valuation_score=None) -- rozbieznosc jest WYLACZNIE w
   skrypcie pomocniczym compute_valuation(), szukamy konkretnej roznicy
   argumentow. Jesli produkcyjna sciezka PONOWNIE URUCHOMIONA NIE
   zgadza sie z persisted (tzn. teraz tez daje nie-None) -- to oznacza
   realna niezgodnosc/niedeterminizm w samym kodzie produkcyjnym,
   zglaszam jako STOP CONDITION."""

from __future__ import annotations

import hashlib
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, ".")

from buffett_scanner.backtest_harness import evaluate_candidate_at_date
from buffett_scanner.config import DEFAULT_CONFIG_PATH, load_config
from buffett_scanner.db import get_backtest_candidates, get_companies_sector_profiles, get_price_series, get_sec_company_facts_cache
from buffett_scanner.fundamentals import net_debt
from buffett_scanner.pit_fundamentals import build_annual_fundamentals_periods_as_of
from buffett_scanner.scanner import PriceBar
from buffett_scanner.valuation import compute_valuation, historical_owner_earnings_cagr_pct, owner_earnings_proxy_fcf

DB_PATH = "baseline_walk_forward_result.db"


def main() -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    config = load_config()

    config_text = Path(DEFAULT_CONFIG_PATH).read_text(encoding="utf-8")
    config_version_now = f"config.yaml:{hashlib.sha256(config_text.encode()).hexdigest()[:16]}"

    run_id = conn.execute(
        "SELECT run_id FROM backtest_coverage ORDER BY decision_date DESC LIMIT 1"
    ).fetchone()["run_id"]
    print(f"run_id = {run_id}")
    print(f"config_version (checked-out TERAZ, ten sam commit co run) = {config_version_now}")

    candidates = get_backtest_candidates(conn, run_id)
    print(f"Kandydaci: {len(candidates)}")

    # Kontrola globalna: czy JAKIKOLWIEK persisted config_version != config_version_now?
    mismatched_config = {c["config_version"] for c in candidates if c["config_version"] != config_version_now}
    print(f"Kandydaci z config_version != teraźniejszy: {len(mismatched_config)} "
          f"(wartości: {mismatched_config})")

    sector_profiles = get_companies_sector_profiles(conn)
    company_facts_by_cik: dict[str, dict] = {}
    price_bars_by_cik: dict[str, list[PriceBar]] = {}

    def facts_for(cik: str) -> dict | None:
        if cik not in company_facts_by_cik:
            company_facts_by_cik[cik] = get_sec_company_facts_cache(conn, cik)
        return company_facts_by_cik[cik]

    def bars_for(cik: str) -> list[PriceBar]:
        if cik not in price_bars_by_cik:
            rows = get_price_series(conn, cik)
            price_bars_by_cik[cik] = [
                PriceBar(date=r["date"], open=r["open"], high=r["high"], low=r["low"],
                         close=r["close"], adj_close=r["adj_close"], volume=r["volume"])
                for r in rows
            ]
        return price_bars_by_cik[cik]

    # Identycznie jak w report_post_debt_baseline.py Część 2, żeby
    # odtworzyć DOKŁADNIE te same 189.
    mismatches = []
    for c in candidates:
        if c["valuation_score"] is not None:
            continue
        facts = facts_for(c["cik"])
        periods = build_annual_fundamentals_periods_as_of(facts, c["decision_date"]) if facts else []
        sector_profile = sector_profiles.get(c["cik"], "GENERAL")
        vresult = compute_valuation(
            sector_profile, periods, current_price=c["decision_price"], config=config.valuation,
        )
        if vresult.implemented:
            mismatches.append({"candidate": c, "periods": periods, "sector_profile": sector_profile, "vresult": vresult})

    print(f"\nRozbieżności (persisted=None, recompute.implemented=True): {len(mismatches)}")

    # ==================================================================
    # Dla KAŻDEJ z nich: PONOWNIE URUCHOM evaluate_candidate_at_date
    # (CAŁA produkcyjna ścieżka) na tych samych wejściach.
    # ==================================================================
    rerun_agrees_with_persisted = 0     # rerun też daje valuation_score=None -> produkcja spójna, winny helper
    rerun_agrees_with_recompute = 0     # rerun daje valuation_score!=None -> PRAWDZIWA niezgodność produkcji
    rerun_different_stage = 0           # rerun w ogóle nie dochodzi do CANDIDATE (zniknął kandydat)
    reason_counter: Counter[str] = Counter()
    full_dump = []

    for m in mismatches:
        c = m["candidate"]
        cik, decision_date = c["cik"], c["decision_date"]
        full_bars = bars_for(cik)
        bars_truncated = [b for b in full_bars if b.date <= decision_date]
        periods = m["periods"]
        sector_profile = m["sector_profile"]

        rerun = evaluate_candidate_at_date(
            cik=cik, ticker_as_of_date=cik, decision_date=decision_date,
            bars=bars_truncated, periods=periods, sector_profile=sector_profile,
            config=config, run_id="REPRO", config_version="REPRO",
            universe_provenance="REPRO",
        )

        latest = periods[-1] if periods else None
        fcf_latest = owner_earnings_proxy_fcf(latest) if latest else None
        fcf_history = [owner_earnings_proxy_fcf(p) for p in periods]
        cagr = historical_owner_earnings_cagr_pct(periods)
        nd = net_debt(latest) if latest else None

        row = {
            "cik": cik, "decision_date": decision_date,
            "persisted_valuation_score": c["valuation_score"],
            "persisted_margin_of_safety_base_pct": c["margin_of_safety_base_pct"],
            "persisted_pit_fundamentals_period_end": c["pit_fundamentals_period_end"],
            "persisted_pit_fundamentals_filed_date": c["pit_fundamentals_filed_date"],
            "persisted_decision_price": c["decision_price"],
            "persisted_config_version": c["config_version"],
            "persisted_scoring_version": c["scoring_version"],
            "persisted_available_components": c["available_components"],
            "persisted_missing_components": c["missing_components"],
            "recompute_period_end": latest.period_end_date if latest else None,
            "recompute_filed_date": latest.filed_date if latest else None,
            "recompute_total_debt": latest.total_debt if latest else None,
            "recompute_debt_resolution_method": latest.total_debt_resolution_method if latest else None,
            "recompute_debt_confidence_tier": latest.total_debt_confidence_tier if latest else None,
            "recompute_cash_and_equivalents": latest.cash_and_equivalents if latest else None,
            "recompute_net_debt": nd,
            "recompute_diluted_shares": latest.diluted_shares_outstanding if latest else None,
            "recompute_fcf_latest": fcf_latest,
            "recompute_fcf_history": fcf_history,
            "recompute_cagr": cagr,
            "recompute_n_periods": len(periods),
            "rerun_stage": rerun.stage,
            "rerun_valuation_score": rerun.candidate.valuation_score if rerun.candidate else (
                rerun.score.valuation_score if rerun.score else "N/A (no score computed)"
            ),
        }
        full_dump.append(row)

        if rerun.stage != "CANDIDATE":
            rerun_different_stage += 1
            reason_counter[f"RERUN_STAGE_CHANGED:{rerun.stage}"] += 1
        elif rerun.candidate.valuation_score is None:
            rerun_agrees_with_persisted += 1
            reason_counter["RERUN_CONFIRMS_PERSISTED_NONE"] += 1
        else:
            rerun_agrees_with_recompute += 1
            reason_counter["RERUN_CONTRADICTS_PERSISTED"] += 1

    print(f"\n== Wynik ponownego uruchomienia CAŁEJ produkcyjnej ścieżki (evaluate_candidate_at_date) ==")
    print(f"Rerun potwierdza persisted (valuation_score=None ponownie): {rerun_agrees_with_persisted}")
    print(f"Rerun zmienia stage (kandydat znika/HARD_GATE/inny): {rerun_different_stage}")
    print(f"Rerun PRZECZY persisted (teraz valuation_score != None, jak recompute): {rerun_agrees_with_recompute}")

    print("\n== Klasyfikacja przyczyn (reason -> count -> % z 189) ==")
    total = len(mismatches)
    for reason, cnt in reason_counter.most_common():
        print(f"  {reason}: {cnt} ({cnt/total*100:.1f}%)")

    # ==================================================================
    # Pełny paired dump dla WSZYSTKICH 189 (do ręcznej inspekcji) --
    # sortowany tak, żeby "RERUN_CONTRADICTS_PERSISTED" (najważniejsze,
    # jeśli istnieją) były na górze.
    # ==================================================================
    print(f"\n== PEŁNY PAIRED DUMP (189 wierszy) ==")
    for row in full_dump:
        print(f"\n  CIK={row['cik']} decision_date={row['decision_date']} rerun_stage={row['rerun_stage']}")
        print(f"    persisted: valuation_score={row['persisted_valuation_score']} "
              f"mos_base={row['persisted_margin_of_safety_base_pct']} "
              f"period_end={row['persisted_pit_fundamentals_period_end']} "
              f"filed={row['persisted_pit_fundamentals_filed_date']} "
              f"decision_price={row['persisted_decision_price']} "
              f"config_version={row['persisted_config_version']} "
              f"scoring_version={row['persisted_scoring_version']}")
        print(f"    persisted available={row['persisted_available_components']} missing={row['persisted_missing_components']}")
        print(f"    recompute: period_end={row['recompute_period_end']} filed={row['recompute_filed_date']} "
              f"n_periods={row['recompute_n_periods']} total_debt={row['recompute_total_debt']} "
              f"method={row['recompute_debt_resolution_method']} tier={row['recompute_debt_confidence_tier']} "
              f"cash={row['recompute_cash_and_equivalents']} net_debt={row['recompute_net_debt']} "
              f"diluted_shares={row['recompute_diluted_shares']}")
        print(f"    recompute: fcf_latest={row['recompute_fcf_latest']} cagr={row['recompute_cagr']} "
              f"fcf_history={row['recompute_fcf_history']}")
        print(f"    RERUN (cała produkcyjna ścieżka, fresh): stage={row['rerun_stage']} "
              f"valuation_score={row['rerun_valuation_score']}")

    # ==================================================================
    # Sanity-check kontrolny: ten sam config_version hash dla WSZYSTKICH
    # kandydatów w tym runie (nie tylko 189) -- potwierdza brak code/config
    # driftu między oryginalnym runem a tym diagnostycznym runem.
    # ==================================================================
    all_versions = {c["config_version"] for c in candidates}
    print(f"\n== Kontrola config drift ==")
    print(f"Unikalne config_version wśród WSZYSTKICH {len(candidates)} kandydatów: {all_versions}")
    print(f"config_version policzony teraz z checked-out config.yaml: {config_version_now}")
    print(f"ZGODNE: {all_versions == {config_version_now}}")


if __name__ == "__main__":
    main()

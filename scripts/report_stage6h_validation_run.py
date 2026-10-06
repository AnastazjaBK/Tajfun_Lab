"""Jednorazowy skrypt diagnostyczny (Faza 6h) — po `analyze-live-scan-
shortlist` dla validation run_id, wypisuje na stdout SZCZEGÓŁOWY
per-ticker raport (status, dokładny validation error, czy repair był
wywołany, wygenerowane thesis_invalidation, pełna telemetria FULL i
REPAIR rozdzielone włącznie z thinking/cache tokens) — niezależnie od
tego, czy końcowy raport TOP-N został wygenerowany (co wymaga, żeby
WSZYSTKIE 5 kandydatów były COMPLETE). Czyta WYŁĄCZNIE bazę przekazaną
jako --db, nie modyfikuje żadnych danych.

Narzędzie operacyjne/diagnostyczne — usunięty po użyciu."""

from __future__ import annotations

import argparse
import json

from buffett_scanner.db import connect, get_live_scan_candidates


def _fmt(value) -> str:
    return "NULL" if value is None else str(value)


def main(db_path: str, run_id: str) -> None:
    conn = connect(db_path)
    rows = get_live_scan_candidates(conn, run_id, only_shortlist=True)

    print(f"\n===== FAZA 6h LIVE VALIDATION TEST — run_id={run_id} =====\n")

    full_calls = 0
    full_input = full_output = full_thinking = full_cache_creation = full_cache_read = 0
    repair_calls = 0
    repair_input = repair_output = repair_thinking = repair_cache_creation = repair_cache_read = 0

    for row in rows:
        ticker = row["ticker"]
        print(f"--- {ticker} ---")
        print(f"llm_status: {row['llm_status']}")
        print(f"llm_error: {_fmt(row['llm_error'])}")

        had_full_usage = row["llm_input_tokens"] is not None
        had_repair_usage = row["llm_repair_input_tokens"] is not None
        print(f"full_analysis_call_made (usage obecny): {had_full_usage}")
        print(f"targeted_repair_call_made (usage obecny): {had_repair_usage}")

        if had_full_usage:
            full_calls += 1
            full_input += row["llm_input_tokens"] or 0
            full_output += row["llm_output_tokens"] or 0
            full_thinking += row["llm_thinking_tokens"] or 0
            full_cache_creation += row["llm_cache_creation_input_tokens"] or 0
            full_cache_read += row["llm_cache_read_input_tokens"] or 0
            print(
                "FULL usage: "
                f"model={row['llm_response_model']} "
                f"input={row['llm_input_tokens']} output={row['llm_output_tokens']} "
                f"thinking={_fmt(row['llm_thinking_tokens'])} "
                f"cache_creation={_fmt(row['llm_cache_creation_input_tokens'])} "
                f"cache_read={_fmt(row['llm_cache_read_input_tokens'])} "
                f"service_tier={_fmt(row['llm_service_tier'])}"
            )

        if had_repair_usage:
            repair_calls += 1
            repair_input += row["llm_repair_input_tokens"] or 0
            repair_output += row["llm_repair_output_tokens"] or 0
            repair_thinking += row["llm_repair_thinking_tokens"] or 0
            repair_cache_creation += row["llm_repair_cache_creation_input_tokens"] or 0
            repair_cache_read += row["llm_repair_cache_read_input_tokens"] or 0
            print(
                "REPAIR usage: "
                f"model={row['llm_repair_response_model']} "
                f"input={row['llm_repair_input_tokens']} output={row['llm_repair_output_tokens']} "
                f"thinking={_fmt(row['llm_repair_thinking_tokens'])} "
                f"cache_creation={_fmt(row['llm_repair_cache_creation_input_tokens'])} "
                f"cache_read={_fmt(row['llm_repair_cache_read_input_tokens'])} "
                f"service_tier={_fmt(row['llm_repair_service_tier'])}"
            )

        if row["llm_status"] == "COMPLETE" and row["analysis_id"] is not None:
            analysis_row = conn.execute(
                "SELECT * FROM analyses WHERE analysis_id = ?", (row["analysis_id"],)
            ).fetchone()
            raw = json.loads(analysis_row["llm_raw_output"])
            print(f"current_price (deterministyczna, pipeline): {row['current_price']}")
            print(
                f"valuation_range_base={_fmt(analysis_row['valuation_range_base'])} "
                f"margin_of_safety_pct={_fmt(analysis_row['margin_of_safety_pct'])} "
                f"margin_of_safety_bear_pct={_fmt(analysis_row['margin_of_safety_bear_pct'])} "
                f"margin_of_safety_bull_pct={_fmt(analysis_row['margin_of_safety_bull_pct'])}"
            )
            print(f"biggest_unknown: {raw.get('biggest_unknown')!r}")
            print(f"thesis_invalidation: {raw.get('thesis_invalidation')!r}")
            print(f"bull_case: {raw.get('bull_case')!r}")
            print(f"bear_case: {raw.get('bear_case')!r}")
            print(f"why_market_may_be_right: {raw.get('why_market_may_be_right')!r}")
            print(f"why_this_may_not_be_a_bargain: {raw.get('why_this_may_not_be_a_bargain')!r}")
        print()

    print("===== AGREGAT TELEMETRII (rozdzielony FULL / REPAIR) =====\n")
    print("FULL ANALYSIS:")
    print(f"  calls: {full_calls}")
    print(f"  input_tokens: {full_input}")
    print(f"  output_tokens: {full_output}")
    print(f"  thinking_tokens: {full_thinking}")
    print(f"  cache_creation_input_tokens: {full_cache_creation}")
    print(f"  cache_read_input_tokens: {full_cache_read}")
    print("\nTARGETED REPAIR:")
    print(f"  calls: {repair_calls}")
    print(f"  input_tokens: {repair_input}")
    print(f"  output_tokens: {repair_output}")
    print(f"  thinking_tokens: {repair_thinking}")
    print(f"  cache_creation_input_tokens: {repair_cache_creation}")
    print(f"  cache_read_input_tokens: {repair_cache_read}")

    n_complete = sum(1 for r in rows if r["llm_status"] == "COMPLETE")
    print(f"\nKRYTERIUM SUKCESU: {n_complete}/{len(rows)} COMPLETE")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    main(args.db, args.run_id)

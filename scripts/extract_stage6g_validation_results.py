"""Jednorazowy skrypt diagnostyczny (Faza 6g) — czyta wynik LIVE
VALIDATION TEST (artefakt `phase6g-validation-result`) i wypisuje do
logów pełną treść pól dla każdego z 5 tickerów (CBOE/PAYX/DECK/INTU/
ACN). Zero sieci, zero nowych wywołań Claude -- tylko odczyt już
istniejącej bazy. Usunięty po użyciu."""

from __future__ import annotations

import argparse
import json

from buffett_scanner.db import connect

VALIDATION_RUN_ID_PREFIX = "validation-6g-"


def main(db_path: str) -> None:
    conn = connect(db_path)
    run_row = conn.execute(
        "SELECT run_id FROM live_scan_runs WHERE run_id LIKE ? ORDER BY created_at DESC LIMIT 1",
        (VALIDATION_RUN_ID_PREFIX + "%",),
    ).fetchone()
    if run_row is None:
        print("BRAK validation run_id w tej bazie.")
        return
    run_id = run_row["run_id"]
    print(f"VALIDATION_RUN_ID={run_id}")

    rows = conn.execute(
        "SELECT * FROM live_scan_candidates WHERE run_id = ? ORDER BY rank", (run_id,)
    ).fetchall()
    for row in rows:
        print(
            f"--- {row['ticker']} --- llm_status={row['llm_status']} "
            f"current_price={row['current_price']} valuation_score={row['valuation_score']} "
            f"margin_of_safety_base_pct={row['margin_of_safety_base_pct']} "
            f"llm_input_tokens={row['llm_input_tokens']} llm_output_tokens={row['llm_output_tokens']} "
            f"llm_thinking_tokens={row['llm_thinking_tokens']}"
        )
        if row["llm_status"] == "COMPLETE" and row["analysis_id"] is not None:
            analysis = conn.execute(
                "SELECT * FROM analyses WHERE analysis_id = ?", (row["analysis_id"],)
            ).fetchone()
            raw = json.loads(analysis["llm_raw_output"])
            print(f"  valuation_range_base(IV)={analysis['valuation_range_base']} "
                  f"margin_of_safety_pct(BASE)={analysis['margin_of_safety_pct']}")
            print(f"  biggest_unknown={raw.get('biggest_unknown')!r}")
            print(f"  thesis_invalidation={raw.get('thesis_invalidation')!r}")
            print(f"  why_this_may_not_be_a_bargain={raw.get('why_this_may_not_be_a_bargain')!r}")
            print(f"  why_market_may_be_right={raw.get('why_market_may_be_right')!r}")
            print(f"  bull_case={raw.get('bull_case')!r}")
            print(f"  bear_case={raw.get('bear_case')!r}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    args = parser.parse_args()
    main(args.db)

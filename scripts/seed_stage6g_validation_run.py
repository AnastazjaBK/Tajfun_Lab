"""Jednorazowy skrypt diagnostyczny (Faza 6g) — seeduje NOWY, osobny
`run_id` w istniejącej bazie `live_scan_result.db` dla ograniczonego
LIVE VALIDATION TEST poprawionego Stage 2 (commit bdfcc92, fix
`thesis_invalidation` semantycznie pusty), WYŁĄCZNIE dla 5 historycznych
finalistów (CBOE/PAYX/DECK/INTU/ACN). Kopiuje JUŻ POLICZONE
deterministyczne wartości (current_price, decline flags, deterministic
score/safety/valuation/dividend, MoS, hard gates) z historycznego
run_id `live-scan-2026-10-06T083825543395Z` — zero nowego decline
screeningu, zero nowego deterministic ranking, zero nowego wyboru
TOP-20. Czyta WYŁĄCZNIE historyczny run_id (tylko SELECT) — nigdy go
nie modyfikuje.

`run_date` nowego runu ma sufiks "-validation6g" (różny od
historycznego "2026-10-06" i od poprzedniego testu
"-validation6f"), żeby `cache_key` NIE trafił w cache ŻADNYCH
wcześniejszych analiz (ani historycznych, ani z Fazy 6f) — wymóg:
realne NOWE wywołania Claude z poprawionym kodem (bdfcc92).

Narzędzie operacyjne (nie zmienia bugfixu/metodologii) — usunięty po
użyciu, jak każda jednorazowa diagnostyka w tym projekcie."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys

from buffett_scanner.db import connect, insert_live_scan_candidate, insert_live_scan_run

HISTORICAL_RUN_ID = "live-scan-2026-10-06T083825543395Z"
VALIDATION_TICKERS = ("CBOE", "PAYX", "DECK", "INTU", "ACN")


def main(db_path: str) -> str:
    conn = connect(db_path)
    historical_run = conn.execute(
        "SELECT * FROM live_scan_runs WHERE run_id = ?", (HISTORICAL_RUN_ID,)
    ).fetchone()
    if historical_run is None:
        print(f"BŁĄD: historyczny run_id '{HISTORICAL_RUN_ID}' nie istnieje w tej bazie.", file=sys.stderr)
        sys.exit(1)

    placeholders = ",".join("?" for _ in VALIDATION_TICKERS)
    rows = conn.execute(
        f"SELECT * FROM live_scan_candidates WHERE run_id = ? AND ticker IN ({placeholders})",
        (HISTORICAL_RUN_ID, *VALIDATION_TICKERS),
    ).fetchall()
    found = {r["ticker"] for r in rows}
    missing = set(VALIDATION_TICKERS) - found
    if missing:
        print(f"BŁĄD: brak w historycznym run_id tickerów: {sorted(missing)}", file=sys.stderr)
        sys.exit(1)

    validation_run_id = "validation-6g-" + dt.datetime.utcnow().strftime("%Y-%m-%dT%H%M%S%fZ")
    validation_run_date = dt.date.today().isoformat() + "-validation6g"

    insert_live_scan_run(
        conn, run_id=validation_run_id, run_date=validation_run_date,
        config_version=historical_run["config_version"],
        universe_size=len(VALIDATION_TICKERS),
        decline_surfaced=len(VALIDATION_TICKERS),
        prefilter_excluded=0,
        shortlist_limit=len(VALIDATION_TICKERS),
        shortlist_size=len(VALIDATION_TICKERS),
    )

    for row in rows:
        insert_live_scan_candidate(
            conn, run_id=validation_run_id, cik=row["cik"], ticker=row["ticker"],
            rank=row["rank"], current_price=row["current_price"],
            decline_flags=json.loads(row["decline_flags_json"]),
            deterministic_score_pct=row["deterministic_score_pct"],
            deterministic_partial_score=row["deterministic_partial_score"],
            available_components=tuple(json.loads(row["available_components_json"])),
            missing_components=tuple(json.loads(row["missing_components_json"])),
            safety_score=row["safety_score"], valuation_score=row["valuation_score"],
            dividend_score=row["dividend_score"],
            margin_of_safety_base_pct=row["margin_of_safety_base_pct"],
            hard_gate_passed_deterministic=bool(row["hard_gate_passed_deterministic"]),
            hard_gate_triggered_deterministic=tuple(
                json.loads(row["hard_gate_triggered_deterministic_json"])
            ),
            in_shortlist=True,
        )
    conn.commit()

    print(
        f"Zseedowano validation run_id={validation_run_id} z {len(rows)} kandydatami "
        f"skopiowanymi z {HISTORICAL_RUN_ID}: {sorted(r['ticker'] for r in rows)}",
        file=sys.stderr,
    )
    print(validation_run_id)
    return validation_run_id


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    args = parser.parse_args()
    main(args.db)

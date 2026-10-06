"""ONE-OFF diagnostyka (Faza 6, COST AUDIT, 2026-10-06, Decyzja
właścicielki: "Najpierw wykonaj COST AUDIT... NIE zgaduj"). Czyta
WYŁĄCZNIE z już istniejącego artefaktu (zero sieci, zero nowych
wywołań Claude API) — mierzy REALNY rozmiar `llm_raw_output` (pełny
JSON `AnalysisOutput.model_dump()`, zapisany przez `insert_analysis`
dla każdej zakończonej sukcesem analizy) i rozkłada go na pola, żeby
ustalić, które pola dominują OUTPUT tokens. Nie liczy realnych
tokenów (Anthropic token counting API niedostępne z tego skryptu —
zero klucza, zero sieci) — tylko dokładną liczbę znaków, jawnie
oznaczoną jako znaki, nie tokeny."""

from __future__ import annotations

import argparse
import json
import statistics

from buffett_scanner.db import connect


def _field_len(obj: dict, path: list) -> int:
    cur = obj
    for key in path:
        if cur is None:
            return 0
        cur = cur.get(key) if isinstance(cur, dict) else None
    if cur is None:
        return 0
    if isinstance(cur, list):
        return sum(len(str(x)) for x in cur)
    return len(str(cur))


_FIELDS = [
    ("business_understandability.reasoning", ["business_understandability", "reasoning"]),
    ("moat.evidence", ["moat", "evidence"]),
    ("moat.counterarguments", ["moat", "counterarguments"]),
    ("financial_quality_commentary.reasoning", ["financial_quality_commentary", "reasoning"]),
    ("management_capital_allocation.evidence", ["management_capital_allocation", "evidence"]),
    ("fear_analysis.trigger", ["fear_analysis", "trigger"]),
    ("fear_analysis.reasoning", ["fear_analysis", "reasoning"]),
    ("dividend_trap_alert.reasoning", ["dividend_trap_alert", "reasoning"]),
    ("bull_case", ["bull_case"]),
    ("bear_case", ["bear_case"]),
    ("why_market_may_be_right", ["why_market_may_be_right"]),
    ("biggest_unknown", ["biggest_unknown"]),
    ("thesis_invalidation", ["thesis_invalidation"]),
    ("why_this_may_not_be_a_bargain", ["why_this_may_not_be_a_bargain"]),
    ("verification_items", ["verification_items"]),
    ("hard_flag_candidates", ["hard_flag_candidates"]),
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    args = parser.parse_args()

    conn = connect(args.db)
    rows = conn.execute(
        """
        SELECT a.analysis_id, a.cik, c.name, a.llm_model_id, a.llm_schema_version,
               a.llm_raw_output
        FROM analyses a
        LEFT JOIN companies c ON c.cik = a.cik
        ORDER BY a.analysis_id
        """
    ).fetchall()

    print(f"Liczba wierszy 'analyses' w tym DB (== liczba UDANYCH Claude calls): {len(rows)}")
    if not rows:
        return 0

    models = sorted({r["llm_model_id"] for r in rows if r["llm_model_id"]})
    schema_versions = sorted({r["llm_schema_version"] for r in rows if r["llm_schema_version"]})
    print(f"Model(e) użyte: {models}")
    print(f"Schema version(e): {schema_versions}")

    total_lens: list[int] = []
    field_totals: dict[str, int] = {name: 0 for name, _ in _FIELDS}

    for r in rows:
        raw = r["llm_raw_output"]
        if not raw:
            continue
        total_lens.append(len(raw))
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue
        for name, path in _FIELDS:
            field_totals[name] += _field_len(obj, path)

    print(f"\n== Rozmiar llm_raw_output (PEŁNY JSON AnalysisOutput, ZNAKI nie tokeny) ==")
    print(f"n={len(total_lens)}  min={min(total_lens)}  "
          f"median={statistics.median(total_lens):.0f}  "
          f"mean={statistics.mean(total_lens):.0f}  max={max(total_lens)}")

    print(f"\n== Suma znaków per pole (across {len(total_lens)} analyses) ==")
    for name, total in sorted(field_totals.items(), key=lambda kv: -kv[1]):
        avg = total / len(total_lens) if total_lens else 0
        print(f"  {name}: total={total}  avg_per_analysis={avg:.0f}")

    print("\n== Przykładowy pierwszy wiersz (cik/ticker/dlugosc) ==")
    for r in rows[:3]:
        raw_len = len(r["llm_raw_output"]) if r["llm_raw_output"] else 0
        print(f"  analysis_id={r['analysis_id']} cik={r['cik']} name={r['name']} "
              f"llm_raw_output_chars={raw_len}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

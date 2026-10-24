"""Testy regresyjne na odpowiedziach Claude zapisanych w realnych skanach
(bez nowych wywołań API).

Fixture `scan_llm_outputs_2026_10.json`: odpowiedzi ze snapshotów
live-scan-2026-10-06T083825543395Z (APP, CTVA, PAYX) i
live-scan-2026-10-22T202049554465Z (APP, UBER -- jedyne COMPLETE).

Ustalona przyczyna 22/24 FAILED w skanie 22.10: sześć pól treści miało w
modelu pydantic wartości domyślne, więc w schemacie JSON wysyłanym do API
nie były wymagane; model pomijał `thesis_invalidation` i
`biggest_unknown` (6.10: 19/20 odpowiedzi), pydantic wstawiał puste
wartości. 6.10 walidacja tego nie sprawdzała (COMPLETE mimo pustych pól),
22.10 sprawdzała, a naprawa obejmowała tylko przypadek „puste wyłącznie
thesis_invalidation” -- więc FAILED bez naprawy.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from buffett_scanner import cli
from buffett_scanner.analysis_schema import AnalysisOutput, collect_validation_violations
from buffett_scanner.db import get_llm_rejected_outputs, init_db
from buffett_scanner.providers.claude import ClaudeAnalysisResult, ClaudeRepairResult, ClaudeUsage

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "scan_llm_outputs_2026_10.json").read_text())
CONTENT_FIELDS = ("bull_case", "bear_case", "why_market_may_be_right", "biggest_unknown",
                  "thesis_invalidation", "why_this_may_not_be_a_bargain")
REPAIR_VALUES = {
    "thesis_invalidation": ["Trwały spadek marży operacyjnej przez dwa kolejne lata obaliłby tezę o przewadze."],
    "biggest_unknown": "Nie wiadomo, czy obecny poziom marży jest trwały, czy wynika z jednorazowych czynników.",
}


def _usage(inp: int, out: int) -> ClaudeUsage:
    return ClaudeUsage(model="claude-sonnet-5", input_tokens=inp, output_tokens=out,
                       cache_creation_input_tokens=0, cache_read_input_tokens=0,
                       thinking_tokens=None, service_tier="standard")


def _saved(key: str) -> AnalysisOutput:
    return AnalysisOutput.model_validate(FIXTURE[key])


def _source_ids(out: AnalysisOutput) -> set[str]:
    return (set(out.cited_source_ids) | {v.source_id for v in out.verification_items}
            | {f.evidence_source_id for f in out.hard_flag_candidates})


class _ReplayClient:
    """Pełna analiza = zapisana odpowiedź; naprawa = podane wartości."""

    def __init__(self, saved: AnalysisOutput, repair_values: dict | None):
        self.saved = saved
        self.repair_values = repair_values
        self.full_calls = 0
        self.repair_calls: list[list[str]] = []

    def generate_analysis(self, prompt):
        self.full_calls += 1
        return ClaudeAnalysisResult(output=self.saved, usage=_usage(4600, 9000))

    def repair_fields(self, prompt, fields):
        self.repair_calls.append(list(fields))
        if self.repair_values is None:
            values = {name: ("" if name == "biggest_unknown" else []) for name in fields}
        else:
            values = {name: self.repair_values[name] for name in fields}
        return ClaudeRepairResult(output=values, usage=_usage(1500, 300))


def _run(tmp_path, client, saved):
    conn = init_db(tmp_path / "t.db")
    ledger: list = []
    result = cli._generate_validated_analysis(
        conn, client, run_id="r", cik="0000000001", ticker=saved.ticker, prompt="p",
        allowed_source_ids=_source_ids(saved), metrics={}, current_price=None,
        decline_snapshot=None, valuation_result=None, ledger=ledger,
    )
    return conn, ledger, result


def test_schema_sent_to_api_requires_all_six_content_fields():
    """Przyczyna źródłowa: schemat po transformacji SDK (to, co trafia do
    API) musi wymagać sześciu pól treści -- inaczej model może je pominąć."""
    from anthropic.lib._parse._transform import transform_schema

    required = set(transform_schema(AnalysisOutput).get("required", []))
    assert set(CONTENT_FIELDS) <= required


@pytest.mark.parametrize("key", ["2026-10-06/APP", "2026-10-06/CTVA"])
def test_saved_6_10_output_has_the_22_10_failure_pattern(key):
    """Zapisana odpowiedź z 6.10 (uznana wtedy za COMPLETE) ma dokładnie
    te dwa puste pola -- i tylko je (żadnego błędu strukturalnego)."""
    out = _saved(key)
    fields = [v.field for v in collect_validation_violations(
        out, allowed_source_ids=_source_ids(out), pdf_paginated_source_ids=set())]
    assert fields == ["thesis_invalidation", "biggest_unknown"]


@pytest.mark.parametrize("key", ["2026-10-06/PAYX", "2026-10-22/APP", "2026-10-22/UBER"])
def test_saved_complete_outputs_pass_current_validation(key):
    out = _saved(key)
    assert collect_validation_violations(
        out, allowed_source_ids=_source_ids(out), pdf_paginated_source_ids=set()) == []


def test_saved_6_10_output_is_repaired_in_one_bounded_call(tmp_path):
    saved = _saved("2026-10-06/APP")
    client = _ReplayClient(saved, REPAIR_VALUES)
    conn, ledger, (analysis, claude_error, validation_error, _, repair_usage, attempts) = _run(
        tmp_path, client, saved)

    assert claude_error is None and validation_error is None
    assert client.full_calls == 1
    assert client.repair_calls == [["thesis_invalidation", "biggest_unknown"]]
    assert attempts == 1 and repair_usage.input_tokens == 1500
    assert [kind for _, kind, _ in ledger] == ["FULL_ANALYSIS", "FIELD_REPAIR"]
    assert analysis.thesis_invalidation == REPAIR_VALUES["thesis_invalidation"]
    assert analysis.biggest_unknown == REPAIR_VALUES["biggest_unknown"]
    # Pozostała treść analizy -- bez zmian.
    for name in ("bull_case", "bear_case", "why_market_may_be_right", "why_this_may_not_be_a_bargain"):
        assert getattr(analysis, name) == getattr(saved, name)
    assert analysis.moat == saved.moat
    rejected = get_llm_rejected_outputs(conn, "r")
    assert [(r["call_kind"], r["attempt"]) for r in rejected] == [("FULL_ANALYSIS", 0)]


def test_saved_complete_output_needs_no_repair(tmp_path):
    saved = _saved("2026-10-06/PAYX")
    client = _ReplayClient(saved, REPAIR_VALUES)
    _, ledger, (analysis, *_rest, attempts) = _run(tmp_path, client, saved)
    assert analysis is not None and attempts == 0 and client.repair_calls == []
    assert len(ledger) == 1


def test_failed_repair_stops_after_limit_with_reason(tmp_path):
    """Naprawa wciąż pusta -> FAILED po MAX_REPAIR_ATTEMPTS, nigdy więcej
    wywołań; przyczyna wymienia oba pola; każda odpowiedź zapisana."""
    saved = _saved("2026-10-06/APP")
    client = _ReplayClient(saved, None)
    conn, ledger, (analysis, claude_error, validation_error, *_rest, attempts) = _run(tmp_path, client, saved)

    assert analysis is None and claude_error is None
    assert attempts == cli.MAX_REPAIR_ATTEMPTS == 2
    assert len(ledger) == 1 + cli.MAX_REPAIR_ATTEMPTS
    assert "thesis_invalidation" in str(validation_error) and "biggest_unknown" in str(validation_error)
    assert len(get_llm_rejected_outputs(conn, "r")) == 1 + cli.MAX_REPAIR_ATTEMPTS


def test_structural_violation_is_never_repaired(tmp_path):
    """Cytowanie spoza listy źródeł -> FAILED bez żadnej naprawy (koszt 1 wywołanie)."""
    saved = _saved("2026-10-06/APP").model_copy(update={"cited_source_ids": ["spoza-listy"]})
    client = _ReplayClient(saved, REPAIR_VALUES)
    conn = init_db(tmp_path / "t.db")
    analysis, _, validation_error, _, _, attempts = cli._generate_validated_analysis(
        conn, client, run_id="r", cik="0000000001", ticker="APP", prompt="p",
        allowed_source_ids=_source_ids(_saved("2026-10-06/APP")) - {"spoza-listy"}, metrics={},
        current_price=None, decline_snapshot=None, valuation_result=None,
    )
    assert analysis is None and attempts == 0 and client.repair_calls == []
    assert "cited_source_ids" in str(validation_error)

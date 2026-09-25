"""Testy structured LLM output schema (sekcja 8 design review)."""

from __future__ import annotations

import pytest

from buffett_scanner.analysis_schema import (
    AnalysisOutput,
    AnalysisValidationError,
    validate_analysis_output,
)


def make_valid_output(**overrides) -> AnalysisOutput:
    base = {
        "ticker": "AAPL",
        "schema_version": "1.0",
        "business_understandability": {"score": 6, "max_score": 7, "confidence": "HIGH"},
        "moat": {"score": 10, "max_score": 12, "confidence": "MEDIUM", "evidence": ["a"]},
        "financial_quality_commentary": {"confidence": "HIGH", "reasoning": "solid"},
        "management_capital_allocation": {"score": 8, "max_score": 10, "confidence": "MEDIUM"},
        "fear_analysis": {
            "classification": "TEMPORARY", "confidence": "MEDIUM",
            "trigger": "guidance cut", "reasoning": "one quarter miss",
        },
        "dividend_trap_alert": {"triggered": False, "reasoning": ""},
        "verification_items": [
            {"source_id": "src-1", "document": "10-K", "section": "Item 7", "reason": "r", "question": "q"},
        ],
        "cited_source_ids": ["src-1"],
        "hard_flag_candidates": [],
    }
    base.update(overrides)
    return AnalysisOutput.model_validate(base)


def test_parses_minimal_valid_output():
    result = make_valid_output()
    assert result.ticker == "AAPL"
    assert result.moat.score == 10


def test_financial_quality_commentary_has_no_score_field():
    """Sekcja 8: wynik liczbowy financial_quality jest liczony
    deterministycznie w Fazie 4 — LLM dostarcza tylko komentarz."""
    result = make_valid_output()
    assert not hasattr(result.financial_quality_commentary, "score")


def test_validate_accepts_valid_output():
    result = make_valid_output()
    validate_analysis_output(
        result, allowed_source_ids={"src-1", "src-2"}, pdf_paginated_source_ids=set(),
    )  # nie rzuca


def test_validate_rejects_cited_source_id_outside_allowed_list():
    result = make_valid_output(cited_source_ids=["src-1", "src-99"])
    with pytest.raises(AnalysisValidationError, match="src-99"):
        validate_analysis_output(
            result, allowed_source_ids={"src-1"}, pdf_paginated_source_ids=set(),
        )


def test_validate_rejects_verification_item_source_id_outside_allowed_list():
    result = make_valid_output(
        verification_items=[{"source_id": "src-99", "reason": "r", "question": "q"}],
        cited_source_ids=[],
    )
    with pytest.raises(AnalysisValidationError, match="verification_items"):
        validate_analysis_output(
            result, allowed_source_ids={"src-1"}, pdf_paginated_source_ids=set(),
        )


def test_validate_rejects_page_on_non_pdf_source():
    result = make_valid_output(
        verification_items=[{"source_id": "src-1", "page": 12, "reason": "r", "question": "q"}],
    )
    with pytest.raises(AnalysisValidationError, match="BLOCKER 4"):
        validate_analysis_output(
            result, allowed_source_ids={"src-1"}, pdf_paginated_source_ids=set(),
        )


def test_validate_accepts_page_on_confirmed_pdf_source():
    result = make_valid_output(
        verification_items=[{"source_id": "src-1", "page": 12, "reason": "r", "question": "q"}],
    )
    validate_analysis_output(
        result, allowed_source_ids={"src-1"}, pdf_paginated_source_ids={"src-1"},
    )  # nie rzuca


def test_validate_rejects_hard_flag_evidence_source_id_outside_allowed_list():
    result = make_valid_output(
        hard_flag_candidates=[
            {"type": "GOING_CONCERN", "evidence_source_id": "src-99", "quoted_text": "x"},
        ],
    )
    with pytest.raises(AnalysisValidationError, match="hard_flag_candidates"):
        validate_analysis_output(
            result, allowed_source_ids={"src-1"}, pdf_paginated_source_ids=set(),
        )


def test_validate_rejects_score_above_max_score():
    result = make_valid_output(moat={"score": 20, "max_score": 12, "confidence": "HIGH"})
    with pytest.raises(AnalysisValidationError, match="reject, nie clamp"):
        validate_analysis_output(
            result, allowed_source_ids={"src-1"}, pdf_paginated_source_ids=set(),
        )


def test_validate_rejects_negative_score():
    result = make_valid_output(
        business_understandability={"score": -1, "max_score": 7, "confidence": "LOW"},
    )
    with pytest.raises(AnalysisValidationError, match="ujemny"):
        validate_analysis_output(
            result, allowed_source_ids={"src-1"}, pdf_paginated_source_ids=set(),
        )

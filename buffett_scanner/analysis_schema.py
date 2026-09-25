"""Structured LLM output schema — Faza 3 (sekcja 8 design review).

`AnalysisOutput` odzwierciedla dokładnie schemat z sekcji 8. Kształt
JSON jest wymuszany przez Claude API (`output_format=AnalysisOutput`,
patrz `providers/claude.py`) — pydantic tu nigdy się nie odrzuci z
powodu złego kształtu, bo API gwarantuje zgodność ze schematem.

`validate_analysis_output` sprawdza reguły z sekcji 8, które NIE są
częścią samego schematu JSON (bo dotyczą relacji między polami, nie
kształtu):
1. `cited_source_ids` i każde `source_id` (w `verification_items` i
   `hard_flag_candidates`) musi istnieć w liście źródeł dostarczonej
   modelowi w tym wywołaniu — inaczej cały rekord jest odrzucany.
2. `page` może być niepuste tylko dla źródeł oznaczonych jako PDF z
   potwierdzoną paginacją (BLOCKER 4).
3. Wynik liczbowy poza zakresem (`score > max_score` lub `score < 0`)
   → reject, nigdy clamp.

Nigdy nie "naprawiamy" łagodnie niepoprawnego wyjścia — `config.llm.
reject_on_schema_violation` jest domyślnie `true` z dobrego powodu:
milczące poprawianie halucynacji jest gorsze niż jawne odrzucenie.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Confidence = Literal["HIGH", "MEDIUM", "LOW"]


class AnalysisValidationError(RuntimeError):
    pass


class ScoredSection(BaseModel):
    score: int
    max_score: int
    confidence: Confidence
    reasoning: str = ""


class MoatSection(BaseModel):
    score: int
    max_score: int
    confidence: Confidence
    evidence: list[str] = Field(default_factory=list)
    counterarguments: list[str] = Field(default_factory=list)


class FinancialQualityCommentary(BaseModel):
    # Brak pola score celowo: wynik liczbowy (0-16) liczony deterministycznie
    # w Fazie 4, LLM dostarcza tylko komentarz jakościowy (sekcja 8).
    confidence: Confidence
    reasoning: str = ""


class ManagementSection(BaseModel):
    score: int
    max_score: int
    confidence: Confidence
    evidence: list[str] = Field(default_factory=list)


class FearAnalysis(BaseModel):
    classification: Literal["TEMPORARY", "UNCERTAIN", "STRUCTURAL"]
    confidence: Confidence
    trigger: str = ""
    reasoning: str = ""


class DividendTrapAlert(BaseModel):
    triggered: bool
    reasoning: str = ""


class VerificationItem(BaseModel):
    source_id: str
    document: str = ""
    section: str = ""
    page: int | None = None
    reason: str = ""
    question: str = ""


class HardFlagCandidate(BaseModel):
    type: str
    evidence_source_id: str
    quoted_text: str = ""


class AnalysisOutput(BaseModel):
    ticker: str
    schema_version: str
    business_understandability: ScoredSection
    moat: MoatSection
    financial_quality_commentary: FinancialQualityCommentary
    management_capital_allocation: ManagementSection
    fear_analysis: FearAnalysis
    dividend_trap_alert: DividendTrapAlert
    bull_case: list[str] = Field(default_factory=list)
    bear_case: list[str] = Field(default_factory=list)
    why_market_may_be_right: list[str] = Field(default_factory=list)
    biggest_unknown: str = ""
    thesis_invalidation: list[str] = Field(default_factory=list)
    why_this_may_not_be_a_bargain: list[str] = Field(default_factory=list)
    verification_items: list[VerificationItem] = Field(default_factory=list)
    cited_source_ids: list[str] = Field(default_factory=list)
    hard_flag_candidates: list[HardFlagCandidate] = Field(default_factory=list)


_SCORED_SECTIONS = ("business_understandability", "moat", "management_capital_allocation")


def validate_analysis_output(
    result: AnalysisOutput,
    *,
    allowed_source_ids: set[str],
    pdf_paginated_source_ids: set[str],
) -> None:
    """Rzuca `AnalysisValidationError` przy pierwszym naruszeniu reguł
    sekcji 8. Nic nie zwraca — brak wyjątku oznacza rekord poprawny."""
    cited = set(result.cited_source_ids)
    unknown_cited = cited - allowed_source_ids
    if unknown_cited:
        raise AnalysisValidationError(
            f"cited_source_ids zawiera id spoza dostarczonej listy: {sorted(unknown_cited)}"
        )

    for item in result.verification_items:
        if item.source_id not in allowed_source_ids:
            raise AnalysisValidationError(
                f"verification_items zawiera source_id spoza dostarczonej listy: {item.source_id}"
            )
        if item.page is not None and item.source_id not in pdf_paginated_source_ids:
            raise AnalysisValidationError(
                f"page={item.page} podane dla source_id={item.source_id}, które nie jest "
                "PDF z potwierdzoną paginacją (BLOCKER 4)"
            )

    for flag in result.hard_flag_candidates:
        if flag.evidence_source_id not in allowed_source_ids:
            raise AnalysisValidationError(
                "hard_flag_candidates zawiera evidence_source_id spoza dostarczonej listy: "
                f"{flag.evidence_source_id}"
            )

    for name in _SCORED_SECTIONS:
        section = getattr(result, name)
        if section.score > section.max_score:
            raise AnalysisValidationError(
                f"{name}.score ({section.score}) > max_score ({section.max_score}) — reject, nie clamp"
            )
        if section.score < 0:
            raise AnalysisValidationError(f"{name}.score ({section.score}) jest ujemny")

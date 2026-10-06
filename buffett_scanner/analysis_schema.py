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
4. BUGFIX V0 OUTPUT CONTRACT (Faza 6f, 2026-10-06 — realny live run
   `live-scan-2026-10-06T083825543395Z`): `output_format` gwarantuje
   tylko KSZTAŁT pól anti-confirmation-bias, nie ich TREŚĆ — model mógł
   (i w praktyce czasem robił) zwrócić pusty `biggest_unknown`/
   `thesis_invalidation` i wciąż przejść walidację strukturalną. Nowa
   `_is_semantically_empty`/sprawdzenie niżej odrzuca taki wynik —
   HEURYSTYKA (blocklist placeholderów + minimalna długość), nie
   prawdziwe NLU — jawnie udokumentowana jako przybliżenie, nigdy
   fałszywa precyzja.

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
    # Stała waga rubryki z sekcji 8 (business_understandability) — NIE
    # coś, co model ma sam wybierać. Literal wymusza tę wartość już na
    # poziomie JSON Schema przekazanego do Claude API (output_format),
    # więc API fizycznie nie pozwoli na inną liczbę — nie tylko
    # sprawdzamy to po fakcie. Potwierdzone empirycznie 2026-09-25
    # (Phase 3 Proof Run): bez tego ograniczenia model sam przyjął
    # skalę 1-10 zamiast właściwej z sekcji 8.
    max_score: Literal[7] = 7
    confidence: Confidence
    reasoning: str = ""


class MoatSection(BaseModel):
    score: int
    max_score: Literal[12] = 12  # stała waga z sekcji 8 — patrz ScoredSection
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
    max_score: Literal[10] = 10  # stała waga z sekcji 8 — patrz ScoredSection
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


class ThesisInvalidationRepair(BaseModel):
    """Faza 6h (TARGETED FIELD REPAIR) — minimalny, dedykowany schemat dla
    jednego, empirycznie potwierdzonego przypadku naprawy: cała reszta
    analizy jest poprawna, zawodzi WYŁĄCZNIE `thesis_invalidation`.
    Celowo NIE jest to `AnalysisOutput` ani jego podzbiór z większą
    liczbą pól — repair call nie ma prawa (i nie ma możliwości w
    schemacie) zwrócić/zmienić żadne inne pole analizy."""

    thesis_invalidation: list[str] = Field(default_factory=list)


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

# BUGFIX V0 OUTPUT CONTRACT (Faza 6f) -- pola, które realny live run
# (live-scan-2026-10-06T083825543395Z) zwrócił semantycznie puste mimo
# poprawnego kształtu JSON: CBOE/DECK/INTU/ACN miały
# `thesis_invalidation=[]` i `biggest_unknown=""`, a walidacja uznawała
# to za COMPLETE. Wymagane: co najmniej jeden semantycznie niepusty
# element w każdym z tych pól listowych.
_REQUIRED_NONEMPTY_LIST_FIELDS = (
    "bull_case",
    "bear_case",
    "why_market_may_be_right",
    "why_this_may_not_be_a_bargain",
    "thesis_invalidation",
)

# Frazy-placeholdery, które same w sobie (po normalizacji) NIE liczą się
# jako konkretna treść -- odrzucane nawet gdy to jedyny element listy.
# Model WOLNO przyznać, że czegoś nie wie (prompt.py go o to prosi) --
# ale musi to zrobić KONKRETNIE (patrz przykład w docs/Faza 6f), nie
# samym "brak"/"N/A".
_PLACEHOLDER_PHRASES = frozenset({
    "", "brak", "n/a", "na", "brak danych", "brak informacji",
    "nie wiadomo", "nieznane", "unknown", "none", "null", "-", "n/d",
    "no data", "not available", "not applicable",
})

# Dolny próg długości dla "konkretnej" treści -- HEURYSTYKA (nie
# analiza NLU), jawnie udokumentowana jako przybliżenie. Wartość
# dobrana tak, by odciąć jednosłowne/formalne zbitki ("brak pewności")
# bez odcinania krótkich, ale realnie konkretnych stwierdzeń.
_MIN_SUBSTANTIVE_LENGTH = 15


def _is_semantically_empty(text: str) -> bool:
    normalized = text.strip().strip(".").lower()
    if normalized in _PLACEHOLDER_PHRASES:
        return True
    return len(normalized) < _MIN_SUBSTANTIVE_LENGTH


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

    # BUGFIX V0 OUTPUT CONTRACT (Faza 6f) -- semantyczna niepustość pól
    # anti-confirmation-bias (patrz docstring modułu, punkt 4).
    for field_name in _REQUIRED_NONEMPTY_LIST_FIELDS:
        values = getattr(result, field_name)
        if not values or all(_is_semantically_empty(v) for v in values):
            raise AnalysisValidationError(
                f"{field_name} jest semantycznie pusty — wymagany co najmniej jeden "
                "konkretny punkt (nie \"\"/null/[]/\"brak\"/\"N/A\")"
            )
    if _is_semantically_empty(result.biggest_unknown):
        raise AnalysisValidationError(
            "biggest_unknown jest semantycznie pusty — wymagany konkretny, materialny "
            "unknown (nie \"\"/\"brak\"/\"N/A\")"
        )


def is_only_thesis_invalidation_semantically_empty(result: AnalysisOutput) -> bool:
    """Faza 6h (TARGETED FIELD REPAIR) -- True wyłącznie gdy JEDYNYM
    naruszeniem semantic completeness w `result` jest `thesis_invalidation`
    (wszystkie pozostałe wymagane pola -- bull_case/bear_case/
    why_market_may_be_right/why_this_may_not_be_a_bargain/biggest_unknown
    -- są semantycznie niepuste). Sprawdza WSZYSTKIE pola niezależnie
    (nie zatrzymuje się na pierwszym naruszeniu, w przeciwieństwie do
    `validate_analysis_output`), żeby targeted repair nigdy nie był
    próbowany, gdy zawodzi więcej niż jedno pole (specyfikacja
    właścicielki, punkt 2: "jeżeli brakuje/inwalidne jest [inne pole]
    ... zachowaj bezpieczny FAILED"). Nie sprawdza reguł strukturalnych
    (cited_source_ids/page/score) -- te mają zawsze iść prosto do
    FAILED, obsługiwane osobno przez wywołującego."""
    other_fields = [name for name in _REQUIRED_NONEMPTY_LIST_FIELDS if name != "thesis_invalidation"]
    for field_name in other_fields:
        values = getattr(result, field_name)
        if not values or all(_is_semantically_empty(v) for v in values):
            return False
    if _is_semantically_empty(result.biggest_unknown):
        return False
    values = result.thesis_invalidation
    return not values or all(_is_semantically_empty(v) for v in values)

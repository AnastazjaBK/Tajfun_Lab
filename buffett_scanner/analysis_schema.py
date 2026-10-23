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

from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

from pydantic import BaseModel, Field, create_model

Confidence = Literal["HIGH", "MEDIUM", "LOW"]


class AnalysisValidationError(RuntimeError):
    """`violations` -- WSZYSTKIE naruszenia (nie tylko pierwsze),
    diagnostyka 2026-10-23: raportowanie tylko pierwszego ukryło, że
    w 22/24 analizach puste było też `biggest_unknown`."""

    def __init__(self, message: str, violations: list["Violation"] | None = None):
        super().__init__(message)
        self.violations = list(violations or [])


@dataclass(frozen=True)
class Violation:
    """Jedno naruszenie walidacji. `field` != None -- semantycznie puste
    pole treści, które wolno uzupełnić naprawą; `field` None -- błąd
    strukturalny (cytowania, zakres punktów), zawsze odrzucenie."""

    message: str
    field: str | None = None

    @property
    def repairable(self) -> bool:
        return self.field is not None


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


class AnalysisOutput(BaseModel):
    ticker: str
    schema_version: str
    business_understandability: ScoredSection
    moat: MoatSection
    financial_quality_commentary: FinancialQualityCommentary
    management_capital_allocation: ManagementSection
    fear_analysis: FearAnalysis
    dividend_trap_alert: DividendTrapAlert
    # 2026-10-23: sześć pól anti-confirmation-bias jest OBOWIĄZKOWYCH w
    # schemacie JSON (bez wartości domyślnych). Wcześniej domyślne ""/[]
    # robiły z nich pola opcjonalne -- model mógł je pominąć, a pydantic
    # po cichu wstawiał puste wartości (run live-scan-2026-10-22: 22/24
    # odrzuconych analiz). Obecność pola nie wystarcza -- treść nadal
    # sprawdza walidacja semantyczna niżej.
    bull_case: list[str]
    bear_case: list[str]
    why_market_may_be_right: list[str]
    biggest_unknown: str
    thesis_invalidation: list[str]
    why_this_may_not_be_a_bargain: list[str]
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


def collect_validation_violations(
    result: AnalysisOutput,
    *,
    allowed_source_ids: set[str],
    pdf_paginated_source_ids: set[str],
) -> list[Violation]:
    """WSZYSTKIE naruszenia reguł sekcji 8 (pusta lista = rekord poprawny),
    w kolejności: strukturalne, potem semantycznie puste pola treści."""
    violations: list[Violation] = []
    cited = set(result.cited_source_ids)
    unknown_cited = cited - allowed_source_ids
    if unknown_cited:
        violations.append(Violation(
            f"cited_source_ids zawiera id spoza dostarczonej listy: {sorted(unknown_cited)}"
        ))

    for item in result.verification_items:
        if item.source_id not in allowed_source_ids:
            violations.append(Violation(
                f"verification_items zawiera source_id spoza dostarczonej listy: {item.source_id}"
            ))
        if item.page is not None and item.source_id not in pdf_paginated_source_ids:
            violations.append(Violation(
                f"page={item.page} podane dla source_id={item.source_id}, które nie jest "
                "PDF z potwierdzoną paginacją (BLOCKER 4)"
            ))

    for flag in result.hard_flag_candidates:
        if flag.evidence_source_id not in allowed_source_ids:
            violations.append(Violation(
                "hard_flag_candidates zawiera evidence_source_id spoza dostarczonej listy: "
                f"{flag.evidence_source_id}"
            ))

    for name in _SCORED_SECTIONS:
        section = getattr(result, name)
        if section.score > section.max_score:
            violations.append(Violation(
                f"{name}.score ({section.score}) > max_score ({section.max_score}) — reject, nie clamp"
            ))
        if section.score < 0:
            violations.append(Violation(f"{name}.score ({section.score}) jest ujemny"))

    # BUGFIX V0 OUTPUT CONTRACT (Faza 6f) -- semantyczna niepustość pól
    # anti-confirmation-bias (patrz docstring modułu, punkt 4).
    for field_name in _REQUIRED_NONEMPTY_LIST_FIELDS:
        values = getattr(result, field_name)
        if not values or all(_is_semantically_empty(v) for v in values):
            violations.append(Violation(
                f"{field_name} jest semantycznie pusty — wymagany co najmniej jeden "
                "konkretny punkt (nie \"\"/null/[]/\"brak\"/\"N/A\")",
                field=field_name,
            ))
    if _is_semantically_empty(result.biggest_unknown):
        violations.append(Violation(
            "biggest_unknown jest semantycznie pusty — wymagany konkretny, materialny "
            "unknown (nie \"\"/\"brak\"/\"N/A\")",
            field="biggest_unknown",
        ))
    return violations


def validate_analysis_output(
    result: AnalysisOutput,
    *,
    allowed_source_ids: set[str],
    pdf_paginated_source_ids: set[str],
) -> None:
    """Rzuca `AnalysisValidationError` z WSZYSTKIMI naruszeniami reguł
    sekcji 8 (`.violations`). Brak wyjątku oznacza rekord poprawny."""
    violations = collect_validation_violations(
        result, allowed_source_ids=allowed_source_ids, pdf_paginated_source_ids=pdf_paginated_source_ids,
    )
    if violations:
        raise AnalysisValidationError(" | ".join(v.message for v in violations), violations)


# Pola, które naprawa uzupełnia osobnym, minimalnym wywołaniem (typy jak
# w `AnalysisOutput`).
REPAIRABLE_FIELDS: dict[str, type] = {
    "bull_case": list[str],
    "bear_case": list[str],
    "why_market_may_be_right": list[str],
    "why_this_may_not_be_a_bargain": list[str],
    "thesis_invalidation": list[str],
    "biggest_unknown": str,
}


def repairable_fields(violations: list[Violation]) -> list[str] | None:
    """Pola do uzupełnienia naprawą -- albo None, gdy którekolwiek
    naruszenie jest strukturalne (takiej analizy nie naprawiamy)."""
    if not violations or any(not v.repairable for v in violations):
        return None
    return [name for name in REPAIRABLE_FIELDS if any(v.field == name for v in violations)]


@lru_cache(maxsize=None)
def repair_model(fields: tuple[str, ...]) -> type[BaseModel]:
    """Schemat odpowiedzi naprawy: WYŁĄCZNIE podane pola, wszystkie
    obowiązkowe -- naprawa nie ma możliwości zwrócić ani zmienić żadnej
    innej części analizy (poprawne pola nie są generowane ponownie)."""
    return create_model(
        "AnalysisFieldsRepair_" + "_".join(fields),
        **{name: (REPAIRABLE_FIELDS[name], ...) for name in fields},
    )

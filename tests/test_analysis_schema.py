"""Testy structured LLM output schema (sekcja 8 design review)."""

from __future__ import annotations

import pytest

from buffett_scanner.analysis_schema import (
    AnalysisOutput,
    AnalysisValidationError,
    ThesisInvalidationRepair,
    is_only_thesis_invalidation_semantically_empty,
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
        "bull_case": ["Silny moat oparty na efektach sieciowych i wysokich kosztach zmiany dostawcy."],
        "bear_case": ["Rosnąca konkurencja regulacyjna może ograniczyć marże w kluczowym segmencie."],
        "why_market_may_be_right": ["Spadek może odzwierciedlać trwałe spowolnienie wzrostu przychodów."],
        "why_this_may_not_be_a_bargain": ["Obecna wycena może już uwzględniać ryzyko regulacyjne."],
        "thesis_invalidation": ["Utrata kluczowego klienta odpowiadającego za >10% przychodów."],
        "biggest_unknown": "Nie wiadomo, czy spadek marży w ostatnim kwartale jest trwały czy cykliczny.",
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


def test_max_score_is_fixed_by_schema_not_chosen_by_model():
    """Potwierdzone empirycznie 2026-09-25 (Phase 3 Proof Run): bez tego
    ograniczenia model sam przyjął skalę 1-10 zamiast stałych wag z
    sekcji 8 (7/12/10). Literal w schemacie wymusza to już na poziomie
    JSON Schema przekazanego do Claude API — nieprawidłowa wartość
    max_score nie przechodzi nawet walidacji pydantic."""
    result = make_valid_output()
    assert result.business_understandability.max_score == 7
    assert result.moat.max_score == 12
    assert result.management_capital_allocation.max_score == 10

    with pytest.raises(Exception):  # pydantic.ValidationError
        AnalysisOutput.model_validate(
            {
                **make_valid_output().model_dump(),
                "business_understandability": {"score": 9, "max_score": 10, "confidence": "HIGH"},
            }
        )


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


# ---------------------------------------------------------------------------
# BUGFIX V0 OUTPUT CONTRACT (Faza 6f, 2026-10-06) -- semantyczna
# niepustość pól anti-confirmation-bias. Realny live run
# (live-scan-2026-10-06T083825543395Z) zwrócił `thesis_invalidation=[]`
# i `biggest_unknown=""` dla CBOE/DECK/INTU/ACN, a dotychczasowa
# walidacja (tylko kształt JSON) to przepuszczała jako COMPLETE.
# ---------------------------------------------------------------------------


def test_validate_rejects_empty_biggest_unknown():
    result = make_valid_output(biggest_unknown="")
    with pytest.raises(AnalysisValidationError, match="biggest_unknown"):
        validate_analysis_output(
            result, allowed_source_ids={"src-1"}, pdf_paginated_source_ids=set(),
        )


@pytest.mark.parametrize("placeholder", ["brak", "N/A", "n/a", "Brak danych", "-", "unknown"])
def test_validate_rejects_placeholder_biggest_unknown(placeholder):
    result = make_valid_output(biggest_unknown=placeholder)
    with pytest.raises(AnalysisValidationError, match="biggest_unknown"):
        validate_analysis_output(
            result, allowed_source_ids={"src-1"}, pdf_paginated_source_ids=set(),
        )


def test_validate_rejects_empty_thesis_invalidation():
    result = make_valid_output(thesis_invalidation=[])
    with pytest.raises(AnalysisValidationError, match="thesis_invalidation"):
        validate_analysis_output(
            result, allowed_source_ids={"src-1"}, pdf_paginated_source_ids=set(),
        )


def test_validate_rejects_thesis_invalidation_with_only_placeholder():
    result = make_valid_output(thesis_invalidation=["brak"])
    with pytest.raises(AnalysisValidationError, match="thesis_invalidation"):
        validate_analysis_output(
            result, allowed_source_ids={"src-1"}, pdf_paginated_source_ids=set(),
        )


@pytest.mark.parametrize(
    "field_name", ["bull_case", "bear_case", "why_market_may_be_right", "why_this_may_not_be_a_bargain"]
)
@pytest.mark.parametrize("empty_value", [[], [""], ["brak"], ["N/A"], ["null"]])
def test_validate_rejects_semantically_empty_required_list_fields(field_name, empty_value):
    """Pokrywa "", null, [], 'brak', 'N/A' dla każdego z czterech
    pozostałych wymaganych pól listowych (bez thesis_invalidation,
    pokrytego osobno powyżej z realnym przykładem z live runu)."""
    result = make_valid_output(**{field_name: empty_value})
    with pytest.raises(AnalysisValidationError, match=field_name):
        validate_analysis_output(
            result, allowed_source_ids={"src-1"}, pdf_paginated_source_ids=set(),
        )


def test_validate_accepts_concrete_honest_unknown_statement():
    """Model MOŻE uczciwie przyznać niewiedzę (prompt.py go o to prosi)
    -- ale konkretnie, nie samym 'brak'/'N/A' (patrz przykład właścicielki)."""
    result = make_valid_output(
        biggest_unknown=(
            "Nie wiadomo, jaka część wzrostu przychodów pochodzi z podwyżek cen a jaka "
            "z wolumenu, i bez tego nie można ocenić trwałości marży."
        ),
    )
    validate_analysis_output(
        result, allowed_source_ids={"src-1"}, pdf_paginated_source_ids=set(),
    )  # nie rzuca


# ---------------------------------------------------------------------------
# TARGETED FIELD REPAIR (Faza 6h, 2026-10-06) -- `is_only_thesis_invalidation_
# semantically_empty` decyduje, czy targeted repair jest WOGÓLE zasadny.
# Specyfikacja właścicielki, punkt 2: "jeżeli brakuje/inwalidne jest [inne
# pole] ... zachowaj bezpieczny FAILED" -- repair NIGDY nie jest próbowany,
# gdy zawodzi więcej niż jedno pole.
# ---------------------------------------------------------------------------


def test_is_only_thesis_invalidation_semantically_empty_true_when_isolated():
    """Test B (specyfikacja właścicielki): wszystkie pozostałe wymagane
    pola są semantycznie niepuste, zawodzi WYŁĄCZNIE thesis_invalidation
    -- jak CBOE/DECK/INTU/ACN w realnym live runie."""
    result = make_valid_output(thesis_invalidation=[])
    assert is_only_thesis_invalidation_semantically_empty(result) is True


def test_is_only_thesis_invalidation_semantically_empty_false_when_already_valid():
    result = make_valid_output()
    assert is_only_thesis_invalidation_semantically_empty(result) is False


@pytest.mark.parametrize(
    "field_name", ["bull_case", "bear_case", "why_market_may_be_right", "why_this_may_not_be_a_bargain"]
)
def test_is_only_thesis_invalidation_semantically_empty_false_when_other_list_field_also_empty(field_name):
    """Test D (specyfikacja właścicielki): thesis_invalidation ORAZ inne
    wymagane pole są puste -> NIE jest to "wyłącznie thesis_invalidation",
    więc targeted repair nie może być próbowany (musi iść do FAILED)."""
    result = make_valid_output(thesis_invalidation=[], **{field_name: []})
    assert is_only_thesis_invalidation_semantically_empty(result) is False


def test_is_only_thesis_invalidation_semantically_empty_false_when_biggest_unknown_also_empty():
    result = make_valid_output(thesis_invalidation=[], biggest_unknown="")
    assert is_only_thesis_invalidation_semantically_empty(result) is False


def test_is_only_thesis_invalidation_semantically_empty_true_for_placeholder_only():
    result = make_valid_output(thesis_invalidation=["brak"])
    assert is_only_thesis_invalidation_semantically_empty(result) is True


def test_thesis_invalidation_repair_model_accepts_minimal_list_payload():
    """`ThesisInvalidationRepair` (Faza 6h) -- WYŁĄCZNIE jedno pole, bez
    verification_items/cited_source_ids/innych pól AnalysisOutput."""
    repaired = ThesisInvalidationRepair.model_validate(
        {"thesis_invalidation": ["Utrata kluczowego klienta odpowiadającego za istotną część przychodów."]}
    )
    assert repaired.thesis_invalidation == [
        "Utrata kluczowego klienta odpowiadającego za istotną część przychodów.",
    ]
    assert not hasattr(repaired, "bull_case")


def test_validate_accepts_payx_like_response():
    """Odpowiedź podobna do PAYX z realnego live runu (jedyny shortlist
    candidate, który poprawnie wygenerował oba pola) musi przejść."""
    result = make_valid_output(
        thesis_invalidation=[
            "Trwały spadek retention rate klientów PEO poniżej historycznego poziomu "
            "wskazywałby na erozję przewagi konkurencyjnej.",
        ],
        biggest_unknown=(
            "Nie wiadomo, jaki wpływ na przyszłe przychody będzie miała konkurencja "
            "cenowa w segmencie HR tech."
        ),
    )
    validate_analysis_output(
        result, allowed_source_ids={"src-1"}, pdf_paginated_source_ids=set(),
    )  # nie rzuca

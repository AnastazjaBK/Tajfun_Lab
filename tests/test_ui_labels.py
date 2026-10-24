"""Testy tłumaczenia etykiet UI (Faza 7). Pilnuje głównie: status
FAILED nigdy nie wygląda jak ocena spółki, nieznana wartość nie
wywala wyjątku (fallback na surowy string, nigdy crash UI)."""

from __future__ import annotations

from buffett_scanner.ui.labels import (
    GLOSSARY,
    acquisition_types_label,
    analysis_status_label,
    broker_label,
    decision_status_label,
    decline_flags_label,
    holding_action_label,
)


def test_failed_status_translated_to_report_incompleteness_not_company_judgement():
    label = analysis_status_label("FAILED")
    assert "niekompletna" in label.lower()
    assert "zła" not in label.lower()
    assert "bad" not in label.lower()


def test_unknown_status_falls_back_to_raw_string_not_crash():
    assert analysis_status_label("SOME_NEW_STATUS") == "SOME_NEW_STATUS"


def test_decline_flags_label_translates_known_flags_and_handles_empty():
    assert decline_flags_label([]) == "—"
    label = decline_flags_label(["daily_decline", "abnormal_volume"])
    assert "spadek dzienny" in label
    assert "nietypowy wolumen obrotu" in label


def test_decline_flags_label_falls_back_for_unknown_flag():
    assert decline_flags_label(["some_new_flag"]) == "some_new_flag"


def test_decision_status_label_matches_four_ui_buttons():
    assert decision_status_label("REJECT") == "Odrzucam"
    assert decision_status_label("WATCH") == "Obserwuję"
    assert decision_status_label("SNOOZE") == "Sprawdzam"
    assert decision_status_label("BOUGHT") == "Kupiłam/Kupiłem"


def test_holding_action_label_matches_existing_enum():
    assert holding_action_label("HOLD") == "Trzymam"
    assert holding_action_label("REVIEW_LATER") == "Do przeglądu"


def test_broker_label_known_and_unknown():
    assert broker_label("TRADE_REPUBLIC") == "Trade Republic"
    assert broker_label("OTHER") == "Inny"
    assert broker_label("XTB") == "XTB"


def test_acquisition_types_label_joins_mixed_and_handles_empty():
    assert acquisition_types_label(()) == "—"
    assert acquisition_types_label(("BUY",)) == "Zakup"
    assert acquisition_types_label(("BONUS", "BUY")) == "Bonus + Zakup"


def test_glossary_covers_all_terms_from_spec_section_17():
    """Sekcja 17 specyfikacji UI wylicza 10 konkretnych pojęć -- ten
    test pilnuje, żeby żadne nie zniknęło przy przyszłej edycji."""
    required_substrings = [
        "DCF", "Margines bezpieczeństwa", "Bear/Base/Bull", "FCF",
        "Dług netto", "Hard gate", "Bull Case", "Bear Case",
        "Thesis Invalidation", "Biggest Unknown",
    ]
    terms = " | ".join(term for term, _ in GLOSSARY)
    for substring in required_substrings:
        assert substring in terms, f"Brak pojęcia '{substring}' w GLOSSARY"


def test_glossary_entries_are_nonempty_term_and_explanation_pairs():
    assert len(GLOSSARY) == 10
    for term, explanation in GLOSSARY:
        assert term.strip()
        assert explanation.strip()
        assert len(explanation) > 20  # nie goła etykieta bez wyjaśnienia


# --- 2026-10-23: status skanu i wyniki częściowe -----------------------

from buffett_scanner.config import load_config  # noqa: E402
from buffett_scanner.ui.labels import (  # noqa: E402
    deterministic_points_label,
    missing_components_label,
    run_status_banner,
)

_WEIGHTS = load_config().scoring.weights.model_dump()


def test_run_status_banner_complete_shows_date_and_counts():
    ok, text = run_status_banner("COMPLETE", "2026-10-06", 5, 5)
    assert ok is True
    assert "COMPLETE" in text and "2026-10-06" in text and "5/5" in text
    assert "nie jest gotowy ranking" not in text


def test_run_status_banner_incomplete_warns_not_investment_ranking():
    """Przypadek skanu 22.10: 2 z 24 analiz ukończone."""
    ok, text = run_status_banner("INCOMPLETE_LLM_ANALYSIS", "2026-10-22", 2, 24)
    assert ok is False
    assert "INCOMPLETE" in text and "2026-10-22" in text and "2/24" in text
    assert "nie jest gotowy ranking inwestycyjny" in text


def test_run_status_banner_unknown_status_is_never_treated_as_complete():
    for status in ("RANKED", "SOMETHING_NEW"):
        ok, text = run_status_banner(status, "2026-10-22", 0, 20)
        assert ok is False
        assert "INCOMPLETE" in text


def test_partial_score_45_of_45_never_reads_as_100():
    label = deterministic_points_label(45.0, ["safety", "valuation", "dividend"], _WEIGHTS)
    assert label == "45.0 / 45 pkt (z 100)"
    assert "100%" not in label and "100 / 100" not in label


def test_partial_score_25_of_25_when_valuation_missing():
    assert deterministic_points_label(25.0, ["safety", "dividend"], _WEIGHTS) == "25.0 / 25 pkt (z 100)"


def test_missing_components_label_lists_components_with_their_weights():
    label = missing_components_label(["business_quality", "fear", "valuation"], _WEIGHTS)
    assert label == "jakość biznesu (45), strach/okazja (10), wycena (20)"
    assert missing_components_label([], _WEIGHTS) == "—"
    assert missing_components_label(["new_component"], _WEIGHTS) == "new_component"


def test_no_dcf_marking_never_reads_as_confirmed_undervaluation():
    from buffett_scanner.ui.labels import NO_DCF_NOTE, has_no_dcf

    assert has_no_dcf(["business_quality", "fear", "valuation"])
    assert not has_no_dcf(["business_quality", "fear"])
    assert "nie potwierdza niedowartościowania" in NO_DCF_NOTE

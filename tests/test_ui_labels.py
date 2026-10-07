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

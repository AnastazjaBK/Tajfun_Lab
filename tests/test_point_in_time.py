"""Testy prototypu warstwy point-in-time (Faza 5, punkt 5.1, OPEN
BLOCKER 1) — wartości referencyjne policzone/wybrane ręcznie."""

from __future__ import annotations

from buffett_scanner.point_in_time import (
    PitFact,
    extract_fact_history,
    find_first_matching_tag,
    value_as_of,
)


def make_company_facts(tag_entries: dict[str, list[dict]]) -> dict:
    """tag_entries: {tag_name: [entry, ...]}. Buduje minimalny szkielet
    company-facts JSON identyczny w kształcie z prawdziwym SEC EDGAR."""
    return {
        "cik": 320193,
        "entityName": "Apple Inc.",
        "facts": {
            "us-gaap": {
                tag: {"label": tag, "units": {"USD": entries}}
                for tag, entries in tag_entries.items()
            }
        },
    }


# ---------------------------------------------------------------------------
# extract_fact_history
# ---------------------------------------------------------------------------

def test_extract_fact_history_parses_and_sorts_by_filed():
    facts = make_company_facts({
        "NetIncomeLoss": [
            {"end": "2024-12-31", "val": 100.0, "filed": "2025-02-01", "fy": 2024, "fp": "FY",
             "form": "10-K", "accn": "0001-24-000001"},
            {"end": "2023-12-31", "val": 90.0, "filed": "2024-02-01", "fy": 2023, "fp": "FY",
             "form": "10-K", "accn": "0001-23-000001"},
        ],
    })
    history = extract_fact_history(facts, "NetIncomeLoss")
    assert len(history) == 2
    # posortowane rosnąco po filed -> starsze najpierw
    assert history[0].filed == "2024-02-01"
    assert history[0].val == 90.0
    assert history[1].filed == "2025-02-01"
    assert history[1].val == 100.0
    assert history[1].form == "10-K"
    assert history[1].accession_number == "0001-24-000001"


def test_extract_fact_history_missing_tag_returns_empty_list_not_error():
    facts = make_company_facts({"NetIncomeLoss": [{"end": "2024-12-31", "val": 1.0, "filed": "2025-01-01"}]})
    assert extract_fact_history(facts, "SomeNonExistentTag") == []


def test_extract_fact_history_skips_entries_missing_required_fields():
    facts = make_company_facts({
        "NetIncomeLoss": [
            {"end": "2024-12-31", "val": 100.0, "filed": "2025-02-01"},
            {"end": "2023-12-31", "val": 90.0},  # brak "filed" -> pomijany
            {"filed": "2022-02-01", "val": 80.0},  # brak "end" -> pomijany
        ],
    })
    history = extract_fact_history(facts, "NetIncomeLoss")
    assert len(history) == 1
    assert history[0].val == 100.0


def test_extract_fact_history_missing_unit_returns_empty_list():
    facts = {"facts": {"us-gaap": {"NetIncomeLoss": {"units": {"EUR": []}}}}}
    assert extract_fact_history(facts, "NetIncomeLoss", unit="USD") == []


# ---------------------------------------------------------------------------
# find_first_matching_tag
# ---------------------------------------------------------------------------

def test_find_first_matching_tag_returns_first_populated_candidate():
    facts = make_company_facts({
        "Revenues": [{"end": "2024-12-31", "val": 1000.0, "filed": "2025-02-01"}],
    })
    result = find_first_matching_tag(facts, "revenue")
    assert result is not None
    tag, history = result
    assert tag == "Revenues"
    assert len(history) == 1


def test_find_first_matching_tag_skips_empty_candidates_in_order():
    """RevenueFromContractWithCustomerExcludingAssessedTax jest pierwszym
    kandydatem (patrz CANDIDATE_TAGS), ale spółka go nie ma — powinien
    spaść do kolejnego kandydata (Revenues)."""
    facts = make_company_facts({
        "Revenues": [{"end": "2024-12-31", "val": 1000.0, "filed": "2025-02-01"}],
    })
    tag, _ = find_first_matching_tag(facts, "revenue")
    assert tag == "Revenues"


def test_find_first_matching_tag_none_when_no_candidate_matches():
    facts = make_company_facts({})
    assert find_first_matching_tag(facts, "revenue") is None


def test_find_first_matching_tag_unknown_concept_returns_none():
    facts = make_company_facts({"NetIncomeLoss": [{"end": "x", "val": 1.0, "filed": "2020-01-01"}]})
    assert find_first_matching_tag(facts, "not_a_real_concept") is None


# ---------------------------------------------------------------------------
# value_as_of — rdzeń PIT, w tym scenariusz restatement (look-ahead bias)
# ---------------------------------------------------------------------------

def _fact(val: float, filed: str) -> PitFact:
    return PitFact(end="2024-12-31", val=val, filed=filed, fiscal_year=None,
                    fiscal_period=None, form=None, accession_number=None)


def test_value_as_of_returns_latest_filed_on_or_before_date():
    history = [_fact(90.0, "2024-02-01"), _fact(100.0, "2025-02-01")]
    result = value_as_of(history, "2025-06-01")
    assert result.val == 100.0


def test_value_as_of_exact_filed_date_is_inclusive():
    history = [_fact(100.0, "2025-02-01")]
    result = value_as_of(history, "2025-02-01")
    assert result is not None
    assert result.val == 100.0


def test_value_as_of_none_when_nothing_filed_yet():
    history = [_fact(100.0, "2025-02-01")]
    result = value_as_of(history, "2024-01-01")
    assert result is None


def test_value_as_of_restatement_scenario_avoids_look_ahead_bias():
    """Rdzeń uzasadnienia PIT (sekcja 13): spółka pierwotnie zgłasza
    100 (filed 2020-02-01), potem koryguje do 105 (filed 2021-03-01) w
    tym samym okresie sprawozdawczym (end=2019-12-31). Backtest
    symulujący decyzję na 2020-06-01 MUSI zobaczyć oryginalne 100, nie
    późniejsze 105 — inaczej to look-ahead bias (wiedza z przyszłości
    wykorzystana do symulowania decyzji z przeszłości)."""
    history = [
        PitFact(end="2019-12-31", val=100.0, filed="2020-02-01", fiscal_year=2019,
                 fiscal_period="FY", form="10-K", accession_number="orig"),
        PitFact(end="2019-12-31", val=105.0, filed="2021-03-01", fiscal_year=2019,
                 fiscal_period="FY", form="10-K/A", accession_number="restated"),
    ]

    # Decyzja symulowana PRZED restatement -> musi widzieć oryginalną wartość
    before_restatement = value_as_of(history, "2020-06-01")
    assert before_restatement.val == 100.0
    assert before_restatement.accession_number == "orig"

    # Decyzja symulowana PO restatement -> widzi już skorygowaną wartość
    after_restatement = value_as_of(history, "2021-06-01")
    assert after_restatement.val == 105.0
    assert after_restatement.accession_number == "restated"

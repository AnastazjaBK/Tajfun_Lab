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


def test_extract_fact_history_parses_start_when_present():
    """Faza 5.3 (2026-10-01): pole `start` dodane po realnym znalezisku
    (pole `fp` SEC NIE jest wiarygodnym wskaźnikiem czasu trwania —
    patrz pit_fundamentals.py). Realny wpis AAPL miał dokładnie ten
    kształt: fp='FY', ale start/end rozstawione o 90 dni."""
    facts = make_company_facts({
        "NetIncomeLoss": [
            {"start": "2014-12-28", "end": "2015-03-28", "val": 13569000000.0,
             "filed": "2015-10-28", "fy": 2015, "fp": "FY", "form": "10-K", "accn": "0001-15-000001"},
        ],
    })
    history = extract_fact_history(facts, "NetIncomeLoss")
    assert history[0].start == "2014-12-28"


def test_extract_fact_history_start_none_when_absent_never_fabricated():
    """Koncept typu "instant" (np. Assets) nie ma `start` w ogóle —
    `None`, nigdy nie zgadywane."""
    facts = make_company_facts({
        "Assets": [{"end": "2024-12-31", "val": 1000.0, "filed": "2025-02-01", "fy": 2024, "fp": "FY"}],
    })
    history = extract_fact_history(facts, "Assets")
    assert history[0].start is None


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


def test_find_first_matching_tag_diluted_shares_resolves_shares_unit_not_usd():
    """REGRESJA (realny błąd znaleziony 2026-10-02, Proof Run na realnych
    AAPL/MSFT/KO): diluted_shares_outstanding wychodziło "ŻADEN_KANDYDAT"
    dla WSZYSTKICH trzech spółek, bo SEC XBRL trzyma liczbę akcji pod
    units["shares"], nie units["USD"] — domyślne globalne unit="USD"
    nigdy by tego nie znalazło, niezależnie od spółki. Fakt pod
    units["USD"] dla tego samego tagu MUSI być zignorowany (to nie byłaby
    ta sama wielkość, nawet gdyby liczbowo pasowała)."""
    facts = {
        "facts": {"us-gaap": {
            "WeightedAverageNumberOfDilutedSharesOutstanding": {
                "units": {
                    "shares": [{"start": "2023-01-01", "end": "2023-12-31", "val": 1_000_000.0, "filed": "2024-02-01"}],
                    "USD": [{"start": "2023-01-01", "end": "2023-12-31", "val": 999.0, "filed": "2024-02-01"}],
                }
            },
        }},
    }
    result = find_first_matching_tag(facts, "diluted_shares_outstanding")
    assert result is not None
    tag, history = result
    assert tag == "WeightedAverageNumberOfDilutedSharesOutstanding"
    assert len(history) == 1
    assert history[0].val == 1_000_000.0


def test_find_first_matching_tag_explicit_unit_overrides_concept_units():
    facts = {
        "facts": {"us-gaap": {
            "WeightedAverageNumberOfDilutedSharesOutstanding": {
                "units": {"USD": [{"end": "2023-12-31", "val": 999.0, "filed": "2024-02-01"}]}
            },
        }},
    }
    result = find_first_matching_tag(facts, "diluted_shares_outstanding", unit="USD")
    assert result is not None
    assert result[0] == "WeightedAverageNumberOfDilutedSharesOutstanding"


def test_find_first_matching_tag_monetary_concepts_still_default_to_usd():
    """Żaden koncept pieniężny (revenue/net_income/...) nie jest w
    CONCEPT_UNITS -> musi nadal domyślnie trafiać do units["USD"],
    zero regresji dla istniejącego zachowania."""
    facts = make_company_facts({
        "Revenues": [{"end": "2024-12-31", "val": 1000.0, "filed": "2025-02-01"}],
    })
    result = find_first_matching_tag(facts, "revenue")
    assert result is not None


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


def test_value_as_of_breaks_filed_tie_by_latest_end_not_json_order():
    """Regresja ze znaleziska z realnego uruchomienia „Phase 5.1 Proof
    Run" (2026-09-25, MSFT/AAPL/KO): jeden 10-K/10-Q zawsze zawiera też
    dane porównawcze z 1-2 poprzednich okresów, złożone tego samego dnia
    co bieżący okres -> wiele faktów z IDENTYCZNYM `filed`, różnym `end`.
    Bez rozstrzygania remisu na korzyść najnowszego `end`, `max()` po
    samym `filed` zwracał pierwszy napotkany w kolejności z SEC JSON
    (najstarszy porównawczy okres), nie bieżący -> `end` nawet 2 lata
    starszy niż `filed`, ewidentna anomalia (10-K/10-Q musi iść do SEC
    w ciągu maksymalnie ~60-90 dni od `end`, nie lat)."""
    history = [
        # Kolejność jak w prawdziwym JSON SEC: starsze porównawcze lata
        # najpierw, mimo tej samej daty `filed` co bieżący rok.
        PitFact(end="2024-06-30", val=88_136_000_000.0, filed="2026-07-29",
                 fiscal_year=2024, fiscal_period="FY", form="10-K", accession_number="fy2024-comparative"),
        PitFact(end="2025-06-30", val=101_832_000_000.0, filed="2026-07-29",
                 fiscal_year=2025, fiscal_period="FY", form="10-K", accession_number="fy2025-comparative"),
        PitFact(end="2026-06-30", val=133_749_000_000.0, filed="2026-07-29",
                 fiscal_year=2026, fiscal_period="FY", form="10-K", accession_number="fy2026-current"),
    ]
    result = value_as_of(history, "2026-09-25")
    assert result.end == "2026-06-30"
    assert result.val == 133_749_000_000.0
    assert result.accession_number == "fy2026-current"

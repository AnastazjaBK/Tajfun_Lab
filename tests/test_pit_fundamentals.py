"""Testy budowy FundamentalsPeriod z realnych danych SEC XBRL (Faza 5.3,
walk-forward backtest harness) — wartości referencyjne policzone ręcznie.

Zawiera regresyjny test dla realnie znalezionego błędu (2026-10-01,
realny Proof Run, AAPL): `fp == 'FY'` NIE jest wiarygodnym wskaźnikiem
rzeczywistego czasu trwania faktu — filtr musi liczyć `end - start`.

Rozszerzone (Faza 5.3b, dependency audit 2026-10-01/02): pokrycie
12 pól FundamentalsPeriod, rozróżnienie duration/instant, kompozyt
EBITDA (zasady 1-5 zatwierdzone przez właścicielkę 2026-10-02),
total_debt (Faza 5.3f) jest kompozytem z total_debt.py, zakotwiczonym
do balance-sheet instant KAŻDEGO okresu (`target_end=end`)."""

from __future__ import annotations

from buffett_scanner.pit_fundamentals import build_annual_fundamentals_periods_as_of


def make_company_facts(tag_entries: dict[str, list[dict]]) -> dict:
    """`diluted_shares_outstanding` leży w SEC XBRL pod units["shares"],
    nie units["USD"] (realny błąd znaleziony 2026-10-02, patrz
    point_in_time.CONCEPT_UNITS) — rozpoznawane tu po nazwie tagu, żeby
    testy nie musiały same o tym pamiętać przy każdym wywołaniu."""
    return {
        "cik": 320193, "entityName": "Test Co",
        "facts": {"us-gaap": {
            tag: {
                "label": tag,
                "units": {
                    "shares" if tag == "WeightedAverageNumberOfDilutedSharesOutstanding" else "USD": entries
                },
            }
            for tag, entries in tag_entries.items()
        }},
    }


def test_build_annual_periods_basic_two_years():
    facts = make_company_facts({
        "NetIncomeLoss": [
            {"start": "2023-01-01", "end": "2023-12-31", "val": 90.0, "filed": "2024-02-01", "fy": 2023, "fp": "FY"},
            {"start": "2024-01-01", "end": "2024-12-31", "val": 100.0, "filed": "2025-02-01", "fy": 2024, "fp": "FY"},
        ],
        "RevenueFromContractWithCustomerExcludingAssessedTax": [
            {"start": "2023-01-01", "end": "2023-12-31", "val": 900.0, "filed": "2024-02-01", "fy": 2023, "fp": "FY"},
            {"start": "2024-01-01", "end": "2024-12-31", "val": 1000.0, "filed": "2025-02-01", "fy": 2024, "fp": "FY"},
        ],
    })
    periods = build_annual_fundamentals_periods_as_of(facts, "2025-06-01")
    assert len(periods) == 2
    assert periods[0].period_end_date == "2023-12-31"
    assert periods[0].net_income == 90.0
    assert periods[0].revenue == 900.0
    assert periods[0].filed_date == "2024-02-01"
    assert periods[1].net_income == 100.0
    assert periods[1].revenue == 1000.0


def test_build_annual_periods_excludes_future_filings_no_look_ahead():
    """as_of_date PRZED złożeniem FY2024 -> FY2024 w ogóle się nie
    pojawia (nie częściowo, nie z None -- w ogóle, bo żadne pole nie
    ma jeszcze wartości as-of tej daty)."""
    facts = make_company_facts({
        "NetIncomeLoss": [
            {"start": "2023-01-01", "end": "2023-12-31", "val": 90.0, "filed": "2024-02-01", "fy": 2023, "fp": "FY"},
            {"start": "2024-01-01", "end": "2024-12-31", "val": 100.0, "filed": "2025-02-01", "fy": 2024, "fp": "FY"},
        ],
    })
    periods = build_annual_fundamentals_periods_as_of(facts, "2024-06-01")  # przed 2025-02-01
    assert len(periods) == 1
    assert periods[0].period_end_date == "2023-12-31"


def test_build_annual_periods_excludes_quarterly_duration_even_when_tagged_fp_fy():
    """REGRESJA (realny błąd znaleziony 2026-10-01, AAPL): fakt o
    długości 90 dni (kwartał), mimo `fp='FY'`, MUSI być odrzucony.
    Replika dokładnie realnego wpisu: start='2014-12-28',
    end='2015-03-28', fp='FY' — a to jest Q1 roku fiskalnego, nie
    rok. Drugi fakt w tym teście to PRAWDZIWY roczny (365 dni)."""
    facts = make_company_facts({
        "NetIncomeLoss": [
            # dokladnie realny przypadek z Proof Run -- 90 dni, fp='FY'
            {"start": "2014-12-28", "end": "2015-03-28", "val": 13569000000.0,
             "filed": "2015-10-28", "fy": 2015, "fp": "FY"},
            # prawdziwy roczny okres
            {"start": "2014-09-28", "end": "2015-09-26", "val": 53394000000.0,
             "filed": "2015-10-28", "fy": 2015, "fp": "FY"},
        ],
    })
    periods = build_annual_fundamentals_periods_as_of(facts, "2025-01-01")
    assert len(periods) == 1
    assert periods[0].period_end_date == "2015-09-26"
    assert periods[0].net_income == 53394000000.0


def test_build_annual_periods_excludes_facts_missing_start_never_guesses():
    """Fakt bez `start` (np. skrócony wpis) nie da się zweryfikować jako
    roczny duration-koncept -> odrzucony, nigdy nie zgadujemy."""
    facts = make_company_facts({
        "NetIncomeLoss": [
            {"end": "2023-12-31", "val": 90.0, "filed": "2024-02-01", "fy": 2023, "fp": "FY"},  # brak start
        ],
    })
    periods = build_annual_fundamentals_periods_as_of(facts, "2024-06-01")
    assert periods == []


def test_build_annual_periods_accepts_52_53_week_fiscal_year_apple_style():
    """Apple-style rok fiskalny (52/53 tygodnie) bywa 364 albo 371 dni,
    nie równo 365 -- musi się mieścić w paśmie tolerancji."""
    facts = make_company_facts({
        "NetIncomeLoss": [
            {"start": "2014-09-28", "end": "2015-09-26", "val": 53394000000.0,  # 363 dni
             "filed": "2015-10-28", "fy": 2015, "fp": "FY"},
        ],
    })
    periods = build_annual_fundamentals_periods_as_of(facts, "2025-01-01")
    assert len(periods) == 1


def test_build_annual_periods_uses_restatement_known_before_as_of_date():
    """Restatement (drugi zapis tego samego `end`) złożony on/before
    as_of_date MUSI być użyty zamiast oryginalnej wartości — to zgodne
    z `value_as_of` ("najnowsza ZNANA wartość"), nie "zawsze oryginał"."""
    facts = make_company_facts({
        "NetIncomeLoss": [
            {"start": "2023-01-01", "end": "2023-12-31", "val": 90.0, "filed": "2024-02-01", "fy": 2023, "fp": "FY"},
            {"start": "2023-01-01", "end": "2023-12-31", "val": 95.0, "filed": "2024-11-01", "fy": 2023, "fp": "FY"},  # restatement
        ],
    })
    before_restatement = build_annual_fundamentals_periods_as_of(facts, "2024-06-01")
    assert before_restatement[0].net_income == 90.0

    after_restatement = build_annual_fundamentals_periods_as_of(facts, "2025-01-01")
    assert after_restatement[0].net_income == 95.0
    assert after_restatement[0].filed_date == "2024-11-01"


def test_build_annual_periods_total_debt_none_when_only_one_component_present():
    """total_debt (Faza 5.3f, total_debt.py) jest None, gdy tylko jeden
    z LongTermDebtCurrent/Noncurrent jest obecny i spółka nie kwalifikuje
    się do żadnego fallbacku -- nigdy fabrykowane, nawet gdyby jakiś tag
    przypadkiem pasował."""
    facts = make_company_facts({
        "NetIncomeLoss": [{"start": "2023-01-01", "end": "2023-12-31", "val": 90.0, "filed": "2024-02-01", "fy": 2023, "fp": "FY"}],
        "LongTermDebtNoncurrent": [{"end": "2023-12-31", "val": 500.0, "filed": "2024-02-01", "fy": 2023, "fp": "FY"}],
    })
    periods = build_annual_fundamentals_periods_as_of(facts, "2025-01-01")
    assert periods[0].total_debt is None
    assert periods[0].total_debt_resolution_method == "INSUFFICIENT_DATA"
    assert periods[0].total_debt_confidence_tier is None


def test_build_annual_periods_total_debt_tier1_current_plus_noncurrent_anchored_to_period_end():
    """total_debt MUSI dotyczyć balance-sheet instant TEGO konkretnego
    rocznego okresu (`target_end=end`), nie "najnowszego dostępnego"
    niezależnie od `end` -- ta sama zasada "ten sam instant", która już
    chroni EBITDA. Spółka ma DWA roczne okresy; każdy dostaje total_debt
    WŁASNEGO roku, nie zawsze najnowszego."""
    facts = make_company_facts({
        "NetIncomeLoss": [
            {"start": "2022-01-01", "end": "2022-12-31", "val": 80.0, "filed": "2023-02-01", "fy": 2022, "fp": "FY"},
            {"start": "2023-01-01", "end": "2023-12-31", "val": 90.0, "filed": "2024-02-01", "fy": 2023, "fp": "FY"},
        ],
        "LongTermDebtCurrent": [
            {"end": "2022-12-31", "val": 10.0, "filed": "2023-02-01", "fy": 2022, "fp": "FY"},
            {"end": "2023-12-31", "val": 20.0, "filed": "2024-02-01", "fy": 2023, "fp": "FY"},
        ],
        "LongTermDebtNoncurrent": [
            {"end": "2022-12-31", "val": 400.0, "filed": "2023-02-01", "fy": 2022, "fp": "FY"},
            {"end": "2023-12-31", "val": 500.0, "filed": "2024-02-01", "fy": 2023, "fp": "FY"},
        ],
    })
    periods = build_annual_fundamentals_periods_as_of(facts, "2025-01-01")
    assert periods[0].period_end_date == "2022-12-31"
    assert periods[0].total_debt == 410.0
    assert periods[0].total_debt_resolution_method == "CURRENT_PLUS_NONCURRENT"
    assert periods[0].total_debt_confidence_tier == "TIER_1"
    assert periods[1].period_end_date == "2023-12-31"
    assert periods[1].total_debt == 520.0


def test_build_annual_periods_total_debt_tier2_synonym_when_never_reports_ltd_current():
    """Faza 5.3f, Tier 2 NONCURRENT_PLUS_DEBTCURRENT_SYNONYM -- spółka
    (wzorzec Realty Income-podobny, ale z noncurrent, nie NotesPayable
    jako całość) nigdy nie raportuje LongTermDebtCurrent, tylko
    DebtCurrent dla tego samego instant co LongTermDebtNoncurrent."""
    facts = make_company_facts({
        "NetIncomeLoss": [{"start": "2023-01-01", "end": "2023-12-31", "val": 90.0, "filed": "2024-02-01", "fy": 2023, "fp": "FY"}],
        "LongTermDebtNoncurrent": [{"end": "2023-12-31", "val": 900.0, "filed": "2024-02-01", "fy": 2023, "fp": "FY"}],
        "DebtCurrent": [{"end": "2023-12-31", "val": 100.0, "filed": "2024-02-01", "fy": 2023, "fp": "FY"}],
    })
    periods = build_annual_fundamentals_periods_as_of(facts, "2025-01-01")
    assert periods[0].total_debt == 1000.0
    assert periods[0].total_debt_resolution_method == "NONCURRENT_PLUS_DEBTCURRENT_SYNONYM"
    assert periods[0].total_debt_confidence_tier == "TIER_2"


def test_build_annual_periods_empty_company_facts_returns_empty_list():
    assert build_annual_fundamentals_periods_as_of(make_company_facts({}), "2025-01-01") == []


def test_build_annual_periods_sorted_ascending_by_period_end_date():
    facts = make_company_facts({
        "NetIncomeLoss": [
            {"start": "2024-01-01", "end": "2024-12-31", "val": 100.0, "filed": "2025-02-01", "fy": 2024, "fp": "FY"},
            {"start": "2022-01-01", "end": "2022-12-31", "val": 80.0, "filed": "2023-02-01", "fy": 2022, "fp": "FY"},
            {"start": "2023-01-01", "end": "2023-12-31", "val": 90.0, "filed": "2024-02-01", "fy": 2023, "fp": "FY"},
        ],
    })
    periods = build_annual_fundamentals_periods_as_of(facts, "2025-06-01")
    assert [p.period_end_date for p in periods] == ["2022-12-31", "2023-12-31", "2024-12-31"]


# ---------------------------------------------------------------------------
# Pola "instant" (bilansowe) -- bez `start`, bez walidacji duration.
# ---------------------------------------------------------------------------

def test_build_annual_periods_instant_fields_no_start_no_duration_filter():
    """cash_and_equivalents/total_current_assets/total_current_liabilities
    to koncepty "instant" -- z definicji nie mają `start` w SEC XBRL.
    Walidacja duration (350-380 dni) NIE może być stosowana, inaczej
    każdy taki fakt byłby błędnie odrzucany (brak start -> False)."""
    facts = make_company_facts({
        "NetIncomeLoss": [{"start": "2023-01-01", "end": "2023-12-31", "val": 90.0, "filed": "2024-02-01", "fy": 2023, "fp": "FY"}],
        "CashAndCashEquivalentsAtCarryingValue": [
            {"end": "2023-12-31", "val": 1000.0, "filed": "2024-02-01", "fy": 2023, "fp": "FY"},
        ],
        "AssetsCurrent": [{"end": "2023-12-31", "val": 2000.0, "filed": "2024-02-01", "fy": 2023, "fp": "FY"}],
        "LiabilitiesCurrent": [{"end": "2023-12-31", "val": 800.0, "filed": "2024-02-01", "fy": 2023, "fp": "FY"}],
    })
    periods = build_annual_fundamentals_periods_as_of(facts, "2025-01-01")
    assert periods[0].cash_and_equivalents == 1000.0
    assert periods[0].total_current_assets == 2000.0
    assert periods[0].total_current_liabilities == 800.0


def test_build_annual_periods_instant_field_missing_is_none_never_fabricated():
    facts = make_company_facts({
        "NetIncomeLoss": [{"start": "2023-01-01", "end": "2023-12-31", "val": 90.0, "filed": "2024-02-01", "fy": 2023, "fp": "FY"}],
    })
    periods = build_annual_fundamentals_periods_as_of(facts, "2025-01-01")
    assert periods[0].cash_and_equivalents is None
    assert periods[0].total_current_assets is None
    assert periods[0].total_current_liabilities is None


# ---------------------------------------------------------------------------
# Pola "duration" rozszerzone (OCF, capex, dywidendy, buybacki, DSO).
# ---------------------------------------------------------------------------

def test_build_annual_periods_extended_duration_fields_basic():
    facts = make_company_facts({
        "NetIncomeLoss": [{"start": "2023-01-01", "end": "2023-12-31", "val": 90.0, "filed": "2024-02-01", "fy": 2023, "fp": "FY"}],
        "NetCashProvidedByUsedInOperatingActivities": [
            {"start": "2023-01-01", "end": "2023-12-31", "val": 300.0, "filed": "2024-02-01", "fy": 2023, "fp": "FY"},
        ],
        "PaymentsToAcquirePropertyPlantAndEquipment": [
            {"start": "2023-01-01", "end": "2023-12-31", "val": 50.0, "filed": "2024-02-01", "fy": 2023, "fp": "FY"},
        ],
        "PaymentsOfDividendsCommonStock": [
            {"start": "2023-01-01", "end": "2023-12-31", "val": 20.0, "filed": "2024-02-01", "fy": 2023, "fp": "FY"},
        ],
        "PaymentsForRepurchaseOfCommonStock": [
            {"start": "2023-01-01", "end": "2023-12-31", "val": 15.0, "filed": "2024-02-01", "fy": 2023, "fp": "FY"},
        ],
        "WeightedAverageNumberOfDilutedSharesOutstanding": [
            {"start": "2023-01-01", "end": "2023-12-31", "val": 1_000_000.0, "filed": "2024-02-01", "fy": 2023, "fp": "FY"},
        ],
    })
    periods = build_annual_fundamentals_periods_as_of(facts, "2025-01-01")
    p = periods[0]
    assert p.operating_cash_flow == 300.0
    assert p.capital_expenditure == 50.0
    assert p.dividends_paid == 20.0
    assert p.share_buybacks == 15.0
    assert p.diluted_shares_outstanding == 1_000_000.0


def test_build_annual_periods_extended_duration_field_rejects_quarterly_even_tagged_fy():
    """Ten sam realny błąd (fp='FY' niewiarygodne) MUSI być naprawiony
    konsekwentnie dla WSZYSTKICH pól duration, nie tylko net_income --
    tu: operating_cash_flow, 90-dniowy fakt mimo fp='FY'."""
    facts = make_company_facts({
        "NetIncomeLoss": [{"start": "2023-01-01", "end": "2023-12-31", "val": 90.0, "filed": "2024-02-01", "fy": 2023, "fp": "FY"}],
        "NetCashProvidedByUsedInOperatingActivities": [
            {"start": "2023-10-01", "end": "2023-12-31", "val": 70.0, "filed": "2024-02-01", "fy": 2023, "fp": "FY"},  # 92 dni -- kwartał
        ],
    })
    periods = build_annual_fundamentals_periods_as_of(facts, "2025-01-01")
    assert periods[0].operating_cash_flow is None


# ---------------------------------------------------------------------------
# EBITDA -- kompozyt dwóch faktów (zasady 1-5, zatwierdzone 2026-10-02).
# ---------------------------------------------------------------------------

def test_ebitda_computed_as_sum_of_both_components_same_period():
    facts = make_company_facts({
        "NetIncomeLoss": [{"start": "2023-01-01", "end": "2023-12-31", "val": 90.0, "filed": "2024-02-01", "fy": 2023, "fp": "FY"}],
        "OperatingIncomeLoss": [
            {"start": "2023-01-01", "end": "2023-12-31", "val": 150.0, "filed": "2024-02-01", "fy": 2023, "fp": "FY"},
        ],
        "DepreciationDepletionAndAmortization": [
            {"start": "2023-01-01", "end": "2023-12-31", "val": 40.0, "filed": "2024-02-01", "fy": 2023, "fp": "FY"},
        ],
    })
    periods = build_annual_fundamentals_periods_as_of(facts, "2025-01-01")
    assert periods[0].ebitda == 190.0


def test_ebitda_none_when_depreciation_component_missing_no_substitute():
    """Zasada 4: brak D&A -> ebitda=None. NIGDY OperatingIncomeLoss jako
    substytut EBITDA."""
    facts = make_company_facts({
        "NetIncomeLoss": [{"start": "2023-01-01", "end": "2023-12-31", "val": 90.0, "filed": "2024-02-01", "fy": 2023, "fp": "FY"}],
        "OperatingIncomeLoss": [
            {"start": "2023-01-01", "end": "2023-12-31", "val": 150.0, "filed": "2024-02-01", "fy": 2023, "fp": "FY"},
        ],
    })
    periods = build_annual_fundamentals_periods_as_of(facts, "2025-01-01")
    assert periods[0].ebitda is None


def test_ebitda_none_when_operating_income_component_missing_no_substitute():
    facts = make_company_facts({
        "NetIncomeLoss": [{"start": "2023-01-01", "end": "2023-12-31", "val": 90.0, "filed": "2024-02-01", "fy": 2023, "fp": "FY"}],
        "DepreciationDepletionAndAmortization": [
            {"start": "2023-01-01", "end": "2023-12-31", "val": 40.0, "filed": "2024-02-01", "fy": 2023, "fp": "FY"},
        ],
    })
    periods = build_annual_fundamentals_periods_as_of(facts, "2025-01-01")
    assert periods[0].ebitda is None


def test_ebitda_none_when_components_from_incompatible_periods():
    """Zasada 3: OperatingIncomeLoss dostępny tylko dla FY2022,
    D&A tylko dla FY2023 -> dla ŻADNEGO z tych okresów nie wolno
    złożyć EBITDA (nie łączymy komponentów z różnych lat fiskalnych,
    mimo że oba mogłyby być value_as_of(D)-dostępne)."""
    facts = make_company_facts({
        "NetIncomeLoss": [
            {"start": "2022-01-01", "end": "2022-12-31", "val": 70.0, "filed": "2023-02-01", "fy": 2022, "fp": "FY"},
            {"start": "2023-01-01", "end": "2023-12-31", "val": 90.0, "filed": "2024-02-01", "fy": 2023, "fp": "FY"},
        ],
        "OperatingIncomeLoss": [
            {"start": "2022-01-01", "end": "2022-12-31", "val": 120.0, "filed": "2023-02-01", "fy": 2022, "fp": "FY"},
        ],
        "DepreciationDepletionAndAmortization": [
            {"start": "2023-01-01", "end": "2023-12-31", "val": 40.0, "filed": "2024-02-01", "fy": 2023, "fp": "FY"},
        ],
    })
    periods = build_annual_fundamentals_periods_as_of(facts, "2025-01-01")
    by_end = {p.period_end_date: p for p in periods}
    assert by_end["2022-12-31"].ebitda is None
    assert by_end["2023-12-31"].ebitda is None


def test_ebitda_component_duration_validated_independently_rejects_quarterly():
    """Zasada 2: D&A tagowane fp='FY', ale 90-dniowe -> odrzucone przez
    tę samą walidację duration co net_income/revenue -> ebitda=None
    (nie "połowa roku D&A" jako substytut)."""
    facts = make_company_facts({
        "NetIncomeLoss": [{"start": "2023-01-01", "end": "2023-12-31", "val": 90.0, "filed": "2024-02-01", "fy": 2023, "fp": "FY"}],
        "OperatingIncomeLoss": [
            {"start": "2023-01-01", "end": "2023-12-31", "val": 150.0, "filed": "2024-02-01", "fy": 2023, "fp": "FY"},
        ],
        "DepreciationDepletionAndAmortization": [
            {"start": "2023-10-01", "end": "2023-12-31", "val": 10.0, "filed": "2024-02-01", "fy": 2023, "fp": "FY"},  # 92 dni
        ],
    })
    periods = build_annual_fundamentals_periods_as_of(facts, "2025-01-01")
    assert periods[0].ebitda is None


def test_ebitda_component_respects_point_in_time_no_look_ahead():
    """D&A dla FY2023 złożone PO as_of_date -> niewidoczne jeszcze ->
    ebitda=None dla tej daty (mimo że OperatingIncomeLoss jest znany)."""
    facts = make_company_facts({
        "NetIncomeLoss": [{"start": "2023-01-01", "end": "2023-12-31", "val": 90.0, "filed": "2024-02-01", "fy": 2023, "fp": "FY"}],
        "OperatingIncomeLoss": [
            {"start": "2023-01-01", "end": "2023-12-31", "val": 150.0, "filed": "2024-02-01", "fy": 2023, "fp": "FY"},
        ],
        "DepreciationDepletionAndAmortization": [
            {"start": "2023-01-01", "end": "2023-12-31", "val": 40.0, "filed": "2024-11-01", "fy": 2023, "fp": "FY"},  # późny restatement/filing
        ],
    })
    before = build_annual_fundamentals_periods_as_of(facts, "2024-06-01")
    assert before[0].ebitda is None
    after = build_annual_fundamentals_periods_as_of(facts, "2024-12-01")
    assert after[0].ebitda == 190.0


def test_ebitda_depreciation_candidate_tags_tried_in_order_not_summed():
    """Zasada 5: gdyby (hipotetycznie) spółka miała wpisy pod dwoma
    różnymi kandydackimi tagami D&A, używamy TYLKO pierwszego
    niepustego -- nigdy sumy obu (ryzyko double counting)."""
    facts = make_company_facts({
        "NetIncomeLoss": [{"start": "2023-01-01", "end": "2023-12-31", "val": 90.0, "filed": "2024-02-01", "fy": 2023, "fp": "FY"}],
        "OperatingIncomeLoss": [
            {"start": "2023-01-01", "end": "2023-12-31", "val": 150.0, "filed": "2024-02-01", "fy": 2023, "fp": "FY"},
        ],
        "DepreciationDepletionAndAmortization": [
            {"start": "2023-01-01", "end": "2023-12-31", "val": 40.0, "filed": "2024-02-01", "fy": 2023, "fp": "FY"},
        ],
        "DepreciationAmortizationAndAccretionNet": [
            {"start": "2023-01-01", "end": "2023-12-31", "val": 999.0, "filed": "2024-02-01", "fy": 2023, "fp": "FY"},
        ],
    })
    periods = build_annual_fundamentals_periods_as_of(facts, "2025-01-01")
    assert periods[0].ebitda == 190.0  # 150 + 40, NIE 150 + 40 + 999

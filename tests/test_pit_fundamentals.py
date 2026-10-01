"""Testy budowy FundamentalsPeriod z realnych danych SEC XBRL (Faza 5.3,
walk-forward backtest harness) — wartości referencyjne policzone ręcznie."""

from __future__ import annotations

from buffett_scanner.pit_fundamentals import build_annual_fundamentals_periods_as_of


def make_company_facts(tag_entries: dict[str, list[dict]]) -> dict:
    return {
        "cik": 320193, "entityName": "Test Co",
        "facts": {"us-gaap": {tag: {"label": tag, "units": {"USD": entries}} for tag, entries in tag_entries.items()}},
    }


def test_build_annual_periods_basic_two_years():
    facts = make_company_facts({
        "NetIncomeLoss": [
            {"end": "2023-12-31", "val": 90.0, "filed": "2024-02-01", "fy": 2023, "fp": "FY"},
            {"end": "2024-12-31", "val": 100.0, "filed": "2025-02-01", "fy": 2024, "fp": "FY"},
        ],
        "RevenueFromContractWithCustomerExcludingAssessedTax": [
            {"end": "2023-12-31", "val": 900.0, "filed": "2024-02-01", "fy": 2023, "fp": "FY"},
            {"end": "2024-12-31", "val": 1000.0, "filed": "2025-02-01", "fy": 2024, "fp": "FY"},
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
            {"end": "2023-12-31", "val": 90.0, "filed": "2024-02-01", "fy": 2023, "fp": "FY"},
            {"end": "2024-12-31", "val": 100.0, "filed": "2025-02-01", "fy": 2024, "fp": "FY"},
        ],
    })
    periods = build_annual_fundamentals_periods_as_of(facts, "2024-06-01")  # przed 2025-02-01
    assert len(periods) == 1
    assert periods[0].period_end_date == "2023-12-31"


def test_build_annual_periods_excludes_quarterly_facts():
    """Fakty z fp != 'FY' (kwartalne, potencjalnie YTD-skumulowane) są
    CAŁKOWICIE pomijane — unika niejednoznaczności duration."""
    facts = make_company_facts({
        "NetIncomeLoss": [
            {"end": "2023-12-31", "val": 90.0, "filed": "2024-02-01", "fy": 2023, "fp": "FY"},
            {"end": "2024-03-31", "val": 25.0, "filed": "2024-05-01", "fy": 2024, "fp": "Q1"},
            {"end": "2024-06-30", "val": 55.0, "filed": "2024-08-01", "fy": 2024, "fp": "Q2"},  # mogloby byc YTD
        ],
    })
    periods = build_annual_fundamentals_periods_as_of(facts, "2024-12-01")
    assert len(periods) == 1
    assert periods[0].period_end_date == "2023-12-31"


def test_build_annual_periods_uses_restatement_known_before_as_of_date():
    """Restatement (drugi zapis tego samego `end`) złożony on/before
    as_of_date MUSI być użyty zamiast oryginalnej wartości — to zgodne
    z `value_as_of` ("najnowsza ZNANA wartość"), nie "zawsze oryginał"."""
    facts = make_company_facts({
        "NetIncomeLoss": [
            {"end": "2023-12-31", "val": 90.0, "filed": "2024-02-01", "fy": 2023, "fp": "FY"},
            {"end": "2023-12-31", "val": 95.0, "filed": "2024-11-01", "fy": 2023, "fp": "FY"},  # restatement
        ],
    })
    before_restatement = build_annual_fundamentals_periods_as_of(facts, "2024-06-01")
    assert before_restatement[0].net_income == 90.0

    after_restatement = build_annual_fundamentals_periods_as_of(facts, "2025-01-01")
    assert after_restatement[0].net_income == 95.0
    assert after_restatement[0].filed_date == "2024-11-01"


def test_build_annual_periods_other_fields_always_none_never_fabricated():
    facts = make_company_facts({
        "NetIncomeLoss": [{"end": "2023-12-31", "val": 90.0, "filed": "2024-02-01", "fy": 2023, "fp": "FY"}],
    })
    periods = build_annual_fundamentals_periods_as_of(facts, "2025-01-01")
    p = periods[0]
    assert p.ebitda is None
    assert p.operating_cash_flow is None
    assert p.capital_expenditure is None
    assert p.total_debt is None
    assert p.cash_and_equivalents is None
    assert p.total_current_assets is None
    assert p.total_current_liabilities is None


def test_build_annual_periods_empty_company_facts_returns_empty_list():
    assert build_annual_fundamentals_periods_as_of(make_company_facts({}), "2025-01-01") == []


def test_build_annual_periods_sorted_ascending_by_period_end_date():
    facts = make_company_facts({
        "NetIncomeLoss": [
            {"end": "2024-12-31", "val": 100.0, "filed": "2025-02-01", "fy": 2024, "fp": "FY"},
            {"end": "2022-12-31", "val": 80.0, "filed": "2023-02-01", "fy": 2022, "fp": "FY"},
            {"end": "2023-12-31", "val": 90.0, "filed": "2024-02-01", "fy": 2023, "fp": "FY"},
        ],
    })
    periods = build_annual_fundamentals_periods_as_of(facts, "2025-06-01")
    assert [p.period_end_date for p in periods] == ["2022-12-31", "2023-12-31", "2024-12-31"]

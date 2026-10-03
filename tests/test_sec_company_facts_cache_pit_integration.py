"""Test integracyjny (Faza 5.3b, dependency audit 2026-10-02/03):
`sec_company_facts_cache` cache'uje WYŁĄCZNIE surowy SEC company_facts
JSON — zero zmiany logiki PIT w `point_in_time.py`/`pit_fundamentals.py`.

Potwierdza wprost zasadę zatwierdzoną przez właścicielkę: dla tego
samego (CIK, as_of_date, concept mapping, wersja kodu),
`build_annual_fundamentals_periods_as_of()` MUSI dawać identyczny wynik
niezależnie od tego, czy `company_facts` przyszedł świeżo z SEC (A) czy
został zapisany do `sec_company_facts_cache` i odczytany z powrotem (B)
— bo cache przechowuje source data, nie wynik interpretacji PIT."""

from __future__ import annotations

from buffett_scanner.db import get_sec_company_facts_cache, init_db, upsert_company, upsert_sec_company_facts_cache
from buffett_scanner.pit_fundamentals import build_annual_fundamentals_periods_as_of

CIK = "0000320193"


def _company_facts_with_restatement():
    """Realistyczny kształt: FY2023 pierwotnie zgłoszone (filed
    2024-02-01), potem skorygowane (filed 2024-11-01, restatement) --
    dokładnie scenariusz, który `value_as_of` musi rozstrzygać poprawnie
    (patrz test_point_in_time.py::test_value_as_of_restatement_scenario_
    avoids_look_ahead_bias), tu testowany PO przejściu przez cache."""
    return {
        "cik": 320193, "entityName": "Apple Inc.",
        "facts": {"us-gaap": {
            "NetIncomeLoss": {"units": {"USD": [
                {"start": "2022-01-01", "end": "2022-12-31", "val": 80.0,
                 "filed": "2023-02-01", "fy": 2022, "fp": "FY"},
                {"start": "2023-01-01", "end": "2023-12-31", "val": 90.0,
                 "filed": "2024-02-01", "fy": 2023, "fp": "FY"},
                # restatement tego samego okresu FY2023, zlozone znacznie
                # pozniej
                {"start": "2023-01-01", "end": "2023-12-31", "val": 95.0,
                 "filed": "2024-11-01", "fy": 2023, "fp": "FY"},
            ]}},
            "RevenueFromContractWithCustomerExcludingAssessedTax": {"units": {"USD": [
                {"start": "2022-01-01", "end": "2022-12-31", "val": 800.0,
                 "filed": "2023-02-01", "fy": 2022, "fp": "FY"},
                {"start": "2023-01-01", "end": "2023-12-31", "val": 900.0,
                 "filed": "2024-02-01", "fy": 2023, "fp": "FY"},
            ]}},
        }},
    }


def _setup_cache(conn, company_facts):
    upsert_company(conn, cik=CIK, name="Apple Inc.")
    upsert_sec_company_facts_cache(conn, cik=CIK, company_facts=company_facts)
    conn.commit()


def test_a_vs_b_identical_before_restatement(tmp_path):
    """as_of_date PRZED restatement: A (bezpośredni JSON) i B (JSON
    przez cache) muszą dać identyczny wynik -- w szczególności
    net_income=90.0, nie 95.0."""
    conn = init_db(tmp_path / "test.db")
    company_facts = _company_facts_with_restatement()
    _setup_cache(conn, company_facts)

    as_of_date = "2024-06-01"  # po pierwotnym filed, przed restatement
    result_a = build_annual_fundamentals_periods_as_of(company_facts, as_of_date)
    cached_json = get_sec_company_facts_cache(conn, CIK)
    result_b = build_annual_fundamentals_periods_as_of(cached_json, as_of_date)

    assert result_a == result_b
    fy2023_a = next(p for p in result_a if p.period_end_date == "2023-12-31")
    assert fy2023_a.net_income == 90.0  # jeszcze NIE restatement


def test_a_vs_b_identical_after_restatement(tmp_path):
    """as_of_date PO restatement: A i B muszą dać identyczny wynik --
    net_income=95.0 (skorygowana wartość), nadal A==B."""
    conn = init_db(tmp_path / "test.db")
    company_facts = _company_facts_with_restatement()
    _setup_cache(conn, company_facts)

    as_of_date = "2025-01-01"  # po restatement
    result_a = build_annual_fundamentals_periods_as_of(company_facts, as_of_date)
    cached_json = get_sec_company_facts_cache(conn, CIK)
    result_b = build_annual_fundamentals_periods_as_of(cached_json, as_of_date)

    assert result_a == result_b
    fy2023_a = next(p for p in result_a if p.period_end_date == "2023-12-31")
    assert fy2023_a.net_income == 95.0  # po restatement


def test_earlier_decision_date_still_blind_to_later_restatement_through_cache():
    """Kluczowa asercja (jej słowami): wcześniejsza decision_date NADAL
    nie widzi późniejszego faktu PO przejściu przez cache -- identyczne
    zachowanie jak bez cache (cache nie wprowadza żadnego look-ahead)."""
    company_facts = _company_facts_with_restatement()
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as d:
        conn = init_db(Path(d) / "test.db")
        _setup_cache(conn, company_facts)
        cached_json = get_sec_company_facts_cache(conn, CIK)

    before_restatement = build_annual_fundamentals_periods_as_of(cached_json, "2024-06-01")
    after_restatement = build_annual_fundamentals_periods_as_of(cached_json, "2025-01-01")

    fy2023_before = next(p for p in before_restatement if p.period_end_date == "2023-12-31")
    fy2023_after = next(p for p in after_restatement if p.period_end_date == "2023-12-31")
    assert fy2023_before.net_income == 90.0
    assert fy2023_after.net_income == 95.0
    assert fy2023_before.filed_date == "2024-02-01"
    assert fy2023_after.filed_date == "2024-11-01"


def test_a_vs_b_identical_across_all_recognized_periods_full_history(tmp_path):
    """Nie tylko jeden okres -- caly wynik (wszystkie rozpoznane
    period_end, wszystkie pola) musi byc identyczny A vs B."""
    conn = init_db(tmp_path / "test.db")
    company_facts = _company_facts_with_restatement()
    _setup_cache(conn, company_facts)

    as_of_date = "2025-06-01"
    result_a = build_annual_fundamentals_periods_as_of(company_facts, as_of_date)
    cached_json = get_sec_company_facts_cache(conn, CIK)
    result_b = build_annual_fundamentals_periods_as_of(cached_json, as_of_date)

    assert len(result_a) == 2
    assert result_a == result_b
    assert [p.period_end_date for p in result_a] == ["2022-12-31", "2023-12-31"]

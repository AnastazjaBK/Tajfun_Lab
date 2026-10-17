"""Faza 10: ostrzeżenie o jakości danych dla CTVA -- wyłącznie dla tej
jednej pary (run_id, cik), żadnej innej spółki ani innego skanu."""

from buffett_scanner.ui.data_quality import CORPORATE_ACTION_WARNING, data_quality_warning

RUN = "live-scan-2026-10-06T083825543395Z"
CTVA_CIK = "0001755672"


def test_ctva_in_flagged_run_gets_warning():
    assert data_quality_warning(RUN, CTVA_CIK) == CORPORATE_ACTION_WARNING
    assert CORPORATE_ACTION_WARNING == "Wynik niewiarygodny — możliwe zniekształcenie przez zdarzenie korporacyjne"


def test_other_company_same_run_has_no_warning():
    assert data_quality_warning(RUN, "0001091667") is None  # inna spółka (CHTR)


def test_ctva_in_other_run_has_no_warning():
    assert data_quality_warning("live-scan-2027-01-05T000000000000Z", CTVA_CIK) is None
    assert data_quality_warning(None, CTVA_CIK) is None

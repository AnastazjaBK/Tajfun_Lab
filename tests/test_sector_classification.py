"""Testy czystej funkcji klasyfikacji SIC -> sector_profile (Faza 5.3c,
Decyzja właścicielki 2026-10-04). Zakresy dokładnie jak w specyfikacji."""

from __future__ import annotations

from buffett_scanner.sector_classification import classify_sic_to_sector_profile


def test_bank_ranges():
    for code in (6020, 6025, 6036, 6060, 6061, 6062, 6080, 6081, 6082):
        assert classify_sic_to_sector_profile(code) == "BANK", code


def test_insurer_range():
    for code in (6300, 6311, 6411):
        assert classify_sic_to_sector_profile(code) == "INSURER", code


def test_reit_codes():
    assert classify_sic_to_sector_profile(6500) == "REIT"
    assert classify_sic_to_sector_profile(6798) == "REIT"


def test_codes_just_outside_ranges_are_general():
    assert classify_sic_to_sector_profile(6019) == "GENERAL"
    assert classify_sic_to_sector_profile(6037) == "GENERAL"
    assert classify_sic_to_sector_profile(6063) == "GENERAL"
    assert classify_sic_to_sector_profile(6083) == "GENERAL"
    assert classify_sic_to_sector_profile(6299) == "GENERAL"
    assert classify_sic_to_sector_profile(6412) == "GENERAL"
    assert classify_sic_to_sector_profile(6501) == "GENERAL"  # samo "Real Estate", nie REIT
    assert classify_sic_to_sector_profile(6799) == "GENERAL"


def test_ordinary_operating_company_sic_is_general():
    assert classify_sic_to_sector_profile(3571) == "GENERAL"  # Apple: Electronic Computers


def test_string_sic_is_accepted():
    assert classify_sic_to_sector_profile("6022") == "BANK"
    assert classify_sic_to_sector_profile(" 6798 ") == "REIT"


def test_none_sic_is_general_not_error():
    assert classify_sic_to_sector_profile(None) == "GENERAL"


def test_malformed_sic_is_general_not_error():
    assert classify_sic_to_sector_profile("") == "GENERAL"
    assert classify_sic_to_sector_profile("N/A") == "GENERAL"
    assert classify_sic_to_sector_profile("60a2") == "GENERAL"

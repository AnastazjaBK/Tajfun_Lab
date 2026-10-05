"""Testy `total_debt` z SEC XBRL (Faza 5.3d/5.3e/5.3f, Decyzje
właścicielki 2026-10-04/05). Scenariusze odtwarzają DOKŁADNIE przypadki
znalezione na realnych danych 10 spółek (AAPL/MSFT/KO/TERADYNE/JABIL/
PG&E/Constellation Energy/EQT/Realty Income/DOW), zgodnie z wymaganiem
właścicielki "testy regresyjne na dokładnie tych przypadkach"."""

from __future__ import annotations

from buffett_scanner.total_debt import (
    CURRENT_PLUS_NONCURRENT,
    INSUFFICIENT_DATA,
    NONCURRENT_PLUS_DEBTCURRENT_SYNONYM,
    NOTES_PAYABLE_ONLY,
    TIER_1,
    TIER_2,
    compute_total_debt_as_of,
)


def _facts(tag_entries: dict[str, list[dict]]) -> dict:
    return {
        "cik": 1, "entityName": "Test Co",
        "facts": {"us-gaap": {
            tag: {"units": {"USD": entries}} for tag, entries in tag_entries.items()
        }},
    }


def _fact(end: str, val: float, filed: str, **kw) -> dict:
    return {"end": end, "val": val, "filed": filed, **kw}


# ---------------------------------------------------------------------------
# PRIMARY: LongTermDebtCurrent + LongTermDebtNoncurrent (KO/MSFT/EQT/JABIL)
# ---------------------------------------------------------------------------


def test_current_plus_noncurrent_exact_identity_like_eqt():
    """EQT Corp, 2025-12-31: LongTermDebt=7,800,328,000 =
    LongTermDebtCurrent(507,119,000) + LongTermDebtNoncurrent(7,293,209,000)
    -- zweryfikowana w diagnostyce v1.46."""
    facts = _facts({
        "LongTermDebtCurrent": [_fact("2025-12-31", 507_119_000, "2026-02-18", form="10-K", accn="x", fy=2025, fp="FY")],
        "LongTermDebtNoncurrent": [_fact("2025-12-31", 7_293_209_000, "2026-02-18", form="10-K", accn="x", fy=2025, fp="FY")],
    })
    result = compute_total_debt_as_of(facts, "2026-06-01")
    assert result.value == 7_800_328_000
    assert result.debt_resolution_method == CURRENT_PLUS_NONCURRENT
    assert result.confidence_tier == TIER_1
    assert result.balance_sheet_instant == "2025-12-31"
    assert result.reason is None
    assert result.component_tags == ("LongTermDebtCurrent", "LongTermDebtNoncurrent")
    assert result.component_values == {
        "LongTermDebtCurrent": 507_119_000, "LongTermDebtNoncurrent": 7_293_209_000,
    }
    assert result.component_provenance["LongTermDebtCurrent"]["filed"] == "2026-02-18"
    assert result.component_provenance["LongTermDebtCurrent"]["form"] == "10-K"


def test_current_plus_noncurrent_is_pit_correct():
    """Restatement scenario: wcześniejsza as_of_date nie widzi później
    złożonej korekty -- ten sam wzorzec co reszta PIT w projekcie."""
    facts = _facts({
        "LongTermDebtCurrent": [
            _fact("2023-12-31", 100.0, "2024-02-01"),
            _fact("2023-12-31", 110.0, "2024-11-01"),  # restatement
        ],
        "LongTermDebtNoncurrent": [
            _fact("2023-12-31", 900.0, "2024-02-01"),
        ],
    })
    before = compute_total_debt_as_of(facts, "2024-06-01")
    after = compute_total_debt_as_of(facts, "2025-01-01")
    assert before.value == 1000.0  # 100 + 900, przed restatement
    assert after.value == 1010.0  # 110 + 900, po restatement


# ---------------------------------------------------------------------------
# Decyzja 1: brak jednego komponentu NIGDY nie jest traktowany jako zero,
# i NIGDY nie ma fallbacku na goly LongTermDebt (PG&E alias trap).
# ---------------------------------------------------------------------------


def test_missing_current_component_is_none_not_zero():
    facts = _facts({
        "LongTermDebtNoncurrent": [_fact("2024-12-31", 900.0, "2025-02-01")],
        "LongTermDebt": [_fact("2024-12-31", 950.0, "2025-02-01")],  # bedzie zignorowany
    })
    result = compute_total_debt_as_of(facts, "2025-06-01")
    assert result.value is None
    assert result.debt_resolution_method == INSUFFICIENT_DATA
    assert result.confidence_tier is None
    assert "LongTermDebtCurrent" in result.reason


def test_bare_long_term_debt_never_used_even_when_it_is_the_only_tag():
    """Scenariusz PG&E: tylko goly LongTermDebt istnieje (brak current/
    noncurrent na te konkretna date) -- Decyzja 1 zakazuje fallbacku,
    wiec wynik MUSI byc None, nawet gdyby LongTermDebt byl "cale
    zadluzenie" u tej spolki akurat na ta date."""
    facts = _facts({
        "LongTermDebt": [_fact("2025-12-31", 57_387_000_000, "2026-02-12")],
    })
    result = compute_total_debt_as_of(facts, "2026-06-01")
    assert result.value is None
    assert result.debt_resolution_method == INSUFFICIENT_DATA


def test_pge_like_scenario_long_term_debt_equals_noncurrent_only():
    """Dokladny PG&E Corp scenariusz z diagnostyki v1.46 (ten sam
    accn/end_date): LongTermDebt == LongTermDebtNoncurrent (alias, NIE
    suma), LongTermDebtCurrent zglaszany osobno. Nasza regula NIGDY nie
    uzywa golego LongTermDebt, wiec poprawnie liczy current+noncurrent
    (821,000,000 + 57,387,000,000), NIE przypadkowo bierze alias jako total."""
    facts = _facts({
        "LongTermDebt": [_fact("2025-12-31", 57_387_000_000, "2026-02-12")],
        "LongTermDebtCurrent": [_fact("2025-12-31", 821_000_000, "2026-02-12")],
        "LongTermDebtNoncurrent": [_fact("2025-12-31", 57_387_000_000, "2026-02-12")],
    })
    result = compute_total_debt_as_of(facts, "2026-06-01")
    assert result.value == 58_208_000_000
    assert result.debt_resolution_method == CURRENT_PLUS_NONCURRENT
    assert result.confidence_tier == TIER_1


def test_end_date_mismatch_between_current_and_noncurrent_is_none():
    """Current i noncurrent istnieja, ale dotycza INNYCH balance-sheet
    instants (np. spolka przestala raportowac jeden z tagow w nowszych
    filingach, PIT zwraca stary end_date dla jednego z nich) -- MUSI
    byc None, nigdy zsumowane przez przypadek."""
    facts = _facts({
        "LongTermDebtCurrent": [_fact("2025-12-31", 100.0, "2026-02-01")],
        "LongTermDebtNoncurrent": [_fact("2024-12-31", 900.0, "2025-02-01")],
    })
    result = compute_total_debt_as_of(facts, "2026-06-01")
    assert result.value is None
    assert result.debt_resolution_method == INSUFFICIENT_DATA
    assert result.confidence_tier is None
    assert "balance-sheet instant" in result.reason


# ---------------------------------------------------------------------------
# SECONDARY: NotesPayable-only fallback (Realty Income), zablokowany gdy
# rodzina LongTermDebt istnieje gdziekolwiek w historii (trap EQT).
# ---------------------------------------------------------------------------


def test_notes_payable_fallback_for_reit_like_company_never_using_ltd_family():
    facts = _facts({
        "NotesPayable": [_fact("2025-12-31", 25_031_947_000, "2026-02-25")],
        "CommercialPaper": [_fact("2025-12-31", 516_800_000, "2026-02-25")],
        "FinanceLeaseLiability": [_fact("2025-12-31", 121_434_000, "2026-02-25")],
    })
    result = compute_total_debt_as_of(facts, "2026-06-01")
    assert result.value == 25_031_947_000
    assert result.debt_resolution_method == NOTES_PAYABLE_ONLY
    assert result.confidence_tier == TIER_1
    assert result.component_tags == ("NotesPayable",)
    # Diagnostyczne, nigdy dodane do value:
    assert result.finance_lease_liability_supplemental == 121_434_000
    assert result.short_term_borrowings_supplemental == 516_800_000


def test_notes_payable_fallback_blocked_when_ltd_family_exists_elsewhere_eqt_trap():
    """EQT Corp: NotesPayable ~105mln jest malym podkomponentem przy
    dominujacej rodzinie LongTermDebt (~7.3mld). Fallback MUSI byc
    zablokowany, nawet na date, gdzie current/noncurrent akurat
    brakuje -- inaczej drastyczne niedoszacowanie."""
    facts = _facts({
        "NotesPayable": [_fact("2019-12-31", 105_056_000, "2020-02-27")],
        # Rodzina LongTermDebt istnieje GDZIEINDZIEJ w historii (inna data):
        "LongTermDebtNoncurrent": [_fact("2025-12-31", 7_293_209_000, "2026-02-18")],
    })
    result = compute_total_debt_as_of(facts, "2020-06-01")
    assert result.value is None
    assert result.debt_resolution_method == INSUFFICIENT_DATA
    assert "EQT" in result.reason or "NotesPayable-fallback" in result.reason


def test_notes_payable_absent_and_ltd_family_entirely_absent_is_none():
    facts = _facts({})
    result = compute_total_debt_as_of(facts, "2020-06-01")
    assert result.value is None
    assert result.debt_resolution_method == INSUFFICIENT_DATA
    assert result.confidence_tier is None


# ---------------------------------------------------------------------------
# Decyzja 2: leasing/combined-lease tagi NIGDY nie wchodza do value.
# ---------------------------------------------------------------------------


def test_and_capital_lease_obligations_combined_tag_never_used_dow_like():
    """DOW Inc: zamiast golego LongTermDebt, filer uzywa
    LongTermDebtAndCapitalLeaseObligations(Current) -- Decyzja 2
    zakazuje uzycia tego skumulowanego tagu (juz zawiera leasing).
    Brak czystej rodziny LongTermDebtCurrent/Noncurrent -> None, mimo
    posiadania duzo danych."""
    facts = _facts({
        "LongTermDebtAndCapitalLeaseObligations": [_fact("2026-03-31", 17_254_000_000, "2026-04-24")],
        "LongTermDebtAndCapitalLeaseObligationsCurrent": [_fact("2026-03-31", 793_000_000, "2026-04-24")],
        "FinanceLeaseLiabilityCurrent": [_fact("2026-03-31", 110_000_000, "2026-04-24")],
        "FinanceLeaseLiabilityNoncurrent": [_fact("2026-03-31", 694_000_000, "2026-04-24")],
    })
    result = compute_total_debt_as_of(facts, "2026-06-01")
    assert result.value is None
    assert result.debt_resolution_method == INSUFFICIENT_DATA
    # Diagnostyczne pole leasingu MUSI byc policzone (current+noncurrent,
    # ten sam end_date), ale nigdy wplywa na `value`.
    assert result.finance_lease_liability_supplemental == 804_000_000


def test_finance_lease_liability_never_added_to_value_even_when_large():
    facts = _facts({
        "LongTermDebtCurrent": [_fact("2025-12-31", 100.0, "2026-02-01")],
        "LongTermDebtNoncurrent": [_fact("2025-12-31", 900.0, "2026-02-01")],
        "FinanceLeaseLiability": [_fact("2025-12-31", 999_999_999.0, "2026-02-01")],
    })
    result = compute_total_debt_as_of(facts, "2026-06-01")
    assert result.value == 1000.0  # NIE +999,999,999
    assert result.finance_lease_liability_supplemental == 999_999_999.0


def test_debt_instrument_carrying_amount_never_used_as_total():
    """DebtInstrumentCarryingAmount jest tagiem instrument-poziomu --
    nie moze byc uzyty jako total, nawet jesli to jedyny obecny tag."""
    facts = _facts({
        "DebtInstrumentCarryingAmount": [_fact("2025-12-31", 123_456.0, "2026-02-01")],
    })
    result = compute_total_debt_as_of(facts, "2026-06-01")
    assert result.value is None
    assert result.debt_resolution_method == INSUFFICIENT_DATA


# ---------------------------------------------------------------------------
# Decyzja F (2026-10-05): Tier 2 NONCURRENT_PLUS_DEBTCURRENT_SYNONYM --
# wylacznie gdy spolka NIGDY (cala historia) nie raportowala
# LongTermDebtCurrent. Tier 2a (joint stale instant) ODRZUCONY -- nie
# implementowany w ogole, zero testu "na to", bo nie istnieje w kodzie.
# ---------------------------------------------------------------------------


def test_tier2_synonym_fires_when_company_never_reports_ltd_current_anywhere():
    facts = _facts({
        "LongTermDebtNoncurrent": [_fact("2024-12-31", 900.0, "2025-02-01")],
        "DebtCurrent": [_fact("2024-12-31", 100.0, "2025-02-01")],
    })
    result = compute_total_debt_as_of(facts, "2025-06-01")
    assert result.value == 1000.0
    assert result.debt_resolution_method == NONCURRENT_PLUS_DEBTCURRENT_SYNONYM
    assert result.confidence_tier == TIER_2
    assert result.balance_sheet_instant == "2024-12-31"
    assert result.component_tags == ("LongTermDebtNoncurrent", "DebtCurrent")
    assert result.component_values == {"LongTermDebtNoncurrent": 900.0, "DebtCurrent": 100.0}


def test_tier2_synonym_blocked_when_company_reports_ltd_current_in_any_other_period():
    """Nawet jesli LongTermDebtCurrent akurat brakuje NA TA date, warunek
    wylacznosci dotyczy CALEJ historii -- jesli spolka kiedykolwiek go
    uzyla (inny rok), DebtCurrent MOZE byc jego aliasem u tej spolki,
    wiec Tier 2 MUSI byc zablokowany."""
    facts = _facts({
        "LongTermDebtNoncurrent": [_fact("2024-12-31", 900.0, "2025-02-01")],
        "DebtCurrent": [_fact("2024-12-31", 100.0, "2025-02-01")],
        # LongTermDebtCurrent zglaszany w INNYM roku -- blokuje wylacznosc:
        "LongTermDebtCurrent": [_fact("2020-12-31", 50.0, "2021-02-01")],
    })
    result = compute_total_debt_as_of(facts, "2025-06-01")
    assert result.value is None
    assert result.debt_resolution_method == INSUFFICIENT_DATA
    assert result.confidence_tier is None


def test_tier2_synonym_requires_same_instant_as_noncurrent():
    """DebtCurrent istnieje, ale dla INNEGO balance-sheet instant niz
    LongTermDebtNoncurrent -- Tier 2 MUSI byc None, nigdy zsumowane
    przez przypadek dwoch roznych dat."""
    facts = _facts({
        "LongTermDebtNoncurrent": [_fact("2024-12-31", 900.0, "2025-02-01")],
        "DebtCurrent": [_fact("2023-12-31", 100.0, "2024-02-01")],
    })
    result = compute_total_debt_as_of(facts, "2025-06-01")
    assert result.value is None
    assert result.debt_resolution_method == INSUFFICIENT_DATA


def test_tier2_synonym_not_used_when_noncurrent_also_missing():
    """Current i noncurrent oba None -- to jest domena NotesPayable-
    fallbacku (Tier 1b) albo NO_FAMILY, nigdy Tier 2 (Tier 2 wymaga
    noncurrent PRESENT)."""
    facts = _facts({
        "DebtCurrent": [_fact("2024-12-31", 100.0, "2025-02-01")],
    })
    result = compute_total_debt_as_of(facts, "2025-06-01")
    assert result.value is None
    assert result.debt_resolution_method == INSUFFICIENT_DATA


# ---------------------------------------------------------------------------
# `target_end` (Faza 5.3f) -- filtruje wszystkie komponenty do konkretnego
# balance-sheet instant, wymagane do poprawnego wpiecia per-FundamentalsPeriod.
# ---------------------------------------------------------------------------


def test_target_end_restricts_to_specific_instant_ignoring_newer_data():
    """Spolka ma dwa roczne instanty; target_end=starszy MUSI zwrocic
    total_debt TEGO roku, nie najnowszego, nawet gdy najnowszy jest PIT-
    dostepny na as_of_date."""
    facts = _facts({
        "LongTermDebtCurrent": [
            _fact("2023-12-31", 50.0, "2024-02-01"),
            _fact("2024-12-31", 60.0, "2025-02-01"),
        ],
        "LongTermDebtNoncurrent": [
            _fact("2023-12-31", 500.0, "2024-02-01"),
            _fact("2024-12-31", 600.0, "2025-02-01"),
        ],
    })
    result = compute_total_debt_as_of(facts, "2025-06-01", target_end="2023-12-31")
    assert result.value == 550.0
    assert result.balance_sheet_instant == "2023-12-31"


def test_target_end_missing_component_for_that_instant_is_none_not_fallback_to_other_year():
    facts = _facts({
        "LongTermDebtCurrent": [_fact("2024-12-31", 60.0, "2025-02-01")],
        "LongTermDebtNoncurrent": [
            _fact("2023-12-31", 500.0, "2024-02-01"),
            _fact("2024-12-31", 600.0, "2025-02-01"),
        ],
    })
    result = compute_total_debt_as_of(facts, "2025-06-01", target_end="2023-12-31")
    assert result.value is None
    assert result.debt_resolution_method == INSUFFICIENT_DATA

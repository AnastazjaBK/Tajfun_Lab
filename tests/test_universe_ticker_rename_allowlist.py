"""Testy reguły wielosygnałowej weryfikacji rename (Faza 5.3,
podejście LIMITED_BUT_HONEST, zatwierdzone 2026-09-30). Wartości
referencyjne policzone ręcznie."""

from __future__ import annotations

from buffett_scanner.universe_ticker_rename_allowlist import (
    CURATED_ALLOWLIST_SEED,
    RenameSignals,
    evaluate_rename_signals,
)


def test_seed_allowlist_contains_exactly_the_two_approved_cases():
    pairs = {(r.old_ticker, r.new_ticker, r.cik) for r in CURATED_ALLOWLIST_SEED}
    assert pairs == {
        ("ANTM", "ELV", "1156039"),
        ("FB", "META", "1326801"),
    }
    assert all(r.resolution_method == "CURATED_MANUAL_ALLOWLIST_V1" for r in CURATED_ALLOWLIST_SEED)
    assert all(len(r.evidence) >= 2 for r in CURATED_ALLOWLIST_SEED)  # nigdy pojedynczy dowód


def test_all_three_signals_true_is_confirmed():
    verdict = evaluate_rename_signals(RenameSignals(True, True, True))
    assert verdict.status == "CONFIRMED_MULTI_SIGNAL"
    assert verdict.positive_signal_count == 3


def test_exactly_two_of_three_signals_true_is_confirmed():
    verdict = evaluate_rename_signals(RenameSignals(True, True, None))
    assert verdict.status == "CONFIRMED_MULTI_SIGNAL"
    assert verdict.positive_signal_count == 2


def test_exactly_one_signal_true_is_insufficient_not_disconfirmed():
    verdict = evaluate_rename_signals(RenameSignals(True, None, None))
    assert verdict.status == "INSUFFICIENT_EVIDENCE"
    assert verdict.positive_signal_count == 1


def test_no_signals_available_is_insufficient():
    verdict = evaluate_rename_signals(RenameSignals(None, None, None))
    assert verdict.status == "INSUFFICIENT_EVIDENCE"
    assert verdict.positive_signal_count == 0
    assert verdict.reasons == ("brak żadnego pozytywnego sygnału",)


def test_explicit_profile_mismatch_disconfirms_even_with_other_signals_true():
    """Jawna sprzeczność (FMP profile wskazuje dziś na INNY CIK dla
    starego tickera — np. recykling) unieważnia kandydata, NIEZALEŻNIE
    od tego, ile innych sygnałów jest pozytywnych."""
    verdict = evaluate_rename_signals(RenameSignals(False, True, True))
    assert verdict.status == "DISCONFIRMED"
    assert verdict.positive_signal_count == 0


def test_profile_mismatch_alone_disconfirms():
    verdict = evaluate_rename_signals(RenameSignals(False, None, None))
    assert verdict.status == "DISCONFIRMED"


def test_false_non_profile_signals_never_count_as_positive_or_disconfirm():
    """`fmp_name_match=False`/`former_name_match=False` oznaczają
    "sprawdzone i NIE pasuje" — to NIE jest dyskwalifikujący dowód
    (w przeciwieństwie do profile mismatch), tylko brak potwierdzenia
    z tego konkretnego sygnału."""
    verdict = evaluate_rename_signals(RenameSignals(True, False, False))
    assert verdict.status == "INSUFFICIENT_EVIDENCE"
    assert verdict.positive_signal_count == 1

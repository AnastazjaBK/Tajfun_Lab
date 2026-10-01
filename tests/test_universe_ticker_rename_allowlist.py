"""Testy reguły wielosygnałowej weryfikacji rename (Faza 5.3,
podejście LIMITED_BUT_HONEST, zatwierdzone 2026-09-30). Wartości
referencyjne policzone ręcznie."""

from __future__ import annotations

from buffett_scanner.universe_ticker_rename_allowlist import (
    CURATED_ALLOWLIST_SEED,
    RenameSignals,
    apply_curated_allowlist,
    evaluate_rename_signals,
)


def test_seed_allowlist_contains_exactly_the_seven_approved_cases():
    """Finalna allowlista zatwierdzona przez właścicielkę 2026-10-01
    (2 ręcznie kuratorowane + 5 potwierdzonych wielosygnałowo i
    niezależnie przez nią w źródłach SEC)."""
    pairs = {(r.old_ticker, r.new_ticker, r.cik) for r in CURATED_ALLOWLIST_SEED}
    assert pairs == {
        ("ANTM", "ELV", "1156039"),
        ("FB", "META", "1326801"),
        ("MMC", "MRSH", "62709"),
        ("SATS", "ECHO", "1415404"),
        ("BK", "BNY", "1390777"),
        ("DISCK", "WBD", "1437107"),
        ("FISV", "FI", "798354"),
    }
    assert all(len(r.evidence) >= 2 for r in CURATED_ALLOWLIST_SEED)  # nigdy pojedynczy dowód
    assert all(
        any(e.startswith("direction:") for e in r.evidence) for r in CURATED_ALLOWLIST_SEED
    )  # każdy rekord ma OSOBNE potwierdzenie kierunku, nie tylko same-company/CIK


# ---------------------------------------------------------------------------
# apply_curated_allowlist
# ---------------------------------------------------------------------------


def test_apply_curated_allowlist_adds_old_ticker_when_new_ticker_matches_declared_cik():
    resolved = {"ELV": "1156039"}
    unresolved = ("ANTM", "GHOST")
    result = apply_curated_allowlist(resolved, unresolved, allowlist=CURATED_ALLOWLIST_SEED)
    assert result.resolved["ANTM"] == "1156039"
    assert result.resolved["ELV"] == "1156039"
    assert "ANTM" in result.resolved_via_curated_allowlist
    assert result.still_unresolved == ("GHOST",)


def test_apply_curated_allowlist_never_overwrites_already_resolved_ticker():
    """ANTM już rozwiązany inną metodą (np. DIRECT, hipotetycznie) —
    allowlista nigdy nie nadpisuje istniejącego wyniku."""
    resolved = {"ANTM": "9999999", "ELV": "1156039"}
    unresolved = ()
    result = apply_curated_allowlist(resolved, unresolved, allowlist=CURATED_ALLOWLIST_SEED)
    assert result.resolved["ANTM"] == "9999999"
    assert "ANTM" not in result.resolved_via_curated_allowlist


def test_apply_curated_allowlist_skips_record_when_new_ticker_cik_diverged_from_sec():
    """Jeśli dzisiejsza mapa SEC rozwiązuje ELV do INNEGO CIK niż
    zadeklarowany w rekordzie (np. dane się zmieniły od zatwierdzenia),
    rekord jest pomijany — nigdy ślepe zaufanie allowlistie."""
    resolved = {"ELV": "DIFFERENT_CIK"}
    unresolved = ("ANTM",)
    result = apply_curated_allowlist(resolved, unresolved, allowlist=CURATED_ALLOWLIST_SEED)
    assert "ANTM" not in result.resolved
    assert result.still_unresolved == ("ANTM",)


def test_apply_curated_allowlist_skips_when_new_ticker_itself_unresolved():
    resolved = {}
    unresolved = ("ANTM", "ELV")
    result = apply_curated_allowlist(resolved, unresolved, allowlist=CURATED_ALLOWLIST_SEED)
    assert "ANTM" not in result.resolved
    assert result.still_unresolved == ("ANTM", "ELV")


def test_apply_curated_allowlist_provenance_note_contains_key_fields():
    resolved = {"ELV": "1156039"}
    unresolved = ("ANTM",)
    result = apply_curated_allowlist(resolved, unresolved, allowlist=CURATED_ALLOWLIST_SEED)
    note = result.resolved_via_curated_allowlist["ANTM"]
    assert "old=ANTM" in note
    assert "new=ELV" in note
    assert "run=seed-2026-09-30" in note
    assert "evidence=" in note


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

"""Kwalifikacja do analizy Claude według kryteriów, nie TOP N (decyzje
właścicielki 2026-10-24, punkty 1-5). Czyste funkcje, zero I/O.

Zatwierdzone:
- rdzeń wypłacalności (sekcja 3.2 rundy 4): FCF z 3 lat > 0; gotówka netto
  albo EBITDA > 0 i dług netto/EBITDA <= próg z configu; zysk netto > 0 w
  co najmniej 2 z 3 lat;
- spółki bez DCF: analiza jakościowa z oznaczeniem „jakość bez potwierdzonej
  ceny” (N1) -- nigdy jako potwierdzona okazja cenowa;
- odrębny status ręcznego przeglądu, gdy standardowe wskaźniki są
  nieadekwatne -- bez automatycznej kwalifikacji i bez cichego odrzucenia;
- przekroczenie limitu wywołań -> zatrzymanie przed Claude.

NIE zatwierdzone (parametr, nie stała): próg MoS dla grupy z DCF
(preferencja właścicielki: >= 0, do potwierdzenia po symulacji).

NIE PODŁĄCZONE do skanu na żywo -- używane w symulacji (docs/analysis).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from buffett_scanner.fundamentals import FundamentalsPeriod, free_cash_flow, low_leverage, net_debt
from buffett_scanner.sector_classification import profile_review_note

QUALIFIED = "KWALIFIKACJA"
QUALIFIED_NO_PRICE = "KWALIFIKACJA_BEZ_POTWIERDZONEJ_CENY"
MANUAL_REVIEW = "PRZEGLAD_RECZNY"
NOT_QUALIFIED = "BRAK_KWALIFIKACJI"
NO_METHOD = "BRAK_METODY_OCENY"
INCOMPLETE = "NIEKOMPLETNE_DANE"

NO_PRICE_LABEL = "jakość bez potwierdzonej ceny"
WINDOW = 3

# Usługi finansowe poza BANK/INSURER/REIT (np. zarządzający aktywami,
# brokerzy, giełdy): dług netto/EBITDA bywa nieadekwatny (konsolidowane
# fundusze, środki klientów).
_FINANCIAL_SERVICES_RANGES = ((6100, 6299), (6700, 6797), (6799, 6799))


@dataclass(frozen=True)
class SolvencyCheck:
    passed: bool
    failures: list[str] = field(default_factory=list)


def solvency_core(periods: list[FundamentalsPeriod], *, leverage_threshold: float) -> SolvencyCheck:
    """Rdzeń wypłacalności (3 warunki). Brak danych -> warunek niespełniony."""
    failures = []
    window = periods[-WINDOW:]
    fcf = [free_cash_flow(p) for p in window]
    if len(window) < WINDOW or None in fcf:
        failures.append("brak FCF z 3 lat")
    elif sum(fcf) <= 0:
        failures.append(f"FCF z 3 lat {sum(fcf) / 1e9:.2f} mld <= 0")
    latest = periods[-1]
    if not low_leverage(latest, leverage_threshold):
        nd = net_debt(latest)
        if nd is None:
            failures.append("brak danych o długu/gotówce")
        elif latest.ebitda is None or latest.ebitda <= 0:
            failures.append("dług netto przy EBITDA <= 0")
        else:
            failures.append(f"dług netto/EBITDA {nd / latest.ebitda:.2f} > {leverage_threshold:g}")
    ni = [p.net_income for p in window]
    if len(window) < WINDOW or None in ni:
        failures.append("brak zysku netto z 3 lat")
    elif sum(1 for v in ni if v > 0) < 2:
        failures.append("zysk netto > 0 w mniej niż 2 z 3 lat")
    return SolvencyCheck(passed=not failures, failures=failures)


def _sic_code(sic) -> int | None:
    try:
        return int(str(sic).strip())
    except (TypeError, ValueError):
        return None


def manual_review_reasons(periods: list[FundamentalsPeriod], check: SolvencyCheck, sic) -> list[str]:
    """Przyczyny, dla których standardowy wskaźnik może nie pasować do spółki
    -- tylko dla spółek, które nie przeszły rdzenia (decyzja nr 4)."""
    if check.passed:
        return []
    reasons = []
    latest = periods[-1]
    if "dług netto przy EBITDA <= 0" in check.failures and (latest.operating_cash_flow or 0) > 0:
        reasons.append("EBITDA <= 0 przy dodatnim przepływie operacyjnym -- możliwe odpisy, dźwignia niemiarodajna")
    window = periods[-WINDOW:]
    ni = [p.net_income for p in window]
    if any(f.startswith("FCF z 3 lat") for f in check.failures) and None not in ni \
            and sum(1 for v in ni if v > 0) >= 2:
        ocf = [p.operating_cash_flow for p in window]
        if None not in ocf and sum(ocf) <= 0:
            reasons.append("ujemny przepływ operacyjny z 3 lat przy zyskach netto -- możliwy efekt klasyfikacji "
                           "przepływów lub kapitału obrotowego")
        else:
            reasons.append("FCF ujemny przez inwestycje (CAPEX > przepływ operacyjny) przy zyskach netto -- "
                           "sprawdź, czy to inwestycje regulowane/finansowane długiem (np. energetyka), czy realne ryzyko")
    note = profile_review_note(sic)
    if note:
        reasons.append(note)
    code = _sic_code(sic)
    if code is not None and any(lo <= code <= hi for lo, hi in _FINANCIAL_SERVICES_RANGES) \
            and any(f.startswith(("dług netto", "brak danych o długu")) for f in check.failures):
        reasons.append(f"usługi finansowe (SIC {code}) -- dług netto/EBITDA może być nieadekwatny")
    return reasons


@dataclass(frozen=True)
class Qualification:
    status: str
    reasons: list[str]
    label: str | None = None


def qualify(*, group: str, periods: list[FundamentalsPeriod], margin_of_safety_base_pct: float | None,
            sic, leverage_threshold: float, min_margin_of_safety_pct: float) -> Qualification:
    """Status jednej spółki. `group`: Z_DCF / BEZ_DCF / BEZ_METODY / NIEKOMPLETNE."""
    if group == "BEZ_METODY":
        return Qualification(NO_METHOD, ["profil bez odpowiedniej metody oceny (BANK/INSURER/REIT)"])
    if group == "NIEKOMPLETNE":
        return Qualification(INCOMPLETE, ["niekompletne lub niewiarygodne dane"])
    check = solvency_core(periods, leverage_threshold=leverage_threshold)
    if not check.passed:
        review = manual_review_reasons(periods, check, sic)
        if review:
            return Qualification(MANUAL_REVIEW, check.failures + review)
        return Qualification(NOT_QUALIFIED, check.failures)
    if group == "BEZ_DCF":
        return Qualification(QUALIFIED_NO_PRICE, [], label=NO_PRICE_LABEL)
    if margin_of_safety_base_pct is None or margin_of_safety_base_pct < min_margin_of_safety_pct:
        mos = "brak" if margin_of_safety_base_pct is None else f"{margin_of_safety_base_pct:.1f}%"
        return Qualification(NOT_QUALIFIED, [f"MoS BASE {mos} < {min_margin_of_safety_pct:g}%"])
    return Qualification(QUALIFIED, [])


def worst_case_calls(n_qualified: int, max_repair_attempts: int) -> int:
    return n_qualified * (1 + max_repair_attempts)


def within_call_limit(n_qualified: int, *, max_calls: int, max_repair_attempts: int) -> bool:
    """Decyzja nr 5: przekroczenie -> zatrzymanie przed Claude (bez obcinania listy)."""
    return worst_case_calls(n_qualified, max_repair_attempts) <= max_calls

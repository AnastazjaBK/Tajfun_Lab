"""Dywidendy na akcje zwykłe vs uprzywilejowane (decyzja właścicielki
2026-10-24, poprawka nr 7).

Problem (diagnostyka 2026-10-24, run 40098265387): FMP `commonDividendsPaid`
bywa sumą dywidend zwykłych i uprzywilejowanych -- BA FY2025: 331 mln USD
jako „common” przy `preferredDividendsPaid` = 0, choć BA nie płaci
dywidendy od akcji zwykłych (SEC: brak tagu dla akcji zwykłych, brak
zadeklarowanego DPS; w 2024 emisja akcji uprzywilejowanych 5,66 mld);
AVGO FY2021-22: FMP 6,21 mld = SEC zwykłe 5,91 + uprzywilejowane 0,30.
Backtest ma to samo ryzyko: gdy spółka nie ma tagu dla akcji zwykłych,
bierze `PaymentsOfDividends` (suma).

Reguła (jedna, wspólna dla skanu i backtestu):
- brak śladów akcji uprzywilejowanych -> kwota bez zmian;
- są ślady i SEC podaje dywidendy na akcje zwykłe -> wartość z SEC;
- są ślady, SEC podaje sumę i część uprzywilejowaną -> różnica;
- w pozostałych przypadkach -> NIEZNANE (None), nigdy zgadywana kwota.
"""

from __future__ import annotations

import datetime as dt

from buffett_scanner.point_in_time import extract_fact_history

COMMON_DIVIDEND_TAGS = ("PaymentsOfDividendsCommonStock", "DividendsCommonStockCash", "DividendsCommonStock")
TOTAL_DIVIDEND_TAG = "PaymentsOfDividends"
PREFERRED_DIVIDEND_TAGS = (
    "PaymentsOfDividendsPreferredStockAndPreferenceStock", "DividendsPreferredStockCash", "DividendsPreferredStock",
)
PREFERRED_STOCK_INSTANT_TAGS = ("PreferredStockValue", "PreferredStockValueOutstanding")

DIV_ZERO = "ZERO"
DIV_NO_PREFERRED = "BEZ_UPRZYWILEJOWANYCH"
DIV_SEC_COMMON = "SEC_ZWYKLE"
DIV_SEC_DERIVED = "SEC_SUMA_MINUS_UPRZYWILEJOWANE"
DIV_UNKNOWN = "NIEZNANE"
DIV_MISSING = "BRAK_DANYCH"

MISMATCH_TOLERANCE = 0.05


def resolve_common_dividends(*, reported: float | None, preferred_evidence: bool, sec_common: float | None,
                             sec_total: float | None, sec_preferred: float | None) -> tuple[float | None, str, str]:
    """(dywidendy na akcje zwykłe albo None, stan, opis). Kwoty dodatnie."""
    if reported is None:
        return None, DIV_MISSING, "brak kwoty dywidend w danych źródłowych"
    if reported == 0:
        return 0.0, DIV_ZERO, ""
    if not preferred_evidence:
        return reported, DIV_NO_PREFERRED, ""
    if sec_common is not None:
        note = ""
        if abs(sec_common - reported) > MISMATCH_TOLERANCE * max(abs(sec_common), 1.0):
            note = f"skorygowane: źródło {reported:,.0f}, SEC (akcje zwykłe) {sec_common:,.0f}"
        return sec_common, DIV_SEC_COMMON, note
    if sec_total is not None and sec_preferred is not None and sec_total - sec_preferred >= 0:
        common = sec_total - sec_preferred
        return common, DIV_SEC_DERIVED, (f"SEC: suma {sec_total:,.0f} - uprzywilejowane {sec_preferred:,.0f}"
                                         f" (źródło: {reported:,.0f})")
    return None, DIV_UNKNOWN, (f"są akcje uprzywilejowane, a SEC nie potwierdza wypłat na akcje zwykłe "
                               f"(źródło podaje {reported:,.0f}) -- dane nieznane")


def _near(end_a: str, end_b: str, days: int = 7) -> bool:
    return abs((dt.date.fromisoformat(end_a[:10]) - dt.date.fromisoformat(end_b[:10])).days) <= days


def sec_annual_tag_value(facts: dict | None, tags: tuple[str, ...], period_end: str, as_of: str) -> float | None:
    """Roczna wartość pierwszego tagu z listy, dla którego istnieje fakt
    okresu kończącego się `period_end` (±7 dni, >= 330 dni), złożony
    najpóźniej `as_of`."""
    if not facts:
        return None
    for tag in tags:
        best = None
        for f in extract_fact_history(facts, tag):
            if f.start is None or f.filed[:10] > as_of or not _near(f.end, period_end):
                continue
            if (dt.date.fromisoformat(f.end) - dt.date.fromisoformat(f.start)).days < 330:
                continue
            if best is None or f.filed > best.filed:
                best = f
        if best is not None:
            return abs(best.val)
    return None


def sec_preferred_stock_present(facts: dict | None, period_end: str, as_of: str) -> bool:
    """Akcje uprzywilejowane w bilansie na koniec okresu (wartość > 0)."""
    if not facts:
        return False
    for tag in PREFERRED_STOCK_INSTANT_TAGS:
        for f in extract_fact_history(facts, tag):
            if f.filed[:10] <= as_of and _near(f.end, period_end) and f.val and f.val > 0:
                return True
    return False


def verify_with_sec(*, reported: float | None, facts: dict | None, period_end: str, as_of: str,
                    source_preferred_evidence: bool = False) -> tuple[float | None, str, str]:
    """Weryfikacja kwoty ze źródła (FMP albo zapasowego tagu SEC) faktami SEC."""
    sec_preferred = sec_annual_tag_value(facts, PREFERRED_DIVIDEND_TAGS, period_end, as_of)
    evidence = (source_preferred_evidence or (sec_preferred is not None and sec_preferred > 0)
                or sec_preferred_stock_present(facts, period_end, as_of))
    return resolve_common_dividends(
        reported=reported, preferred_evidence=evidence,
        sec_common=sec_annual_tag_value(facts, COMMON_DIVIDEND_TAGS, period_end, as_of),
        sec_total=sec_annual_tag_value(facts, (TOTAL_DIVIDEND_TAG,), period_end, as_of),
        sec_preferred=sec_preferred,
    )

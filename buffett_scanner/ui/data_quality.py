"""Ręczne ostrzeżenia o jakości danych dla konkretnych wyników skanu
(Faza 10, Decyzja właścicielki 2026-10-17).

WYŁĄCZNIE prezentacja: nie zmienia scoringu, DCF, rankingu ani danych
snapshotu -- liczby kandydata zostają dokładnie takie, jakie policzył
skan; UI tylko dokleja widoczne ostrzeżenie. Lista jest jawna i
zamknięta (para `run_id` + `cik`), nie automatyczny detektor -- detektor
zdarzeń korporacyjnych wymaga osobnej zgody.

CTVA w `live-scan-2026-10-06T083825543395Z`: wydzielenie Vylor (VYLR)
2026-10-01, zweryfikowane w FMP `splits` (splitType=spin-off), SEC 8-K
z 2026-10-01 i w snapshocie (CTVA 12,57 + VYLR 68,26 = 80,83 USD vs
77,65 USD dzień wcześniej). Sygnał spadku, Margin of Safety, yield
dywidendy i analiza Claude oparte na cenie po wydzieleniu i
fundamentach całej firmy sprzed wydzielenia."""

from __future__ import annotations

CORPORATE_ACTION_WARNING = "Wynik niewiarygodny — możliwe zniekształcenie przez zdarzenie korporacyjne"

_FLAGGED_RESULTS: dict[tuple[str, str], str] = {
    ("live-scan-2026-10-06T083825543395Z", "0001755672"): CORPORATE_ACTION_WARNING,  # CTVA
}


def data_quality_warning(run_id: str | None, cik: str) -> str | None:
    if run_id is None:
        return None
    return _FLAGGED_RESULTS.get((run_id, cik))

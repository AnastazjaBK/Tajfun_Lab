"""Faza 5.3c — klasyfikacja `sector_profile` z kodu SIC (SEC Submissions
API), zatwierdzona przez właścicielkę 2026-10-04.

Problem (odkryty podczas przygotowań do pełnego BASELINE walk-forward):
`sector_profile` nigdy nie był realnie wyliczany w całym pipeline —
`cmd_build_universe_membership` woła `upsert_company(...)` bez parametru
`sector_profile`, więc WSZYSTKIE 615 CIK mają domyślne `GENERAL`.
`config.valuation.method_by_sector_profile` poprawnie mapuje
BANK/INSURER/REIT -> `None` (NOT_YET_IMPLEMENTED), ale ta ścieżka nigdy
się nie uruchamia — `compute_valuation` stosuje `dcf_owner_earnings`
(metoda dla zwykłych spółek operacyjnych) do realnych banków/
ubezpieczycieli w datasetcie (np. BK/BNY, Marsh McLennan), gdzie jest to
metodologicznie bezsensowne.

Zakres tej klasyfikacji: WYŁĄCZNIE BANK/INSURER/REIT. BIOTECH ma odrębną,
jeszcze nie zaimplementowaną ścieżkę — poza zakresem tej zmiany (nikt
tego nie zlecił, nie zgadujemy czy/jak klasyfikować BIOTECH z SIC).

Źródło danych: pole `sic`/`sicDescription` z tego samego SEC Submissions
API, z którego już korzystają `get_filings`/`get_former_names` — NIE nowy
provider, NIE nowa zależność sieciowa.

Zakresy SIC (specyfikacja właścicielki, dokładnie jak podana, bez zmian):
- BANK:    6020-6036, 6060-6062, 6080-6082
- INSURER: 6300-6411
- REIT:    6500, 6798

Kod SIC spoza tych zakresów, brak kodu, albo niepoprawny format ->
GENERAL. Nigdy nie zgadujemy klasyfikacji tam, gdzie SEC nie dał
jednoznacznego kodu."""

from __future__ import annotations

_BANK_RANGES: tuple[tuple[int, int], ...] = ((6020, 6036), (6060, 6062), (6080, 6082))
_INSURER_RANGE: tuple[int, int] = (6300, 6411)
_REIT_CODES: frozenset[int] = frozenset({6500, 6798})


def classify_sic_to_sector_profile(sic: str | int | None) -> str:
    """Czysta funkcja: kod SIC (string, int, albo None) -> jeden z
    {GENERAL, BANK, INSURER, REIT} wg zakresów zatwierdzonych przez
    właścicielkę. `None`/niepoprawny format/kod spoza zakresów -> GENERAL
    (bezpieczna wartość domyślna, nie błąd — SIC bywa nieobecny dla
    niektórych spółek w SEC)."""
    if sic is None:
        return "GENERAL"
    try:
        code = int(str(sic).strip())
    except (TypeError, ValueError):
        return "GENERAL"

    if code in _REIT_CODES:
        return "REIT"
    if _INSURER_RANGE[0] <= code <= _INSURER_RANGE[1]:
        return "INSURER"
    for lo, hi in _BANK_RANGES:
        if lo <= code <= hi:
            return "BANK"
    return "GENERAL"

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

Zakresy SIC (specyfikacja właścicielki; zmiana 2026-10-24):
- BANK:    6020-6036, 6060-6062, 6080-6082
- INSURER: 6300-6411
- REIT:    6798 (6500 „Real Estate” usunięty -- obejmował firmy usług
  nieruchomościowych, np. CBRE, które nie są REIT-ami)

Kod spoza zakresów -> GENERAL. Brak kodu albo niepoprawny format ->
NIEZNANY (decyzja właścicielki 2026-10-24: brak klasyfikacji nie jest
dowodem profilu GENERAL; spółka poza ocenianym rankingiem, z przyczyną w
raporcie). Kody nieruchomościowe inne niż 6798 dostają GENERAL z
oznaczeniem do weryfikacji (`profile_review_note`)."""

from __future__ import annotations

_BANK_RANGES: tuple[tuple[int, int], ...] = ((6020, 6036), (6060, 6062), (6080, 6082))
_INSURER_RANGE: tuple[int, int] = (6300, 6411)
_REIT_CODES: frozenset[int] = frozenset({6798})
# Nieruchomości (SIC 6500-6553) poza REIT: GENERAL, ale do weryfikacji
# profilu -- część może być w praktyce REIT-em albo deweloperem.
_REAL_ESTATE_REVIEW_RANGE: tuple[int, int] = (6500, 6553)

UNKNOWN_PROFILE = "NIEZNANY"


def _sic_code(sic: str | int | None) -> int | None:
    if sic is None:
        return None
    try:
        return int(str(sic).strip())
    except (TypeError, ValueError):
        return None


def classify_sic_to_sector_profile(sic: str | int | None) -> str:
    """Czysta funkcja: kod SIC (string, int, albo None) -> jeden z
    {GENERAL, BANK, INSURER, REIT, NIEZNANY} wg zakresów zatwierdzonych
    przez właścicielkę. Brak kodu / niepoprawny format -> NIEZNANY, nigdy
    GENERAL."""
    code = _sic_code(sic)
    if code is None:
        return UNKNOWN_PROFILE

    if code in _REIT_CODES:
        return "REIT"
    if _INSURER_RANGE[0] <= code <= _INSURER_RANGE[1]:
        return "INSURER"
    for lo, hi in _BANK_RANGES:
        if lo <= code <= hi:
            return "BANK"
    return "GENERAL"


def profile_review_note(sic: str | int | None) -> str | None:
    """Oznaczenie nietypowego przypadku do ręcznej weryfikacji profilu
    (nie zmienia profilu)."""
    code = _sic_code(sic)
    if code is not None and code not in _REIT_CODES and \
            _REAL_ESTATE_REVIEW_RANGE[0] <= code <= _REAL_ESTATE_REVIEW_RANGE[1]:
        return (f"SIC {code} (nieruchomości) klasyfikowany jako GENERAL -- sprawdź, czy spółka nie jest REIT-em "
                "albo czy standardowe wskaźniki do niej pasują")
    return None

"""Budowa listy `FundamentalsPeriod` z realnych danych SEC XBRL
(`point_in_time.py`), na potrzeby walk-forward backtestu (Faza 5.3,
sekcja 13). Zero I/O — `company_facts` jest już pobranym JSON-em
(`SecEdgarClient.get_company_facts`).

CELOWO OGRANICZONE do okresów ROCZNYCH — kwartalne fakty XBRL
(`NetIncomeLoss`/`Revenues` z 10-Q) bywają wartościami SKUMULOWANYMI OD
POCZĄTKU ROKU (YTD), nie czystą wartością danego kwartału (zwłaszcza
Q2-Q4) — rozróżnienie tego to osobna praca, jawnie odłożona w design
review (sekcja 13). Użycie wyłącznie rocznych danych unika tej
niejednoznaczności CAŁKOWICIE, kosztem rzadszej granulacji (1 okres/rok,
nie 4) — świadomy, udokumentowany wybór zakresu dla Proof Run (Faza
5.3), NIE decyzja o zakresie pełnego backfillu, którą trzeba podjąć
osobno.

KRYTYCZNE, EMPIRYCZNIE POTWIERDZONE (2026-10-01, realny Proof Run,
AAPL): pole `fp` SEC XBRL ("FY"/"Q1"/...) NIE JEST wiarygodnym
wskaźnikiem rzeczywistego czasu trwania faktu. Realny wpis znaleziony w
danych AAPL miał `fp='FY'`, ale `start='2014-12-28'`..`end='2015-03-28'`
to 90 dni (jeden kwartał) — drugi, późniejszy wpis dla TEJ SAMEJ daty
`end` miał pole `frame='CY2015Q1'`, jawnie potwierdzające kwartał mimo
`fp='FY'`. Pierwsza wersja tego modułu filtrowała po `fp == 'FY'` —
BŁĘDNIE (wpuszczała fakty kwartalne oznaczone `fp='FY'`, co fałszywie
zniekształcałoby revenue_yoy_growth_pct/no_persistent_losses, mieszając
kwartalny net_income z rocznymi porównaniami). NAPRAWIONE: filtr liczy
RZECZYWISTY czas trwania (`end - start` w dniach), nigdy nie ufa `fp`.

Pokrywa WYŁĄCZNIE `net_income`/`revenue` (jedyne skonfigurowane
`CANDIDATE_TAGS` w `point_in_time.py`, empirycznie potwierdzone w Fazie
5.1) — reszta pól `FundamentalsPeriod` jest jawnie `None`, NIGDY
fabrykowana. Konsekwencja: w Proof Run większość komponentów
`compute_deterministic_score` będzie None/0 NIE dlatego, że spółka jest
słaba, tylko dlatego, że te pola nie są jeszcze w PIT — znana,
zgłoszona granica tego etapu, do rozszerzenia przed pełnym backfillem,
nie przed tym Proof Run."""

from __future__ import annotations

import datetime as dt

from buffett_scanner.fundamentals import FundamentalsPeriod
from buffett_scanner.point_in_time import PitFact, find_first_matching_tag, value_as_of

ANNUAL_CANONICAL_CONCEPTS = ("net_income", "revenue")

# Pasmo akceptowanej długości okresu "rocznego": 350-380 dni. Obejmuje z
# zapasem zarówno czyste 365/366-dniowe lata kalendarzowe, jak i
# 52/53-tygodniowe lata fiskalne (np. Apple: 364 albo 371 dni).
ANNUAL_DURATION_MIN_DAYS = 350
ANNUAL_DURATION_MAX_DAYS = 380


def _is_annual_duration(fact: PitFact) -> bool:
    """Jedyne źródło prawdy o tym, czy fakt jest "roczny" — RZECZYWISTA
    długość `end - start`, NIGDY pole `fp` (patrz docstring modułu).
    Fakt bez `start` (np. koncept "instant") nie da się zweryfikować ->
    odrzucony, nigdy nie zgadujemy."""
    if fact.start is None:
        return False
    try:
        start = dt.date.fromisoformat(fact.start)
        end = dt.date.fromisoformat(fact.end)
    except ValueError:
        return False
    duration_days = (end - start).days
    return ANNUAL_DURATION_MIN_DAYS <= duration_days <= ANNUAL_DURATION_MAX_DAYS


def build_annual_fundamentals_periods_as_of(
    company_facts: dict, as_of_date: str
) -> list[FundamentalsPeriod]:
    """Dla każdego rocznego okresu fiskalnego (`end`, zweryfikowanego
    PRZEZ RZECZYWISTY CZAS TRWANIA — `_is_annual_duration`, nigdy przez
    `fp`) obecnego w historii faktów SEC, bierze wartość ZNANĄ na
    `as_of_date` (`value_as_of` na faktach ograniczonych do tego
    konkretnego `end`) — czyli ewentualną restatement, jeśli złożono ją
    on/before `as_of_date`, nigdy przyszłą. `filed_date` okresu to
    NAJPÓŹNIEJSZA z dat `filed` użytych pól (konserwatywnie: okres jest
    "w pełni znany" dopiero, gdy WSZYSTKIE jego użyte pola są znane).
    Rok bez ŻADNEJ wartości dla żadnego z `ANNUAL_CANONICAL_CONCEPTS`
    jest pomijany, nie generuje pustego wiersza. Posortowane rosnąco po
    `period_end_date`."""
    concept_histories: dict[str, list[PitFact]] = {}
    for concept in ANNUAL_CANONICAL_CONCEPTS:
        found = find_first_matching_tag(company_facts, concept)
        if found is None:
            continue
        _, history = found
        concept_histories[concept] = [f for f in history if _is_annual_duration(f)]

    period_ends = sorted({f.end for history in concept_histories.values() for f in history})
    periods: list[FundamentalsPeriod] = []
    for end in period_ends:
        values: dict[str, float] = {}
        filed_dates: list[str] = []
        for concept, history in concept_histories.items():
            facts_for_end = [f for f in history if f.end == end]
            fact = value_as_of(facts_for_end, as_of_date)
            if fact is not None:
                values[concept] = fact.val
                filed_dates.append(fact.filed)
        if not values:
            continue
        periods.append(
            FundamentalsPeriod(
                fiscal_period=f"FY{end[:4]}",
                period_end_date=end,
                filed_date=max(filed_dates),
                revenue=values.get("revenue"),
                net_income=values.get("net_income"),
                ebitda=None,
                operating_cash_flow=None,
                capital_expenditure=None,
                total_debt=None,
                cash_and_equivalents=None,
                total_current_assets=None,
                total_current_liabilities=None,
            )
        )
    periods.sort(key=lambda p: p.period_end_date)
    return periods

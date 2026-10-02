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
nie 4) — świadomy, udokumentowany wybór zakresu (Faza 5.3), dotyczący
też pełnego backfillu, nie tylko Proof Run.

KRYTYCZNE, EMPIRYCZNIE POTWIERDZONE (2026-10-01, realny Proof Run,
AAPL): pole `fp` SEC XBRL ("FY"/"Q1"/...) NIE JEST wiarygodnym
wskaźnikiem rzeczywistego czasu trwania faktu. Realny wpis znaleziony w
danych AAPL miał `fp='FY'`, ale `start='2014-12-28'`..`end='2015-03-28'`
to 90 dni (jeden kwartał) — drugi, późniejszy wpis dla TEJ SAMEJ daty
`end` miał pole `frame='CY2015Q1'`, jawnie potwierdzające kwartał mimo
`fp='FY'`. NAPRAWIONE: filtr liczy RZECZYWISTY czas trwania (`end -
start` w dniach), nigdy nie ufa `fp`. Zasada ta jest stosowana
KONSEKWENTNIE do WSZYSTKICH konceptów typu "duration" poniżej (nie
tylko net_income/revenue) — ten sam ryzyk dotyczy każdego z nich.

ROZSZERZENIE (Faza 5.3b, dependency audit 2026-10-01/02): pokrycie
rozszerzone z (net_income, revenue) do wszystkich 12 pól
`FundamentalsPeriod` wymaganych przez istniejący deterministic pipeline
(compute_metrics/financial_quality_score/compute_valuation/
evaluate_dividend_shareholder_return) — patrz docs/
buffett-scanner-design-review.md, sekcja 13 (dependency audit). Dwie
kategorie konceptów XBRL, rozróżniane celowo (pomylenie ich byłoby
błędem point-in-time):
  - DURATION (okres, wymaga walidacji rzeczywistego czasu trwania
    350-380 dni, patrz wyżej): net_income, revenue, operating_cash_flow,
    capital_expenditure, dividends_paid, share_buybacks,
    diluted_shares_outstanding, i składniki EBITDA (operating_income_loss,
    depreciation_and_amortization).
  - INSTANT (stan na dany dzień `end`, z definicji BEZ `start` w SEC
    XBRL — walidacja czasu trwania nie ma zastosowania, bo nie ma
    "trwania"): cash_and_equivalents, total_current_assets,
    total_current_liabilities.
Wszystkie pola są dopasowywane do tego samego zbioru `period_end`
("kotwica" — wyznaczona WYŁĄCZNIE przez duration-zweryfikowane
net_income/revenue, zgodnie z już potwierdzoną metodą rozpoznawania
rocznych okresów) — żadne pole nie tworzy własnego, niezależnego zestawu
okresów.

EBITDA jest KOMPOZYTEM dwóch osobnych faktów XBRL (SEC nie ma jednego
ustandaryzowanego tagu "EBITDA"):
    ebitda = OperatingIncomeLoss + DepreciationDepletionAndAmortization
Zasady (zatwierdzone przez właścicielkę 2026-10-02):
  1. Oba składniki — niezależny PIT lookup (`value_as_of`), każdy musi
     mieć `filed <= as_of_date`.
  2. Oba składniki — ta sama walidacja duration (350-380 dni), nigdy
     `fp`.
  3. Liczone TYLKO gdy oba składniki są dostępne dla TEGO SAMEGO `end`
     (p. "kotwica" wyżej) — nigdy OperatingIncomeLoss z jednego roku z
     D&A z innego, mimo że oba mogłyby być `value_as_of(D)`-dostępne.
  4. Którykolwiek składnik None -> `ebitda = None`. Zero fallbacku
     (D&A=0), zero substytutu (OperatingIncomeLoss jako EBITDA), zero
     imputacji/estymacji.
  5. D&A ma udokumentowaną, wersjonowaną listę kandydatów (patrz
     `point_in_time.CANDIDATE_TAGS["depreciation_and_amortization"]`) —
     PRÓBOWANE PO KOLEI (pierwszy niepusty wygrywa), NIGDY sumowane
     automatycznie (ryzyko double counting, gdyby więcej niż jeden tag
     faktycznie reprezentował tę samą wielkość u danej spółki).

`total_debt` POZOSTAJE jawnie `None` na tym etapie — w SEC XBRL nie ma
jednego uniwersalnego tagu "total debt" (spółki różnie dzielą
current/noncurrent/short-term borrowings), złożenie kompozytu
analogicznego do EBITDA wymaga osobnej decyzji właścicielki (zgłoszone
w audycie 2026-10-02, jeszcze nierozstrzygnięte) — fabrykowanie go teraz
byłoby zgadywaniem zakresu wielkości, niedopuszczalnym wg §24."""

from __future__ import annotations

import datetime as dt

from buffett_scanner.fundamentals import FundamentalsPeriod
from buffett_scanner.point_in_time import PitFact, find_first_matching_tag, value_as_of

# Koncepty "duration" — wymagają walidacji rzeczywistego czasu trwania
# (patrz docstring modułu). Kolejność nieistotna (każdy traktowany
# niezależnie), ale wypisana jawnie dla czytelności/audytu.
DURATION_CONCEPTS = (
    "net_income",
    "revenue",
    "operating_cash_flow",
    "capital_expenditure",
    "dividends_paid",
    "share_buybacks",
    "diluted_shares_outstanding",
)

# Składniki kompozytu EBITDA — też "duration", ale nie są samodzielnym
# polem FundamentalsPeriod (patrz docstring modułu, zasady 1-5).
EBITDA_COMPONENT_CONCEPTS = ("operating_income_loss", "depreciation_and_amortization")

# Koncepty "instant" — stan na dany dzień `end`, bez `start` w SEC XBRL;
# walidacja czasu trwania nie ma zastosowania.
INSTANT_CONCEPTS = ("cash_and_equivalents", "total_current_assets", "total_current_liabilities")

# "Kotwica" rozpoznawania rocznych okresów — WYŁĄCZNIE te dwa koncepty
# (empirycznie potwierdzone w Fazie 5.1/5.3a) definiują zbiór `period_end`
# dla całego okresu; wszystkie inne pola są do niego dopasowywane, nigdy
# nie tworzą własnego, niezależnego zestawu okresów (zasada 6 dla EBITDA,
# zastosowana konsekwentnie do wszystkich pól).
ANNUAL_ANCHOR_CONCEPTS = ("net_income", "revenue")

ANNUAL_DURATION_MIN_DAYS = 350
ANNUAL_DURATION_MAX_DAYS = 380


def fact_duration_days(fact: PitFact) -> int | None:
    """Rzeczywisty czas trwania faktu w dniach (`end - start`), albo
    `None`, jeśli fakt nie ma `start` (koncept instant) albo daty się
    nie parsują. Publiczna — współdzielona z diagnostyką Proof Run
    (`walk_forward_proof_run.py`), żeby diagnostyka i filtr
    `_is_annual_duration` liczyły identycznie, nigdy dwoma różnymi
    wzorami."""
    if fact.start is None:
        return None
    try:
        start = dt.date.fromisoformat(fact.start)
        end = dt.date.fromisoformat(fact.end)
    except ValueError:
        return None
    return (end - start).days


def _is_annual_duration(fact: PitFact) -> bool:
    """Jedyne źródło prawdy o tym, czy fakt "duration" jest "roczny" —
    RZECZYWISTA długość `end - start`, NIGDY pole `fp` (patrz docstring
    modułu). Fakt bez `start` nie da się zweryfikować -> odrzucony,
    nigdy nie zgadujemy."""
    duration_days = fact_duration_days(fact)
    return duration_days is not None and ANNUAL_DURATION_MIN_DAYS <= duration_days <= ANNUAL_DURATION_MAX_DAYS


def _duration_history(company_facts: dict, concept: str) -> list[PitFact]:
    found = find_first_matching_tag(company_facts, concept)
    if found is None:
        return []
    _, history = found
    return [f for f in history if _is_annual_duration(f)]


def _instant_history(company_facts: dict, concept: str) -> list[PitFact]:
    """Koncepty "instant" nie mają `start` z definicji w SEC XBRL —
    żadna walidacja czasu trwania nie ma tu zastosowania (nie ma czego
    walidować). Przyjmowane jak są, dopasowanie do okresu następuje
    wyłącznie przez `end` (patrz ANNUAL_ANCHOR_CONCEPTS)."""
    found = find_first_matching_tag(company_facts, concept)
    if found is None:
        return []
    _, history = found
    return list(history)


def build_annual_fundamentals_periods_as_of(
    company_facts: dict, as_of_date: str
) -> list[FundamentalsPeriod]:
    """Dla każdego rocznego okresu fiskalnego (`end`, zweryfikowanego
    wyłącznie przez ANNUAL_ANCHOR_CONCEPTS — net_income/revenue,
    RZECZYWISTYM czasem trwania, nigdy przez `fp`) obecnego w historii
    faktów SEC, bierze wartość ZNANĄ na `as_of_date` (`value_as_of` na
    faktach ograniczonych do tego konkretnego `end`) dla każdego z 12
    pól `FundamentalsPeriod` niezależnie — czyli ewentualną restatement,
    jeśli złożono ją on/before `as_of_date`, nigdy przyszłą.
    `filed_date` okresu to NAJPÓŹNIEJSZA z dat `filed` użytych pól
    (konserwatywnie: okres jest "w pełni znany" dopiero, gdy WSZYSTKIE
    jego użyte pola są znane). `total_debt` jest jawnie `None` (patrz
    docstring modułu — decyzja o kompozycie jeszcze nierozstrzygnięta).
    `ebitda` jest kompozytem dwóch faktów (zasady 1-5, docstring modułu).
    Rok bez ŻADNEJ wartości `net_income`/`revenue` jest pomijany, nie
    generuje pustego wiersza. Posortowane rosnąco po `period_end_date`."""
    duration_histories: dict[str, list[PitFact]] = {
        concept: _duration_history(company_facts, concept)
        for concept in DURATION_CONCEPTS + EBITDA_COMPONENT_CONCEPTS
    }
    instant_histories: dict[str, list[PitFact]] = {
        concept: _instant_history(company_facts, concept) for concept in INSTANT_CONCEPTS
    }

    anchor_ends = sorted(
        {
            f.end
            for concept in ANNUAL_ANCHOR_CONCEPTS
            for f in duration_histories.get(concept, [])
        }
    )

    periods: list[FundamentalsPeriod] = []
    for end in anchor_ends:
        values: dict[str, float] = {}
        filed_dates: list[str] = []

        for concept, history in {**duration_histories, **instant_histories}.items():
            facts_for_end = [f for f in history if f.end == end]
            fact = value_as_of(facts_for_end, as_of_date)
            if fact is not None:
                values[concept] = fact.val
                filed_dates.append(fact.filed)

        if not any(c in values for c in ANNUAL_ANCHOR_CONCEPTS):
            continue

        # EBITDA: kompozyt, TYLKO gdy oba składniki dostępne dla TEGO
        # SAMEGO `end` (zasada 3) — nigdy substytut/fallback (zasada 4).
        operating_income = values.get("operating_income_loss")
        depreciation_amortization = values.get("depreciation_and_amortization")
        ebitda = (
            operating_income + depreciation_amortization
            if operating_income is not None and depreciation_amortization is not None
            else None
        )

        periods.append(
            FundamentalsPeriod(
                fiscal_period=f"FY{end[:4]}",
                period_end_date=end,
                filed_date=max(filed_dates) if filed_dates else None,
                revenue=values.get("revenue"),
                net_income=values.get("net_income"),
                ebitda=ebitda,
                operating_cash_flow=values.get("operating_cash_flow"),
                capital_expenditure=values.get("capital_expenditure"),
                total_debt=None,
                cash_and_equivalents=values.get("cash_and_equivalents"),
                total_current_assets=values.get("total_current_assets"),
                total_current_liabilities=values.get("total_current_liabilities"),
                dividends_paid=values.get("dividends_paid"),
                share_buybacks=values.get("share_buybacks"),
                diluted_shares_outstanding=values.get("diluted_shares_outstanding"),
            )
        )
    periods.sort(key=lambda p: p.period_end_date)
    return periods

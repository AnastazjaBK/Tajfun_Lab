"""`total_debt` z SEC XBRL (Faza 5.3d/5.3e/5.3f, Decyzje właścicielki
2026-10-04 i 2026-10-05, po diagnostyce v1.46 + diagnostyce coverage gap
2026-10-05 na 10 realnych spółkach — AAPL/MSFT/KO/TERADYNE/JABIL/PG&E/
Constellation Energy/EQT/DOW/Realty Income — oraz na pełnym 615-CIK
zbiorze).

Decyzje metodologiczne (właścicielka, verbatim z tur 2026-10-04/05):

1. Goły `LongTermDebt` NIGDY nie jest używany jako automatyczny
   fallback. Diagnostyka v1.46 pokazała, że jego semantyka NIE jest
   stabilna między filerami: u większości spółek (KO, MSFT, EQT,
   JABIL) `LongTermDebt` = `LongTermDebtCurrent + LongTermDebtNoncurrent`
   w tym samym filingu — ale u PG&E Corp, w TYM SAMYM 10-K
   (`accn=0001004980-26-000009`, `end=2025-12-31`), `LongTermDebt`
   jest IDENTYCZNY z `LongTermDebtNoncurrent`, z `LongTermDebtCurrent`
   zgłoszonym OSOBNO, NIE odjętym. Bez niezależnego sposobu odróżnienia
   "total" od "noncurrent-only" per filer -> nigdy nie używamy tego tagu.

2. `FinanceLeaseLiability`/`...AndCapitalLeaseObligations`/`...AndFinance
   LeaseObligations` NIGDY nie wchodzą do `total_debt`. Diagnostyka
   potwierdziła realne ryzyko double counting (DOW Inc). Leasing jest
   przechowywany jako OSOBNE pole diagnostyczne, NIGDY dodawany
   automatycznie do `value`.

3. Nie zwiększamy coverage kosztem niejednoznacznej semantyki — brak
   bezpiecznego, rozłącznego zestawu komponentów = `None`, nigdy
   estymacja/imputacja/zgadywanie.

4. (Decyzja F, 2026-10-05, po diagnostyce coverage gap) Tier 2a
   "CURRENT_PLUS_NONCURRENT_JOINT_INSTANT" (dopasowanie current/noncurrent
   do wspólnego, ale STARSZEGO balance-sheet instant niż ten, który
   resolver wybrałby dla każdego z tagów osobno) jest ODRZUCONY.
   Zmierzony staleness (decision_date - wspólny_instant): mediana 883
   dni, >2 lata dla 54.9% przypadków, SYSTEMATYCZNIE POGARSZAJĄCY SIĘ w
   czasie (mediana 397 dni w 2012 -> 1735 dni w 2026). Formalna zgodność
   PIT (ten sam instant, zero imputacji) NIE WYSTARCZA, jeśli instant
   jest ekonomicznie nieaktualny względem decision_date. NIE wprowadzamy
   arbitralnego progu staleness (365/180 dni) tylko żeby odzyskać część
   coverage — to byłby kolejny parametr wymagający kalibracji.

5. (Decyzja F, 2026-10-05) Tier 2
   "NONCURRENT_PLUS_DEBTCURRENT_SYNONYM" jest ZAAKCEPTOWANY, wyłącznie
   dla CIK, które w CAŁEJ dostępnej historii Company Facts NIGDY nie
   raportowały `LongTermDebtCurrent` — zero ryzyka aliasu/double
   countingu z konstrukcji (nie ma z czym konkurować). Diagnostyka
   pokazała, że `DebtCurrent` jest w >50% przypadków współwystępowania z
   `LongTermDebtCurrent` dosłownym aliasem (ratio≈1.0) — stąd warunek
   wyłączności jest obowiązkowy, nie opcjonalny. Odzyskuje ~21% z
   przypadków "missing CURRENT" (+2.19 pkt proc. overall na próbce
   diagnostycznej, confidence_tier=TIER_2, osobny
   `debt_resolution_method`, żeby wyniki backtestu dały się analizować
   per jakość źródła).

HIERARCHIA (Tier 1 = wysokie zaufanie, komponenty z tej samej rodziny
tagów; Tier 2 = zaakceptowany wyjątek, inna rodzina tagów, zero aliasu
z konstrukcji):

TIER 1a — CURRENT_PLUS_NONCURRENT:
    total_debt = LongTermDebtCurrent + LongTermDebtNoncurrent
TYLKO gdy oba fakty: są PIT-dostępne (`filed <= as_of_date`), dotyczą
TEGO SAMEGO balance-sheet instant, i OBA istnieją — brak jednego z
dwóch NIGDY nie jest traktowany jako zero.

TIER 1b — NOTES_PAYABLE_ONLY (fallback WYŁĄCZNIE dla spółek, które w
CAŁEJ swojej historii raportowania nigdy nie użyły rodziny
`LongTermDebt`/`LongTermDebtCurrent`/`LongTermDebtNoncurrent` — wzorzec
Realty Income/REIT):
    total_debt = NotesPayable (pojedynczy, PIT-poprawny fakt)
Zablokowany, jeśli spółka KIEDYKOLWIEK raportowała cokolwiek z rodziny
`LongTermDebt*` (diagnostyka v1.46, EQT Corp: `NotesPayable`≈105 mln
vs `LongTermDebtNoncurrent`≈7,3 mld — użycie samego `NotesPayable`
byłoby drastycznym niedoszacowaniem).

TIER 2 — NONCURRENT_PLUS_DEBTCURRENT_SYNONYM (Decyzja F, 2026-10-05):
    total_debt = LongTermDebtNoncurrent + DebtCurrent
TYLKO gdy: `LongTermDebtNoncurrent` jest PIT-dostępny dla danego
balance-sheet instant, `DebtCurrent` jest PIT-dostępny dla TEGO SAMEGO
instant, ORAZ spółka w CAŁEJ dostępnej historii Company Facts NIGDY nie
raportowała `LongTermDebtCurrent` (warunek wyłączności — bez niego
`DebtCurrent` bywa aliasem `LongTermDebtCurrent`, ryzyko double
countingu, patrz Decyzja 5 wyżej).

NIE WCHODZI do `total_debt` na tym etapie (przechowywane jako pola
diagnostyczne, osobno, nigdy dodawane automatycznie):
- `FinanceLeaseLiability(Current/Noncurrent)` — Decyzja 2.
- `CommercialPaper`/`ShortTermBorrowings` — diagnostyka coverage gap
  (2026-10-05) potwierdziła niejednoznaczną relację do
  `LongTermDebtCurrent` (częściowo alias, częściowo niezależny
  instrument) — nie da się tego dowieść wyłącznie z zagregowanych SEC
  `company_facts`. Traktowane z tą samą ostrożnością co leasing.

WYKLUCZONE CAŁKOWICIE:
- `DebtInstrumentCarryingAmount` — tag INSTRUMENT-poziomu, nie
  company-level total (potwierdzone empirycznie: u EQT = 0 wielokrotnie
  mimo realnego długu >5 mld USD).
- `...AndCapitalLeaseObligations`/`...AndFinanceLeaseObligations` jako
  fallback — z definicji już zawierają leasing.
- Goły `LongTermDebt` — Decyzja 1.
- Tier 2a "CURRENT_PLUS_NONCURRENT_JOINT_INSTANT" (dopasowanie do
  starszego wspólnego instant) — Decyzja F, 2026-10-05.
- Missing component = 0, imputacja, estymacja — Decyzja 3.

PARAMETR `target_end` (Faza 5.3f, wymagane do poprawnego wpięcia do
`pit_fundamentals.build_annual_fundamentals_periods_as_of`): gdy podany,
WSZYSTKIE komponenty (current/noncurrent/NotesPayable/DebtCurrent/
leasing/short-term) są filtrowane do `end == target_end` PRZED
`value_as_of` — ten sam wzorzec "filtruj do konkretnego end, potem PIT",
co reszta pól "instant" w `pit_fundamentals.py` (cash_and_equivalents
itd.). Bez tego, total_debt obliczony dla NAJNOWSZEGO dostępnego
instant (per tag, niezależnie) mógłby nie odpowiadać balance-sheet
instant konkretnego `FundamentalsPeriod`, do którego jest przypisywany
— złamałoby to tę samą zasadę "ten sam instant", która już chroni EBITDA
(patrz `pit_fundamentals.py`, zasada 3). `target_end=None` (domyślnie)
zachowuje dotychczasowe zachowanie (najnowszy PIT-dostępny instant per
tag, używane w diagnostyce i testach jednostkowych poniżej) — current/
noncurrent nadal muszą mieć zgodny `end`, inaczej `END_DATE_MISMATCH`."""

from __future__ import annotations

from dataclasses import dataclass, field

from buffett_scanner.point_in_time import PitFact, extract_fact_history, value_as_of

_LONG_TERM_DEBT_FAMILY_TAGS = ("LongTermDebt", "LongTermDebtCurrent", "LongTermDebtNoncurrent")

LTD_CURRENT_TAG = "LongTermDebtCurrent"
LTD_NONCURRENT_TAG = "LongTermDebtNoncurrent"
NOTES_PAYABLE_TAG = "NotesPayable"
DEBT_CURRENT_SYNONYM_TAG = "DebtCurrent"

CURRENT_PLUS_NONCURRENT = "CURRENT_PLUS_NONCURRENT"
NOTES_PAYABLE_ONLY = "NOTES_PAYABLE_ONLY"
NONCURRENT_PLUS_DEBTCURRENT_SYNONYM = "NONCURRENT_PLUS_DEBTCURRENT_SYNONYM"
INSUFFICIENT_DATA = "INSUFFICIENT_DATA"

TIER_1 = "TIER_1"
TIER_2 = "TIER_2"


@dataclass(frozen=True)
class TotalDebtResult:
    value: float | None
    debt_resolution_method: str  # CURRENT_PLUS_NONCURRENT | NOTES_PAYABLE_ONLY | NONCURRENT_PLUS_DEBTCURRENT_SYNONYM | INSUFFICIENT_DATA
    confidence_tier: str | None  # TIER_1 | TIER_2 | None (None tylko dla INSUFFICIENT_DATA)
    reason: str | None  # wypełnione, gdy value is None — wyjaśnia dlaczego
    balance_sheet_instant: str | None = None  # end użyty w `value` (audyt)
    component_tags: tuple[str, ...] = ()
    component_values: dict[str, float] = field(default_factory=dict)
    # tag -> {filed, form, accession_number, fiscal_year, fiscal_period} (audyt/provenance)
    component_provenance: dict[str, dict] = field(default_factory=dict)
    # Pola diagnostyczne (Decyzja właścicielki: przechowuj, NIGDY nie
    # dodawaj automatycznie do `value` — patrz docstring modułu).
    finance_lease_liability_supplemental: float | None = None
    short_term_borrowings_supplemental: float | None = None


def _filter_to_end(history: list[PitFact], target_end: str | None) -> list[PitFact]:
    if target_end is None:
        return history
    return [f for f in history if f.end == target_end]


def _provenance(fact: PitFact) -> dict:
    return {
        "filed": fact.filed,
        "form": fact.form,
        "accession_number": fact.accession_number,
        "fiscal_year": fact.fiscal_year,
        "fiscal_period": fact.fiscal_period,
    }


def _company_ever_reported_tag(company_facts: dict, tag: str) -> bool:
    """True, jeśli spółka KIEDYKOLWIEK (dowolna data, dowolny filing) w
    swojej CAŁEJ historii Company Facts użyła tego tagu — niezależnie od
    PIT (`as_of_date`/`target_end`). Nigdy filtrowane do konkretnego
    instant — warunek wyłączności dotyczy całej historii, nie jednej
    daty (patrz Decyzja 5, docstring modułu)."""
    return bool(extract_fact_history(company_facts, tag))


def _company_ever_reported_long_term_debt_family(company_facts: dict) -> bool:
    """True, jeśli spółka KIEDYKOLWIEK użyła dowolnego tagu z rodziny
    `LongTermDebt*` — blokuje `NotesPayable`-fallback dla spółek jak
    EQT, gdzie ten tag jest tylko małym podkomponentem przy dominującej
    rodzinie `LongTermDebt`."""
    return any(_company_ever_reported_tag(company_facts, tag) for tag in _LONG_TERM_DEBT_FAMILY_TAGS)


def _supplemental_lease_and_short_term(
    company_facts: dict, as_of_date: str, target_end: str | None
) -> tuple[float | None, float | None]:
    """Pola DIAGNOSTYCZNE (Decyzja 2 + ostrożność wobec CommercialPaper/
    ShortTermBorrowings) — liczone i zwracane, ale NIGDY nie wchodzą do
    `TotalDebtResult.value`. Filtrowane do `target_end`, jeśli podany,
    żeby odpowiadały temu samemu instant co `value`."""
    finance_lease_history = _filter_to_end(
        extract_fact_history(company_facts, "FinanceLeaseLiability"), target_end
    )
    finance_lease = value_as_of(finance_lease_history, as_of_date)
    if finance_lease is not None:
        finance_lease_val: float | None = finance_lease.val
    else:
        fl_current = value_as_of(
            _filter_to_end(extract_fact_history(company_facts, "FinanceLeaseLiabilityCurrent"), target_end),
            as_of_date,
        )
        fl_noncurrent = value_as_of(
            _filter_to_end(extract_fact_history(company_facts, "FinanceLeaseLiabilityNoncurrent"), target_end),
            as_of_date,
        )
        if fl_current is not None and fl_noncurrent is not None and fl_current.end == fl_noncurrent.end:
            finance_lease_val = fl_current.val + fl_noncurrent.val
        else:
            finance_lease_val = None

    cp = value_as_of(_filter_to_end(extract_fact_history(company_facts, "CommercialPaper"), target_end), as_of_date)
    stb = value_as_of(
        _filter_to_end(extract_fact_history(company_facts, "ShortTermBorrowings"), target_end), as_of_date
    )
    short_term_vals = [f.val for f in (cp, stb) if f is not None]
    short_term_val = sum(short_term_vals) if short_term_vals else None

    return finance_lease_val, short_term_val


def compute_total_debt_as_of(
    company_facts: dict, as_of_date: str, *, target_end: str | None = None
) -> TotalDebtResult:
    """Zob. docstring modułu dla pełnej decyzji metodologicznej
    (właścicielka, 2026-10-04/05). Czysta funkcja, PIT-poprawna
    (`filed <= as_of_date` przez `value_as_of`), nigdy nie zgaduje/
    imputuje/estymuje brakującego składnika.

    `target_end`: patrz docstring modułu (parametr). Gdy `None`
    (domyślnie), każdy tag jest rozwiązywany do swojego NAJNOWSZEGO
    PIT-dostępnego instant niezależnie — current/noncurrent muszą mieć
    zgodny `end`, inaczej `INSUFFICIENT_DATA` (end mismatch). Gdy podany
    (wymagane wywołanie z `pit_fundamentals.py`), wszystkie komponenty
    są filtrowane do tego `end` przed PIT lookup — eliminuje możliwość
    end mismatch z konstrukcji, bo current/noncurrent są odczytywane z
    tego samego, jawnie wybranego balance-sheet instant."""
    finance_lease_val, short_term_val = _supplemental_lease_and_short_term(company_facts, as_of_date, target_end)

    current_history = _filter_to_end(extract_fact_history(company_facts, LTD_CURRENT_TAG), target_end)
    noncurrent_history = _filter_to_end(extract_fact_history(company_facts, LTD_NONCURRENT_TAG), target_end)
    current = value_as_of(current_history, as_of_date)
    noncurrent = value_as_of(noncurrent_history, as_of_date)

    if current is not None and noncurrent is not None:
        if current.end != noncurrent.end:
            return TotalDebtResult(
                value=None, debt_resolution_method=INSUFFICIENT_DATA, confidence_tier=None,
                reason=(
                    f"LongTermDebtCurrent (end={current.end}) i LongTermDebtNoncurrent "
                    f"(end={noncurrent.end}) nie dotyczą tego samego balance-sheet instant."
                ),
                finance_lease_liability_supplemental=finance_lease_val,
                short_term_borrowings_supplemental=short_term_val,
            )
        return TotalDebtResult(
            value=current.val + noncurrent.val,
            debt_resolution_method=CURRENT_PLUS_NONCURRENT, confidence_tier=TIER_1, reason=None,
            balance_sheet_instant=current.end,
            component_tags=(LTD_CURRENT_TAG, LTD_NONCURRENT_TAG),
            component_values={LTD_CURRENT_TAG: current.val, LTD_NONCURRENT_TAG: noncurrent.val},
            component_provenance={LTD_CURRENT_TAG: _provenance(current), LTD_NONCURRENT_TAG: _provenance(noncurrent)},
            finance_lease_liability_supplemental=finance_lease_val,
            short_term_borrowings_supplemental=short_term_val,
        )

    if current is None and noncurrent is None:
        if not _company_ever_reported_long_term_debt_family(company_facts):
            notes_payable_history = _filter_to_end(extract_fact_history(company_facts, NOTES_PAYABLE_TAG), target_end)
            notes_payable = value_as_of(notes_payable_history, as_of_date)
            if notes_payable is not None:
                return TotalDebtResult(
                    value=notes_payable.val,
                    debt_resolution_method=NOTES_PAYABLE_ONLY, confidence_tier=TIER_1, reason=None,
                    balance_sheet_instant=notes_payable.end,
                    component_tags=(NOTES_PAYABLE_TAG,),
                    component_values={NOTES_PAYABLE_TAG: notes_payable.val},
                    component_provenance={NOTES_PAYABLE_TAG: _provenance(notes_payable)},
                    finance_lease_liability_supplemental=finance_lease_val,
                    short_term_borrowings_supplemental=short_term_val,
                )
            return TotalDebtResult(
                value=None, debt_resolution_method=INSUFFICIENT_DATA, confidence_tier=None,
                reason="Brak rodziny LongTermDebt* w całej historii spółki i brak NotesPayable na tę datę.",
                finance_lease_liability_supplemental=finance_lease_val,
                short_term_borrowings_supplemental=short_term_val,
            )
        return TotalDebtResult(
            value=None, debt_resolution_method=INSUFFICIENT_DATA, confidence_tier=None,
            reason=(
                "Brakuje LongTermDebtCurrent, LongTermDebtNoncurrent na tę datę (PIT) — "
                "NotesPayable-fallback zablokowany, bo spółka raportuje rodzinę LongTermDebt "
                "w innych okresach (ryzyko niedoszacowania jak u EQT Corp w diagnostyce v1.46)."
            ),
            finance_lease_liability_supplemental=finance_lease_val,
            short_term_borrowings_supplemental=short_term_val,
        )

    # Dokładnie jeden z (current, noncurrent) jest None.
    if noncurrent is not None and current is None:
        # Tier 2 (Decyzja F, 2026-10-05): NONCURRENT_PLUS_DEBTCURRENT_SYNONYM
        # -- wyłącznie gdy spółka NIGDY (cała historia) nie raportowała
        # LongTermDebtCurrent, czyli DebtCurrent nie może być aliasem
        # czegoś, co ta spółka już gdzie indziej raportuje tym tagiem.
        if not _company_ever_reported_tag(company_facts, LTD_CURRENT_TAG):
            debt_current_history = _filter_to_end(
                extract_fact_history(company_facts, DEBT_CURRENT_SYNONYM_TAG), target_end
            )
            debt_current = value_as_of(debt_current_history, as_of_date)
            if debt_current is not None and debt_current.end == noncurrent.end:
                return TotalDebtResult(
                    value=noncurrent.val + debt_current.val,
                    debt_resolution_method=NONCURRENT_PLUS_DEBTCURRENT_SYNONYM, confidence_tier=TIER_2, reason=None,
                    balance_sheet_instant=noncurrent.end,
                    component_tags=(LTD_NONCURRENT_TAG, DEBT_CURRENT_SYNONYM_TAG),
                    component_values={LTD_NONCURRENT_TAG: noncurrent.val, DEBT_CURRENT_SYNONYM_TAG: debt_current.val},
                    component_provenance={
                        LTD_NONCURRENT_TAG: _provenance(noncurrent),
                        DEBT_CURRENT_SYNONYM_TAG: _provenance(debt_current),
                    },
                    finance_lease_liability_supplemental=finance_lease_val,
                    short_term_borrowings_supplemental=short_term_val,
                )
        missing = "LongTermDebtCurrent"
    else:
        missing = "LongTermDebtNoncurrent"

    return TotalDebtResult(
        value=None, debt_resolution_method=INSUFFICIENT_DATA, confidence_tier=None,
        reason=(
            f"Brakuje {missing} na tę datę (PIT) — fallback na inną rodzinę tagów "
            f"niedostępny lub zablokowany (patrz Decyzje 1/5, docstring modułu)."
        ),
        finance_lease_liability_supplemental=finance_lease_val,
        short_term_borrowings_supplemental=short_term_val,
    )

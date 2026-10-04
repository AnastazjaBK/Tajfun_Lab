"""`total_debt` z SEC XBRL (Faza 5.3d/5.3e, Decyzja właścicielki
2026-10-04, po diagnostyce v1.46 na 10 realnych spółkach — AAPL/MSFT/KO
+ TERADYNE/JABIL [proste] + PG&E/Constellation Energy/EQT/DOW
[złożone] + Realty Income [REIT]).

Decyzje metodologiczne (właścicielka, verbatim z tury 2026-10-04):

1. Goły `LongTermDebt` NIGDY nie jest używany jako automatyczny
   fallback. Diagnostyka v1.46 pokazała, że jego semantyka NIE jest
   stabilna między filerami: u większości spółek (KO, MSFT, EQT,
   JABIL) `LongTermDebt` = `LongTermDebtCurrent + LongTermDebtNoncurrent`
   w tym samym filingu — ale u PG&E Corp, w TYM SAMYM 10-K
   (`accn=0001004980-26-000009`, `end=2025-12-31`), `LongTermDebt`
   jest IDENTYCZNY z `LongTermDebtNoncurrent` (57 387 000 000 = 57 387
   000 000), z `LongTermDebtCurrent` (821 000 000) zgłoszonym OSOBNO,
   NIE odjętym. Bez niezależnego sposobu odróżnienia "total" od
   "noncurrent-only" per filer -> nie zgadujemy, nigdy nie używamy tego
   tagu.

2. `FinanceLeaseLiability`/`...AndCapitalLeaseObligations`/`...AndFinance
   LeaseObligations` NIGDY nie wchodzą do `total_debt`. Diagnostyka
   potwierdziła realne ryzyko double counting: u DOW Inc tag
   `LongTermDebtAndCapitalLeaseObligations` JUŻ zawiera leasing (filer
   przełączył się na ten skumulowany koncept, zastępując gołe
   `LongTermDebt`); osobne dodanie `FinanceLeaseLiability` by go
   podwoiło. Leasing jest przechowywany jako OSOBNE pole diagnostyczne
   (`finance_lease_liability_supplemental`), NIGDY dodawany
   automatycznie do `value`.

3. Nie zwiększamy coverage kosztem niejednoznacznej semantyki — brak
   bezpiecznego, rozłącznego zestawu komponentów = `None`, nigdy
   estymacja/imputacja/zgadywanie.

HIERARCHIA:

PRIMARY (jedyny automatycznie sumowany wariant):
    total_debt = LongTermDebtCurrent + LongTermDebtNoncurrent
TYLKO gdy oba fakty: są PIT-dostępne (`filed <= as_of_date`, przez
`value_as_of` — ten sam mechanizm co resztę PIT w tym projekcie),
dotyczą TEGO SAMEGO balance-sheet instant (identyczny `end`), i OBA
istnieją — brak jednego z dwóch NIGDY nie jest traktowany jako zero.

SECONDARY (fallback WYŁĄCZNIE dla spółek, które w CAŁEJ swojej
historii raportowania nigdy nie użyły rodziny `LongTermDebt`/
`LongTermDebtCurrent`/`LongTermDebtNoncurrent` — wzorzec Realty Income/
REIT, które tagują cały dług jako `NotesPayable` bez podziału
current/noncurrent):
    total_debt = NotesPayable (pojedynczy, PIT-poprawny fakt)
Ten fallback jest ZABLOKOWANY, jeśli spółka KIEDYKOLWIEK (w całej
historii, nie tylko na tę datę) raportowała cokolwiek z rodziny
`LongTermDebt*` — diagnostyka pokazała (EQT Corp), że `NotesPayable`
bywa MAŁYM podkomponentem przy spółce, której realny dług jest w
większości w rodzinie `LongTermDebt` (u EQT `NotesPayable`≈105 mln USD
vs `LongTermDebtNoncurrent`≈7,3 mld USD — użycie samego `NotesPayable`
jako total byłoby drastycznym niedoszacowaniem).

NIE WCHODZI do `total_debt` na tym etapie (przechowywane jako pola
diagnostyczne, osobno, nigdy dodawane automatycznie):
- `FinanceLeaseLiability(Current/Noncurrent)` — Decyzja 2.
- `CommercialPaper`/`ShortTermBorrowings` — semantycznie wygląda na
  rozłączny, dodatkowy krótkoterminowy dług (inny instrument niż
  "current portion of long-term debt"; u AAPL oba tagi są niezależnie
  niezerowe w tym samym okresie), ALE tej hipotezy NIE DA SIĘ udowodnić
  wyłącznie z zagregowanych SEC `company_facts` — brak niezależnego
  źródła (np. harmonogramu zapadalności z notes) do krzyżowej
  weryfikacji braku overlap. Traktowane z tą samą ostrożnością co
  leasing, dopóki nie znajdziemy sposobu to udowodnić.

WYKLUCZONE CAŁKOWICIE:
- `DebtInstrumentCarryingAmount` — to tag INSTRUMENT-poziomu (jedna
  emisja/nota), nie company-level total. Potwierdzone empirycznie: u
  EQT = 0 wielokrotnie mimo realnego długu >5 mld USD; u Realty Income
  ≈166 mln USD, podczas gdy ich realny dług (`NotesPayable`) to >25 mld
  USD.
- `...AndCapitalLeaseObligations`/`...AndFinanceLeaseObligations` jako
  fallback — z definicji już zawierają leasing, złamałoby to Decyzję 2,
  i nie ma sposobu oddzielenia samego długu od leasingu w zagregowanym
  tagu.
- Goły `LongTermDebt` — Decyzja 1."""

from __future__ import annotations

from dataclasses import dataclass

from buffett_scanner.point_in_time import extract_fact_history, value_as_of

_LONG_TERM_DEBT_FAMILY_TAGS = ("LongTermDebt", "LongTermDebtCurrent", "LongTermDebtNoncurrent")

CURRENT_PLUS_NONCURRENT = "CURRENT_PLUS_NONCURRENT"
NOTES_PAYABLE_ONLY = "NOTES_PAYABLE_ONLY"
INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


@dataclass(frozen=True)
class TotalDebtResult:
    value: float | None
    variant: str  # CURRENT_PLUS_NONCURRENT | NOTES_PAYABLE_ONLY | INSUFFICIENT_DATA
    reason: str | None  # wypełnione, gdy value is None — wyjaśnia dlaczego
    as_of_end_date: str | None = None  # balance-sheet instant użyty w `value` (audyt)
    # Pola diagnostyczne (Decyzja właścicielki: przechowuj, NIGDY nie
    # dodawaj automatycznie do `value` — patrz docstring modułu).
    finance_lease_liability_supplemental: float | None = None
    short_term_borrowings_supplemental: float | None = None


def _company_ever_reported_long_term_debt_family(company_facts: dict) -> bool:
    """True, jeśli spółka KIEDYKOLWIEK (dowolna data, dowolny filing) w
    swojej historii użyła dowolnego tagu z rodziny `LongTermDebt*` —
    niezależnie od tego, czy jest dostępny na konkretne `as_of_date`.
    Blokuje `NotesPayable`-fallback dla spółek jak EQT, gdzie ten tag
    jest tylko małym podkomponentem przy dominującej rodzinie
    `LongTermDebt`."""
    return any(extract_fact_history(company_facts, tag) for tag in _LONG_TERM_DEBT_FAMILY_TAGS)


def _supplemental_lease_and_short_term(
    company_facts: dict, as_of_date: str
) -> tuple[float | None, float | None]:
    """Pola DIAGNOSTYCZNE (Decyzja 2 + ostrożność wobec CommercialPaper/
    ShortTermBorrowings) — liczone i zwracane, ale NIGDY nie wchodzą do
    `TotalDebtResult.value`."""
    finance_lease = value_as_of(extract_fact_history(company_facts, "FinanceLeaseLiability"), as_of_date)
    if finance_lease is not None:
        finance_lease_val: float | None = finance_lease.val
    else:
        fl_current = value_as_of(extract_fact_history(company_facts, "FinanceLeaseLiabilityCurrent"), as_of_date)
        fl_noncurrent = value_as_of(extract_fact_history(company_facts, "FinanceLeaseLiabilityNoncurrent"), as_of_date)
        if fl_current is not None and fl_noncurrent is not None and fl_current.end == fl_noncurrent.end:
            finance_lease_val = fl_current.val + fl_noncurrent.val
        else:
            finance_lease_val = None

    cp = value_as_of(extract_fact_history(company_facts, "CommercialPaper"), as_of_date)
    stb = value_as_of(extract_fact_history(company_facts, "ShortTermBorrowings"), as_of_date)
    short_term_vals = [f.val for f in (cp, stb) if f is not None]
    short_term_val = sum(short_term_vals) if short_term_vals else None

    return finance_lease_val, short_term_val


def compute_total_debt_as_of(company_facts: dict, as_of_date: str) -> TotalDebtResult:
    """Zob. docstring modułu dla pełnej decyzji metodologicznej
    (właścicielka, 2026-10-04, po diagnostyce v1.46). Czysta funkcja,
    PIT-poprawna (`filed <= as_of_date` przez `value_as_of` — ten sam
    mechanizm, co reszta PIT w tym projekcie), nigdy nie
    zgaduje/imputuje/estymuje brakującego składnika."""
    finance_lease_val, short_term_val = _supplemental_lease_and_short_term(company_facts, as_of_date)

    current = value_as_of(extract_fact_history(company_facts, "LongTermDebtCurrent"), as_of_date)
    noncurrent = value_as_of(extract_fact_history(company_facts, "LongTermDebtNoncurrent"), as_of_date)

    if current is not None and noncurrent is not None:
        if current.end != noncurrent.end:
            return TotalDebtResult(
                value=None, variant=INSUFFICIENT_DATA,
                reason=(
                    f"LongTermDebtCurrent (end={current.end}) i LongTermDebtNoncurrent "
                    f"(end={noncurrent.end}) nie dotyczą tego samego balance-sheet instant."
                ),
                finance_lease_liability_supplemental=finance_lease_val,
                short_term_borrowings_supplemental=short_term_val,
            )
        return TotalDebtResult(
            value=current.val + noncurrent.val, variant=CURRENT_PLUS_NONCURRENT, reason=None,
            as_of_end_date=current.end,
            finance_lease_liability_supplemental=finance_lease_val,
            short_term_borrowings_supplemental=short_term_val,
        )

    if current is None and noncurrent is None and not _company_ever_reported_long_term_debt_family(company_facts):
        notes_payable = value_as_of(extract_fact_history(company_facts, "NotesPayable"), as_of_date)
        if notes_payable is not None:
            return TotalDebtResult(
                value=notes_payable.val, variant=NOTES_PAYABLE_ONLY, reason=None,
                as_of_end_date=notes_payable.end,
                finance_lease_liability_supplemental=finance_lease_val,
                short_term_borrowings_supplemental=short_term_val,
            )
        return TotalDebtResult(
            value=None, variant=INSUFFICIENT_DATA,
            reason="Brak rodziny LongTermDebt* w całej historii spółki i brak NotesPayable na tę datę.",
            finance_lease_liability_supplemental=finance_lease_val,
            short_term_borrowings_supplemental=short_term_val,
        )

    missing = [name for name, fact in (("LongTermDebtCurrent", current), ("LongTermDebtNoncurrent", noncurrent)) if fact is None]
    return TotalDebtResult(
        value=None, variant=INSUFFICIENT_DATA,
        reason=(
            f"Brakuje {', '.join(missing)} na tę datę (PIT) — NotesPayable-fallback "
            f"zablokowany, bo spółka raportuje rodzinę LongTermDebt w innych okresach "
            f"(ryzyko niedoszacowania jak u EQT Corp w diagnostyce v1.46)."
        ),
        finance_lease_liability_supplemental=finance_lease_val,
        short_term_borrowings_supplemental=short_term_val,
    )

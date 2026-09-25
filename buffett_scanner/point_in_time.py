"""Prototyp warstwy point-in-time (PIT) na SEC XBRL — Faza 5, punkt 5.1
(OPEN BLOCKER 1, sekcja 13 design review).

Cel: udowodnić, że da się deterministycznie odtworzyć "jaka była
ostatnia wartość X *filed* na dzień <= D" z danych SEC EDGAR XBRL
company-facts, bez zgadywania — komercyjni dostawcy (FMP itp.) dają
tylko dzisiejszy, skorygowany widok, nie stan wiedzy rynku na
historyczną datę. To PROTOTYP na kilku spółkach testowych (sekcja 15,
punkt 5.1), nie produkcyjny system PIT dla całego uniwersum — pełne
pokrycie wszystkich wariantów tagowania XBRL to praca dla późniejszej
fazy, dopiero po potwierdzeniu, że sama metoda działa.

Różne spółki tagują te same koncepty księgowe różnymi tagami XBRL
(np. `Revenues` vs `RevenueFromContractWithCustomerExcludingAssessedTax`
po wejściu ASC 606) — dlatego dla każdego kanonicznego konceptu
próbujemy listę kandydatów w kolejności i JAWNIE zwracamy, który
faktycznie zadziałał, zamiast zakładać jeden uniwersalny tag (ten sam
duch co defensywne parsowanie FMP w Fazie 0/1).

Zero I/O w tym module — `SecEdgarClient.get_company_facts` pobiera dane,
funkcje tutaj są czystymi transformacjami już pobranego JSON-a.
"""

from __future__ import annotations

from dataclasses import dataclass

# Kandydaci XBRL us-gaap per kanoniczny koncept, w kolejności próbowania.
# Lista NIE jest wyczerpująca — prototyp na kilku spółkach testowych,
# nie pełne pokrycie wszystkich wariantów tagowania w uniwersum S&P 500.
CANDIDATE_TAGS: dict[str, list[str]] = {
    "net_income": ["NetIncomeLoss", "ProfitLoss"],
    "revenue": [
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
    ],
}


@dataclass(frozen=True)
class PitFact:
    end: str  # koniec okresu, którego dotyczy fakt (np. "2024-09-28")
    val: float
    filed: str  # data faktycznego złożenia — klucz zapytań PIT
    fiscal_year: str | None
    fiscal_period: str | None
    form: str | None
    accession_number: str | None


def extract_fact_history(company_facts: dict, tag: str, *, unit: str = "USD") -> list[PitFact]:
    """Wyciąga historię faktów dla jednego tagu XBRL us-gaap z surowej
    odpowiedzi company-facts, posortowaną rosnąco po `filed`. Brak tagu
    w danych spółki -> pusta lista, NIGDY wyjątek — różne spółki tagują
    różnymi tagami, to oczekiwane, nie błąd. Wpis bez `filed`/`val`/`end`
    jest pomijany, nigdy nie fabrykujemy brakującego pola."""
    try:
        entries = company_facts["facts"]["us-gaap"][tag]["units"][unit]
    except (KeyError, TypeError):
        return []
    facts = [
        PitFact(
            end=e["end"], val=e["val"], filed=e["filed"],
            fiscal_year=e.get("fy"), fiscal_period=e.get("fp"),
            form=e.get("form"), accession_number=e.get("accn"),
        )
        for e in entries
        if "filed" in e and "val" in e and "end" in e
    ]
    facts.sort(key=lambda f: f.filed)
    return facts


def find_first_matching_tag(
    company_facts: dict, canonical_concept: str, *, unit: str = "USD"
) -> tuple[str, list[PitFact]] | None:
    """Próbuje kandydatów z `CANDIDATE_TAGS[canonical_concept]` po
    kolei, zwraca `(tag, historia)` dla pierwszego z niepustą historią,
    albo `None`, jeśli żaden kandydat nie pasuje."""
    for tag in CANDIDATE_TAGS.get(canonical_concept, []):
        history = extract_fact_history(company_facts, tag, unit=unit)
        if history:
            return tag, history
    return None


def value_as_of(fact_history: list[PitFact], as_of_date: str) -> PitFact | None:
    """Rdzeń point-in-time: "jaka była ostatnia wartość X *filed* na
    dzień <= D". Zwraca najnowszy (po `filed`) fakt spośród złożonych
    on/before `as_of_date`, albo `None`, jeśli nic jeszcze nie było
    złożone na ten dzień — poprawne zachowanie, nigdy nie zgadujemy
    wartości sprzed pierwszego filingu.

    To jest dokładnie mechanizm, który eliminuje look-ahead bias w
    backteście (sekcja 13): zapytanie o datę SPRZED restatement musi
    zwrócić oryginalną, jeszcze nieskorygowaną wartość, nie tę, którą
    rynek pozna dopiero później."""
    eligible = [f for f in fact_history if f.filed <= as_of_date]
    if not eligible:
        return None
    return max(eligible, key=lambda f: f.filed)

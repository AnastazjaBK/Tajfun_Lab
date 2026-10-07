"""Tłumaczenie surowych/technicznych stringów systemu na język
zrozumiały dla nietechnicznego użytkownika (Faza 7, UI + PORTFOLIO V0).

JEDNO miejsce w całym UI wykonujące ten przekład — żadna techniczna
etykieta (`FAILED`, `UNCALIBRATED`, nazwa pola z `scanner.py`) nie ma
wyciekać bezpośrednio na ekran. Status `FAILED` jest statusem RAPORTU
(analiza jakościowa LLM niekompletna), NIGDY oceną samej spółki —
Decyzja właścicielki, sekcja 4 specyfikacji UI.
"""

from __future__ import annotations

ANALYSIS_STATUS_LABELS: dict[str, str] = {
    "COMPLETE": "Analiza jakościowa kompletna",
    "FAILED": "Analiza jakościowa niekompletna",
    "PENDING": "Analiza w toku",
    "NOT_SHORTLISTED": "Poza shortlistą tego skanu",
}

# Nazwy dokładnie takie, jak zwraca `scanner.evaluate_decline_flags` --
# nigdy nie zgadywane, zweryfikowane przez odczyt scanner.py.
DECLINE_FLAG_LABELS: dict[str, str] = {
    "daily_decline": "spadek dzienny",
    "week_decline": "spadek tygodniowy",
    "month_decline": "spadek miesięczny",
    "quarter_decline": "spadek kwartalny",
    "drawdown_from_52w_high": "spadek od szczytu 52-tygodniowego",
    "abnormal_volume": "nietypowy wolumen obrotu",
}

DECISION_STATUS_LABELS: dict[str, str] = {
    "WATCH": "Obserwuję",
    "REJECT": "Odrzucam",
    "SNOOZE": "Sprawdzam",
    "BOUGHT": "Kupiłam/Kupiłem",
}

HOLDING_ACTION_LABELS: dict[str, str] = {
    "HOLD": "Trzymam",
    "REDUCE": "Redukuję",
    "SOLD": "Sprzedane",
    "REVIEW_LATER": "Do przeglądu",
}

BROKER_LABELS: dict[str, str] = {
    "TRADE_REPUBLIC": "Trade Republic",
    "REVOLUT": "Revolut",
    "OTHER": "Inny",
}

ACQUISITION_TYPE_LABELS: dict[str, str] = {
    "BUY": "Zakup",
    "BONUS": "Bonus",
}

# Decyzja właścicielki, sekcja 21 specyfikacji UI: NIGDY starego
# "UNCALIBRATED until Phase 5" ani sugestii, że backtesting/kalibracja
# wciąż czeka na wykonanie. Treść poniżej cytuje wprost ustalenia z
# "Faza 6 — DOMKNIĘCIE MVP V0" (design review) -- nie jest wymyślona.
METHODOLOGY_DISCLAIMER = (
    "Scanner jest narzędziem wspierającym analizę inwestycyjną, a nie "
    "zwalidowanym modelem przewidującym ponadprzeciętne stopy zwrotu. "
    "Backtest i kalibracja zostały wykonane i zamrożone — finalny test na "
    "danych historycznych (2022–2026) nie wykazał przewagi inwestycyjnej "
    "modelu względem rynku. To jest udokumentowane, trwałe ograniczenie "
    "metodologiczne, nie etap „w budowie”."
)


# Sekcja 17/18 specyfikacji UI: "Jak to czytać?" -- wyjaśnienie pojęć
# prostym językiem, BEZ usuwania profesjonalnych terminów (żeby
# właścicielka mogła nadal rozpoznać je w raportach/analizach). Każdy
# wpis to (termin_profesjonalny, wyjaśnienie_prostym_językiem).
GLOSSARY: tuple[tuple[str, str], ...] = (
    (
        "DCF (zdyskontowane przepływy pieniężne)",
        "Metoda szacowania wartości firmy na podstawie tego, ile gotówki firma "
        "prawdopodobnie wygeneruje w przyszłości, przeliczonej na dzisiejszą wartość. "
        "To MODEL oparty na założeniach, nie pomiar — inna firma licząca inaczej może dostać inny wynik.",
    ),
    (
        "Margines bezpieczeństwa (Margin of Safety, MoS)",
        "Różnica między tym, ile model szacuje, że firma jest warta, a tym, ile kosztuje dziś na giełdzie. "
        "Dodatni margines = cena rynkowa niższa od szacowanej wartości według modelu "
        "(ale to wciąż szacunek, nie gwarancja okazji).",
    ),
    (
        "Scenariusze Pesymistyczny/Bazowy/Optymistyczny (Bear/Base/Bull)",
        "Model liczy wycenę trzykrotnie, przy różnych założeniach: ostrożnych (Pesymistyczny), "
        "najbardziej prawdopodobnych w ocenie modelu (Bazowy) i korzystnych (Optymistyczny) — "
        "żeby pokazać rozpiętość możliwych wyników, zamiast jednej, fałszywie precyzyjnej liczby.",
    ),
    (
        "FCF (wolne przepływy pieniężne, Free Cash Flow)",
        "Gotówka, jaka zostaje firmie po opłaceniu bieżącej działalności i inwestycji w swój biznes — "
        "to, co firma realnie mogłaby wypłacić właścicielom, spłacić dług albo zainwestować dalej.",
    ),
    (
        "Dług netto / EBITDA",
        "Dług firmy pomniejszony o jej gotówkę, podzielony przez w przybliżeniu roczny zysk operacyjny. "
        "Pokazuje, jak wiele \"lat\" takiego zysku zajęłoby spłacenie całego zadłużenia — "
        "wyższa liczba = firma bardziej zadłużona względem tego, ile zarabia.",
    ),
    (
        "Hard gate (twarda bramka)",
        "Zasada eliminująca spółkę z dalszej analizy automatycznie, bez oceny jakościowej, gdy dane "
        "deterministyczne (np. bardzo wysokie zadłużenie) wskazują na zbyt duże ryzyko — "
        "żeby nie tracić czasu na pogłębioną analizę spółek odpadających już na starcie.",
    ),
    (
        "Bull Case (argumenty za)",
        "Najmocniejsze powody, dla których inwestycja może się opłacić, zidentyfikowane przez model "
        "na podstawie dostępnych danych — nie obietnica, że tak się stanie.",
    ),
    (
        "Bear Case (argumenty przeciw)",
        "Najpoważniejsze ryzyka i powody, dla których inwestycja może się NIE opłacić — "
        "celowo pokazywane obok argumentów za, żeby uniknąć jednostronnego obrazu.",
    ),
    (
        "Thesis Invalidation (co obaliłoby tezę)",
        "Konkretne zdarzenia lub dane, które — gdyby się pojawiły — oznaczałyby, że pierwotne "
        "uzasadnienie inwestycji się nie sprawdziło. Warto je obserwować PO zakupie, nie tylko przed.",
    ),
    (
        "Biggest Unknown (największa niewiadoma)",
        "Najważniejsza rzecz, której model NIE wie albo nie jest w stanie ocenić na podstawie dostępnych "
        "danych, a która mogłaby zmienić ocenę spółki — uczciwe przyznanie granicy tego, co analiza pokrywa.",
    ),
)


def analysis_status_label(llm_status: str) -> str:
    return ANALYSIS_STATUS_LABELS.get(llm_status, llm_status)


def decline_flags_label(flags: list[str]) -> str:
    if not flags:
        return "—"
    return ", ".join(DECLINE_FLAG_LABELS.get(f, f) for f in flags)


def decision_status_label(status: str) -> str:
    return DECISION_STATUS_LABELS.get(status, status)


def holding_action_label(action: str) -> str:
    return HOLDING_ACTION_LABELS.get(action, action)


def broker_label(broker: str) -> str:
    return BROKER_LABELS.get(broker, broker)


def acquisition_types_label(acquisition_types: tuple[str, ...]) -> str:
    if not acquisition_types:
        return "—"
    return " + ".join(ACQUISITION_TYPE_LABELS.get(t, t) for t in acquisition_types)

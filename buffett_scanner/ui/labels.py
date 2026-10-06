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

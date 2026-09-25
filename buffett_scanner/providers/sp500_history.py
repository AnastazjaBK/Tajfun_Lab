"""Klient źródła społecznościowego `fja05680/sp500` (GitHub) — Faza 5,
punkt 5.2 (OPEN BLOCKER 2). Darmowe, bez klucza API, licencja MIT.
Plik `S&P 500 Historical Components & Changes (Updated).csv` to pełne
snapshoty składu S&P 500 per data zmiany (kolumny `date,tickers`),
potwierdzone bezpośrednim pobraniem w tej sesji (2026-09-25): zakres
1996-01-02 do 2026-08-18, format zgodny z `parse_components_csv`
(`universe_history.py`).

Traktowane jako JEDNO z dwóch źródeł do krzyżowej walidacji (Faza 5.2
plan, v1.21) — nie jako automatycznie przyjęte źródło prawdy."""

from __future__ import annotations

import httpx

COMPONENTS_CSV_URL = (
    "https://raw.githubusercontent.com/fja05680/sp500/master/"
    "S%26P%20500%20Historical%20Components%20%26%20Changes%20(Updated).csv"
)
DEFAULT_TIMEOUT = 30.0  # plik ma ~5.5MB, dłuższy limit niż inne klienty


class Sp500HistoryError(RuntimeError):
    pass


def fetch_components_csv(*, timeout: float = DEFAULT_TIMEOUT) -> str:
    """Pobiera surowy tekst CSV historycznego składu S&P 500 z
    `fja05680/sp500`. Zwraca tekst do sparsowania przez
    `universe_history.parse_components_csv` — brak logiki
    biznesowej tutaj, tylko transport."""
    try:
        resp = httpx.get(COMPONENTS_CSV_URL, timeout=timeout, follow_redirects=True)
    except httpx.HTTPError as exc:
        raise Sp500HistoryError(f"Błąd sieci przy pobieraniu fja05680/sp500: {exc}") from exc
    if resp.status_code != 200:
        raise Sp500HistoryError(
            f"fja05680/sp500 zwróciło status {resp.status_code} zamiast pliku CSV."
        )
    return resp.text

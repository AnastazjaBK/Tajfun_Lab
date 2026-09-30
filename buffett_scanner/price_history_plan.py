"""Plan pobrania historycznych cen (Faza 5.3, Price Data Proof Run) —
czysta logika, zero I/O. FMP `historical-price-eod/full` jest keyowany
po tickerze, nie po CIK, więc backfill musi iterować po PRZEDZIAŁACH
TICKERA (`universe_history.TickerInterval`, poziom przed scaleniem do
CIK w `universe_membership_build`), nie po CIK wprost — inaczej
zapytanie pod dzisiejszym tickerem spółki, która zmieniła nazwę (np.
META), mogłoby nie zwrócić historii sprzed zmiany zapisanej pod starym
symbolem (FB). Jeden `PriceFetchTask` = jedno zapytanie do FMP dla
jednego tickera w jego własnym oknie aktywności."""

from __future__ import annotations

from dataclasses import dataclass

from buffett_scanner.universe_history import TickerInterval


@dataclass(frozen=True)
class PriceFetchTask:
    cik: str
    ticker: str
    from_date: str
    to_date: str


def build_price_fetch_plan(
    ticker_intervals: list[TickerInterval],
    resolved: dict[str, str],
    *,
    cutoff_date: str,
    today: str,
) -> tuple[list[PriceFetchTask], tuple[str, ...]]:
    """Buduje listę zadań pobrania cen z przedziałów ticker-poziomu,
    używając WYŁĄCZNIE potwierdzonego mapowania `resolved` — ticker bez
    CIK jest pomijany (nie generuje zadania) i trafia jawnie do drugiego
    elementu zwracanej krotki (`unresolved`, posortowane, bez
    duplikatów), tak samo jak w `universe_membership_build`. Okno
    zapytania to przecięcie [`cutoff_date`, `today`] z własnym oknem
    aktywności tickera [`start_date`, `end_date` lub `today`] — nigdy
    nie pytamy o dane sprzed cutoff (poza zakresem D14) ani z przyszłości.
    Przedział, którego przecięcie jest puste (np. cały poza oknem
    cutoff-today), jest pomijany bez tworzenia zadania."""
    tasks: list[PriceFetchTask] = []
    unresolved: set[str] = set()
    for iv in ticker_intervals:
        cik = resolved.get(iv.ticker)
        if cik is None:
            unresolved.add(iv.ticker)
            continue
        from_date = max(cutoff_date, iv.start_date)
        to_date = min(today, iv.end_date) if iv.end_date is not None else today
        if from_date > to_date:
            continue
        tasks.append(PriceFetchTask(cik=cik, ticker=iv.ticker, from_date=from_date, to_date=to_date))
    tasks.sort(key=lambda t: (t.cik, t.from_date))
    return tasks, tuple(sorted(unresolved))


def detect_large_day_over_day_moves(
    rows: list[dict], *, threshold_pct: float = 35.0
) -> list[tuple[str, str, float]]:
    """Skanuje serię cen (posortowaną po `date`, pola `date`+`close`) w
    poszukiwaniu dnia-do-dnia zmiany `close` przekraczającej
    `threshold_pct` — kandydat na split (jeśli seria NIE jest
    adjustowana) albo anomalię danych (duplikat/gap/błędny tick). Nie
    rozstrzyga PRZYCZYNY — tylko zwraca surowe kandydatów (data
    poprzednia, data bieżąca, % zmiany) do ręcznej/empirycznej oceny,
    zgodnie z zasadą „nie zgaduj". Wiersz z brakującym/zerowym `close`
    jest pomijany (dzielenie przez zero niedefiniowalne, nie zgadujemy
    zastępczej wartości)."""
    candidates: list[tuple[str, str, float]] = []
    prev_row: dict | None = None
    for row in sorted(rows, key=lambda r: r["date"]):
        close = row.get("close")
        if close is None or close == 0:
            prev_row = None  # zerwij ciągłość — następne porównanie i tak nie miałoby sensu
            continue
        if prev_row is not None:
            prev_close = prev_row["close"]
            pct_change = (close - prev_close) / prev_close * 100
            if abs(pct_change) >= threshold_pct:
                candidates.append((prev_row["date"], row["date"], round(pct_change, 2)))
        prev_row = row
    return candidates

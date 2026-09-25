"""Analiza historycznego składu S&P 500 — Faza 5, punkt 5.2 (OPEN BLOCKER 2,
sekcja 13 design review). ETAP DIAGNOSTYCZNY, zatwierdzony przez
właściciela (2026-09-25): parsowanie i ocena jakości źródła
`fja05680/sp500`, ograniczone do okna 2012+ (Decyzja D14,
`LIMITED_BUT_HONEST`), z jawnym oznaczaniem `CIK_UNRESOLVED` zamiast
zgadywania mapowania ticker->CIK. **Nie zapisuje jeszcze do
`universe_membership`** — to osobna decyzja, wciąż do zatwierdzenia.

Format źródła (`S&P 500 Historical Components & Changes (Updated).csv`,
potwierdzony bezpośrednim pobraniem w tej sesji): dwie kolumny
`date,tickers`, jeden wiersz na KAŻDĄ datę, w której skład faktycznie
się zmienił (nie codziennie) — pełny snapshot tickerów aktywnych na tę
datę, nie log zdarzeń. Odtworzenie składu na dowolny dzień D to
"znajdź najnowszy wiersz z datą <= D" — dokładnie ten sam wzorzec co
`value_as_of` z Fazy 5.1 (`point_in_time.py`).

Zero I/O w tym module poza `parse_components_csv` (czysty parser
tekstu) — pobieranie pliku i mapowania SEC dzieje się w warstwie
providerów/CLI, tutaj tylko transformacje już pobranych danych.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass


@dataclass(frozen=True)
class ComponentsRow:
    date: str  # YYYY-MM-DD
    tickers: tuple[str, ...]


@dataclass(frozen=True)
class TickerInterval:
    ticker: str
    start_date: str  # data, od której ticker jest członkiem OKNA (>= cutoff)
    end_date: str | None  # None = wciąż obecny w ostatnim wierszu źródła


def parse_components_csv(csv_text: str) -> list[ComponentsRow]:
    """Parsuje surowy tekst CSV `date,tickers` na listę `ComponentsRow`,
    posortowaną rosnąco po dacie. Wiersz bez `date` lub bez niepustej
    listy tickerów jest pomijany, nigdy nie fabrykujemy brakujących
    danych. Zakłada nagłówek `date,tickers` w pierwszym wierszu."""
    reader = csv.reader(io.StringIO(csv_text))
    rows: list[ComponentsRow] = []
    for i, raw in enumerate(reader):
        if i == 0:
            continue  # nagłówek
        if len(raw) < 2:
            continue
        date, tickers_field = raw[0].strip(), raw[1]
        tickers = tuple(t.strip() for t in tickers_field.split(",") if t.strip())
        if not date or not tickers:
            continue
        rows.append(ComponentsRow(date=date, tickers=tickers))
    rows.sort(key=lambda r: r.date)
    return rows


def window_from_cutoff(rows: list[ComponentsRow], cutoff_date: str) -> list[ComponentsRow]:
    """Zwraca wiersze od BASELINE (ostatni wiersz z datą <= cutoff_date,
    ustanawiający skład "na wejściu" w okno) do końca źródła. Pusta
    lista, jeśli źródło nie ma żadnego wiersza <= cutoff_date — nigdy
    nie zgadujemy baseline'u sprzed pierwszego dostępnego wiersza."""
    baseline_idx = None
    for i, row in enumerate(rows):
        if row.date <= cutoff_date:
            baseline_idx = i
        else:
            break
    if baseline_idx is None:
        return []
    return rows[baseline_idx:]


def distinct_tickers(window_rows: list[ComponentsRow]) -> set[str]:
    """Zbiór wszystkich tickerów pojawiających się w którymkolwiek
    wierszu okna (baseline + kolejne zmiany)."""
    result: set[str] = set()
    for row in window_rows:
        result.update(row.tickers)
    return result


def build_ticker_intervals(window_rows: list[ComponentsRow], cutoff_date: str) -> list[TickerInterval]:
    """Przekształca sekwencję pełnych snapshotów w przedziały
    członkostwa per ticker, ograniczone do okna [cutoff_date, ostatni
    wiersz źródła]. Ticker obecny już w wierszu baseline dostaje
    `start_date = cutoff_date` (nie zakładamy dokładnej wcześniejszej
    daty wejścia — poza oknem to nieistotne dla D14). Ticker, który
    znika w kolejnym wierszu, dostaje `end_date` = data TEGO
    kolejnego wiersza (dzień, w którym wiadomo, że już go nie ma).
    Ticker wciąż obecny w ostatnim wierszu źródła dostaje
    `end_date = None`."""
    if not window_rows:
        return []

    open_since: dict[str, str] = {t: cutoff_date for t in window_rows[0].tickers}
    intervals: list[TickerInterval] = []

    prev_tickers = set(window_rows[0].tickers)
    for row in window_rows[1:]:
        current_tickers = set(row.tickers)
        entered = current_tickers - prev_tickers
        left = prev_tickers - current_tickers
        for t in left:
            intervals.append(TickerInterval(ticker=t, start_date=open_since.pop(t), end_date=row.date))
        for t in entered:
            open_since[t] = row.date
        prev_tickers = current_tickers

    for ticker, start in open_since.items():
        intervals.append(TickerInterval(ticker=ticker, start_date=start, end_date=None))

    intervals.sort(key=lambda iv: (iv.ticker, iv.start_date))
    return intervals


@dataclass(frozen=True)
class ResolutionResult:
    resolved: dict[str, str]  # ticker -> cik
    unresolved: tuple[str, ...]  # posortowane tickery bez pewnego mapowania


def resolve_tickers_to_cik(tickers: set[str], sec_ticker_map: dict[str, str]) -> ResolutionResult:
    """Rozwiązuje tickery na CIK wyłącznie przez potwierdzone mapowanie
    SEC (`sec_ticker_map`, np. z `company_tickers.json`, aktualne NA
    DZIŚ — nie punkt-w-czasie). Ticker nieobecny w mapowaniu ->
    `CIK_UNRESOLVED`, NIGDY nie zgadywany ani przypisywany domyślnie.
    Uwaga (do jawnego raportowania, nie ukrywania): nawet "resolved"
    niesie rezydualne ryzyko recyklingu tickera, bo `sec_ticker_map`
    jest dzisiejszym stanem, nie historycznym — to pierwszy przebieg
    diagnostyczny, nie finalna walidacja tożsamości."""
    resolved: dict[str, str] = {}
    unresolved: list[str] = []
    for ticker in sorted(tickers):
        cik = sec_ticker_map.get(ticker)
        if cik:
            resolved[ticker] = cik
        else:
            unresolved.append(ticker)
    return ResolutionResult(resolved=resolved, unresolved=tuple(unresolved))

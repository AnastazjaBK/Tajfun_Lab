"""Plan pobrania historycznych cen (Faza 5.3, Price Data Proof Run) —
czysta logika, zero I/O. FMP `historical-price-eod/full` jest keyowany
po tickerze, nie po CIK. Model v1.37 (po empirycznym znalezisku): dla
KAŻDEGO CIK pytamy o KAŻDY jego historyczny ticker w PEŁNYM oknie
aktywności tego CIK (nie tylko w oknie tego konkretnego tickera) —
FMP bywa niekonsekwentne w tym, pod którym symbolem trzyma historię
spółki po zmianie tickera (czasem cała historia jest wyłącznie pod
najnowszym symbolem, np. META; czasem każdy symbol poprawnie zwraca
tylko swój własny okres, np. ANTM/ELV) — więc pytamy o oba, żeby nie
zgadywać, i scalamy wynik po (cik, date) przez
`merge_ticker_price_rows`, z jawnym wykrywaniem konfliktów zamiast
cichego wyboru jednej wartości."""

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
    """Buduje listę zadań pobrania cen — jedno zadanie PER TICKER
    posiadany przez dany CIK, każde obejmujące PEŁNE okno aktywności
    tego CIK (nie własny pod-przedział tego konkretnego tickera).

    Zmiana modelu (v1.37, po empirycznym znalezisku Price Data Proof
    Run): pierwotny projekt pytał FMP o dany ticker tylko w jego
    własnym przedziale (np. `FB` wyłącznie 2013-2022). Realny test
    wykazał, że FMP historical-price-eod/full może przechowywać CAŁĄ
    historię pod NAJNOWSZYM tickerem spółki (np. cała historia FB jest
    dostępna wyłącznie pod symbolem `META`, zapytanie o `FB` zwraca 0
    wierszy) — pierwotny projekt cicho gubiłby lata danych dla każdej
    spółki, która kiedykolwiek zmieniła ticker. Poprawka: dla KAŻDEGO
    tickera CIK-a pytamy o CAŁE okno aktywności tego CIK — nadmiarowe/
    puste odpowiedzi dla tickerów spoza ich faktycznego okresu są
    akceptowalne (nie błąd), scalenie do jednej serii po (cik, date)
    robi `merge_ticker_price_rows`.

    CIK bez potwierdzonego mapowania jest pomijany (ticker trafia do
    `unresolved`, nigdy nie zgadywany). Okno CIK to PRZECIĘCIE
    [`cutoff_date`, `today`] z sumą wszystkich jego przedziałów
    tickera w tym oknie — nigdy nie pytamy o dane sprzed cutoff (D14)
    ani z przyszłości. To OGRANICZENIE chroni przed recyklingiem
    tickera (np. `BBBY`: spółka opuściła indeks w 2017, więc nawet
    jeśli ticker `BBBY` został później przypisany innej spółce, okno
    zapytania kończy się na 2017, nie sięga do przyszłego recyklingu)."""
    unresolved: set[str] = set()
    intervals_by_cik: dict[str, list[TickerInterval]] = {}
    for iv in ticker_intervals:
        cik = resolved.get(iv.ticker)
        if cik is None:
            unresolved.add(iv.ticker)
            continue
        intervals_by_cik.setdefault(cik, []).append(iv)

    tasks: list[PriceFetchTask] = []
    for cik, ivs in intervals_by_cik.items():
        span_start = min(iv.start_date for iv in ivs)
        span_end = today if any(iv.end_date is None for iv in ivs) else max(iv.end_date for iv in ivs)
        from_date = max(cutoff_date, span_start)
        to_date = min(today, span_end)
        if from_date > to_date:
            continue
        for ticker in sorted({iv.ticker for iv in ivs}):
            tasks.append(PriceFetchTask(cik=cik, ticker=ticker, from_date=from_date, to_date=to_date))
    tasks.sort(key=lambda t: (t.cik, t.ticker))
    return tasks, tuple(sorted(unresolved))


@dataclass(frozen=True)
class MergedPriceRow:
    cik: str
    date: str
    row: dict
    source_tickers: tuple[str, ...]  # tickery, których dane ZGODNIE potwierdziły ten wiersz


@dataclass(frozen=True)
class PriceRowConflict:
    cik: str
    date: str
    ticker_a: str
    row_a: dict
    ticker_b: str
    row_b: dict


@dataclass(frozen=True)
class PriceMergeResult:
    merged: list[MergedPriceRow]
    conflicts: list[PriceRowConflict]


def _rows_price_equal(
    a: dict, b: dict, *, relative_tolerance: float = 0.001, absolute_floor: float = 0.01
) -> bool:
    """Dwa wiersze cenowe są 'zgodne', jeśli open/high/low/close/
    adj_close różnią się o mniej niż WZGLĘDNA tolerancja (domyślnie
    0,1% wartości), z bezwzględnym minimum `absolute_floor` (domyślnie
    1 cent) dla bardzo tanich instrumentów. Poprawka v1.37b (po
    realnym uruchomieniu 2026-09-30): stała tolerancja bezwzględna
    (0.01) była błędnie skalibrowana — zbyt luźna dla groszowych
    spółek, zbyt ostra dla spółek wycenianych w setkach/tysiącach
    dolarów (gdzie 1 cent to szum zaokrąglenia dostawcy, nie realna
    rozbieżność). Pole obecne w jednym wierszu a brakujące w drugim ->
    NIEZGODNE (nie zgadujemy, że brak wartości znaczy to samo co jej
    obecność)."""
    for field in ("open", "high", "low", "close", "adj_close"):
        va, vb = a.get(field), b.get(field)
        if va is None or vb is None:
            if va != vb:
                return False
            continue
        allowed = max(absolute_floor, relative_tolerance * max(abs(va), abs(vb)))
        if abs(va - vb) > allowed:
            return False
    return True


def diff_price_fields(a: dict, b: dict) -> dict[str, tuple[float | None, float | None]]:
    """Zwraca WSZYSTKIE pola open/high/low/close/adj_close, które różnią
    się między dwoma wierszami (nawet w granicach tolerancji) — do
    diagnostyki konfliktów w raportach Proof Run, żeby nie ukrywać, w
    którym KONKRETNIE polu leży rozbieżność (samo `close` bywa zgodne,
    podczas gdy `open`/`high`/`low`/`adj_close` się różnią)."""
    return {
        field: (a.get(field), b.get(field))
        for field in ("open", "high", "low", "close", "adj_close")
        if a.get(field) != b.get(field)
    }


def merge_ticker_price_rows(cik: str, rows_by_ticker: dict[str, list[dict]]) -> PriceMergeResult:
    """Scala odpowiedzi z WIELU tickerów TEGO SAMEGO CIK w jedną serię
    po (cik, date) — ticker jest tylko etykietą zapytania, CIK
    pozostaje tożsamością (patrz `build_price_fetch_plan`).

    Zasady bezpieczeństwa (zatwierdzone przez właścicielkę, 2026-09-30):
    1. Jeśli >=2 tickery mają wiersz dla tej samej daty i są ZGODNE
       (`_rows_price_equal`) — deterministyczna dedukcja: jeden wiersz
       w `merged`, `source_tickers` = wszystkie zgodne tickery
       (posortowane alfabetycznie, więc wynik jest odtwarzalny).
    2. Jeśli >=2 tickery mają wiersz dla tej samej daty i są
       NIEZGODNE — NIGDY nie wybieramy po cichu jednej wartości. Ta
       data NIE trafia do `merged` (nie zapisujemy niepewnej wartości),
       a KAŻDA niezgodna para trafia do `conflicts` z pełnym
       provenance (oba tickery, oba wiersze) do ręcznej oceny przed
       użyciem w backteście."""
    by_date: dict[str, list[tuple[str, dict]]] = {}
    for ticker in sorted(rows_by_ticker):
        for row in rows_by_ticker[ticker]:
            by_date.setdefault(row["date"], []).append((ticker, row))

    merged: list[MergedPriceRow] = []
    conflicts: list[PriceRowConflict] = []
    for date in sorted(by_date):
        entries = sorted(by_date[date], key=lambda te: te[0])
        if len(entries) == 1:
            ticker, row = entries[0]
            merged.append(MergedPriceRow(cik=cik, date=date, row=row, source_tickers=(ticker,)))
            continue

        pairwise_conflicts = [
            (entries[i][0], entries[i][1], entries[j][0], entries[j][1])
            for i in range(len(entries))
            for j in range(i + 1, len(entries))
            if not _rows_price_equal(entries[i][1], entries[j][1])
        ]
        if pairwise_conflicts:
            for ticker_a, row_a, ticker_b, row_b in pairwise_conflicts:
                conflicts.append(
                    PriceRowConflict(cik=cik, date=date, ticker_a=ticker_a, row_a=row_a, ticker_b=ticker_b, row_b=row_b)
                )
        else:
            source_tickers = tuple(t for t, _ in entries)
            merged.append(MergedPriceRow(cik=cik, date=date, row=entries[0][1], source_tickers=source_tickers))
    return PriceMergeResult(merged=merged, conflicts=conflicts)


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

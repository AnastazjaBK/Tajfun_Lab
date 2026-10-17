"""Historyczne zmiany cen 1D/1W/1M/3M/1Y/5Y/MAX (Faza 11, P2).

Czyste funkcje nad listą notowań `(data ISO, zamknięcie)` -- źródło
(snapshot skanu, FMP, EODHD) wybiera wołający. WYŁĄCZNIE prezentacja:
nic tu nie wpływa na scoring, ranking ani flagi spadku scannera.

Metodologia (deterministyczna, na rzeczywistych notowaniach):
- data odniesienia = ostatnia sesja <= `ref_date` (domyślnie ostatnia w serii);
- 1D = poprzednia sesja; pozostałe okresy kalendarzowo (7 dni, 1/3/12/60
  miesięcy wstecz), cena początkowa = ostatnia sesja <= data docelowa --
  dni bez sesji, święta i strefy czasowe są obsłużone, bo liczymy po
  datach sesji danej giełdy;
- historia zaczyna się PÓŹNIEJ niż data docelowa -> None (N/A), nigdy
  krótszy okres udający pełny;
- MAX = najstarsza dostępna cena; gdy historia jest z góry ucięta
  (snapshot skanu, plan EODHD Free = 1 rok) -> None, bo to nie jest
  "najstarsza dostępna";
- to zmiana CENY (nie total return z dywidendami ani wynik inwestycji).
Ceny dostawców są przeliczone wstecz o splity, ale NIE o wydzielenia
(spin-off): `detect_price_anomalies` oznacza takie skoki zamiast je
"poprawiać" (patrz CTVA, Faza 10).
"""

from __future__ import annotations

import datetime as dt
import statistics
from dataclasses import dataclass

PERIODS = ("1D", "1W", "1M", "3M", "1Y", "5Y", "MAX")
_MONTHS = {"1M": 1, "3M": 3, "1Y": 12, "5Y": 60}

ANOMALY_STRONG_PCT = 50.0
ANOMALY_SOFT_PCT = 25.0
ANOMALY_VOLUME_MULTIPLE = 5.0


@dataclass(frozen=True)
class PeriodChange:
    pct: float
    start_date: str
    start_close: float
    end_date: str
    end_close: float


@dataclass(frozen=True)
class PriceAnomaly:
    date: str
    pct: float
    volume_multiple: float | None
    strong: bool  # >= 50% albo 25-50% przy wielokrotnym wolumenie


def _months_back(day: dt.date, months: int) -> dt.date:
    year, month = divmod(day.year * 12 + (day.month - 1) - months, 12)
    month += 1
    for d in (day.day, 30, 29, 28):
        try:
            return dt.date(year, month, d)
        except ValueError:
            continue
    raise ValueError(day)


def _target_date(end: dt.date, period: str) -> dt.date:
    if period == "1W":
        return end - dt.timedelta(days=7)
    return _months_back(end, _MONTHS[period])


def compute_period_changes(
    series: list[tuple[str, float]], *, ref_date: str | None = None, history_complete: bool = True,
) -> dict[str, PeriodChange | None]:
    rows = sorted((d[:10], c) for d, c in series if c is not None and c > 0)
    if ref_date is not None:
        rows = [r for r in rows if r[0] <= ref_date[:10]]
    result: dict[str, PeriodChange | None] = {p: None for p in PERIODS}
    if not rows:
        return result
    end_date, end_close = rows[-1]

    def change(start: tuple[str, float]) -> PeriodChange:
        return PeriodChange(
            pct=(end_close / start[1] - 1.0) * 100.0, start_date=start[0], start_close=start[1],
            end_date=end_date, end_close=end_close,
        )

    if len(rows) >= 2:
        result["1D"] = change(rows[-2])
    end = dt.date.fromisoformat(end_date)
    for period in ("1W", "1M", "3M", "1Y", "5Y"):
        target = _target_date(end, period).isoformat()
        candidates = [r for r in rows if r[0] <= target]
        if candidates:
            result[period] = change(candidates[-1])
    if history_complete and len(rows) >= 2:
        result["MAX"] = change(rows[0])
    return result


def detect_price_anomalies(rows: list[dict]) -> list[PriceAnomaly]:
    """`rows`: [{"date", "close", "volume"}] posortowane lub nie. Flaga
    jakości danych, NIE korekta: jednodniowy ruch >= 50% albo >= 25% przy
    wolumenie >= 5x mediany 20 poprzednich sesji."""
    data = sorted((r for r in rows if r.get("close")), key=lambda r: r["date"])
    anomalies = []
    for i in range(1, len(data)):
        prev, cur = data[i - 1]["close"], data[i]["close"]
        pct = (cur / prev - 1.0) * 100.0
        if abs(pct) < ANOMALY_SOFT_PCT:
            continue
        window = [r.get("volume") or 0 for r in data[max(0, i - 20):i]]
        median = statistics.median(window) if window else 0
        multiple = (data[i].get("volume") or 0) / median if median else None
        strong = abs(pct) >= ANOMALY_STRONG_PCT
        soft = multiple is not None and multiple >= ANOMALY_VOLUME_MULTIPLE
        if strong or soft:
            anomalies.append(PriceAnomaly(date=data[i]["date"][:10], pct=pct, volume_multiple=multiple, strong=strong))
    return anomalies


def periods_affected(changes: dict[str, PeriodChange | None], anomalies: list[PriceAnomaly]) -> set[str]:
    """Okresy, których przedział (start, koniec] obejmuje anomalię --
    ich zmiana może być zniekształcona przez zdarzenie korporacyjne."""
    affected = set()
    for period, change in changes.items():
        if change is None:
            continue
        if any(change.start_date < a.date <= change.end_date for a in anomalies):
            affected.add(period)
    return affected

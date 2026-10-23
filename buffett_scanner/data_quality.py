"""Kontrola świeżości i kompletności danych rynkowych przed pełnym skanem
(decyzja właścicielki 2026-10-23).

FMP nie publikuje godziny, o której dane EOD stają się ostateczne (FAQ:
"aktualizowane po zamknięciu rynku", bez konkretnej godziny). Dlatego
sama godzina zamknięcia nie jest kryterium. Dane są uznawane za gotowe,
gdy:
- ostatnie notowanie każdej spółki jest z oczekiwanej sesji i ma cenę
  zamknięcia oraz dodatni wolumen,
- odsetek takich spółek nie spada poniżej progu,
- notowania próbki spółek nie zmieniają się między dwoma pobraniami
  (test stabilności przed skanem i ponownie po pobraniu wszystkich cen),
- wolumen sesji nie wygląda na niepełny dzień (mediana wolumen sesji /
  średnia z 20 poprzednich sesji).
Każde naruszenie progu przerywa skan PRZED wywołaniami Claude; drobne
braki trafiają do raportu jako ostrzeżenia. Brak tu jakiejkolwiek logiki
scoringu ani kwalifikacji spółek.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field

# Duże, płynne spółki S&P 500 -- próbka do testu stabilności notowań.
# Używane tylko te, które są w aktualnym uniwersum.
PROBE_TICKERS = (
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "JPM", "XOM", "JNJ", "WMT",
    "PG", "V", "UNH", "HD", "KO", "PEP", "CVX", "BAC", "CSCO", "ORCL",
)
BAR_FIELDS = ("open", "high", "low", "close", "volume")


def last_bar_problem(rows: list[dict], session_date: str) -> str | None:
    """None, gdy ostatnie notowanie jest z `session_date` i kompletne;
    inaczej krótki opis problemu."""
    if not rows:
        return "brak notowań"
    last = rows[-1]
    if last["date"] != session_date:
        return f"ostatnie notowanie z {last['date']}, oczekiwano {session_date}"
    if last.get("close") is None:
        return "brak ceny zamknięcia sesji"
    if not last.get("volume"):
        return "brak wolumenu sesji"
    return None


def session_volume_ratio(rows: list[dict]) -> float | None:
    """Wolumen ostatniej sesji / średnia z 20 poprzednich; None, gdy za
    mało historii albo brak wolumenu."""
    if len(rows) < 21:
        return None
    previous = [r.get("volume") for r in rows[-21:-1]]
    if not all(previous) or not rows[-1].get("volume"):
        return None
    return rows[-1]["volume"] / statistics.mean(previous)


def bar_for(rows: list[dict], session_date: str) -> dict | None:
    return next((r for r in reversed(rows) if r["date"] == session_date), None)


def changed_fields(before: dict | None, after: dict | None) -> list[str]:
    """Pola OHLCV, które różnią się między dwoma pobraniami tej samej sesji."""
    if before is None or after is None:
        return ["brak notowania sesji"] if before is not after else []
    return [f for f in BAR_FIELDS if before.get(f) != after.get(f)]


@dataclass
class DataQualityThresholds:
    min_universe_size: int = 480
    min_price_coverage_pct: float = 98.0
    min_volume_ratio_median: float = 0.5
    warn_volume_ratio_median: float = 0.8
    max_fundamentals_failure_pct: float = 5.0


@dataclass
class DataQuality:
    session_date: str
    universe_size: int = 0
    price_ok: list[str] = field(default_factory=list)
    price_problems: dict[str, str] = field(default_factory=dict)
    volume_ratios: list[float] = field(default_factory=list)
    stability: list[dict] = field(default_factory=list)
    surfaced: int = 0
    fundamentals_ok: int = 0
    fundamentals_problems: dict[str, str] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def price_coverage_pct(self) -> float:
        return 100.0 * len(self.price_ok) / self.universe_size if self.universe_size else 0.0

    @property
    def volume_ratio_median(self) -> float | None:
        return statistics.median(self.volume_ratios) if self.volume_ratios else None

    def check_universe(self, t: DataQualityThresholds) -> bool:
        if self.universe_size < t.min_universe_size:
            self.errors.append(
                f"Uniwersum ma {self.universe_size} spółek, minimum {t.min_universe_size} -- "
                "skład indeksu z FMP wygląda na niepełny."
            )
            return False
        return True

    def check_prices(self, t: DataQualityThresholds) -> bool:
        ok = True
        if self.price_problems:
            self.warnings.append(
                f"{len(self.price_problems)} spółek bez kompletnego notowania z {self.session_date} "
                "-- pominięte w skanie: "
                + "; ".join(f"{k} ({v})" for k, v in sorted(self.price_problems.items()))
            )
        if self.price_coverage_pct < t.min_price_coverage_pct:
            self.errors.append(
                f"Pokrycie cen sesji {self.session_date}: {self.price_coverage_pct:.1f}% "
                f"({len(self.price_ok)}/{self.universe_size}), minimum {t.min_price_coverage_pct:g}%."
            )
            ok = False
        median = self.volume_ratio_median
        if median is None:
            self.errors.append("Brak danych do oceny kompletności wolumenu sesji.")
            ok = False
        elif median < t.min_volume_ratio_median:
            self.errors.append(
                f"Mediana wolumen sesji / średnia 20 sesji = {median:.2f} (minimum "
                f"{t.min_volume_ratio_median:g}) -- wolumen wygląda na niepełny dzień."
            )
            ok = False
        elif median < t.warn_volume_ratio_median:
            self.warnings.append(
                f"Mediana wolumen sesji / średnia 20 sesji = {median:.2f} -- niska, sprawdź "
                "czy dane sesji są ostateczne."
            )
        return ok

    def check_stability(self, label: str, before: dict[str, dict | None], after: dict[str, dict | None]) -> bool:
        diffs = {t: changed_fields(before.get(t), after.get(t)) for t in sorted(set(before) | set(after))}
        diffs = {t: f for t, f in diffs.items() if f}
        self.stability.append({"etap": label, "spolki": len(after), "zmiany": diffs})
        if diffs:
            self.errors.append(
                f"Test stabilności ({label}): notowania sesji {self.session_date} zmieniły się dla "
                + "; ".join(f"{t} ({', '.join(f)})" for t, f in diffs.items())
                + " -- dane FMP nie są jeszcze ostateczne."
            )
            return False
        return True

    def check_fundamentals(self, t: DataQualityThresholds) -> bool:
        if not self.fundamentals_problems:
            return True
        failed_pct = 100.0 * len(self.fundamentals_problems) / self.surfaced if self.surfaced else 0.0
        text = (
            f"{len(self.fundamentals_problems)}/{self.surfaced} wytypowanych spółek bez danych finansowych "
            "-- nie trafiły do rankingu: "
            + "; ".join(f"{k} ({v})" for k, v in sorted(self.fundamentals_problems.items()))
        )
        if failed_pct > t.max_fundamentals_failure_pct:
            self.errors.append(text + f" (limit {t.max_fundamentals_failure_pct:g}%).")
            return False
        self.warnings.append(text)
        return True

    def to_dict(self) -> dict:
        return {
            "session_date": self.session_date,
            "universe_size": self.universe_size,
            "price_ok": len(self.price_ok),
            "price_coverage_pct": round(self.price_coverage_pct, 2),
            "price_problems": self.price_problems,
            "volume_ratio_median": (
                round(self.volume_ratio_median, 3) if self.volume_ratio_median is not None else None
            ),
            "volume_ratio_samples": len(self.volume_ratios),
            "stability": self.stability,
            "surfaced": self.surfaced,
            "fundamentals_ok": self.fundamentals_ok,
            "fundamentals_problems": self.fundamentals_problems,
            "errors": self.errors,
            "warnings": self.warnings,
            "passed": not self.errors,
        }

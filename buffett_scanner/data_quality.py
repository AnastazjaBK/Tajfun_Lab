"""Kontrola świeżości i kompletności danych rynkowych przed pełnym skanem
(decyzja właścicielki 2026-10-23).

FMP nie publikuje godziny, o której dane EOD stają się ostateczne (FAQ:
"aktualizowane po zamknięciu rynku", bez konkretnej godziny). Dlatego
sama godzina zamknięcia nie jest kryterium. Dane są uznawane za gotowe,
gdy:
- ostatnie notowanie każdej spółki jest z oczekiwanej sesji i ma cenę
  zamknięcia oraz dodatni wolumen,
- odsetek takich spółek nie spada poniżej progu,
- skan startuje co najmniej N godzin po zamknięciu sesji (warunek
  konieczny, nie wystarczający),
- notowania próbki spółek (OHLC i wolumen) nie zmieniają się między dwoma
  pobraniami (test stabilności przed skanem i ponownie po pobraniu
  wszystkich cen).
Mediana wolumen sesji / średnia 20 sesji jest tylko OSTRZEŻENIEM: na
historii 257 sesji spadała poniżej 0,5 przy prawidłowych danych (sesje
skrócone 2025-11-28 i 2025-12-24, okres świąteczny 2025-12-26), a nie
wykrywa danych "prawie pełnych". Dane finansowe: okres jest używany
tylko, gdy był dostępny najpóźniej w dniu sesji.
Każde naruszenie progu przerywa skan PRZED wywołaniami Claude; drobne
braki trafiają do raportu jako ostrzeżenia. Brak tu jakiejkolwiek logiki
scoringu ani kwalifikacji spółek.
"""

from __future__ import annotations

import datetime as dt
import statistics
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

# Duże, płynne spółki S&P 500 -- próbka do testu stabilności notowań.
# Używane tylko te, które są w aktualnym uniwersum.
PROBE_TICKERS = (
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "JPM", "XOM", "JNJ", "WMT",
    "PG", "V", "UNH", "HD", "KO", "PEP", "CVX", "BAC", "CSCO", "ORCL",
)
BAR_FIELDS = ("open", "high", "low", "close", "volume")
NYSE_CLOSE_LOCAL = dt.time(16, 0)
NEW_YORK = ZoneInfo("America/New_York")
# Raport roczny (10-K) nie może być złożony w dniu zamknięcia roku -- data
# złożenia bliżej niż 7 dni od końca okresu jest uznana za niewiarygodną
# (FMP: m.in. spółki po spin-offie/IPO). Termin złożenia 10-K: 60/75/90 dni
# zależnie od kategorii emitenta (SEC), więc 90 dni to górna granica.
MIN_PLAUSIBLE_FILING_LAG_DAYS = 7
MAX_10K_DEADLINE_DAYS = 90


def session_close_utc(session_day: dt.date) -> dt.datetime:
    """Regularne zamknięcie NYSE (16:00 czasu nowojorskiego) w UTC."""
    return dt.datetime.combine(session_day, NYSE_CLOSE_LOCAL, tzinfo=NEW_YORK).astimezone(dt.timezone.utc)


def period_availability_problem(period_end: str, filed: str | None, session_date: str) -> str | None:
    """None, gdy okres finansowy był dostępny najpóźniej w dniu sesji.
    Data złożenia brakująca albo niewiarygodna -> okres przyjęty tylko,
    jeśli od końca okresu minął maksymalny termin złożenia 10-K."""
    end = dt.date.fromisoformat(period_end[:10])
    session = dt.date.fromisoformat(session_date)
    if filed:
        filed_day = dt.date.fromisoformat(filed[:10])
        if filed_day > session:
            return f"złożony {filed_day}, po dniu sesji"
        if (filed_day - end).days >= MIN_PLAUSIBLE_FILING_LAG_DAYS:
            return None
        reason = f"niewiarygodna data złożenia {filed_day} (koniec okresu {end})"
    else:
        reason = "brak daty złożenia"
    if (session - end).days >= MAX_10K_DEADLINE_DAYS:
        return None
    return f"{reason}; od końca okresu minęło mniej niż {MAX_10K_DEADLINE_DAYS} dni"


def filter_available_fundamentals(rows: list[dict], session_date: str) -> tuple[list[dict], dict[str, str]]:
    """Usuwa całe okresy niedostępne w dniu sesji. Zwraca (zachowane
    wiersze, {okres: powód}). Okres oceniany po najpóźniejszej dacie
    złożenia spośród jego wierszy (rachunek, bilans, przepływy)."""
    periods: dict[str, dict] = {}
    for r in rows:
        p = periods.setdefault(r["fiscal_period"], {"end": r["period_end_date"], "filed": []})
        p["filed"].append(r.get("filed_date"))
    dropped: dict[str, str] = {}
    for name, p in periods.items():
        filed = [f for f in p["filed"] if f]
        latest = max(filed, key=lambda f: f[:10]) if len(filed) == len(p["filed"]) else None
        problem = period_availability_problem(p["end"], latest, session_date)
        if problem:
            dropped[name] = problem
    return [r for r in rows if r["fiscal_period"] not in dropped], dropped


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
    warn_volume_ratio_median: float = 0.6
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
    dropped_periods: dict[str, dict[str, str]] = field(default_factory=dict)
    prefilter_excluded: dict[str, list[str]] = field(default_factory=dict)
    shortlist_dcf: dict[str, str] = field(default_factory=dict)
    sector_profiles: dict[str, str] = field(default_factory=dict)
    sector_problems: dict[str, str] = field(default_factory=dict)
    sic_missing: list[str] = field(default_factory=list)
    profile_review: dict[str, str] = field(default_factory=dict)
    # 2026-10-24 (poprawka nr 7): weryfikacja dywidend na akcje zwykłe.
    dividend_checks: dict[str, dict[str, str]] = field(default_factory=dict)
    dividend_unknown: list[str] = field(default_factory=list)
    capex_zero: dict[str, dict[str, str]] = field(default_factory=dict)
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
            self.warnings.append("Brak danych do porównania wolumenu sesji ze średnią 20 sesji.")
        elif median < t.warn_volume_ratio_median:
            self.warnings.append(
                f"Mediana wolumen sesji / średnia 20 sesji = {median:.2f} -- niska (tak bywa w sesjach "
                "skróconych i świątecznych); finalizację danych potwierdza test stabilności, nie ten wskaźnik."
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

    def check_sectors(self, t: DataQualityThresholds) -> bool:
        """Spółki bez klasyfikacji sektorowej (błąd SEC albo brak kodu SIC
        -> profil NIEZNANY, decyzja właścicielki 2026-10-24) są poza
        rankingiem z przyczyną w raporcie; ponad próg -> skan przerwany."""
        if self.profile_review:
            self.warnings.append(
                "Profil do weryfikacji: " + "; ".join(f"{k} ({v})" for k, v in sorted(self.profile_review.items()))
            )
        if not self.sector_problems:
            return True
        total = len(self.sector_problems) + len(self.sector_profiles)
        failed_pct = 100.0 * len(self.sector_problems) / total if total else 0.0
        text = (
            f"{len(self.sector_problems)}/{total} spółek bez klasyfikacji sektorowej -- poza rankingiem: "
            + "; ".join(f"{k} ({v})" for k, v in sorted(self.sector_problems.items()))
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
            "dropped_periods": self.dropped_periods,
            "prefilter_excluded": self.prefilter_excluded,
            "shortlist_dcf": self.shortlist_dcf,
            "sector_profiles": self.sector_profiles,
            "sector_problems": self.sector_problems,
            "sic_missing": self.sic_missing,
            "profile_review": self.profile_review,
            "dividend_checks": self.dividend_checks,
            "dividend_unknown": self.dividend_unknown,
            "capex_zero": self.capex_zero,
            "errors": self.errors,
            "warnings": self.warnings,
            "passed": not self.errors,
        }


# --- Kompletność danych wejściowych spółek z shortlisty -----------------
#
# Model punktuje brakujące pole jak niespełnione kryterium (0 pkt), a brak
# danych do DCF wyłącza wycenę. Te funkcje NIE zmieniają punktacji -- tylko
# nazywają braki, żeby odróżnić brak danych źródłowych od uzasadnionego
# (wynikającego z reguł wyceny) braku DCF.

# (pole FundamentalsPeriod, który okres: -1 najnowszy, -2 poprzedni, 0 pierwszy)
REQUIRED_INPUTS = (
    ("operating_cash_flow", -1), ("capital_expenditure", -1), ("revenue", -1), ("revenue", -2),
    ("net_income", -1), ("ebitda", -1), ("total_debt", -1), ("cash_and_equivalents", -1),
    ("total_current_assets", -1), ("total_current_liabilities", -1), ("dividends_paid", -1),
    ("dividends_paid", -2), ("share_buybacks", -1), ("diluted_shares_outstanding", -1),
    ("diluted_shares_outstanding", -2), ("operating_cash_flow", 0), ("capital_expenditure", 0),
)
_PERIOD_LABEL = {-1: "najnowszy", -2: "poprzedni", 0: "pierwszy"}


def input_gaps(periods: list) -> list[str]:
    """Brakujące dane wejściowe potrzebne do oceny deterministycznej
    (bezpieczeństwo finansowe, dywidendy, wycena)."""
    if len(periods) < 2:
        return [f"za mało okresów finansowych ({len(periods)}, potrzeba co najmniej 2)"]
    return [
        f"{name} ({_PERIOD_LABEL[index]} okres {periods[index].fiscal_period})"
        for name, index in REQUIRED_INPUTS
        if getattr(periods[index], name) is None
    ]


def dcf_absence_kind(gaps: list[str], valuation) -> str | None:
    """None, gdy DCF policzony; "BRAK_DANYCH", gdy brak wynika z braków
    danych źródłowych; "REGUŁA_WYCENY", gdy dane są kompletne, a DCF
    wyłącza reguła metody (np. ujemny FCF na początku lub końcu okna)."""
    if valuation.implemented:
        return None
    if valuation.method is None:
        return "REGUŁA_WYCENY"  # sektor bez zaimplementowanej metody
    dcf_fields = ("operating_cash_flow", "capital_expenditure", "total_debt", "cash_and_equivalents",
                  "diluted_shares_outstanding", "za mało okresów")
    return "BRAK_DANYCH" if any(g.startswith(dcf_fields) for g in gaps) else "REGUŁA_WYCENY"


# --- Zerowe nakłady inwestycyjne (CAPEX) z FMP --------------------------
#
# FMP zapisuje brak pozycji jako 0 u części spółek (np. finansowych), a
# wtedy FCF = cały przepływ operacyjny. Zero jest przyjmowane tylko, gdy
# potwierdza je SEC XBRL albo gdy profil (bank/ubezpieczyciel/REIT) nie
# używa CAPEX do wyceny; zero sprzeczne z SEC albo niepotwierdzone u spółki
# operacyjnej jest traktowane jako brak danych (nigdy jako prawdziwe zero).

CAPEX_CONFIRMED_ZERO = "POTWIERDZONE_ZERO"
CAPEX_SUSPICIOUS = "PODEJRZANE"
CAPEX_UNVERIFIED_ACCEPTED = "NIEZWERYFIKOWANE_PRZYJĘTE"
NON_OPERATING_PROFILES = ("BANK", "INSURER", "REIT")


def sec_annual_value(company_facts: dict | None, concept: str, period_end: str, session_date: str) -> float | None:
    """Roczna wartość konceptu z SEC XBRL dla okresu kończącego się
    `period_end` (±7 dni, czas trwania >= 330 dni), złożona najpóźniej w
    dniu sesji. None, gdy SEC nie ma takiego faktu."""
    from buffett_scanner.point_in_time import find_first_matching_tag

    if not company_facts:
        return None
    found = find_first_matching_tag(company_facts, concept)
    if found is None:
        return None
    end = dt.date.fromisoformat(period_end[:10])
    candidates = []
    for f in found[1]:
        if f.start is None or f.filed[:10] > session_date:
            continue
        f_end, f_start = dt.date.fromisoformat(f.end), dt.date.fromisoformat(f.start)
        if abs((f_end - end).days) <= 7 and (f_end - f_start).days >= 330:
            candidates.append(f)
    if not candidates:
        return None
    return max(candidates, key=lambda f: f.filed).val


def capex_zero_state(sector_profile: str, sec_value: float | None) -> tuple[str, str]:
    """(stan, opis) dla CAPEX = 0 z FMP."""
    if sec_value is not None:
        if sec_value == 0:
            return CAPEX_CONFIRMED_ZERO, "SEC XBRL też podaje 0"
        return CAPEX_SUSPICIOUS, f"sprzeczne z SEC XBRL ({sec_value:,.0f} USD) -- traktowane jako brak danych"
    if sector_profile in NON_OPERATING_PROFILES:
        return (CAPEX_UNVERIFIED_ACCEPTED,
                f"brak potwierdzenia w SEC; profil {sector_profile} nie używa CAPEX do wyceny -- przyjęte 0")
    return CAPEX_SUSPICIOUS, "spółka operacyjna, brak potwierdzenia w SEC -- traktowane jako brak danych"

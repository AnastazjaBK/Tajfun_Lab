"""Backfill 626 CIK / 2012+ dla walk-forward backtestu — Faza 5.3b,
projekt zatwierdzony przez właścicielkę 2026-10-03.

Łączy WYŁĄCZNIE już zwalidowane mechanizmy, zero nowej logiki
identity/PIT:
  - `price_history_plan.py` (Faza 5.3, Price Data Proof Run) — plan
    pobrania cen per CIK x wszystkie historyczne tickery, pełne okno
    aktywności CIK, merge po (cik, date), jawne konflikty, nigdy cichy
    wybór wartości.
  - `sec_company_facts_cache` (Faza 5.3b, db.py) — cache WYŁĄCZNIE
    surowego SEC `company_facts` JSON; zero interpretacji PIT na etapie
    backfillu — `build_annual_fundamentals_periods_as_of(cached_json,
    as_of_date)` dzieje się dopiero przy samym walk-forward runie.
  - `providers/retry.py` — retry/backoff dla 429/5xx (Decyzja
    właścicielki 2026-10-03: plan FMP Premium 750 calls/min, ale bez
    agresywnego wykorzystania limitu — rate limiting z marginesem,
    bez równoległego requestowania).

RESUMABILITY (Decyzja właścicielki): obecność wierszy w `price_daily`/
`sec_company_facts_cache` NIE jest dowodem kompletności backfillu dla
CIK — stąd `backfill_status` (db.py) i jawna klasyfikacja
COMPLETE/PARTIAL/FAILED/NOT_ATTEMPTED tutaj. Tylko COMPLETE jest
pomijane przy wznowieniu (chyba że `--refresh`); PARTIAL/FAILED/
NOT_ATTEMPTED są ZAWSZE ponawiane — to jest sens resumability.

ŚWIADOMIE ODŁOŻONE, NIETYKANE w tym module (Decyzja właścicielki
2026-10-03): pozostałych 189 CIK_UNRESOLVED, metodologia D&A MSFT,
metodologia `total_debt` — backfill gromadzi source data, nie
rozstrzyga tych pytań."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, replace
from typing import Literal

from buffett_scanner.db import (
    get_backfill_status,
    get_price_series,
    insert_price_rows,
    upsert_backfill_status,
    upsert_sec_company_facts_cache,
)
from buffett_scanner.price_history_plan import PriceFetchTask, build_price_fetch_plan, merge_ticker_price_rows
from buffett_scanner.providers.fmp import FMPClient, FMPError
from buffett_scanner.providers.sec_edgar import SecEdgarClient, SecEdgarError
from buffett_scanner.universe_history import (
    TickerInterval,
    build_ticker_intervals,
    distinct_tickers,
    parse_components_csv,
    resolve_tickers_to_cik,
    window_from_cutoff,
)
from buffett_scanner.universe_ticker_rename_allowlist import apply_curated_allowlist

BackfillStatus = Literal["COMPLETE", "PARTIAL", "FAILED", "NOT_ATTEMPTED"]

# Tolerancja pokrycia dni roboczych -- święta/dni bez notowań nie są
# liczone jako dni robocze przez _count_weekdays, ale nie próbujemy
# ich precyzyjnie wykluczać (kalendarz świąt to nowa zależność, nie
# potrzebna do samego rozróżnienia COMPLETE/PARTIAL) — 80% jest
# bezpiecznym marginesem poniżej typowego ~98% realnego pokrycia.
PRICE_COVERAGE_MIN_RATIO = 0.80
# Tolerancja brzegowa (dni kalendarzowe) na to, że pierwszy/ostatni
# dzień okna nie jest dniem roboczym (weekend/święto) — pierwszy/
# ostatni faktyczny bar może więc paść kilka dni od granicy okna.
BOUNDARY_TOLERANCE_DAYS = 10


# ---------------------------------------------------------------------------
# Derivacja (ticker_intervals, resolved) dla price_history_plan — ZERO
# nowej logiki identity, replikuje Krok 1-2 + allowlistę
# `cli.cmd_build_universe_membership` (Faza 5.2/5.3a), ograniczone do
# CIK już obecnych w zbudowanym `universe_membership`.
# ---------------------------------------------------------------------------

def derive_price_fetch_ticker_universe(
    *, sec_ticker_map: dict[str, str], fja_csv: str, cutoff: str, in_scope_ciks: set[str]
) -> tuple[list[TickerInterval], dict[str, str]]:
    """Odtwarza `(ticker_intervals, resolved)` identycznie jak Krok 1-2 +
    kuratorowana allowlista w `cmd_build_universe_membership` (Faza
    5.2/5.3a) — używa WYŁĄCZNIE już przetestowanych funkcji
    (`build_ticker_intervals`, `resolve_tickers_to_cik`,
    `apply_curated_allowlist`), nigdy nowej logiki rozwiązywania
    identity. `universe_membership` jest tu tylko CZYTANA (źródło
    `in_scope_ciks`), nigdy nie zapisywana — backfill nie przebudowuje
    uniwersum, tylko odtwarza ticker-poziomowy widok potrzebny
    `build_price_fetch_plan` (ta tabela nie przechowuje tickerów, patrz
    docstring modułu `db.py`/`universe_membership_build.py`)."""
    fja_rows = parse_components_csv(fja_csv)
    fja_window = window_from_cutoff(fja_rows, cutoff)
    fja_intervals = build_ticker_intervals(fja_window, cutoff_date=cutoff)
    fja_all_tickers = distinct_tickers(fja_window)
    fja_resolution = resolve_tickers_to_cik(fja_all_tickers, sec_ticker_map)
    allowlist_result = apply_curated_allowlist(fja_resolution.resolved, fja_resolution.unresolved)
    resolved = {t: cik for t, cik in allowlist_result.resolved.items() if cik in in_scope_ciks}
    ticker_intervals = [iv for iv in fja_intervals if resolved.get(iv.ticker) in in_scope_ciks]
    return ticker_intervals, resolved


# ---------------------------------------------------------------------------
# Resumability — czysta decyzja, zero I/O.
# ---------------------------------------------------------------------------

def should_fetch(existing_status: str | None, *, refresh: bool) -> bool:
    """Tylko `COMPLETE` jest pomijane przy wznowieniu (chyba że
    `refresh=True`) — PARTIAL/FAILED/NOT_ATTEMPTED/`None` (nigdy nie
    próbowano) są ZAWSZE ponawiane. To jest cała treść resumability
    (Decyzja właścicielki): "już poprawnie pobrane dane nie powinny być
    ponownie pobierane" — poprawnie pobrane = COMPLETE, nic mniej."""
    if refresh:
        return True
    return existing_status != "COMPLETE"


# ---------------------------------------------------------------------------
# Klasyfikacja pokrycia cen — czysta logika, zero I/O.
# ---------------------------------------------------------------------------

def _count_weekdays(from_date: str, to_date: str) -> int:
    start = dt.date.fromisoformat(from_date)
    end = dt.date.fromisoformat(to_date)
    if start > end:
        return 0
    count = 0
    d = start
    while d <= end:
        if d.weekday() < 5:
            count += 1
        d += dt.timedelta(days=1)
    return count


@dataclass(frozen=True)
class PriceCoverageResult:
    cik: str
    expected_from: str
    expected_to: str
    actual_min_date: str | None
    actual_max_date: str | None
    actual_row_count: int
    expected_weekday_count: int
    status: BackfillStatus
    detail: str


def classify_price_coverage(
    cik: str,
    *,
    expected_from: str,
    expected_to: str,
    actual_min_date: str | None,
    actual_max_date: str | None,
    actual_row_count: int,
    fetch_attempted: bool,
    fetch_error: str | None,
) -> PriceCoverageResult:
    """Jawne rozróżnienie COMPLETE/PARTIAL/FAILED/NOT_ATTEMPTED
    (Decyzja właścicielki: samo "są jakieś wiersze" NIE jest dowodem
    kompletności). COMPLETE wymaga ZARAZEM: (1) pokrycia brzegowego —
    pierwszy/ostatni bar w tolerancji `BOUNDARY_TOLERANCE_DAYS` od
    oczekiwanych granic okna, (2) liczby wierszy >= `PRICE_COVERAGE_
    MIN_RATIO` oczekiwanych dni roboczych. Którykolwiek warunek
    niespełniony, ale są JAKIEŚ wiersze -> PARTIAL, nigdy fałszywie
    COMPLETE."""
    expected_weekdays = _count_weekdays(expected_from, expected_to)
    if not fetch_attempted:
        return PriceCoverageResult(
            cik=cik, expected_from=expected_from, expected_to=expected_to,
            actual_min_date=actual_min_date, actual_max_date=actual_max_date,
            actual_row_count=actual_row_count, expected_weekday_count=expected_weekdays,
            status="NOT_ATTEMPTED", detail="backfill nie podjął jeszcze próby pobrania",
        )
    if actual_row_count == 0:
        return PriceCoverageResult(
            cik=cik, expected_from=expected_from, expected_to=expected_to,
            actual_min_date=actual_min_date, actual_max_date=actual_max_date,
            actual_row_count=0, expected_weekday_count=expected_weekdays,
            status="FAILED", detail=fetch_error or "zero wierszy po próbie pobrania",
        )
    boundary_ok = (
        actual_min_date is not None
        and actual_max_date is not None
        and dt.date.fromisoformat(actual_min_date)
        <= dt.date.fromisoformat(expected_from) + dt.timedelta(days=BOUNDARY_TOLERANCE_DAYS)
        and dt.date.fromisoformat(actual_max_date)
        >= dt.date.fromisoformat(expected_to) - dt.timedelta(days=BOUNDARY_TOLERANCE_DAYS)
    )
    ratio_ok = expected_weekdays == 0 or actual_row_count >= PRICE_COVERAGE_MIN_RATIO * expected_weekdays
    if boundary_ok and ratio_ok:
        status: BackfillStatus = "COMPLETE"
        detail = f"{actual_row_count} wierszy, oczekiwano ok. {expected_weekdays} dni roboczych ({expected_from}..{expected_to})"
    else:
        status = "PARTIAL"
        detail = (
            f"{actual_row_count} wierszy (oczekiwano ok. {expected_weekdays}), "
            f"zakres {actual_min_date}..{actual_max_date} (oczekiwano {expected_from}..{expected_to})"
        )
        if fetch_error:
            detail += f"; błąd podczas pobierania: {fetch_error}"
    return PriceCoverageResult(
        cik=cik, expected_from=expected_from, expected_to=expected_to,
        actual_min_date=actual_min_date, actual_max_date=actual_max_date,
        actual_row_count=actual_row_count, expected_weekday_count=expected_weekdays,
        status=status, detail=detail,
    )


# ---------------------------------------------------------------------------
# Klasyfikacja pokrycia fundamentals (cache) — czysta logika, zero I/O.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FundamentalsCoverageResult:
    cik: str
    status: BackfillStatus
    detail: str
    payload_sha256: str | None = None


def classify_fundamentals_coverage(
    cik: str, *, fetch_attempted: bool, fetch_error: str | None, company_facts: dict | None
) -> FundamentalsCoverageResult:
    """`company_facts=None` + `fetch_attempted=True` -> FAILED (próba
    była, nie powiodła się). JSON pobrany, ale bez żadnych faktów
    us-gaap -> PARTIAL (rzadkie, ale realne — np. spółka bez
    jakichkolwiek zgłoszonych faktów XBRL w tym API). Pełny JSON z
    niepustym `facts.us-gaap` -> COMPLETE (sam JSON to source data —
    jego INTERPRETACJA, czy ma wystarczające pola dla konkretnego
    konceptu, dzieje się później, w pit_fundamentals.py, nie tutaj)."""
    if not fetch_attempted:
        return FundamentalsCoverageResult(cik=cik, status="NOT_ATTEMPTED", detail="backfill nie podjął jeszcze próby pobrania")
    if company_facts is None:
        return FundamentalsCoverageResult(cik=cik, status="FAILED", detail=fetch_error or "nieznany błąd pobierania")
    us_gaap = (company_facts.get("facts") or {}).get("us-gaap") or {}
    if not us_gaap:
        return FundamentalsCoverageResult(cik=cik, status="PARTIAL", detail="pobrano JSON, ale brak faktów us-gaap")
    return FundamentalsCoverageResult(cik=cik, status="COMPLETE", detail=f"{len(us_gaap)} tagów us-gaap w odpowiedzi")


# ---------------------------------------------------------------------------
# Orkiestracja (I/O: SEC/FMP/db) — jedna funkcja per CIK per task_type,
# wołana z cli.py w pętli po `in_scope_ciks`.
# ---------------------------------------------------------------------------

def backfill_fundamentals_for_cik(
    sec_client: SecEdgarClient,
    conn,
    *,
    cik: str,
    run_id: str,
    refresh: bool,
) -> FundamentalsCoverageResult:
    existing = get_backfill_status(conn, cik, "FUNDAMENTALS")
    existing_status = existing["status"] if existing else None
    if not should_fetch(existing_status, refresh=refresh):
        return FundamentalsCoverageResult(
            cik=cik, status="COMPLETE",
            detail=f"pominięte (już COMPLETE z run_id={existing['run_id']}); użyj --refresh, by wymusić ponowne pobranie",
        )

    try:
        company_facts = sec_client.get_company_facts(cik)
        fetch_error = None
    except SecEdgarError as exc:
        company_facts = None
        fetch_error = str(exc)

    result = classify_fundamentals_coverage(cik, fetch_attempted=True, fetch_error=fetch_error, company_facts=company_facts)
    if company_facts is not None:
        payload_sha256 = upsert_sec_company_facts_cache(conn, cik=cik, company_facts=company_facts)
        result = replace(result, payload_sha256=payload_sha256)
    upsert_backfill_status(conn, cik=cik, task_type="FUNDAMENTALS", status=result.status, detail=result.detail, run_id=run_id)
    return result


def backfill_prices_for_cik(
    fmp_client: FMPClient,
    conn,
    *,
    cik: str,
    tasks: list[PriceFetchTask],
    run_id: str,
    refresh: bool,
) -> PriceCoverageResult:
    if not tasks:
        result = PriceCoverageResult(
            cik=cik, expected_from="", expected_to="", actual_min_date=None, actual_max_date=None,
            actual_row_count=0, expected_weekday_count=0, status="FAILED",
            detail="brak zadania pobrania cen (zero rozwiązanych tickerów/okien dla tego CIK)",
        )
        upsert_backfill_status(conn, cik=cik, task_type="PRICES", status=result.status, detail=result.detail, run_id=run_id)
        return result

    expected_from = min(t.from_date for t in tasks)
    expected_to = max(t.to_date for t in tasks)

    existing = get_backfill_status(conn, cik, "PRICES")
    existing_status = existing["status"] if existing else None
    if not should_fetch(existing_status, refresh=refresh):
        return PriceCoverageResult(
            cik=cik, expected_from=expected_from, expected_to=expected_to,
            actual_min_date=None, actual_max_date=None, actual_row_count=-1,
            expected_weekday_count=_count_weekdays(expected_from, expected_to),
            status="COMPLETE",
            detail=f"pominięte (już COMPLETE z run_id={existing['run_id']}); użyj --refresh, by wymusić ponowne pobranie",
        )

    rows_by_ticker: dict[str, list[dict]] = {}
    fetch_errors: list[str] = []
    for task in tasks:
        try:
            rows_by_ticker[task.ticker] = fmp_client.get_historical_prices(
                task.ticker, from_date=task.from_date, to_date=task.to_date,
            )
        except FMPError as exc:
            fetch_errors.append(f"{task.ticker}: {exc}")
            rows_by_ticker[task.ticker] = []

    merge_result = merge_ticker_price_rows(cik, rows_by_ticker)
    insert_price_rows(conn, cik, source="fmp", rows=[m.row for m in merge_result.merged])

    window_rows = [
        r for r in get_price_series(conn, cik) if expected_from <= r["date"] <= expected_to
    ]
    actual_dates = sorted(r["date"] for r in window_rows)

    result = classify_price_coverage(
        cik, expected_from=expected_from, expected_to=expected_to,
        actual_min_date=actual_dates[0] if actual_dates else None,
        actual_max_date=actual_dates[-1] if actual_dates else None,
        actual_row_count=len(actual_dates),
        fetch_attempted=True,
        fetch_error="; ".join(fetch_errors) if fetch_errors else None,
    )
    if merge_result.conflicts:
        result = replace(result, detail=result.detail + f"; {len(merge_result.conflicts)} konfliktów merge")
    upsert_backfill_status(conn, cik=cik, task_type="PRICES", status=result.status, detail=result.detail, run_id=run_id)
    return result

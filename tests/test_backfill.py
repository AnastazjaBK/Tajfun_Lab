"""Testy backfillu 626 CIK / 2012+ (Faza 5.3b, projekt zatwierdzony
2026-10-03). Czysta logika (klasyfikacja/resumability) + orkiestracja
z fake klientami SEC/FMP (zero sieci, zgodnie z dyscypliną projektu)."""

from __future__ import annotations

import pytest

from buffett_scanner.backfill import (
    backfill_fundamentals_for_cik,
    backfill_prices_for_cik,
    classify_fundamentals_coverage,
    classify_price_coverage,
    derive_price_fetch_ticker_universe,
    should_fetch,
)
from buffett_scanner.db import (
    get_backfill_status,
    get_sec_company_facts_cache,
    init_db,
    upsert_backfill_status,
    upsert_company,
)
from buffett_scanner.price_history_plan import PriceFetchTask
from buffett_scanner.providers.fmp import FMPError
from buffett_scanner.providers.sec_edgar import SecEdgarError


@pytest.fixture
def conn(tmp_path):
    return init_db(tmp_path / "test.db")


# ---------------------------------------------------------------------------
# should_fetch (resumability) — czysta logika.
# ---------------------------------------------------------------------------

def test_should_fetch_skips_complete_without_refresh():
    assert should_fetch("COMPLETE", refresh=False) is False


def test_should_fetch_retries_partial_without_refresh():
    assert should_fetch("PARTIAL", refresh=False) is True


def test_should_fetch_retries_failed_without_refresh():
    assert should_fetch("FAILED", refresh=False) is True


def test_should_fetch_retries_not_attempted_string():
    assert should_fetch("NOT_ATTEMPTED", refresh=False) is True


def test_should_fetch_retries_never_tried_before():
    assert should_fetch(None, refresh=False) is True


def test_should_fetch_refresh_forces_even_complete():
    assert should_fetch("COMPLETE", refresh=True) is True


# ---------------------------------------------------------------------------
# classify_price_coverage — czysta logika.
# ---------------------------------------------------------------------------

def test_price_coverage_not_attempted_when_never_tried():
    result = classify_price_coverage(
        "CIK1", expected_from="2020-01-01", expected_to="2020-12-31",
        actual_min_date=None, actual_max_date=None, actual_row_count=0,
        fetch_attempted=False, fetch_error=None,
    )
    assert result.status == "NOT_ATTEMPTED"


def test_price_coverage_failed_when_zero_rows_after_attempt():
    result = classify_price_coverage(
        "CIK1", expected_from="2020-01-01", expected_to="2020-12-31",
        actual_min_date=None, actual_max_date=None, actual_row_count=0,
        fetch_attempted=True, fetch_error="FMP: 500",
    )
    assert result.status == "FAILED"
    assert "500" in result.detail


def test_price_coverage_complete_when_full_window_covered():
    result = classify_price_coverage(
        "CIK1", expected_from="2020-01-01", expected_to="2020-01-31",
        actual_min_date="2020-01-02", actual_max_date="2020-01-31", actual_row_count=23,
        fetch_attempted=True, fetch_error=None,
    )
    assert result.status == "COMPLETE"


def test_price_coverage_partial_when_boundary_gap_at_end():
    """Dane zatrzymują się 2 miesiące przed końcem okna -- mimo że
    liczba wierszy mogłaby wydawać się "dużo", brzeg okna NIE jest
    pokryty -> PARTIAL, nigdy fałszywie COMPLETE."""
    result = classify_price_coverage(
        "CIK1", expected_from="2020-01-01", expected_to="2020-12-31",
        actual_min_date="2020-01-02", actual_max_date="2020-10-30", actual_row_count=210,
        fetch_attempted=True, fetch_error=None,
    )
    assert result.status == "PARTIAL"


def test_price_coverage_partial_when_too_few_rows_despite_boundary_ok():
    """Brzegi w tolerancji, ale dziura w środku (mało wierszy jak na
    cały zakres) -> PARTIAL."""
    result = classify_price_coverage(
        "CIK1", expected_from="2020-01-01", expected_to="2020-12-31",
        actual_min_date="2020-01-02", actual_max_date="2020-12-30", actual_row_count=50,
        fetch_attempted=True, fetch_error=None,
    )
    assert result.status == "PARTIAL"


def test_price_coverage_partial_reports_fetch_error_even_with_some_rows():
    result = classify_price_coverage(
        "CIK1", expected_from="2020-01-01", expected_to="2020-12-31",
        actual_min_date="2020-01-02", actual_max_date="2020-06-30", actual_row_count=100,
        fetch_attempted=True, fetch_error="TICKERB: FMP 500",
    )
    assert result.status == "PARTIAL"
    assert "TICKERB" in result.detail


def test_price_coverage_presence_of_some_rows_is_not_proof_of_complete():
    """Kluczowa zasada (Decyzja właścicielki): same wiersze nie
    wystarczają -- tu mamy dużo wierszy, ale żaden z nich nie jest
    blisko końca oczekiwanego okna."""
    result = classify_price_coverage(
        "CIK1", expected_from="2012-01-01", expected_to="2026-01-01",
        actual_min_date="2012-01-03", actual_max_date="2013-01-01", actual_row_count=260,
        fetch_attempted=True, fetch_error=None,
    )
    assert result.status == "PARTIAL"


# ---------------------------------------------------------------------------
# classify_fundamentals_coverage — czysta logika.
# ---------------------------------------------------------------------------

def test_fundamentals_coverage_not_attempted():
    result = classify_fundamentals_coverage("CIK1", fetch_attempted=False, fetch_error=None, company_facts=None)
    assert result.status == "NOT_ATTEMPTED"


def test_fundamentals_coverage_failed_on_fetch_error():
    result = classify_fundamentals_coverage("CIK1", fetch_attempted=True, fetch_error="404", company_facts=None)
    assert result.status == "FAILED"
    assert result.detail == "404"


def test_fundamentals_coverage_partial_when_empty_us_gaap():
    result = classify_fundamentals_coverage(
        "CIK1", fetch_attempted=True, fetch_error=None, company_facts={"facts": {"us-gaap": {}}},
    )
    assert result.status == "PARTIAL"


def test_fundamentals_coverage_complete_when_facts_present():
    result = classify_fundamentals_coverage(
        "CIK1", fetch_attempted=True, fetch_error=None,
        company_facts={"facts": {"us-gaap": {"NetIncomeLoss": {}}}},
    )
    assert result.status == "COMPLETE"
    assert "1 tag" in result.detail


# ---------------------------------------------------------------------------
# derive_price_fetch_ticker_universe — reużywa już przetestowanych
# funkcji universe_history/allowlist, restricted do in_scope_ciks.
# ---------------------------------------------------------------------------

def test_derive_price_fetch_ticker_universe_restricts_to_in_scope_ciks():
    fja_csv = 'date,tickers\n2012-01-01,"AAPL,MSFT,KO"\n'
    sec_ticker_map = {"AAPL": "320193", "MSFT": "789019", "KO": "21344"}
    ticker_intervals, resolved = derive_price_fetch_ticker_universe(
        sec_ticker_map=sec_ticker_map, fja_csv=fja_csv, cutoff="2012-01-01",
        in_scope_ciks={"320193", "789019"},  # KO poza zakresem
    )
    assert resolved == {"AAPL": "320193", "MSFT": "789019"}
    assert {iv.ticker for iv in ticker_intervals} == {"AAPL", "MSFT"}


def test_derive_price_fetch_ticker_universe_empty_in_scope_yields_nothing():
    fja_csv = "date,tickers\n2012-01-01,AAPL\n"
    ticker_intervals, resolved = derive_price_fetch_ticker_universe(
        sec_ticker_map={"AAPL": "320193"}, fja_csv=fja_csv, cutoff="2012-01-01", in_scope_ciks=set(),
    )
    assert resolved == {}
    assert ticker_intervals == []


# ---------------------------------------------------------------------------
# backfill_fundamentals_for_cik — orkiestracja z fake klientem SEC.
# ---------------------------------------------------------------------------

class _FakeSecClientOk:
    def __init__(self, payload):
        self._payload = payload

    def get_company_facts(self, cik):
        return self._payload


class _FakeSecClientFails:
    def get_company_facts(self, cik):
        raise SecEdgarError("SEC zwrócił 404")


def test_backfill_fundamentals_success_writes_cache_and_status(conn):
    upsert_company(conn, cik="0000320193", name="Apple Inc.")
    payload = {"facts": {"us-gaap": {"NetIncomeLoss": {}}}}
    result = backfill_fundamentals_for_cik(
        _FakeSecClientOk(payload), conn, cik="0000320193", run_id="run-1", refresh=False,
    )
    conn.commit()
    assert result.status == "COMPLETE"
    assert get_sec_company_facts_cache(conn, "0000320193") == payload
    assert get_backfill_status(conn, "0000320193", "FUNDAMENTALS")["status"] == "COMPLETE"


def test_backfill_fundamentals_failure_records_failed_status_no_cache_write(conn):
    upsert_company(conn, cik="0000320193", name="Apple Inc.")
    result = backfill_fundamentals_for_cik(
        _FakeSecClientFails(), conn, cik="0000320193", run_id="run-1", refresh=False,
    )
    conn.commit()
    assert result.status == "FAILED"
    assert get_sec_company_facts_cache(conn, "0000320193") is None
    assert get_backfill_status(conn, "0000320193", "FUNDAMENTALS")["status"] == "FAILED"


def test_backfill_fundamentals_resumability_skips_already_complete(conn):
    upsert_company(conn, cik="0000320193", name="Apple Inc.")
    upsert_backfill_status(conn, cik="0000320193", task_type="FUNDAMENTALS", status="COMPLETE", run_id="run-0")
    conn.commit()

    class _ShouldNotBeCalled:
        def get_company_facts(self, cik):
            raise AssertionError("nie powinno być wołane -- juz COMPLETE, resumability")

    result = backfill_fundamentals_for_cik(
        _ShouldNotBeCalled(), conn, cik="0000320193", run_id="run-1", refresh=False,
    )
    assert result.status == "COMPLETE"
    assert "pominięte" in result.detail


def test_backfill_fundamentals_refresh_forces_refetch_even_when_complete(conn):
    upsert_company(conn, cik="0000320193", name="Apple Inc.")
    upsert_backfill_status(conn, cik="0000320193", task_type="FUNDAMENTALS", status="COMPLETE", run_id="run-0")
    conn.commit()
    payload = {"facts": {"us-gaap": {"NetIncomeLoss": {}}}}
    result = backfill_fundamentals_for_cik(
        _FakeSecClientOk(payload), conn, cik="0000320193", run_id="run-1", refresh=True,
    )
    assert result.status == "COMPLETE"
    assert get_backfill_status(conn, "0000320193", "FUNDAMENTALS")["run_id"] == "run-1"


def test_backfill_fundamentals_retries_previously_partial(conn):
    upsert_company(conn, cik="0000320193", name="Apple Inc.")
    upsert_backfill_status(conn, cik="0000320193", task_type="FUNDAMENTALS", status="PARTIAL", run_id="run-0")
    conn.commit()
    payload = {"facts": {"us-gaap": {"NetIncomeLoss": {}}}}
    result = backfill_fundamentals_for_cik(
        _FakeSecClientOk(payload), conn, cik="0000320193", run_id="run-1", refresh=False,
    )
    assert result.status == "COMPLETE"  # PARTIAL -> ponowione bez --refresh


# ---------------------------------------------------------------------------
# backfill_prices_for_cik — orkiestracja z fake klientem FMP.
# ---------------------------------------------------------------------------

class _FakeFmpClient:
    def __init__(self, rows_by_ticker: dict[str, list[dict]], *, errors: dict[str, str] | None = None):
        self._rows_by_ticker = rows_by_ticker
        self._errors = errors or {}

    def get_historical_prices(self, symbol, *, from_date, to_date):
        if symbol in self._errors:
            raise FMPError(self._errors[symbol])
        return self._rows_by_ticker.get(symbol, [])


def _daily_rows(from_date: str, to_date: str) -> list[dict]:
    import datetime as _dt
    rows = []
    d = _dt.date.fromisoformat(from_date)
    end = _dt.date.fromisoformat(to_date)
    while d <= end:
        if d.weekday() < 5:
            rows.append({
                "date": d.isoformat(), "open": 100.0, "high": 101.0, "low": 99.0,
                "close": 100.5, "adj_close": 100.5, "volume": 1000,
            })
        d += _dt.timedelta(days=1)
    return rows


def test_backfill_prices_complete_single_ticker(conn):
    upsert_company(conn, cik="0000320193", name="Apple Inc.")
    tasks = [PriceFetchTask(cik="0000320193", ticker="AAPL", from_date="2020-01-01", to_date="2020-03-31")]
    client = _FakeFmpClient({"AAPL": _daily_rows("2020-01-01", "2020-03-31")})
    result = backfill_prices_for_cik(client, conn, cik="0000320193", tasks=tasks, run_id="run-1", refresh=False)
    conn.commit()
    assert result.status == "COMPLETE"
    assert get_backfill_status(conn, "0000320193", "PRICES")["status"] == "COMPLETE"


def test_backfill_prices_merges_multiple_tickers_same_cik(conn):
    """Replikuje price_history_plan: dwa tickery tego samego CIK,
    każdy w pełnym oknie CIK -- scalenie do jednej serii, bez
    duplikatów wierszy dla wspólnych dat."""
    upsert_company(conn, cik="0001326801", name="Meta Platforms Inc.")
    rows = _daily_rows("2020-01-01", "2020-01-31")
    tasks = [
        PriceFetchTask(cik="0001326801", ticker="FB", from_date="2020-01-01", to_date="2020-01-31"),
        PriceFetchTask(cik="0001326801", ticker="META", from_date="2020-01-01", to_date="2020-01-31"),
    ]
    client = _FakeFmpClient({"FB": rows, "META": rows})
    result = backfill_prices_for_cik(client, conn, cik="0001326801", tasks=tasks, run_id="run-1", refresh=False)
    conn.commit()
    assert result.status == "COMPLETE"
    stored = conn.execute("SELECT COUNT(*) AS n FROM price_daily WHERE cik = ?", ("0001326801",)).fetchone()
    assert stored["n"] == len(rows)  # zero duplikatow, mimo 2 zrodel tego samego dnia


def test_backfill_prices_conflict_detected_and_reported_never_silently_chosen(conn):
    upsert_company(conn, cik="0001326801", name="Meta Platforms Inc.")
    rows_fb = _daily_rows("2020-01-01", "2020-01-02")
    rows_meta = [{**r, "close": r["close"] * 2, "adj_close": r["adj_close"] * 2} for r in rows_fb]
    tasks = [
        PriceFetchTask(cik="0001326801", ticker="FB", from_date="2020-01-01", to_date="2020-01-02"),
        PriceFetchTask(cik="0001326801", ticker="META", from_date="2020-01-01", to_date="2020-01-02"),
    ]
    client = _FakeFmpClient({"FB": rows_fb, "META": rows_meta})
    result = backfill_prices_for_cik(client, conn, cik="0001326801", tasks=tasks, run_id="run-1", refresh=False)
    conn.commit()
    assert "konfliktów merge" in result.detail
    # Wiersze konfliktowe NIE trafiają do price_daily (nigdy cichy wybór).
    stored = conn.execute("SELECT COUNT(*) AS n FROM price_daily WHERE cik = ?", ("0001326801",)).fetchone()
    assert stored["n"] == 0


def test_backfill_prices_partial_ticker_error_still_classified_correctly(conn):
    upsert_company(conn, cik="0000320193", name="Apple Inc.")
    tasks = [
        PriceFetchTask(cik="0000320193", ticker="AAPL", from_date="2020-01-01", to_date="2020-12-31"),
    ]
    client = _FakeFmpClient({}, errors={"AAPL": "FMP 500 timeout"})
    result = backfill_prices_for_cik(client, conn, cik="0000320193", tasks=tasks, run_id="run-1", refresh=False)
    conn.commit()
    assert result.status == "FAILED"
    assert "timeout" in result.detail


def test_backfill_prices_no_tasks_is_explicit_failed_never_silently_skipped(conn):
    upsert_company(conn, cik="0000999999", name="Spółka bez tickera")
    result = backfill_prices_for_cik(
        _FakeFmpClient({}), conn, cik="0000999999", tasks=[], run_id="run-1", refresh=False,
    )
    conn.commit()
    assert result.status == "FAILED"
    assert get_backfill_status(conn, "0000999999", "PRICES")["status"] == "FAILED"


def test_backfill_prices_resumability_skips_already_complete(conn):
    upsert_company(conn, cik="0000320193", name="Apple Inc.")
    upsert_backfill_status(conn, cik="0000320193", task_type="PRICES", status="COMPLETE", run_id="run-0")
    conn.commit()

    class _ShouldNotBeCalled:
        def get_historical_prices(self, *a, **k):
            raise AssertionError("nie powinno być wołane -- juz COMPLETE, resumability")

    tasks = [PriceFetchTask(cik="0000320193", ticker="AAPL", from_date="2020-01-01", to_date="2020-12-31")]
    result = backfill_prices_for_cik(
        _ShouldNotBeCalled(), conn, cik="0000320193", tasks=tasks, run_id="run-1", refresh=False,
    )
    assert result.status == "COMPLETE"
    assert "pominięte" in result.detail

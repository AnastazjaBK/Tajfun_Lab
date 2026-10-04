import sqlite3

import pytest

from buffett_scanner.db import (
    create_user,
    get_fundamentals_periods,
    get_price_series,
    get_sec_company_facts_cache,
    get_universe_membership_as_of,
    init_db,
    insert_analysis,
    insert_analysis_sources,
    insert_fundamentals_rows,
    insert_price_rows,
    insert_unresolved_ticker,
    insert_universe_membership_conflict,
    upsert_company,
    upsert_derived_metric,
    upsert_scoring_model_version,
    upsert_sec_company_facts_cache,
    upsert_ticker_history,
    upsert_universe_membership,
)
from buffett_scanner.sources import VerifiedSource


@pytest.fixture
def conn(tmp_path):
    return init_db(tmp_path / "test.db")


def test_init_db_creates_expected_tables(conn):
    tables = {
        row["name"]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert {"companies", "ticker_history", "price_daily", "users"} <= tables


def test_init_db_is_idempotent(tmp_path):
    path = tmp_path / "test.db"
    init_db(path)
    conn2 = init_db(path)  # nie powinno rzucić błędu przy istniejącym schemacie
    assert conn2 is not None


def test_upsert_company_identity_is_cik_not_ticker(conn):
    upsert_company(conn, cik="0000320193", name="Apple Inc.", sector="Technology")
    upsert_company(conn, cik="0000320193", name="Apple Inc. (updated)", sector="Technology")
    rows = conn.execute("SELECT * FROM companies").fetchall()
    assert len(rows) == 1
    assert rows[0]["name"] == "Apple Inc. (updated)"


def test_sector_profile_defaults_to_general_and_is_constrained(conn):
    upsert_company(conn, cik="0000320193", name="Apple Inc.")
    row = conn.execute("SELECT sector_profile FROM companies").fetchone()
    assert row["sector_profile"] == "GENERAL"

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO companies (cik, name, sector_profile) VALUES (?, ?, ?)",
            ("0000000001", "Nieprawidłowy sektor", "NOT_A_REAL_SECTOR"),
        )


def test_ticker_recycling_is_disambiguated_by_cik(conn):
    """Symulacja ryzyka z sekcji 5/14 design review: ten sam ticker,
    dwie różne spółki w różnych okresach — muszą pozostać rozróżnialne
    po CIK, nie po tickerze."""
    upsert_company(conn, cik="0000111111", name="SunTrust Banks (przykład)")
    upsert_ticker_history(conn, cik="0000111111", ticker="STI", start_date="2010-01-01")

    upsert_company(conn, cik="0000222222", name="Inna spółka (przykład)")
    upsert_ticker_history(conn, cik="0000222222", ticker="STI", start_date="2020-01-01")

    history = conn.execute(
        "SELECT cik, ticker, start_date, end_date FROM ticker_history "
        "WHERE ticker = 'STI' ORDER BY start_date"
    ).fetchall()
    assert len(history) == 2
    assert history[0]["cik"] == "0000111111"
    assert history[1]["cik"] == "0000222222"
    # rekord tylko przypisany do TEGO SAMEGO CIK jest domykany przy zmianie
    # tickera; ticker recycling na inny CIK nie zamyka cudzego wpisu
    assert history[0]["end_date"] is None


def test_get_cik_for_active_ticker_returns_resolved_cik(conn):
    from buffett_scanner.db import get_cik_for_active_ticker

    upsert_company(conn, cik="0000884394", name="SPDR S&P 500 ETF Trust")
    upsert_ticker_history(conn, cik="0000884394", ticker="SPY", start_date="2012-01-01")
    conn.commit()
    assert get_cik_for_active_ticker(conn, "SPY") == "0000884394"


def test_get_cik_for_active_ticker_none_when_unresolved(conn):
    from buffett_scanner.db import get_cik_for_active_ticker

    assert get_cik_for_active_ticker(conn, "SPY") is None


def test_get_cik_for_active_ticker_raises_on_ambiguous_recycled_ticker(conn):
    """Edge case z `test_ticker_recycling_is_disambiguated_by_cik`: dwa
    różne CIK mogą mieć jednocześnie aktywny (end_date IS NULL) ten sam
    ticker — funkcja NIE wybiera cicho jednego z nich."""
    from buffett_scanner.db import get_cik_for_active_ticker

    upsert_company(conn, cik="0000111111", name="SunTrust Banks (przykład)")
    upsert_ticker_history(conn, cik="0000111111", ticker="STI", start_date="2010-01-01")
    upsert_company(conn, cik="0000222222", name="Inna spółka (przykład)")
    upsert_ticker_history(conn, cik="0000222222", ticker="STI", start_date="2020-01-01")
    conn.commit()
    with pytest.raises(ValueError):
        get_cik_for_active_ticker(conn, "STI")


def test_insert_and_read_price_series_ordered_by_date(conn):
    upsert_company(conn, cik="0000320193", name="Apple Inc.")
    rows = [
        {"date": "2026-01-03", "open": 1, "high": 2, "low": 0.5, "close": 1.5, "adj_close": 1.5, "volume": 100},
        {"date": "2026-01-02", "open": 1, "high": 2, "low": 0.5, "close": 1.4, "adj_close": 1.4, "volume": 90},
    ]
    n = insert_price_rows(conn, "0000320193", source="fmp", rows=rows)
    conn.commit()
    assert n == 2

    series = get_price_series(conn, "0000320193")
    assert [r["date"] for r in series] == ["2026-01-02", "2026-01-03"]


def test_insert_price_rows_upserts_on_conflict(conn):
    upsert_company(conn, cik="0000320193", name="Apple Inc.")
    insert_price_rows(
        conn, "0000320193", source="fmp",
        rows=[{"date": "2026-01-02", "close": 1.0, "volume": 10}],
    )
    insert_price_rows(
        conn, "0000320193", source="fmp",
        rows=[{"date": "2026-01-02", "close": 9.9, "volume": 999}],
    )
    conn.commit()
    series = get_price_series(conn, "0000320193")
    assert len(series) == 1
    assert series[0]["close"] == 9.9
    assert series[0]["volume"] == 999


def test_create_user_minimal_no_auth(conn):
    user_id = create_user(conn, "Anastazja")
    conn.commit()
    row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
    assert row["display_name"] == "Anastazja"


def test_init_db_creates_phase1_tables(conn):
    tables = {
        row["name"]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert {"fundamentals_raw", "derived_metrics"} <= tables


def test_insert_fundamentals_rows_and_pivot_to_periods(conn):
    upsert_company(conn, cik="0000320193", name="Apple Inc.")
    rows = [
        {"fiscal_period": "2023-FY", "period_end_date": "2023-12-31",
         "filed_date": "2024-01-15", "line_item": "revenue", "value": 100.0},
        {"fiscal_period": "2023-FY", "period_end_date": "2023-12-31",
         "filed_date": "2024-01-15", "line_item": "net_income", "value": 10.0},
        {"fiscal_period": "2024-FY", "period_end_date": "2024-12-31",
         "filed_date": "2025-01-15", "line_item": "revenue", "value": 110.0},
        {"fiscal_period": "2024-FY", "period_end_date": "2024-12-31",
         "filed_date": "2025-01-15", "line_item": "operating_cash_flow", "value": 900.0},
    ]
    n = insert_fundamentals_rows(conn, "0000320193", source="fmp", rows=rows)
    conn.commit()
    assert n == 4

    periods = get_fundamentals_periods(conn, "0000320193")
    assert [p.fiscal_period for p in periods] == ["2023-FY", "2024-FY"]  # rosnąco
    assert periods[0].revenue == 100.0
    assert periods[0].net_income == 10.0
    # brakujący line_item dla danego okresu -> None, nigdy 0
    assert periods[0].operating_cash_flow is None
    assert periods[-1].revenue == 110.0
    assert periods[-1].operating_cash_flow == 900.0
    assert periods[-1].net_income is None


def test_insert_fundamentals_rows_rejects_unknown_line_item(conn):
    upsert_company(conn, cik="0000320193", name="Apple Inc.")
    with pytest.raises(ValueError):
        insert_fundamentals_rows(
            conn, "0000320193", source="fmp",
            rows=[{"fiscal_period": "2024-FY", "period_end_date": "2024-12-31",
                   "line_item": "not_a_real_metric", "value": 1.0}],
        )


def test_insert_fundamentals_rows_upserts_on_conflict(conn):
    upsert_company(conn, cik="0000320193", name="Apple Inc.")
    insert_fundamentals_rows(
        conn, "0000320193", source="fmp",
        rows=[{"fiscal_period": "2024-FY", "period_end_date": "2024-12-31",
               "line_item": "revenue", "value": 100.0}],
    )
    insert_fundamentals_rows(
        conn, "0000320193", source="fmp",
        rows=[{"fiscal_period": "2024-FY", "period_end_date": "2024-12-31",
               "line_item": "revenue", "value": 999.0}],
    )
    conn.commit()
    periods = get_fundamentals_periods(conn, "0000320193")
    assert len(periods) == 1
    assert periods[0].revenue == 999.0


def test_upsert_derived_metric_is_idempotent_per_calc_version(conn):
    upsert_company(conn, cik="0000320193", name="Apple Inc.")
    upsert_derived_metric(
        conn, cik="0000320193", as_of_date="2024-12-31", metric_name="fcf_ttm",
        value=700.0, calc_version="0.1.0",
    )
    upsert_derived_metric(
        conn, cik="0000320193", as_of_date="2024-12-31", metric_name="fcf_ttm",
        value=750.0, calc_version="0.1.0",
    )
    conn.commit()
    rows = conn.execute("SELECT * FROM derived_metrics").fetchall()
    assert len(rows) == 1
    assert rows[0]["value"] == 750.0


def test_init_db_creates_phase4_tables(conn):
    tables = {
        row["name"]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert {"scoring_model_versions", "analyses", "analysis_sources"} <= tables


def test_upsert_scoring_model_version_is_idempotent(conn):
    upsert_scoring_model_version(
        conn, version="0.1.0-draft", description="v1",
        weights_json='{"business_quality": 45}', gates_json="{}",
    )
    upsert_scoring_model_version(
        conn, version="0.1.0-draft", description="v2 (updated)",
        weights_json='{"business_quality": 50}', gates_json="{}",
    )
    conn.commit()
    rows = conn.execute("SELECT * FROM scoring_model_versions").fetchall()
    assert len(rows) == 1
    assert rows[0]["description"] == "v2 (updated)"


def test_insert_analysis_is_append_only(conn):
    upsert_company(conn, cik="0000320193", name="Apple Inc.")
    upsert_scoring_model_version(
        conn, version="0.1.0-draft", description=None,
        weights_json="{}", gates_json="{}",
    )
    id1 = insert_analysis(
        conn, cik="0000320193", run_date="2026-09-25", price_at_analysis=15.0,
        scoring_model_version="0.1.0-draft", total_score=80.0,
    )
    id2 = insert_analysis(
        conn, cik="0000320193", run_date="2026-09-26", price_at_analysis=16.0,
        scoring_model_version="0.1.0-draft", total_score=82.0,
    )
    conn.commit()
    assert id1 != id2
    rows = conn.execute("SELECT * FROM analyses WHERE cik = ?", ("0000320193",)).fetchall()
    assert len(rows) == 2  # ponowna ocena = nowy wiersz, nigdy UPDATE


def test_insert_analysis_sources_stores_verified_and_unverified(conn):
    upsert_company(conn, cik="0000320193", name="Apple Inc.")
    upsert_scoring_model_version(
        conn, version="0.1.0-draft", description=None, weights_json="{}", gates_json="{}",
    )
    analysis_id = insert_analysis(
        conn, cik="0000320193", run_date="2026-09-25",
        scoring_model_version="0.1.0-draft",
    )
    sources = [
        VerifiedSource(
            source_type="SEC_FILING", title="10-K (2024-11-01)", issuer="Apple Inc.",
            doc_date="2024-11-01", url="https://www.sec.gov/doc.htm",
            accession_number="0000320193-24-000123", section=None,
            content_hash="abc123", verified=True, reason=None,
        ),
        VerifiedSource(
            source_type="SEC_FILING", title="(lista filingów)", issuer="Apple Inc.",
            doc_date=None, url="", accession_number=None, section=None,
            content_hash=None, verified=False, reason="Błąd sieci",
        ),
    ]
    n = insert_analysis_sources(conn, analysis_id, sources)
    conn.commit()
    assert n == 2
    rows = conn.execute(
        "SELECT * FROM analysis_sources WHERE analysis_id = ? ORDER BY source_id", (analysis_id,)
    ).fetchall()
    assert rows[0]["verified"] == 1
    assert rows[0]["content_hash"] == "abc123"
    assert rows[1]["verified"] == 0
    assert rows[1]["reason"] == "Błąd sieci"


# ---------------------------------------------------------------------------
# Faza 5.2 — universe_membership (domknięcie OPEN BLOCKER 2, v1.35)
# ---------------------------------------------------------------------------


def test_init_db_creates_universe_membership_tables(conn):
    tables = {
        row["name"]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert {
        "universe_membership", "universe_membership_conflicts", "universe_membership_unresolved_tickers",
    } <= tables


def test_upsert_universe_membership_inserts_and_updates_on_conflict(conn):
    upsert_company(conn, cik="0001326801", name="Meta Platforms Inc.")
    upsert_universe_membership(
        conn, cik="0001326801", index_name="SP500", start_date="2012-01-01",
        end_date=None, source="fja05680", source_snapshot_ref="ref1",
        cik_resolution_method="DIRECT",
    )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM universe_membership WHERE cik = ?", ("0001326801",)
    ).fetchone()
    assert row["end_date"] is None
    assert row["entry_validation_status"] == "NOT_VALIDATED"  # domyślne

    # Ponowny build tego samego przedziału (np. po zmianie tolerancji)
    # aktualizuje metadane walidacji, nie duplikuje wiersza.
    upsert_universe_membership(
        conn, cik="0001326801", index_name="SP500", start_date="2012-01-01",
        end_date="2023-01-01", source="fja05680", source_snapshot_ref="ref2",
        cik_resolution_method="DIRECT", entry_validation_status="MATCHED",
    )
    conn.commit()
    rows = conn.execute("SELECT * FROM universe_membership WHERE cik = ?", ("0001326801",)).fetchall()
    assert len(rows) == 1
    assert rows[0]["end_date"] == "2023-01-01"
    assert rows[0]["entry_validation_status"] == "MATCHED"


def test_upsert_universe_membership_accepts_curated_allowlist_method_and_note(conn):
    """Faza 5.3 (LIMITED_BUT_HONEST, v1.39): `cik_resolution_method`
    akceptuje `CURATED_ALLOWLIST`, a `cik_resolution_note` niesie pełną
    ścieżkę dowodową — kolumna NULL-owalna, nieużywana dla DIRECT/
    FORMAT_VARIANT."""
    upsert_company(conn, cik="0001156039", name="Elevance Health Inc")
    upsert_universe_membership(
        conn, cik="0001156039", index_name="SP500", start_date="2012-01-01",
        end_date="2022-06-28", source="fja05680", source_snapshot_ref="ref1",
        cik_resolution_method="CURATED_ALLOWLIST",
        cik_resolution_note="MULTI_SIGNAL_VERIFIED_V1 old=ANTM new=ELV",
    )
    conn.commit()
    row = conn.execute("SELECT * FROM universe_membership WHERE cik = ?", ("0001156039",)).fetchone()
    assert row["cik_resolution_method"] == "CURATED_ALLOWLIST"
    assert row["cik_resolution_note"] == "MULTI_SIGNAL_VERIFIED_V1 old=ANTM new=ELV"


def test_upsert_universe_membership_accepts_overlap_merge_note(conn):
    """Decyzja właścicielki 2026-10-04: `overlap_merge_note` niesie
    audytowalny ślad company-level interval union (dual-class share
    tickery) -- kolumna NULL-owalna, domyślnie nieustawiona."""
    upsert_company(conn, cik="0001652044", name="Alphabet Inc.")
    upsert_universe_membership(
        conn, cik="0001652044", index_name="SP500", start_date="2012-01-01",
        end_date=None, source="fja05680", source_snapshot_ref="ref1",
        cik_resolution_method="DIRECT",
        overlap_merge_note="company-level interval union: pochłonięto [2014-04-03, None)",
    )
    conn.commit()
    row = conn.execute("SELECT * FROM universe_membership WHERE cik = ?", ("0001652044",)).fetchone()
    assert row["overlap_merge_note"] == "company-level interval union: pochłonięto [2014-04-03, None)"


def test_clear_universe_membership_for_rebuild_removes_only_that_index(conn):
    """Decyzja właścicielki 2026-10-04: ponowny build musi być pełnym
    zastąpieniem, nie dopisaniem -- stary wiersz, którego nowy
    (poprawiony) wynik już nie produkuje, nie może zostać osieroconym
    duplikatem. Usuwanie jest ograniczone do jednego `index_name`."""
    from buffett_scanner.db import clear_universe_membership_for_rebuild, insert_unresolved_ticker

    upsert_company(conn, cik="0001", name="Test SP500")
    upsert_company(conn, cik="0002", name="Test OTHER_INDEX")
    upsert_universe_membership(
        conn, cik="0001", index_name="SP500", start_date="2012-01-01", end_date=None,
        source="fja05680", source_snapshot_ref="ref1", cik_resolution_method="DIRECT",
    )
    upsert_universe_membership(
        conn, cik="0002", index_name="OTHER_INDEX", start_date="2012-01-01", end_date=None,
        source="fja05680", source_snapshot_ref="ref1", cik_resolution_method="DIRECT",
    )
    insert_universe_membership_conflict(
        conn, cik="0001", index_name="SP500", event_date="2013-01-05", action="REMOVE",
        conflict_type="ONLY_CANONICAL", tolerance_days=6, date_field="dateAdded",
        validation_rule_version="cik_tolerance_match_v1", validation_run_id="run1",
    )
    insert_unresolved_ticker(
        conn, source="fja05680", ticker="ZZZ", index_name="SP500",
        source_snapshot_ref="ref1", run_id="run1",
    )
    conn.commit()

    clear_universe_membership_for_rebuild(conn, "SP500")
    conn.commit()

    assert conn.execute(
        "SELECT COUNT(*) AS n FROM universe_membership WHERE index_name = 'SP500'"
    ).fetchone()["n"] == 0
    assert conn.execute(
        "SELECT COUNT(*) AS n FROM universe_membership_conflicts WHERE index_name = 'SP500'"
    ).fetchone()["n"] == 0
    assert conn.execute(
        "SELECT COUNT(*) AS n FROM universe_membership_unresolved_tickers WHERE index_name = 'SP500'"
    ).fetchone()["n"] == 0
    # OTHER_INDEX nietknięty.
    assert conn.execute(
        "SELECT COUNT(*) AS n FROM universe_membership WHERE index_name = 'OTHER_INDEX'"
    ).fetchone()["n"] == 1


def test_universe_membership_rejects_invalid_cik_resolution_method(conn):
    upsert_company(conn, cik="0001", name="Test Co")
    with pytest.raises(sqlite3.IntegrityError):
        upsert_universe_membership(
            conn, cik="0001", index_name="SP500", start_date="2012-01-01",
            end_date=None, source="fja05680", source_snapshot_ref="ref1",
            cik_resolution_method="GUESSED",  # nigdy nie zgadujemy -> tylko DIRECT/FORMAT_VARIANT
        )


def test_insert_universe_membership_conflict_is_append_only(conn):
    id1 = insert_universe_membership_conflict(
        conn, cik="0001", index_name="SP500", event_date="2013-01-05", action="REMOVE",
        conflict_type="ONLY_CANONICAL", tolerance_days=6, date_field="dateAdded",
        validation_rule_version="cik_tolerance_match_v1", validation_run_id="run1",
    )
    id2 = insert_universe_membership_conflict(
        conn, cik="0001", index_name="SP500", event_date="2013-01-05", action="REMOVE",
        conflict_type="ONLY_CANONICAL", tolerance_days=6, date_field="dateAdded",
        validation_rule_version="cik_tolerance_match_v1", validation_run_id="run2",
    )
    conn.commit()
    assert id1 != id2
    rows = conn.execute("SELECT * FROM universe_membership_conflicts WHERE cik = '0001'").fetchall()
    assert len(rows) == 2  # ponowne uruchomienie walidacji = nowe wiersze, nigdy UPDATE


def test_insert_unresolved_ticker_is_explicit_never_silent(conn):
    insert_unresolved_ticker(
        conn, source="fja05680", ticker="AABA", index_name="SP500",
        source_snapshot_ref="ref1", run_id="run1",
    )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM universe_membership_unresolved_tickers WHERE ticker = 'AABA'"
    ).fetchone()
    assert row is not None
    assert row["source"] == "fja05680"


def test_insert_unresolved_ticker_ignores_exact_duplicate(conn):
    insert_unresolved_ticker(
        conn, source="fja05680", ticker="AABA", index_name="SP500",
        source_snapshot_ref="ref1", run_id="run1",
    )
    insert_unresolved_ticker(
        conn, source="fja05680", ticker="AABA", index_name="SP500",
        source_snapshot_ref="ref1", run_id="run1",
    )
    conn.commit()
    rows = conn.execute(
        "SELECT * FROM universe_membership_unresolved_tickers WHERE ticker = 'AABA'"
    ).fetchall()
    assert len(rows) == 1


def test_get_universe_membership_as_of_end_date_is_exclusive(conn):
    upsert_company(conn, cik="A", name="A Corp")
    upsert_company(conn, cik="B", name="B Corp")
    upsert_universe_membership(
        conn, cik="A", index_name="SP500", start_date="2012-01-01", end_date="2015-01-01",
        source="fja05680", source_snapshot_ref="ref1", cik_resolution_method="DIRECT",
    )
    upsert_universe_membership(
        conn, cik="B", index_name="SP500", start_date="2012-06-01", end_date=None,
        source="fja05680", source_snapshot_ref="ref1", cik_resolution_method="DIRECT",
    )
    conn.commit()
    assert get_universe_membership_as_of(conn, "SP500", "2013-01-01") == ["A", "B"]
    assert get_universe_membership_as_of(conn, "SP500", "2015-01-01") == ["B"]  # A kończy się TEGO dnia
    assert get_universe_membership_as_of(conn, "SP500", "2011-01-01") == []


# ---------------------------------------------------------------------------
# sec_company_facts_cache (Faza 5.3b) — cache WYŁĄCZNIE surowego SEC
# company_facts JSON na potrzeby walk-forward backtestu. Nigdy wyliczonych
# historycznych fundamentals/snapshotów as_of; całkowicie niezależna od
# fundamentals_raw (ścieżka FMP/live-scan, bez zmian).
# ---------------------------------------------------------------------------

import hashlib
import json


def _sample_company_facts():
    return {
        "cik": 320193, "entityName": "Apple Inc.",
        "facts": {"us-gaap": {
            "NetIncomeLoss": {"units": {"USD": [
                {"start": "2023-01-01", "end": "2023-12-31", "val": 90.0, "filed": "2024-02-01", "fy": 2023, "fp": "FY"},
            ]}},
        }},
    }


def test_upsert_sec_company_facts_cache_round_trips_identical_json(conn):
    upsert_company(conn, cik="0000320193", name="Apple Inc.")
    facts = _sample_company_facts()
    upsert_sec_company_facts_cache(conn, cik="0000320193", company_facts=facts)
    conn.commit()
    cached = get_sec_company_facts_cache(conn, "0000320193")
    assert cached == facts


def test_get_sec_company_facts_cache_none_when_cik_never_cached(conn):
    upsert_company(conn, cik="0000320193", name="Apple Inc.")
    assert get_sec_company_facts_cache(conn, "0000320193") is None


def test_get_sec_company_facts_cache_does_not_fall_back_to_fundamentals_raw(conn):
    """Brak danych w sec_company_facts_cache MUSI pozostać jawnym None,
    nawet jeśli fundamentals_raw (inna ścieżka, inny provider) ma dane
    dla tego samego CIK — zero fallbacku między tymi dwoma tabelami."""
    upsert_company(conn, cik="0000320193", name="Apple Inc.")
    insert_fundamentals_rows(
        conn, "0000320193", source="fmp",
        rows=[{"fiscal_period": "FY2023", "period_end_date": "2023-12-31",
               "filed_date": "2024-02-01", "line_item": "net_income", "value": 999.0}],
    )
    conn.commit()
    assert get_sec_company_facts_cache(conn, "0000320193") is None


def test_upsert_sec_company_facts_cache_overwrites_on_same_cik(conn):
    upsert_company(conn, cik="0000320193", name="Apple Inc.")
    upsert_sec_company_facts_cache(conn, cik="0000320193", company_facts=_sample_company_facts())
    updated = _sample_company_facts()
    updated["facts"]["us-gaap"]["NetIncomeLoss"]["units"]["USD"].append(
        {"start": "2024-01-01", "end": "2024-12-31", "val": 100.0, "filed": "2025-02-01", "fy": 2024, "fp": "FY"}
    )
    upsert_sec_company_facts_cache(conn, cik="0000320193", company_facts=updated)
    conn.commit()
    cached = get_sec_company_facts_cache(conn, "0000320193")
    assert len(cached["facts"]["us-gaap"]["NetIncomeLoss"]["units"]["USD"]) == 2


def test_upsert_sec_company_facts_cache_returns_sha256_of_payload(conn):
    upsert_company(conn, cik="0000320193", name="Apple Inc.")
    facts = _sample_company_facts()
    returned_hash = upsert_sec_company_facts_cache(conn, cik="0000320193", company_facts=facts)
    expected = hashlib.sha256(json.dumps(facts, sort_keys=True).encode("utf-8")).hexdigest()
    assert returned_hash == expected
    row = conn.execute(
        "SELECT payload_sha256, source FROM sec_company_facts_cache WHERE cik = ?", ("0000320193",)
    ).fetchone()
    assert row["payload_sha256"] == expected
    assert row["source"] == "sec_edgar"


def test_init_db_creates_sec_company_facts_cache_table(conn):
    tables = {
        row["name"]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    assert "sec_company_facts_cache" in tables


# ---------------------------------------------------------------------------
# backfill_status (Faza 5.3b) — jawny status (cik, task_type) na potrzeby
# resumability; obecność wierszy w price_daily/sec_company_facts_cache
# NIE jest dowodem kompletności, stąd osobna, jawna klasyfikacja.
# ---------------------------------------------------------------------------

from buffett_scanner.db import get_backfill_status, list_backfill_statuses, upsert_backfill_status


def test_upsert_and_get_backfill_status_round_trip(conn):
    upsert_company(conn, cik="0000320193", name="Apple Inc.")
    upsert_backfill_status(
        conn, cik="0000320193", task_type="PRICES", status="COMPLETE",
        detail="1500 wierszy", run_id="run-1",
    )
    conn.commit()
    row = get_backfill_status(conn, "0000320193", "PRICES")
    assert row["status"] == "COMPLETE"
    assert row["detail"] == "1500 wierszy"
    assert row["run_id"] == "run-1"


def test_get_backfill_status_none_when_never_attempted(conn):
    upsert_company(conn, cik="0000320193", name="Apple Inc.")
    assert get_backfill_status(conn, "0000320193", "PRICES") is None


def test_upsert_backfill_status_overwrites_latest_status_not_history(conn):
    upsert_company(conn, cik="0000320193", name="Apple Inc.")
    upsert_backfill_status(conn, cik="0000320193", task_type="PRICES", status="PARTIAL", run_id="run-1")
    upsert_backfill_status(conn, cik="0000320193", task_type="PRICES", status="COMPLETE", run_id="run-2")
    conn.commit()
    row = get_backfill_status(conn, "0000320193", "PRICES")
    assert row["status"] == "COMPLETE"
    assert row["run_id"] == "run-2"
    all_rows = conn.execute(
        "SELECT * FROM backfill_status WHERE cik = ? AND task_type = ?", ("0000320193", "PRICES")
    ).fetchall()
    assert len(all_rows) == 1  # nadpisanie, nie druga linia historii


def test_backfill_status_prices_and_fundamentals_independent(conn):
    upsert_company(conn, cik="0000320193", name="Apple Inc.")
    upsert_backfill_status(conn, cik="0000320193", task_type="PRICES", status="COMPLETE", run_id="run-1")
    upsert_backfill_status(conn, cik="0000320193", task_type="FUNDAMENTALS", status="FAILED", run_id="run-1")
    conn.commit()
    assert get_backfill_status(conn, "0000320193", "PRICES")["status"] == "COMPLETE"
    assert get_backfill_status(conn, "0000320193", "FUNDAMENTALS")["status"] == "FAILED"


def test_backfill_status_rejects_unknown_status_value(conn):
    upsert_company(conn, cik="0000320193", name="Apple Inc.")
    with pytest.raises(sqlite3.IntegrityError):
        upsert_backfill_status(conn, cik="0000320193", task_type="PRICES", status="BOGUS", run_id="run-1")


def test_list_backfill_statuses_filters_by_task_type(conn):
    upsert_company(conn, cik="0000320193", name="Apple Inc.")
    upsert_company(conn, cik="0000789019", name="Microsoft Corp.")
    upsert_backfill_status(conn, cik="0000320193", task_type="PRICES", status="COMPLETE", run_id="run-1")
    upsert_backfill_status(conn, cik="0000789019", task_type="FUNDAMENTALS", status="COMPLETE", run_id="run-1")
    conn.commit()
    prices_only = list_backfill_statuses(conn, "PRICES")
    assert len(prices_only) == 1
    assert prices_only[0]["cik"] == "0000320193"
    assert len(list_backfill_statuses(conn)) == 2


# ---------------------------------------------------------------------------
# backtest_coverage / backtest_candidates (Faza 5.3c, pełny baseline
# walk-forward) — persystencja wyniku do artefaktu DB.
# ---------------------------------------------------------------------------

from buffett_scanner.backtest_harness import BacktestCandidate, ForwardReturns
from buffett_scanner.db import get_backtest_candidates, get_backtest_coverage, get_companies_sector_profiles, insert_backtest_candidate, insert_backtest_coverage
from buffett_scanner.walk_forward_coverage import CoverageSnapshot


def _coverage_snapshot(decision_date="2020-01-01"):
    return CoverageSnapshot(
        decision_date=decision_date, pit_universe_count=500, sufficient_price_count=450,
        sufficient_fundamentals_count=400, scanned_count=380, excluded_missing_price_count=50,
        excluded_missing_fundamentals_count=100, stage_no_decline_signal=350,
        stage_excluded_by_prefilter=10, stage_hard_gate_failed=15, stage_candidate=5,
    )


def _backtest_candidate(forward_returns=None):
    return BacktestCandidate(
        run_id="run-1", decision_date="2020-01-01", cik="0000320193", ticker_as_of_date="0000320193",
        decision_price=100.0, decline_flags={"month_decline": True},
        pit_fundamentals_period_end="2019-12-31", pit_fundamentals_filed_date="2020-02-01",
        financial_quality_breakdown={"fcf_positive": True}, safety_score=10.0, valuation_score=None,
        dividend_score=5.0, full_score=None, deterministic_partial_score=15.0,
        deterministic_score_pct=60.0, available_components=("safety", "dividend"),
        missing_components=("business_quality", "fear", "valuation"), hard_gate_passed=True,
        hard_gate_triggered=(), margin_of_safety_base_pct=None, config_version="config.yaml:abc",
        scoring_version="0.1.0-draft", universe_provenance="test", forward_returns=forward_returns,
    )


def test_insert_and_get_backtest_coverage(conn):
    insert_backtest_coverage(conn, run_id="run-1", snapshot=_coverage_snapshot())
    conn.commit()
    rows = get_backtest_coverage(conn, "run-1")
    assert len(rows) == 1
    assert rows[0]["pit_universe_count"] == 500
    assert rows[0]["scanned_count"] == 380


def test_backtest_coverage_isolated_by_run_id(conn):
    insert_backtest_coverage(conn, run_id="run-1", snapshot=_coverage_snapshot())
    insert_backtest_coverage(conn, run_id="run-2", snapshot=_coverage_snapshot())
    conn.commit()
    assert len(get_backtest_coverage(conn, "run-1")) == 1
    assert len(get_backtest_coverage(conn, "run-2")) == 1


def test_insert_and_get_backtest_candidate_without_forward_returns(conn):
    upsert_company(conn, cik="0000320193", name="Apple Inc.")
    insert_backtest_candidate(conn, run_id="run-1", candidate=_backtest_candidate())
    conn.commit()
    rows = get_backtest_candidates(conn, "run-1")
    assert len(rows) == 1
    assert rows[0]["cik"] == "0000320193"
    assert rows[0]["return_1m_pct"] is None
    assert rows[0]["available_components"] == "safety,dividend"


def test_insert_backtest_candidate_with_forward_returns(conn):
    upsert_company(conn, cik="0000320193", name="Apple Inc.")
    fr = ForwardReturns(return_1m_pct=5.0, return_3m_pct=10.0, return_6m_pct=None, return_12m_pct=20.0)
    insert_backtest_candidate(conn, run_id="run-1", candidate=_backtest_candidate(forward_returns=fr))
    conn.commit()
    row = get_backtest_candidates(conn, "run-1")[0]
    assert row["return_1m_pct"] == 5.0
    assert row["return_6m_pct"] is None
    assert row["return_12m_pct"] == 20.0


def test_get_companies_sector_profiles_defaults_to_general(conn):
    upsert_company(conn, cik="0000320193", name="Apple Inc.")
    conn.commit()
    assert get_companies_sector_profiles(conn) == {"0000320193": "GENERAL"}


def test_update_company_sector_profile_changes_only_that_column(conn):
    from buffett_scanner.db import update_company_sector_profile

    upsert_company(conn, cik="0000019617", name="JPMorgan Chase & Co.", sector="Financials")
    conn.commit()
    update_company_sector_profile(conn, cik="0000019617", sector_profile="BANK")
    conn.commit()
    row = conn.execute("SELECT name, sector, sector_profile FROM companies WHERE cik = ?", ("0000019617",)).fetchone()
    assert row["name"] == "JPMorgan Chase & Co."
    assert row["sector"] == "Financials"
    assert row["sector_profile"] == "BANK"


def test_update_company_sector_profile_is_noop_for_unknown_cik(conn):
    from buffett_scanner.db import update_company_sector_profile

    update_company_sector_profile(conn, cik="0000000001", sector_profile="BANK")
    conn.commit()
    assert get_companies_sector_profiles(conn) == {}


def _benchmark_snapshot(decision_date="2020-01-01"):
    from buffett_scanner.benchmark import BenchmarkSnapshot

    return BenchmarkSnapshot(
        decision_date=decision_date,
        ew_pit_universe_return_1m_pct=1.5, ew_pit_universe_return_3m_pct=3.0,
        ew_pit_universe_return_6m_pct=None, ew_pit_universe_return_12m_pct=12.0,
        ew_pit_universe_n_1m=480, ew_pit_universe_n_3m=470, ew_pit_universe_n_6m=0, ew_pit_universe_n_12m=400,
        spy_return_1m_pct=1.0, spy_return_3m_pct=2.5, spy_return_6m_pct=5.0, spy_return_12m_pct=10.0,
    )


def test_insert_and_get_backtest_benchmark(conn):
    from buffett_scanner.db import get_backtest_benchmark, insert_backtest_benchmark

    insert_backtest_benchmark(conn, run_id="run-1", snapshot=_benchmark_snapshot())
    conn.commit()
    rows = get_backtest_benchmark(conn, "run-1")
    assert len(rows) == 1
    assert rows[0]["ew_pit_universe_return_1m_pct"] == 1.5
    assert rows[0]["ew_pit_universe_return_6m_pct"] is None
    assert rows[0]["ew_pit_universe_n_6m"] == 0
    assert rows[0]["spy_return_12m_pct"] == 10.0


def test_backtest_benchmark_isolated_by_run_id(conn):
    from buffett_scanner.db import get_backtest_benchmark, insert_backtest_benchmark

    insert_backtest_benchmark(conn, run_id="run-1", snapshot=_benchmark_snapshot())
    insert_backtest_benchmark(conn, run_id="run-2", snapshot=_benchmark_snapshot())
    conn.commit()
    assert len(get_backtest_benchmark(conn, "run-1")) == 1
    assert len(get_backtest_benchmark(conn, "run-2")) == 1

"""Testy CLI na poziomie `cli.main` -- na razie tylko defensywna asercja
Fazy 5.3c (Decyzja właścicielki 2026-10-04, po realnym znalezisku:
dual-class share tickery dawały nakładające się przedziały membership
tego samego CIK w `universe_membership`, co crashowało realny baseline
walk-forward na UNIQUE constraint w `backtest_candidates`)."""

from __future__ import annotations

import pytest

import buffett_scanner.cli as cli
from buffett_scanner.db import init_db, upsert_company, upsert_universe_membership


def test_run_baseline_walk_forward_fails_fast_on_duplicate_cik_in_universe_membership(tmp_path):
    """Jeśli `universe_membership` zawiera (wbrew naprawie z 2026-10-04)
    nakładające się przedziały tego samego CIK -- symulowane tu wprost,
    bez przechodzenia przez builder -- `run-baseline-walk-forward` MUSI
    rzucić czytelny błąd zamiast cicho liczyć zdublowanego kandydata
    (co wcześniej crashowało na UNIQUE constraint w backtest_candidates,
    głębiej w funkcji, z mniej czytelnym komunikatem). Nigdy nie wolno
    "naprawić" tego przez DISTINCT w zapytaniu -- to by ukryło problem."""
    db_path = tmp_path / "test.db"
    conn = init_db(db_path)
    upsert_company(conn, cik="0001652044", name="Alphabet Inc.")
    # Dwa NAKŁADAJĄCE SIĘ przedziały tego samego CIK -- dokładnie kształt
    # realnego błędu (GOOGL/GOOG), wstrzyknięty wprost do bazy, symulując
    # dataset, który nie przeszedł jeszcze przez naprawiony builder.
    upsert_universe_membership(
        conn, cik="0001652044", index_name="SP500", start_date="2012-01-01", end_date=None,
        source="fja05680", source_snapshot_ref="test", cik_resolution_method="DIRECT",
    )
    upsert_universe_membership(
        conn, cik="0001652044", index_name="SP500", start_date="2014-04-03", end_date=None,
        source="fja05680", source_snapshot_ref="test", cik_resolution_method="DIRECT",
    )
    conn.commit()
    conn.close()

    with pytest.raises(RuntimeError, match="FAIL FAST"):
        cli.main([
            "--db", str(db_path), "run-baseline-walk-forward",
            "--window-start", "2015-01-01", "--window-end", "2015-02-01",
        ])


# ---------------------------------------------------------------------------
# run-calibration-candidate (Faza 5.4, protokół zatwierdzony 2026-10-05)
# ---------------------------------------------------------------------------


def test_run_calibration_candidate_unknown_round_is_an_error(tmp_path, capsys):
    db_path = tmp_path / "test.db"
    init_db(db_path).close()
    exit_code = cli.main([
        "--db", str(db_path), "run-calibration-candidate", "--round", "99", "--candidate", "baseline",
    ])
    assert exit_code == 1
    assert "nieznana runda" in capsys.readouterr().err


def test_run_calibration_candidate_unknown_candidate_is_an_error(tmp_path, capsys):
    db_path = tmp_path / "test.db"
    init_db(db_path).close()
    exit_code = cli.main([
        "--db", str(db_path), "run-calibration-candidate", "--round", "1", "--candidate", "nope",
    ])
    assert exit_code == 1
    assert "nieznany kandydat" in capsys.readouterr().err


def test_run_calibration_candidate_fails_fast_on_duplicate_cik(tmp_path):
    """Ten sam FAIL FAST co run-baseline-walk-forward -- okno kalibracyjne
    (2012-2021) MUSI też wykryć nakładające się przedziały membership,
    nigdy cicho przez DISTINCT."""
    db_path = tmp_path / "test.db"
    conn = init_db(db_path)
    upsert_company(conn, cik="0001652044", name="Alphabet Inc.")
    upsert_universe_membership(
        conn, cik="0001652044", index_name="SP500", start_date="2012-01-01", end_date=None,
        source="fja05680", source_snapshot_ref="test", cik_resolution_method="DIRECT",
    )
    upsert_universe_membership(
        conn, cik="0001652044", index_name="SP500", start_date="2014-04-03", end_date=None,
        source="fja05680", source_snapshot_ref="test", cik_resolution_method="DIRECT",
    )
    conn.commit()
    conn.close()

    with pytest.raises(RuntimeError, match="FAIL FAST"):
        cli.main(["--db", str(db_path), "run-calibration-candidate", "--round", "1", "--candidate", "baseline"])


def test_run_calibration_candidate_baseline_smoke_test_on_empty_db(tmp_path, capsys):
    """Smoke test -- zero spółek, zero kandydatów, ale pipeline (config
    override, okno kalibracyjne hardkodowane, zapis do calibration_runs)
    musi przejść od początku do końca bez wyjątku."""
    db_path = tmp_path / "test.db"
    init_db(db_path).close()
    exit_code = cli.main([
        "--db", str(db_path), "run-calibration-candidate", "--round", "1", "--candidate", "baseline",
    ])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "Łącznie kandydatów na oknie kalibracyjnym: 0" in out

    from buffett_scanner.db import connect, get_calibration_runs

    conn = connect(db_path)
    rows = get_calibration_runs(conn, round=1)
    assert len(rows) == 1
    assert rows[0]["candidate_name"] == "baseline"
    assert rows[0]["training_window_end"] == "2021-12-01"
    assert rows[0]["pooled_spearman"] is None  # Round 1: PRIMARY pozostaje median excess, Spearman kolumny NULL


# ---------------------------------------------------------------------------
# run-calibration-candidate Round 2A/2B (Faza 5.4b, korekta metodologii
# zatwierdzona 2026-10-05) -- wymagają --subround.
# ---------------------------------------------------------------------------


def test_run_calibration_candidate_round_2_without_subround_is_an_error(tmp_path, capsys):
    db_path = tmp_path / "test.db"
    init_db(db_path).close()
    exit_code = cli.main([
        "--db", str(db_path), "run-calibration-candidate", "--round", "2", "--candidate", "2a_default",
    ])
    assert exit_code == 1
    assert "--subround" in capsys.readouterr().err


def test_run_calibration_candidate_round_2a_unknown_candidate_is_an_error(tmp_path, capsys):
    db_path = tmp_path / "test.db"
    init_db(db_path).close()
    exit_code = cli.main([
        "--db", str(db_path), "run-calibration-candidate", "--round", "2", "--subround", "a", "--candidate", "nope",
    ])
    assert exit_code == 1
    assert "nieznany kandydat" in capsys.readouterr().err


def test_run_calibration_candidate_round_2a_smoke_test_on_empty_db(tmp_path, capsys):
    """Round 2A (SAFETY+DIVIDEND) -- PRIMARY metric to Spearman, nie
    median excess (Faza 5.4b). Smoke test na pustej bazie: pipeline musi
    przejść od początku do końca i zapisać kolumny spearman_*."""
    db_path = tmp_path / "test.db"
    init_db(db_path).close()
    exit_code = cli.main([
        "--db", str(db_path), "run-calibration-candidate",
        "--round", "2", "--subround", "a", "--candidate", "2a_default",
    ])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "PRIMARY metric Round 2a (Faza 5.4b): Spearman" in out
    assert "DIAGNOSTIC (Round 1 primary metric" in out

    from buffett_scanner.db import connect, get_calibration_runs

    conn = connect(db_path)
    rows = get_calibration_runs(conn, round=2)
    assert len(rows) == 1
    assert rows[0]["candidate_name"] == "2a_default"
    assert rows[0]["subround"] == "2a"
    assert rows[0]["population"] == "FULL_PARTIAL_MODEL"
    assert rows[0]["pooled_n"] == 0  # pusta baza
    assert rows[0]["pooled_spearman"] is None


def test_run_calibration_candidate_round_2b_smoke_test_on_empty_db(tmp_path, capsys):
    """Round 2B (VALUATION) -- wyłącznie complete-valuation subset."""
    db_path = tmp_path / "test.db"
    init_db(db_path).close()
    exit_code = cli.main([
        "--db", str(db_path), "run-calibration-candidate",
        "--round", "2", "--subround", "b", "--candidate", "2b_valuation_0",
    ])
    assert exit_code == 0

    from buffett_scanner.db import connect, get_calibration_runs

    conn = connect(db_path)
    rows = get_calibration_runs(conn, round=2)
    assert len(rows) == 1
    assert rows[0]["candidate_name"] == "2b_valuation_0"
    assert rows[0]["subround"] == "2b"
    assert rows[0]["population"] == "COMPLETE_VALUATION_SUBSET"


# ---------------------------------------------------------------------------
# run-live-scan (Faza 6, domknięcie MVP V0) -- end-to-end z fejkowymi
# providerami (zero realnej sieci/Claude API), żeby wyłapać realne bugi
# integracyjne w orkiestracji (np. brakujący upsert_scoring_model_version
# -> FOREIGN KEY constraint failed na insert_analysis, znaleziony w
# pierwszym małym teście na GitHub Actions 2026-10-05, run 37353678323).
# ---------------------------------------------------------------------------

def _flat_then_drop_price_rows(n_flat: int = 260) -> list[dict]:
    """`n_flat` sesji po 100.0, potem jedna sesja spadku do 70.0 (-30%,
    przekracza drawdown_from_52w_high_pct=-25.0 z config.yaml) --
    najprostszy sposób, by decline scanner coś wytypował niezależnie od
    realnej daty uruchomienia testu."""
    import datetime as _dt

    start = _dt.date(2024, 1, 2)
    rows = []
    for i in range(n_flat):
        d = start + _dt.timedelta(days=i)
        rows.append({"date": d.isoformat(), "open": 100.0, "high": 101.0, "low": 99.0,
                     "close": 100.0, "adj_close": 100.0, "volume": 1_000_000})
    last = start + _dt.timedelta(days=n_flat)
    rows.append({"date": last.isoformat(), "open": 100.0, "high": 100.0, "low": 69.0,
                 "close": 70.0, "adj_close": 70.0, "volume": 5_000_000})
    return rows


class _FakeFMPClient:
    def __init__(self, api_key):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_sp500_constituents(self):
        return [{"cik": "0000320193", "symbol": "AAPL", "name": "Apple Inc.",
                  "sector": "Technology", "subSector": "Consumer Electronics"}]

    def get_historical_prices(self, symbol, *, from_date, to_date):
        return _flat_then_drop_price_rows()

    def get_income_statement(self, symbol):
        return [
            {"date": "2023-12-31", "fiscalYear": 2023, "period": "FY",
             "revenue": 900.0, "netIncome": 50.0, "ebitda": 200.0,
             "weightedAverageShsOutDil": 100.0},
            {"date": "2024-12-31", "fiscalYear": 2024, "period": "FY",
             "revenue": 1000.0, "netIncome": 70.0, "ebitda": 220.0,
             "weightedAverageShsOutDil": 100.0},
        ]

    def get_balance_sheet_statement(self, symbol):
        return [
            {"date": "2023-12-31", "fiscalYear": 2023, "period": "FY",
             "totalDebt": 100.0, "cashAndCashEquivalents": 150.0,
             "totalCurrentAssets": 400.0, "totalCurrentLiabilities": 200.0},
            {"date": "2024-12-31", "fiscalYear": 2024, "period": "FY",
             "totalDebt": 100.0, "cashAndCashEquivalents": 150.0,
             "totalCurrentAssets": 400.0, "totalCurrentLiabilities": 200.0},
        ]

    def get_cash_flow_statement(self, symbol):
        return [
            {"date": "2023-12-31", "fiscalYear": 2023, "period": "FY",
             "operatingCashFlow": 150.0, "capitalExpenditure": -20.0,
             "commonDividendsPaid": -10.0, "commonStockRepurchased": -10.0},
            {"date": "2024-12-31", "fiscalYear": 2024, "period": "FY",
             "operatingCashFlow": 170.0, "capitalExpenditure": -20.0,
             "commonDividendsPaid": -12.0, "commonStockRepurchased": -10.0},
        ]


class _FakeSecEdgarClient:
    def __init__(self, user_agent):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_filings(self, cik):
        return [{"form": "10-K", "accession_number": "0000320193-24-000001",
                  "filing_date": "2024-11-01", "report_date": "2024-09-28",
                  "primary_document": "aapl10k.htm"}]

    def fetch_and_hash_document(self, url):
        return {"url": url, "content_hash": "a" * 64, "content_length": 100}


class _FakeClaudeClient:
    def __init__(self, api_key, *, model, max_output_tokens=4000):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def generate_analysis(self, prompt):
        from buffett_scanner.analysis_schema import (
            AnalysisOutput,
            DividendTrapAlert,
            FearAnalysis,
            FinancialQualityCommentary,
            ManagementSection,
            MoatSection,
            ScoredSection,
        )

        return AnalysisOutput(
            ticker="AAPL", schema_version="1.0",
            business_understandability=ScoredSection(score=5, confidence="MEDIUM"),
            moat=MoatSection(score=6, confidence="MEDIUM"),
            financial_quality_commentary=FinancialQualityCommentary(confidence="MEDIUM"),
            management_capital_allocation=ManagementSection(score=6, confidence="MEDIUM"),
            fear_analysis=FearAnalysis(classification="TEMPORARY", confidence="MEDIUM",
                                        trigger="Spadek ceny -30%"),
            dividend_trap_alert=DividendTrapAlert(triggered=False),
            bull_case=["Silna marka"], bear_case=["Presja konkurencyjna"],
            why_market_may_be_right=["Możliwe spowolnienie wzrostu"],
            why_this_may_not_be_a_bargain=["MoS może być iluzoryczny"],
            thesis_invalidation=["Dalszy spadek marż"],
            biggest_unknown="Wpływ nowego cyklu produktowego",
            cited_source_ids=["src-1"],
        )


def test_run_live_scan_end_to_end_with_fake_providers(tmp_path, monkeypatch, capsys):
    """Regresja dla realnego buga znalezionego 2026-10-05 (GH Actions run
    37353678323): `cmd_run_live_scan` nie wołał `upsert_scoring_model_version`
    przed `insert_analysis`, co dawało `sqlite3.IntegrityError: FOREIGN KEY
    constraint failed` dla KAŻDEGO kandydata, który przeszedł decline
    screening + prefilter. Fejkowe providery (zero sieci/Claude API) -- ten
    sam poziom izolacji co pozostałe testy CLI w tym pliku."""
    monkeypatch.setenv("FMP_API_KEY", "dummy")
    monkeypatch.setenv("SEC_EDGAR_USER_AGENT", "Tajfun Lab test test@example.com")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy")
    monkeypatch.setattr(cli, "FMPClient", _FakeFMPClient)
    monkeypatch.setattr(cli, "SecEdgarClient", _FakeSecEdgarClient)
    monkeypatch.setattr(cli, "ClaudeClient", _FakeClaudeClient)

    db_path = tmp_path / "test.db"
    exit_code = cli.main([
        "--db", str(db_path), "run-live-scan", "--sample", "AAPL", "--limit", "5",
    ])

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "WYTYPOWANO AAPL" in out
    assert "Kandydat 1: AAPL" in out
    assert "Silna marka" in out
    assert "No qualifying opportunities" not in out

    from buffett_scanner.db import connect

    conn = connect(db_path)
    rows = conn.execute("SELECT cik, total_score FROM analyses").fetchall()
    assert len(rows) == 1
    assert rows[0]["cik"] == "0000320193"


def test_run_live_scan_reports_no_qualifying_opportunities_when_nothing_surfaces(
    tmp_path, monkeypatch, capsys,
):
    monkeypatch.setenv("FMP_API_KEY", "dummy")
    monkeypatch.setenv("SEC_EDGAR_USER_AGENT", "Tajfun Lab test test@example.com")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy")

    class _FlatFMPClient(_FakeFMPClient):
        def get_historical_prices(self, symbol, *, from_date, to_date):
            import datetime as _dt
            start = _dt.date(2024, 1, 2)
            return [
                {"date": (start + _dt.timedelta(days=i)).isoformat(), "open": 100.0,
                 "high": 101.0, "low": 99.0, "close": 100.0, "adj_close": 100.0,
                 "volume": 1_000_000}
                for i in range(260)
            ]

    monkeypatch.setattr(cli, "FMPClient", _FlatFMPClient)

    db_path = tmp_path / "test.db"
    exit_code = cli.main([
        "--db", str(db_path), "run-live-scan", "--sample", "AAPL", "--limit", "5",
    ])

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "No qualifying opportunities today" in out

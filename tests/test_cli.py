"""Testy CLI na poziomie `cli.main` -- na razie tylko defensywna asercja
Fazy 5.3c (Decyzja właścicielki 2026-10-04, po realnym znalezisku:
dual-class share tickery dawały nakładające się przedziały membership
tego samego CIK w `universe_membership`, co crashowało realny baseline
walk-forward na UNIQUE constraint w `backtest_candidates`)."""

from __future__ import annotations

import json

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
            "--db", str(db_path), "run-baseline-walk-forward", "--sector-profiles", "current",
            "--window-start", "2015-01-01", "--window-end", "2015-02-01",
        ])


# ---------------------------------------------------------------------------
# run-calibration-candidate (Faza 5.4, protokół zatwierdzony 2026-10-05)
# ---------------------------------------------------------------------------


def test_run_calibration_candidate_unknown_round_is_an_error(tmp_path, capsys):
    db_path = tmp_path / "test.db"
    init_db(db_path).close()
    exit_code = cli.main([
        "--db", str(db_path), "run-calibration-candidate", "--sector-profiles", "current", "--round", "99", "--candidate", "baseline",
    ])
    assert exit_code == 1
    assert "nieznana runda" in capsys.readouterr().err


def test_run_calibration_candidate_unknown_candidate_is_an_error(tmp_path, capsys):
    db_path = tmp_path / "test.db"
    init_db(db_path).close()
    exit_code = cli.main([
        "--db", str(db_path), "run-calibration-candidate", "--sector-profiles", "current", "--round", "1", "--candidate", "nope",
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
        cli.main(["--db", str(db_path), "run-calibration-candidate", "--sector-profiles", "current", "--round", "1", "--candidate", "baseline"])


def test_run_calibration_candidate_baseline_smoke_test_on_empty_db(tmp_path, capsys):
    """Smoke test -- zero spółek, zero kandydatów, ale pipeline (config
    override, okno kalibracyjne hardkodowane, zapis do calibration_runs)
    musi przejść od początku do końca bez wyjątku."""
    db_path = tmp_path / "test.db"
    init_db(db_path).close()
    exit_code = cli.main([
        "--db", str(db_path), "run-calibration-candidate", "--sector-profiles", "current", "--round", "1", "--candidate", "baseline",
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
        "--db", str(db_path), "run-calibration-candidate", "--sector-profiles", "current", "--round", "2", "--candidate", "2a_default",
    ])
    assert exit_code == 1
    assert "--subround" in capsys.readouterr().err


def test_run_calibration_candidate_round_2a_unknown_candidate_is_an_error(tmp_path, capsys):
    db_path = tmp_path / "test.db"
    init_db(db_path).close()
    exit_code = cli.main([
        "--db", str(db_path), "run-calibration-candidate", "--sector-profiles", "current", "--round", "2", "--subround", "a", "--candidate", "nope",
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
        "--db", str(db_path), "run-calibration-candidate", "--sector-profiles", "current",
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
        "--db", str(db_path), "run-calibration-candidate", "--sector-profiles", "current",
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

    # 2026-10-23: skan na żywo klasyfikuje sektor z SIC (jak backtest) i
    # weryfikuje zerowy CAPEX w SEC XBRL. Domyślnie: spółka technologiczna
    # (SIC 3571 -> GENERAL), bez faktów XBRL.
    sic = "3571"
    company_facts: dict = {}

    def get_sic_classification(self, cik):
        return {"sic": self.sic, "sic_description": None}

    def get_company_facts(self, cik):
        return self.company_facts


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
        from buffett_scanner.providers.claude import ClaudeAnalysisResult, ClaudeUsage

        output = AnalysisOutput(
            ticker="AAPL", schema_version="1.0",
            business_understandability=ScoredSection(score=5, confidence="MEDIUM"),
            moat=MoatSection(score=6, confidence="MEDIUM"),
            financial_quality_commentary=FinancialQualityCommentary(confidence="MEDIUM"),
            management_capital_allocation=ManagementSection(score=6, confidence="MEDIUM"),
            fear_analysis=FearAnalysis(classification="TEMPORARY", confidence="MEDIUM",
                                        trigger="Spadek ceny -30%"),
            dividend_trap_alert=DividendTrapAlert(triggered=False),
            bull_case=["Silna marka i wysokie bariery wejścia dla konkurentów."],
            bear_case=["Presja konkurencyjna może trwale obniżyć marże w kluczowym segmencie."],
            why_market_may_be_right=["Możliwe trwałe spowolnienie wzrostu przychodów."],
            why_this_may_not_be_a_bargain=["MoS może być iluzoryczny przy niepewnych założeniach wzrostu."],
            thesis_invalidation=["Dalszy spadek marż operacyjnych poniżej historycznego poziomu."],
            biggest_unknown="Wpływ nowego cyklu produktowego na przyszłe przychody i marże.",
            cited_source_ids=["src-1"],
        )
        usage = ClaudeUsage(
            model="claude-sonnet-5", input_tokens=1000, output_tokens=200,
            cache_creation_input_tokens=None, cache_read_input_tokens=None,
            thinking_tokens=None, service_tier="standard",
        )
        return ClaudeAnalysisResult(output=output, usage=usage)


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
    # Faza 6e — agregat per-run w raporcie CLI, bez wyliczonego $.
    assert "Telemetria Anthropic API usage" in out
    assert "input_tokens: 1000, output_tokens: 200" in out
    assert "Brak wyliczonego kosztu $" in out

    from buffett_scanner.db import connect

    conn = connect(db_path)
    rows = conn.execute(
        "SELECT cik, total_score, llm_response_model, llm_input_tokens, llm_output_tokens "
        "FROM analyses"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["cik"] == "0000320193"
    # Faza 6e — realny usage z `_FakeClaudeClient` (model/input_tokens/
    # output_tokens zdefiniowane w teście) musi trafić do `analyses`.
    assert rows[0]["llm_response_model"] == "claude-sonnet-5"
    assert rows[0]["llm_input_tokens"] == 1000
    assert rows[0]["llm_output_tokens"] == 200

    candidate_rows = conn.execute(
        "SELECT llm_input_tokens, llm_output_tokens FROM live_scan_candidates"
    ).fetchall()
    assert len(candidate_rows) == 1
    assert candidate_rows[0]["llm_input_tokens"] == 1000
    assert candidate_rows[0]["llm_output_tokens"] == 200


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


# ---------------------------------------------------------------------------
# Faza 6c (OPCJA 3, 2026-10-06) -- dwustopniowy pipeline: deterministic
# ranking WSZYSTKICH screened kandydatów (zero LLM) -> shortlist (TOP N +
# remisy, operacyjny/kosztowy budget) -> pełna analiza Claude WYŁĄCZNIE
# dla shortlisty, resumable (PENDING/COMPLETE/FAILED) + cache'owana.
# ---------------------------------------------------------------------------


class _TwoTickerFMPClient(_FakeFMPClient):
    """AAPL i MSFT, z RÓŻNYMI finalnymi cenami (-> różny Margin of Safety
    -> różny deterministic_score_pct, zero przypadkowego remisu) --
    niezbędne do testowania obcięcia shortlisty do konkretnego `limit`."""

    FINAL_CLOSE = {"AAPL": 70.0, "MSFT": 50.0}

    def get_sp500_constituents(self):
        return [
            {"cik": "0000320193", "symbol": "AAPL", "name": "Apple Inc.",
             "sector": "Technology", "subSector": "Consumer Electronics"},
            {"cik": "0000789019", "symbol": "MSFT", "name": "Microsoft Corp.",
             "sector": "Technology", "subSector": "Software"},
        ]

    def get_historical_prices(self, symbol, *, from_date, to_date):
        return _flat_then_drop_price_rows_with_close(self.FINAL_CLOSE[symbol])


def _flat_then_drop_price_rows_with_close(final_close: float, n_flat: int = 260) -> list[dict]:
    import datetime as _dt

    start = _dt.date(2024, 1, 2)
    rows = []
    for i in range(n_flat):
        d = start + _dt.timedelta(days=i)
        rows.append({"date": d.isoformat(), "open": 100.0, "high": 101.0, "low": 99.0,
                     "close": 100.0, "adj_close": 100.0, "volume": 1_000_000})
    last = start + _dt.timedelta(days=n_flat)
    rows.append({"date": last.isoformat(), "open": 100.0, "high": 100.0, "low": final_close - 1,
                 "close": final_close, "adj_close": final_close, "volume": 5_000_000})
    return rows


class _CountingClaudeClient:
    """Fejkowy ClaudeClient liczący wywołania w module-level liczniku
    (przetrwa wiele osobnych `cli.main()` -- np. run-live-scan +
    analyze-live-scan-shortlist w jednym teście) i opcjonalnie failujący
    dla tickerów podanych w `fail_tickers` (rozpoznawanych po treści
    promptu, który zawsze zawiera dokładny ticker -- patrz prompt.py)."""

    call_count = {"n": 0}
    fail_tickers: set[str] = set()
    # Faza 6f (BUGFIX V0 OUTPUT CONTRACT): tickery, dla których fake zwraca
    # WIELE semantycznie pustych pól anti-bias naraz (thesis_invalidation
    # ORAZ biggest_unknown) -- jak CBOE/DECK/INTU/ACN w realnym live runie.
    # Faza 6h: to NIE jest izolowany przypadek thesis_invalidation, więc
    # musi iść prosto do FAILED, bez targeted repair (Test D).
    semantically_incomplete_tickers: set[str] = set()
    # Faza 6h (TARGETED FIELD REPAIR): tickery, dla których fake zwraca
    # WYŁĄCZNIE puste thesis_invalidation -- wszystkie inne wymagane pola
    # (bull_case/bear_case/why_market_may_be_right/why_this_may_not_be_a_
    # bargain/biggest_unknown) poprawne. To jest izolowany przypadek, dla
    # którego targeted repair MUSI być próbowany (Test B/C).
    thesis_invalidation_only_empty_tickers: set[str] = set()
    # Faza 6h: tickery, dla których SAM repair call też zwraca semantycznie
    # puste thesis_invalidation -- FAILED po repair, bez kolejnego repair
    # (Test C).
    repair_fails_tickers: set[str] = set()
    repair_call_count = {"n": 0}
    # Pełna treść promptu każdego full analysis call, w kolejności -- m.in.
    # do potwierdzenia, że full-analysis call nigdy nie jest powtarzany
    # (Faza 6h usunęła full-response retry -- co najwyżej 1 full call).
    received_prompts: list = []
    # Faza 6h: pełna treść promptu każdego targeted repair call, w kolejności.
    received_repair_prompts: list = []
    # 2026-10-23: pola żądane w każdym wywołaniu naprawy, w kolejności.
    received_repair_fields: list = []
    # 2026-10-23: tickery z błędem strukturalnym (cytowanie spoza listy) +
    # pustym polem -- takiej analizy nie naprawiamy.
    structural_violation_tickers: set[str] = set()

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
        from buffett_scanner.providers.claude import ClaudeAnalysisResult, ClaudeError, ClaudeUsage

        type(self).call_count["n"] += 1
        type(self).received_prompts.append(prompt)
        for ticker in self.fail_tickers:
            if f'"{ticker}"' in prompt:
                # Realny 400 insufficient-credit: SDK nigdy nie dostaje
                # `response`, więc `usage=None` -- nic nie wymyślamy.
                raise ClaudeError(
                    f"Claude API zwróciło błąd (400): Your credit balance is too low ({ticker})"
                )

        for ticker in self.structural_violation_tickers:
            if f'"{ticker}"' in prompt:
                structural_output = AnalysisOutput(
                    ticker=ticker, schema_version="1.0",
                    business_understandability=ScoredSection(score=5, confidence="MEDIUM"),
                    moat=MoatSection(score=6, confidence="MEDIUM"),
                    financial_quality_commentary=FinancialQualityCommentary(confidence="MEDIUM"),
                    management_capital_allocation=ManagementSection(score=6, confidence="MEDIUM"),
                    fear_analysis=FearAnalysis(classification="TEMPORARY", confidence="MEDIUM", trigger="x"),
                    dividend_trap_alert=DividendTrapAlert(triggered=False),
                    bull_case=["Solidna pozycja rynkowa i stabilne przepływy pieniężne."],
                    bear_case=["Rosnąca konkurencja może ograniczyć tempo wzrostu przychodów."],
                    why_market_may_be_right=["Spadek może odzwierciedlać trwałe spowolnienie wzrostu."],
                    why_this_may_not_be_a_bargain=["Obecna wycena może już uwzględniać realne ryzyko."],
                    thesis_invalidation=[],
                    biggest_unknown="Nie wiadomo, czy spadek marży w ostatnim kwartale jest trwały.",
                    cited_source_ids=["src-1", "zrodlo-spoza-listy"],  # błąd strukturalny
                )
                return ClaudeAnalysisResult(output=structural_output, usage=ClaudeUsage(
                    model="claude-sonnet-5", input_tokens=700, output_tokens=90,
                    cache_creation_input_tokens=None, cache_read_input_tokens=None,
                    thinking_tokens=None, service_tier="standard",
                ))

        for ticker in self.semantically_incomplete_tickers:
            if f'"{ticker}"' in prompt:
                incomplete_output = AnalysisOutput(
                    ticker=ticker, schema_version="1.0",
                    business_understandability=ScoredSection(score=5, confidence="MEDIUM"),
                    moat=MoatSection(score=6, confidence="MEDIUM"),
                    financial_quality_commentary=FinancialQualityCommentary(confidence="MEDIUM"),
                    management_capital_allocation=ManagementSection(score=6, confidence="MEDIUM"),
                    fear_analysis=FearAnalysis(classification="TEMPORARY", confidence="MEDIUM", trigger="x"),
                    dividend_trap_alert=DividendTrapAlert(triggered=False),
                    bull_case=["Solidna pozycja rynkowa i stabilne przepływy pieniężne."],
                    bear_case=["Rosnąca konkurencja może ograniczyć tempo wzrostu przychodów."],
                    why_market_may_be_right=["Spadek może odzwierciedlać trwałe spowolnienie wzrostu."],
                    why_this_may_not_be_a_bargain=["Obecna wycena może już uwzględniać realne ryzyko."],
                    thesis_invalidation=[],  # semantycznie pusty -- jak CBOE/DECK/INTU/ACN w realnym runie
                    biggest_unknown="",  # semantycznie pusty
                    cited_source_ids=["src-1"],
                )
                incomplete_usage = ClaudeUsage(
                    model="claude-sonnet-5", input_tokens=500, output_tokens=80,
                    cache_creation_input_tokens=None, cache_read_input_tokens=None,
                    thinking_tokens=None, service_tier="standard",
                )
                return ClaudeAnalysisResult(output=incomplete_output, usage=incomplete_usage)

        for ticker in self.thesis_invalidation_only_empty_tickers:
            if f'"{ticker}"' in prompt:
                isolated_incomplete_output = AnalysisOutput(
                    ticker=ticker, schema_version="1.0",
                    business_understandability=ScoredSection(score=5, confidence="MEDIUM"),
                    moat=MoatSection(score=6, confidence="MEDIUM"),
                    financial_quality_commentary=FinancialQualityCommentary(confidence="MEDIUM"),
                    management_capital_allocation=ManagementSection(score=6, confidence="MEDIUM"),
                    fear_analysis=FearAnalysis(classification="TEMPORARY", confidence="MEDIUM", trigger="x"),
                    dividend_trap_alert=DividendTrapAlert(triggered=False),
                    bull_case=["Solidna pozycja rynkowa i stabilne przepływy pieniężne."],
                    bear_case=["Rosnąca konkurencja może ograniczyć tempo wzrostu przychodów."],
                    why_market_may_be_right=["Spadek może odzwierciedlać trwałe spowolnienie wzrostu."],
                    why_this_may_not_be_a_bargain=["Obecna wycena może już uwzględniać realne ryzyko."],
                    thesis_invalidation=[],  # JEDYNY semantycznie puste pole -- izolowany przypadek
                    biggest_unknown="Nie wiadomo, czy spadek marży w ostatnim kwartale jest trwały czy cykliczny.",
                    cited_source_ids=["src-1"],
                )
                isolated_incomplete_usage = ClaudeUsage(
                    model="claude-sonnet-5", input_tokens=950, output_tokens=140,
                    cache_creation_input_tokens=None, cache_read_input_tokens=None,
                    thinking_tokens=None, service_tier="standard",
                )
                return ClaudeAnalysisResult(output=isolated_incomplete_output, usage=isolated_incomplete_usage)

        output = AnalysisOutput(
            ticker="X", schema_version="1.0",
            business_understandability=ScoredSection(score=5, confidence="MEDIUM"),
            moat=MoatSection(score=6, confidence="MEDIUM"),
            financial_quality_commentary=FinancialQualityCommentary(confidence="MEDIUM"),
            management_capital_allocation=ManagementSection(score=6, confidence="MEDIUM"),
            fear_analysis=FearAnalysis(classification="TEMPORARY", confidence="MEDIUM", trigger="x"),
            dividend_trap_alert=DividendTrapAlert(triggered=False),
            bull_case=["Solidna pozycja rynkowa i stabilne przepływy pieniężne."],
            bear_case=["Rosnąca konkurencja może ograniczyć tempo wzrostu przychodów."],
            why_market_may_be_right=["Spadek może odzwierciedlać trwałe spowolnienie wzrostu."],
            why_this_may_not_be_a_bargain=["Obecna wycena może już uwzględniać realne ryzyko."],
            thesis_invalidation=["Utrata kluczowego klienta odpowiadającego za istotną część przychodów."],
            biggest_unknown="Nie wiadomo, czy spadek marży w ostatnim kwartale jest trwały czy cykliczny.",
            cited_source_ids=["src-1"],
        )
        usage = ClaudeUsage(
            model="claude-sonnet-5", input_tokens=900, output_tokens=150,
            cache_creation_input_tokens=None, cache_read_input_tokens=None,
            thinking_tokens=None, service_tier="standard",
        )
        return ClaudeAnalysisResult(output=output, usage=usage)

    def repair_fields(self, prompt, fields):
        """Atrapa naprawy pól (2026-10-23): zwraca WYŁĄCZNIE `fields`.
        `repair_fails_tickers` -- naprawa sama zwraca puste wartości."""
        from buffett_scanner.providers.claude import ClaudeRepairResult, ClaudeUsage

        type(self).repair_call_count["n"] += 1
        type(self).received_repair_prompts.append(prompt)
        type(self).received_repair_fields.append(list(fields))

        for ticker in self.repair_fails_tickers:
            if f"spółki {ticker}" in prompt:
                empty = {name: ("" if name == "biggest_unknown" else []) for name in fields}
                empty_usage = ClaudeUsage(
                    model="claude-sonnet-5", input_tokens=250, output_tokens=20,
                    cache_creation_input_tokens=None, cache_read_input_tokens=None,
                    thinking_tokens=None, service_tier="standard",
                )
                return ClaudeRepairResult(output=empty, usage=empty_usage)

        values = {
            "thesis_invalidation": [
                "Trwały spadek retention rate klientów poniżej historycznego poziomu "
                "wskazywałby na erozję przewagi konkurencyjnej.",
            ],
            "biggest_unknown": "Nie wiadomo, czy nowy cykl produktowy odwróci spadek marży brutto.",
            "bear_case": ["Rosnąca konkurencja cenowa może trwale obniżyć marże w segmencie."],
        }
        repair_usage = ClaudeUsage(
            model="claude-sonnet-5", input_tokens=300, output_tokens=40,
            cache_creation_input_tokens=None, cache_read_input_tokens=None,
            thinking_tokens=None, service_tier="standard",
        )
        return ClaudeRepairResult(output={name: values[name] for name in fields}, usage=repair_usage)


def _set_live_scan_env(monkeypatch):
    monkeypatch.setenv("FMP_API_KEY", "dummy")
    monkeypatch.setenv("SEC_EDGAR_USER_AGENT", "Tajfun Lab test test@example.com")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy")


def test_run_live_scan_rank_only_stops_before_claude(tmp_path, monkeypatch, capsys):
    _set_live_scan_env(monkeypatch)
    monkeypatch.setattr(cli, "FMPClient", _FakeFMPClient)
    monkeypatch.setattr(cli, "SecEdgarClient", _FakeSecEdgarClient)  # klasyfikacja SIC przed rankingiem

    db_path = tmp_path / "test.db"
    exit_code = cli.main([
        "--db", str(db_path), "run-live-scan", "--sample", "AAPL", "--rank-only",
    ])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Pełny deterministyczny ranking" in out
    assert "Shortlist" in out
    assert "--rank-only: STOP po etapie 1" in out

    from buffett_scanner.db import connect, get_live_scan_candidates, get_live_scan_run

    conn = connect(db_path)
    assert conn.execute("SELECT COUNT(*) AS n FROM analyses").fetchone()["n"] == 0

    run_row = conn.execute("SELECT run_id FROM live_scan_runs").fetchone()
    run_id = run_row["run_id"]
    assert get_live_scan_run(conn, run_id)["status"] == "RANKED"
    candidates = get_live_scan_candidates(conn, run_id)
    assert len(candidates) == 1
    assert candidates[0]["ticker"] == "AAPL"
    assert candidates[0]["llm_status"] == "PENDING"
    assert candidates[0]["in_shortlist"] == 1


def test_run_live_scan_shortlist_limit_only_analyzes_top_n(tmp_path, monkeypatch, capsys):
    """AAPL (cena 70 -> MoS ujemny -> valuation_score=0) i MSFT (cena 50
    -> MoS ~21% -> valuation_score>0) oba surfacują decline, ale MSFT ma
    wyższy deterministic_score_pct -- `--shortlist-limit 1` wysyła do
    Claude TYLKO MSFT, AAPL zostaje NOT_SHORTLISTED, zero wywołania
    Claude dla niego."""
    _set_live_scan_env(monkeypatch)
    monkeypatch.setattr(cli, "FMPClient", _TwoTickerFMPClient)
    monkeypatch.setattr(cli, "SecEdgarClient", _FakeSecEdgarClient)
    _CountingClaudeClient.call_count = {"n": 0}
    _CountingClaudeClient.fail_tickers = set()
    _CountingClaudeClient.semantically_incomplete_tickers = set()
    _CountingClaudeClient.thesis_invalidation_only_empty_tickers = set()
    _CountingClaudeClient.repair_fails_tickers = set()
    _CountingClaudeClient.repair_call_count = {"n": 0}
    _CountingClaudeClient.received_repair_prompts = []
    monkeypatch.setattr(cli, "ClaudeClient", _CountingClaudeClient)

    db_path = tmp_path / "test.db"
    exit_code = cli.main([
        "--db", str(db_path), "run-live-scan", "--sample", "AAPL,MSFT", "--shortlist-limit", "1",
    ])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert _CountingClaudeClient.call_count["n"] == 1

    from buffett_scanner.db import connect, get_live_scan_candidates

    conn = connect(db_path)
    run_id = conn.execute("SELECT run_id FROM live_scan_runs").fetchone()["run_id"]
    by_ticker = {r["ticker"]: r for r in get_live_scan_candidates(conn, run_id)}
    assert by_ticker["MSFT"]["in_shortlist"] == 1
    assert by_ticker["MSFT"]["llm_status"] == "COMPLETE"
    assert by_ticker["AAPL"]["in_shortlist"] == 0
    assert by_ticker["AAPL"]["llm_status"] == "NOT_SHORTLISTED"
    assert conn.execute("SELECT COUNT(*) AS n FROM analyses").fetchone()["n"] == 1


def test_analyze_live_scan_shortlist_incomplete_status_never_emits_partial_report(
    tmp_path, monkeypatch, capsys,
):
    """MSFT (ranga 1, lepszy score) COMPLETE, AAPL (ranga 2, symulowane
    wyczerpanie kredytu Claude) FAILED -> status INCOMPLETE_LLM_ANALYSIS,
    ZERO finalnego raportu top-N (Decyzja właścicielki, Faza 6c: nigdy
    partial top-N). AAPL jako DRUGI/ostatni w kolejce przetwarzania —
    fail-fast po jego błędzie nie gubi niczego ukrytego."""
    _set_live_scan_env(monkeypatch)
    monkeypatch.setattr(cli, "FMPClient", _TwoTickerFMPClient)
    monkeypatch.setattr(cli, "SecEdgarClient", _FakeSecEdgarClient)
    _CountingClaudeClient.call_count = {"n": 0}
    _CountingClaudeClient.fail_tickers = {"AAPL"}
    _CountingClaudeClient.semantically_incomplete_tickers = set()
    _CountingClaudeClient.thesis_invalidation_only_empty_tickers = set()
    _CountingClaudeClient.repair_fails_tickers = set()
    _CountingClaudeClient.repair_call_count = {"n": 0}
    _CountingClaudeClient.received_repair_prompts = []
    monkeypatch.setattr(cli, "ClaudeClient", _CountingClaudeClient)

    db_path = tmp_path / "test.db"
    exit_code = cli.main([
        "--db", str(db_path), "run-live-scan", "--sample", "AAPL,MSFT", "--shortlist-limit", "20",
    ])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "INCOMPLETE_LLM_ANALYSIS" in out
    assert "Kandydat 1:" not in out  # żaden finalny top-N raport

    from buffett_scanner.db import connect, get_live_scan_candidates, get_live_scan_run

    conn = connect(db_path)
    run_id = conn.execute("SELECT run_id FROM live_scan_runs").fetchone()["run_id"]
    assert get_live_scan_run(conn, run_id)["status"] == "INCOMPLETE_LLM_ANALYSIS"
    by_ticker = {r["ticker"]: r for r in get_live_scan_candidates(conn, run_id)}
    assert by_ticker["MSFT"]["llm_status"] == "COMPLETE"
    assert by_ticker["AAPL"]["llm_status"] == "FAILED"
    assert conn.execute("SELECT COUNT(*) AS n FROM analyses").fetchone()["n"] == 1
    # Faza 6e: MSFT (sukces) ma realny usage; AAPL (400 insufficient-credit,
    # SDK nigdy nie dostał `response`) ma NULL -- nigdy nie wymyślamy
    # tokenów dla niewykonanego wywołania.
    assert by_ticker["MSFT"]["llm_input_tokens"] == 900
    assert by_ticker["AAPL"]["llm_input_tokens"] is None


def test_analyze_live_scan_shortlist_resume_skips_complete_and_finishes(
    tmp_path, monkeypatch, capsys,
):
    """Kontynuacja powyższego scenariusza: po 'uzupełnieniu kredytu'
    (fail_tickers wyczyszczony), `analyze-live-scan-shortlist --run-id`
    analizuje TYLKO AAPL (PENDING/FAILED) -- MSFT (już COMPLETE) nie
    wywołuje Claude drugi raz -- i generuje finalny raport."""
    _set_live_scan_env(monkeypatch)
    monkeypatch.setattr(cli, "FMPClient", _TwoTickerFMPClient)
    monkeypatch.setattr(cli, "SecEdgarClient", _FakeSecEdgarClient)
    _CountingClaudeClient.call_count = {"n": 0}
    _CountingClaudeClient.fail_tickers = {"AAPL"}
    _CountingClaudeClient.semantically_incomplete_tickers = set()
    _CountingClaudeClient.thesis_invalidation_only_empty_tickers = set()
    _CountingClaudeClient.repair_fails_tickers = set()
    _CountingClaudeClient.repair_call_count = {"n": 0}
    _CountingClaudeClient.received_repair_prompts = []
    monkeypatch.setattr(cli, "ClaudeClient", _CountingClaudeClient)

    db_path = tmp_path / "test.db"
    cli.main([
        "--db", str(db_path), "run-live-scan", "--sample", "AAPL,MSFT", "--shortlist-limit", "20",
    ])
    capsys.readouterr()
    assert _CountingClaudeClient.call_count["n"] == 2  # MSFT (COMPLETE) + AAPL (FAILED)

    from buffett_scanner.db import connect

    conn = connect(db_path)
    run_id = conn.execute("SELECT run_id FROM live_scan_runs").fetchone()["run_id"]

    _CountingClaudeClient.fail_tickers = set()  # "kredyt uzupełniony"
    exit_code = cli.main([
        "--db", str(db_path), "analyze-live-scan-shortlist", "--run-id", run_id,
    ])
    out = capsys.readouterr().out

    assert exit_code == 0
    assert _CountingClaudeClient.call_count["n"] == 3  # TYLKO +1 (AAPL) -- MSFT nie ponownie
    assert "INCOMPLETE_LLM_ANALYSIS" not in out
    assert "Kandydat" in out  # finalny raport wygenerowany
    assert conn.execute("SELECT COUNT(*) AS n FROM analyses").fetchone()["n"] == 2


def test_analyze_live_scan_shortlist_cache_hit_reuses_prior_analysis(
    tmp_path, monkeypatch, capsys,
):
    """Dwa OSOBNE run_id na tej samej bazie, identyczny ticker/dane/config
    -> identyczny cache_key -> drugi run_id dostaje COMPLETE przez cache,
    ZERO nowego wywołania Claude (nawet gdy fake zawsze by rzucił błąd)."""
    _set_live_scan_env(monkeypatch)
    monkeypatch.setattr(cli, "FMPClient", _FakeFMPClient)
    monkeypatch.setattr(cli, "SecEdgarClient", _FakeSecEdgarClient)
    _CountingClaudeClient.call_count = {"n": 0}
    _CountingClaudeClient.fail_tickers = set()
    _CountingClaudeClient.semantically_incomplete_tickers = set()
    _CountingClaudeClient.thesis_invalidation_only_empty_tickers = set()
    _CountingClaudeClient.repair_fails_tickers = set()
    _CountingClaudeClient.repair_call_count = {"n": 0}
    _CountingClaudeClient.received_repair_prompts = []
    monkeypatch.setattr(cli, "ClaudeClient", _CountingClaudeClient)

    db_path = tmp_path / "test.db"
    cli.main(["--db", str(db_path), "run-live-scan", "--sample", "AAPL"])
    capsys.readouterr()
    assert _CountingClaudeClient.call_count["n"] == 1

    from buffett_scanner.db import connect

    conn = connect(db_path)
    first_analysis_id = conn.execute("SELECT analysis_id FROM analyses").fetchone()["analysis_id"]

    # Druga runda tego samego dnia, identyczne dane -- fake Claude TERAZ
    # ZAWSZE failuje, żeby dowieść, że cache hit nie woła API wcale.
    _CountingClaudeClient.fail_tickers = {"AAPL"}
    exit_code = cli.main([
        "--db", str(db_path), "run-live-scan", "--sample", "AAPL", "--skip-universe-refresh",
    ])
    out = capsys.readouterr().out

    assert exit_code == 0
    assert _CountingClaudeClient.call_count["n"] == 1  # BEZ zmiany -- cache hit, zero nowego wywołania
    assert "CACHE HIT" in out
    assert "INCOMPLETE_LLM_ANALYSIS" not in out

    rows = conn.execute("SELECT analysis_id FROM live_scan_candidates WHERE llm_status='COMPLETE'").fetchall()
    assert all(r["analysis_id"] == first_analysis_id for r in rows)
    assert conn.execute("SELECT COUNT(*) AS n FROM analyses").fetchone()["n"] == 1


# ---------------------------------------------------------------------------
# BUGFIX V0 OUTPUT CONTRACT (Faza 6f, 2026-10-06) -- testy C/D/G ze
# specyfikacji właścicielki: COMPLETE musi oznaczać rzeczywistą
# kompletność (retry bounded, FAILED po wyczerpaniu prób, NIE COMPLETE),
# a dotychczasowe failure/resume i usage telemetry nadal działają.
# ---------------------------------------------------------------------------
#
# TARGETED FIELD REPAIR (Faza 6h, 2026-10-06): DWA REALNE validation runy
# (validation-6f, po bdfcc92 validation-6g) wykazały, że full-response
# retry (ślepy, i z dołączonym konkretnym feedbackiem) NIE naprawiał
# rzetelnie pustego `thesis_invalidation` -- 1/5 COMPLETE w obu runach.
# Zastąpione: maksymalnie 1 full analysis call + (TYLKO gdy JEDYNYM
# naruszeniem jest semantycznie pusty thesis_invalidation) 1 targeted
# repair call, WYŁĄCZNIE dla tego pola. Testy A-I niżej (specyfikacja
# właścicielki).
# ---------------------------------------------------------------------------


def _use_counting_claude(monkeypatch, **scenario):
    """Atrapa Claude z czystym stanem + scenariusz testu (2026-10-23)."""
    _set_live_scan_env(monkeypatch)
    monkeypatch.setattr(cli, "FMPClient", _FakeFMPClient)
    monkeypatch.setattr(cli, "SecEdgarClient", _FakeSecEdgarClient)
    _CountingClaudeClient.call_count = {"n": 0}
    _CountingClaudeClient.repair_call_count = {"n": 0}
    _CountingClaudeClient.received_prompts = []
    _CountingClaudeClient.received_repair_prompts = []
    _CountingClaudeClient.received_repair_fields = []
    for name in ("fail_tickers", "semantically_incomplete_tickers", "thesis_invalidation_only_empty_tickers",
                 "repair_fails_tickers", "structural_violation_tickers"):
        setattr(_CountingClaudeClient, name, set(scenario.get(name, set())))
    monkeypatch.setattr(cli, "ClaudeClient", _CountingClaudeClient)


def _single_candidate(db_path):
    from buffett_scanner.db import connect, get_live_scan_candidates, get_live_scan_run, get_llm_rejected_outputs

    conn = connect(db_path)
    run_id = conn.execute("SELECT run_id FROM live_scan_runs").fetchone()["run_id"]
    return (conn, get_live_scan_run(conn, run_id), get_live_scan_candidates(conn, run_id)[0],
            get_llm_rejected_outputs(conn, run_id))


def test_analyze_live_scan_shortlist_clean_response_needs_zero_repair_calls(tmp_path, monkeypatch, capsys):
    """Pełna analiza poprawna od razu -> 1 wywołanie, 0 napraw, COMPLETE,
    zero zapisanych odrzuceń."""
    _use_counting_claude(monkeypatch)
    db_path = tmp_path / "test.db"
    exit_code = cli.main(["--db", str(db_path), "run-live-scan", "--sample", "AAPL"])
    out = capsys.readouterr().out

    assert exit_code == 0
    assert _CountingClaudeClient.call_count["n"] == 1
    assert _CountingClaudeClient.repair_call_count["n"] == 0
    assert "Wywołania naprawy pól (wszystkie próby): 0" in out
    _, run, row, rejected = _single_candidate(db_path)
    assert run["status"] == "COMPLETE"
    assert row["llm_status"] == "COMPLETE"
    assert row["llm_repair_input_tokens"] is None and row["llm_repair_attempts"] == 0
    assert rejected == []


def test_two_empty_fields_like_scan_of_22_10_are_repaired_in_one_call(tmp_path, monkeypatch, capsys):
    """Dokładnie przypadek 22/24 z runu live-scan-2026-10-22: puste
    `thesis_invalidation` ORAZ `biggest_unknown`. Wcześniej -> FAILED bez
    naprawy; teraz 1 naprawa uzupełnia OBA pola, reszta analizy nietknięta."""
    _use_counting_claude(monkeypatch, semantically_incomplete_tickers={"AAPL"})
    db_path = tmp_path / "test.db"
    exit_code = cli.main(["--db", str(db_path), "run-live-scan", "--sample", "AAPL"])
    out = capsys.readouterr().out

    assert exit_code == 0
    assert _CountingClaudeClient.call_count["n"] == 1  # pełna analiza NIE jest generowana ponownie
    assert _CountingClaudeClient.repair_call_count["n"] == 1
    assert _CountingClaudeClient.received_repair_fields == [["thesis_invalidation", "biggest_unknown"]]
    assert "INCOMPLETE_LLM_ANALYSIS" not in out
    # Komunikat walidacji wymienia OBA naruszenia, nie tylko pierwsze.
    assert "thesis_invalidation jest semantycznie pusty" in out and "biggest_unknown jest semantycznie pusty" in out

    conn, run, row, rejected = _single_candidate(db_path)
    assert run["status"] == "COMPLETE" and row["llm_status"] == "COMPLETE"
    assert row["llm_repair_attempts"] == 1
    raw = json.loads(conn.execute("SELECT llm_raw_output FROM analyses WHERE analysis_id = ?",
                                  (row["analysis_id"],)).fetchone()["llm_raw_output"])
    assert raw["biggest_unknown"] == "Nie wiadomo, czy nowy cykl produktowy odwróci spadek marży brutto."
    assert raw["thesis_invalidation"][0].startswith("Trwały spadek retention rate")
    assert raw["bull_case"] == ["Solidna pozycja rynkowa i stabilne przepływy pieniężne."]  # bez zmian
    # Pierwotna, odrzucona odpowiedź jest zapisana z wszystkimi przyczynami.
    assert [(r["call_kind"], r["attempt"]) for r in rejected] == [("FULL_ANALYSIS", 0)]
    assert len(json.loads(rejected[0]["violations_json"])) == 2
    assert json.loads(rejected[0]["raw_output"])["biggest_unknown"] == ""
    assert rejected[0]["input_tokens"] == 500


def test_analyze_live_scan_shortlist_isolated_empty_thesis_invalidation_triggers_one_repair_call(
    tmp_path, monkeypatch, capsys,
):
    """Tylko puste `thesis_invalidation` -> 1 naprawa tylko tego pola ->
    COMPLETE; telemetria pełnej analizy i naprawy odrębna."""
    _use_counting_claude(monkeypatch, thesis_invalidation_only_empty_tickers={"AAPL"})
    db_path = tmp_path / "test.db"
    exit_code = cli.main(["--db", str(db_path), "run-live-scan", "--sample", "AAPL"])
    out = capsys.readouterr().out

    assert exit_code == 0
    assert _CountingClaudeClient.call_count["n"] == 1
    assert _CountingClaudeClient.received_repair_fields == [["thesis_invalidation"]]
    assert "Wywołania naprawy pól (wszystkie próby): 1" in out
    _, run, row, _ = _single_candidate(db_path)
    assert row["llm_status"] == "COMPLETE"
    assert (row["llm_input_tokens"], row["llm_output_tokens"]) == (950, 140)
    assert (row["llm_repair_input_tokens"], row["llm_repair_output_tokens"]) == (300, 40)
    assert "repair input_tokens: 300, repair output_tokens: 40" in out


def test_failed_repair_is_bounded_and_fails_cleanly_with_all_material_saved(tmp_path, monkeypatch, capsys):
    """Naprawa sama zwraca puste pola -> najwyżej MAX_REPAIR_ATTEMPTS prób,
    potem FAILED (nigdy COMPLETE), bez analizy w `analyses`; usage
    wszystkich prób zsumowane, każda odrzucona odpowiedź zapisana."""
    _use_counting_claude(monkeypatch, semantically_incomplete_tickers={"AAPL"}, repair_fails_tickers={"AAPL"})
    db_path = tmp_path / "test.db"
    exit_code = cli.main(["--db", str(db_path), "run-live-scan", "--sample", "AAPL"])
    out = capsys.readouterr().out

    assert exit_code == 0  # proces zakończony; o kompletności decyduje verify-run-complete
    assert _CountingClaudeClient.call_count["n"] == 1
    assert _CountingClaudeClient.repair_call_count["n"] == cli.MAX_REPAIR_ATTEMPTS == 2
    assert "INCOMPLETE_LLM_ANALYSIS" in out
    conn, run, row, rejected = _single_candidate(db_path)
    assert run["status"] == "INCOMPLETE_LLM_ANALYSIS"
    assert row["llm_status"] == "FAILED"
    assert "thesis_invalidation jest semantycznie pusty" in row["llm_error"]
    assert "biggest_unknown jest semantycznie pusty" in row["llm_error"]
    assert (row["llm_input_tokens"], row["llm_repair_input_tokens"], row["llm_repair_attempts"]) == (500, 500, 2)
    assert [(r["call_kind"], r["attempt"]) for r in rejected] == [
        ("FULL_ANALYSIS", 0), ("FIELD_REPAIR", 1), ("FIELD_REPAIR", 2)]
    assert conn.execute("SELECT COUNT(*) AS n FROM analyses").fetchone()["n"] == 0


def test_structural_violation_is_never_repaired(tmp_path, monkeypatch, capsys):
    """Cytowanie spoza listy źródeł = błąd strukturalny -> FAILED bez
    naprawy, nawet gdy jest też puste pole treści; oba naruszenia w błędzie."""
    _use_counting_claude(monkeypatch, structural_violation_tickers={"AAPL"})
    db_path = tmp_path / "test.db"
    cli.main(["--db", str(db_path), "run-live-scan", "--sample", "AAPL"])
    out = capsys.readouterr().out

    assert _CountingClaudeClient.repair_call_count["n"] == 0
    assert "brak naprawy -- naruszenie strukturalne" in out
    _, run, row, rejected = _single_candidate(db_path)
    assert row["llm_status"] == "FAILED" and run["status"] == "INCOMPLETE_LLM_ANALYSIS"
    assert "cited_source_ids zawiera id spoza dostarczonej listy" in row["llm_error"]
    assert "thesis_invalidation jest semantycznie pusty" in row["llm_error"]
    assert len(rejected) == 1


def test_verify_run_complete_fails_and_reports_incomplete_scan(tmp_path, monkeypatch, capsys):
    """Bramka kompletności: niekompletny skan -> kod 1, adnotacja ::error,
    raport diagnostyczny (plik + podsumowanie joba GitHub)."""
    _use_counting_claude(monkeypatch, semantically_incomplete_tickers={"AAPL"}, repair_fails_tickers={"AAPL"})
    db_path = tmp_path / "test.db"
    cli.main(["--db", str(db_path), "run-live-scan", "--sample", "AAPL"])
    capsys.readouterr()
    summary = tmp_path / "step_summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))

    exit_code = cli.main(["--db", str(db_path), "verify-run-complete", "--report-out", str(tmp_path / "reports")])
    out = capsys.readouterr().out

    assert exit_code == 1
    assert "::error title=Skan niekompletny::" in out
    report = (tmp_path / "reports" / "run_status.md").read_text(encoding="utf-8")
    assert "INCOMPLETE_LLM_ANALYSIS" in report and "ZABLOKOWANA" in report
    assert "| 1 | AAPL | FAILED | 3 |" in report  # 3 zapisane odrzucone odpowiedzi
    assert summary.read_text(encoding="utf-8") == report + "\n"


def test_verify_run_complete_passes_complete_scan(tmp_path, monkeypatch, capsys):
    _use_counting_claude(monkeypatch)
    db_path = tmp_path / "test.db"
    cli.main(["--db", str(db_path), "run-live-scan", "--sample", "AAPL"])
    capsys.readouterr()
    exit_code = cli.main(["--db", str(db_path), "verify-run-complete", "--report-out", str(tmp_path / "r")])
    assert exit_code == 0
    assert "Publikacja w aplikacji: dozwolona" in capsys.readouterr().out


def test_publish_snapshot_cli_refuses_incomplete_scan(tmp_path, monkeypatch, capsys):
    _use_counting_claude(monkeypatch, semantically_incomplete_tickers={"AAPL"}, repair_fails_tickers={"AAPL"})
    db_path = tmp_path / "test.db"
    cli.main(["--db", str(db_path), "run-live-scan", "--sample", "AAPL"])
    capsys.readouterr()
    calls = []
    monkeypatch.setattr(cli, "GhReleaseClient", lambda **kw: calls.append(kw) or object())
    exit_code = cli.main(["--db", str(db_path), "publish-snapshot"])
    assert exit_code == 1
    assert "::error title=Publikacja zablokowana::" in capsys.readouterr().out


def test_analyze_live_scan_shortlist_existing_resume_and_telemetry_still_work(
    tmp_path, monkeypatch, capsys,
):
    """Test G (specyfikacja właścicielki): dotychczasowe failure/resume
    (fail-fast na ClaudeError, resume TYLKO PENDING/FAILED) i usage
    telemetry (Faza 6e) nadal działają niezmienione po BUGFIX V0 OUTPUT
    CONTRACT -- regresja na realnym scenariuszu z Fazy 6c (MSFT COMPLETE,
    AAPL FAILED przez 400, resume kończy AAPL, telemetria realna)."""
    _set_live_scan_env(monkeypatch)
    monkeypatch.setattr(cli, "FMPClient", _TwoTickerFMPClient)
    monkeypatch.setattr(cli, "SecEdgarClient", _FakeSecEdgarClient)
    _CountingClaudeClient.call_count = {"n": 0}
    _CountingClaudeClient.fail_tickers = {"AAPL"}
    _CountingClaudeClient.semantically_incomplete_tickers = set()
    _CountingClaudeClient.thesis_invalidation_only_empty_tickers = set()
    _CountingClaudeClient.repair_fails_tickers = set()
    _CountingClaudeClient.repair_call_count = {"n": 0}
    _CountingClaudeClient.received_repair_prompts = []
    monkeypatch.setattr(cli, "ClaudeClient", _CountingClaudeClient)

    db_path = tmp_path / "test.db"
    cli.main([
        "--db", str(db_path), "run-live-scan", "--sample", "AAPL,MSFT", "--shortlist-limit", "20",
    ])
    capsys.readouterr()
    assert _CountingClaudeClient.call_count["n"] == 2  # MSFT (COMPLETE) + AAPL (FAILED, bez retry na 400)

    from buffett_scanner.db import connect

    conn = connect(db_path)
    run_id = conn.execute("SELECT run_id FROM live_scan_runs").fetchone()["run_id"]

    _CountingClaudeClient.fail_tickers = set()  # "kredyt uzupełniony"
    exit_code = cli.main([
        "--db", str(db_path), "analyze-live-scan-shortlist", "--run-id", run_id,
    ])
    out = capsys.readouterr().out

    assert exit_code == 0
    assert _CountingClaudeClient.call_count["n"] == 3  # TYLKO +1 (AAPL) -- MSFT nie ponownie
    assert "INCOMPLETE_LLM_ANALYSIS" not in out
    assert "Kandydat" in out
    assert conn.execute("SELECT COUNT(*) AS n FROM analyses").fetchone()["n"] == 2
    # Telemetria (Faza 6e) nadal realna po BUGFIX -- agregat per-run sumuje
    # OBA kompletne kandydaty (MSFT + AAPL), 900/150 input/output każdy
    # (zdefiniowane w _CountingClaudeClient).
    assert "Telemetria Anthropic API usage" in out
    assert "input_tokens: 1800, output_tokens: 300" in out


def test_analyze_live_scan_shortlist_repair_prompt_carries_price_valuation_context(
    tmp_path, monkeypatch, capsys,
):
    """Test H (specyfikacja właścicielki): price/valuation context
    pozostaje dostępny -- regresja na to, że BUGFIX V0 OUTPUT CONTRACT
    (Faza 6f) nie został zgubiony przy wprowadzeniu targeted repair.
    Targeted repair prompt (budowany przez `build_thesis_invalidation_
    repair_prompt`) dostaje te SAME deterministyczne current_price/DCF/
    decline context co pełny prompt -- nigdy nie jest to pusty prompt bez
    kontekstu."""
    _set_live_scan_env(monkeypatch)
    monkeypatch.setattr(cli, "FMPClient", _FakeFMPClient)
    monkeypatch.setattr(cli, "SecEdgarClient", _FakeSecEdgarClient)
    _CountingClaudeClient.call_count = {"n": 0}
    _CountingClaudeClient.fail_tickers = set()
    _CountingClaudeClient.semantically_incomplete_tickers = set()
    _CountingClaudeClient.thesis_invalidation_only_empty_tickers = {"AAPL"}
    _CountingClaudeClient.repair_fails_tickers = set()
    _CountingClaudeClient.structural_violation_tickers = set()
    _CountingClaudeClient.repair_call_count = {"n": 0}
    _CountingClaudeClient.received_repair_prompts = []
    _CountingClaudeClient.received_repair_fields = []
    _CountingClaudeClient.received_prompts = []
    monkeypatch.setattr(cli, "ClaudeClient", _CountingClaudeClient)

    db_path = tmp_path / "test.db"
    cli.main(["--db", str(db_path), "run-live-scan", "--sample", "AAPL"])
    capsys.readouterr()

    assert len(_CountingClaudeClient.received_repair_prompts) == 1
    repair_prompt = _CountingClaudeClient.received_repair_prompts[0]
    assert "KONTEKST CENY I WYCENY" in repair_prompt
    assert "analizy spółki AAPL" in repair_prompt
    # Nigdy pełny source payload -- repair nie cytuje źródeł (specyfikacja
    # właścicielki, punkt 6).
    assert "ŹRÓDŁA" not in repair_prompt


# --- 2026-10-23: przygotowanie płatnej walidacji na 3-5 spółkach -------


def _two_failed_candidates(tmp_path, monkeypatch, capsys, **scenario):
    """Skan AAPL+MSFT, w którym pierwsze wywołanie Claude kończy się błędem
    API (fail-fast) -> obie spółki PENDING/FAILED, jak 22 spółki z 22.10."""
    _use_counting_claude(monkeypatch, fail_tickers={"AAPL", "MSFT"})
    monkeypatch.setattr(cli, "FMPClient", _TwoTickerFMPClient)
    db_path = tmp_path / "test.db"
    cli.main(["--db", str(db_path), "run-live-scan", "--sample", "AAPL,MSFT", "--shortlist-limit", "20"])
    capsys.readouterr()
    _use_counting_claude(monkeypatch, **scenario)
    monkeypatch.setattr(cli, "FMPClient", _TwoTickerFMPClient)

    from buffett_scanner.db import connect

    conn = connect(db_path)
    run_id = conn.execute("SELECT run_id FROM live_scan_runs").fetchone()["run_id"]
    return db_path, conn, run_id


def _statuses(conn, run_id):
    from buffett_scanner.db import get_live_scan_candidates

    return {r["ticker"]: r for r in get_live_scan_candidates(conn, run_id, only_shortlist=True)}


def test_tickers_option_analyzes_only_selected_companies(tmp_path, monkeypatch, capsys):
    db_path, conn, run_id = _two_failed_candidates(tmp_path, monkeypatch, capsys)
    exit_code = cli.main(["--db", str(db_path), "analyze-live-scan-shortlist", "--run-id", run_id,
                          "--tickers", "aapl"])
    out = capsys.readouterr().out

    assert exit_code == 0
    assert _CountingClaudeClient.call_count["n"] == 1
    assert all('"AAPL"' in p for p in _CountingClaudeClient.received_prompts)
    rows = _statuses(conn, run_id)
    assert rows["AAPL"]["llm_status"] == "COMPLETE"
    assert rows["MSFT"]["llm_status"] in ("PENDING", "FAILED")  # nietknięty
    # Część spółek -> skan dalej niekompletny, więc nie może zostać opublikowany.
    assert "INCOMPLETE_LLM_ANALYSIS" in out
    assert cli.main(["--db", str(db_path), "verify-run-complete", "--report-out", str(tmp_path / "r")]) == 1


def test_tickers_option_rejects_unknown_or_already_complete_without_calls(tmp_path, monkeypatch, capsys):
    db_path, conn, run_id = _two_failed_candidates(tmp_path, monkeypatch, capsys)
    assert cli.main(["--db", str(db_path), "analyze-live-scan-shortlist", "--run-id", run_id,
                     "--tickers", "AAPL,XYZ"]) == 1
    assert "spoza shortlisty" in capsys.readouterr().err

    cli.main(["--db", str(db_path), "analyze-live-scan-shortlist", "--run-id", run_id, "--tickers", "AAPL"])
    capsys.readouterr()
    calls = _CountingClaudeClient.call_count["n"]
    assert cli.main(["--db", str(db_path), "analyze-live-scan-shortlist", "--run-id", run_id,
                     "--tickers", "AAPL"]) == 1
    assert "już COMPLETE" in capsys.readouterr().err
    assert _CountingClaudeClient.call_count["n"] == calls  # zero nowych wywołań


def test_max_claude_calls_is_never_exceeded(tmp_path, monkeypatch, capsys):
    """Obie spółki w najgorszym przypadku (pełna + 2 nieudane naprawy =
    3 wywołania). Limit 4 -> pierwsza spółka zużywa 3, druga się nie
    zaczyna (potrzebowałaby do 3 kolejnych)."""
    db_path, conn, run_id = _two_failed_candidates(
        tmp_path, monkeypatch, capsys,
        semantically_incomplete_tickers={"AAPL", "MSFT"}, repair_fails_tickers={"AAPL", "MSFT"},
    )
    exit_code = cli.main(["--db", str(db_path), "analyze-live-scan-shortlist", "--run-id", run_id,
                          "--max-claude-calls", "4"])
    out = capsys.readouterr().out

    assert exit_code == 0
    total = _CountingClaudeClient.call_count["n"] + _CountingClaudeClient.repair_call_count["n"]
    assert total == 3
    assert "STOP: limit wywołań Claude (3/4)" in out
    assert "Wywołania Claude w tym przebiegu (pełne + naprawy): 3 / limit 4" in out


def test_max_claude_calls_below_worst_case_makes_zero_calls(tmp_path, monkeypatch, capsys):
    db_path, conn, run_id = _two_failed_candidates(tmp_path, monkeypatch, capsys)
    cli.main(["--db", str(db_path), "analyze-live-scan-shortlist", "--run-id", run_id, "--max-claude-calls", "2"])
    capsys.readouterr()
    assert _CountingClaudeClient.call_count["n"] == 0


def test_sources_until_run_date_passes_scan_date_as_filing_cutoff(tmp_path, monkeypatch, capsys):
    db_path, conn, run_id = _two_failed_candidates(tmp_path, monkeypatch, capsys)
    seen = []
    real = cli.build_sec_source_packet

    def spy(client, **kwargs):
        seen.append(kwargs.get("filed_on_or_before"))
        return real(client, **kwargs)

    monkeypatch.setattr(cli, "build_sec_source_packet", spy)
    cli.main(["--db", str(db_path), "analyze-live-scan-shortlist", "--run-id", run_id, "--tickers", "AAPL"])
    cli.main(["--db", str(db_path), "analyze-live-scan-shortlist", "--run-id", run_id, "--tickers", "MSFT",
              "--sources-until-run-date"])
    capsys.readouterr()
    run_date = conn.execute("SELECT run_date FROM live_scan_runs").fetchone()["run_date"]
    assert seen == [None, run_date]


def _summary(db_path, tmp_path, usage, *extra):
    return cli.main(["--db", str(db_path), "validation-summary", "--usage-json", str(usage),
                     "--price-input-per-mtok", "2", "--price-output-per-mtok", "10",
                     "--report-out", str(tmp_path / "reports"), *extra])


def test_validation_summary_reports_this_runs_calls_tokens_cost_and_scan_state(tmp_path, monkeypatch, capsys):
    """Koszt liczony z wywołań TEGO przebiegu (plik --usage-out), nie z
    tokenów zapisanych w bazie przez wcześniejsze przebiegi."""
    db_path, conn, run_id = _two_failed_candidates(
        tmp_path, monkeypatch, capsys, semantically_incomplete_tickers={"AAPL"},
    )
    usage = tmp_path / "usage.json"
    cli.main(["--db", str(db_path), "analyze-live-scan-shortlist", "--run-id", run_id, "--tickers", "AAPL",
              "--sources-until-run-date", "--max-claude-calls", "3", "--usage-out", str(usage)])
    capsys.readouterr()
    data = json.loads(usage.read_text(encoding="utf-8"))
    aapl = data["companies"]["AAPL"]
    assert (data["total_calls"], aapl["full_calls"], aapl["repair_calls"], aapl["calls_without_usage"]) == (2, 1, 1, 0)
    assert "MSFT" not in data["companies"]  # nieanalizowana -> zero kosztu w raporcie
    run_date = conn.execute("SELECT run_date FROM live_scan_runs").fetchone()["run_date"]
    assert data["sources_filed_on_or_before"] == run_date

    assert _summary(db_path, tmp_path, usage) == 0
    out = capsys.readouterr().out
    cost = (aapl["input_tokens"] * 2 + aapl["output_tokens"] * 10) / 1e6
    assert (f"| AAPL | COMPLETE | 1 | 1 | 1 | 0 | {aapl['input_tokens']} | {aapl['output_tokens']} "
            f"({aapl['thinking_tokens']}) | {cost:.4f} |") in out
    assert "Wywołania Claude w tym przebiegu: 2 (limit 3), w tym naprawy: 1" in out
    assert "- Analizy jakościowe: 1/2 COMPLETE" in out
    assert "Ranking kompletny technicznie: NIE" in out
    assert "Spółki bez DCF" in out
    assert "## Look-ahead: BRAK" in out and "NARUSZENIE" not in out
    assert "**Wynik: OK**" in (tmp_path / "reports" / "validation_summary.md").read_text(encoding="utf-8")

    # Sprawdzana spółka niekompletna -> wynik nieudany (czerwony job).
    assert _summary(db_path, tmp_path, usage, "--tickers", "AAPL,MSFT") == 1
    assert "::error title=Walidacja nieudana::" in capsys.readouterr().out


def test_validation_summary_flags_look_ahead_when_sec_filter_was_off(tmp_path, monkeypatch, capsys):
    db_path, conn, run_id = _two_failed_candidates(tmp_path, monkeypatch, capsys)
    usage = tmp_path / "usage.json"
    cli.main(["--db", str(db_path), "analyze-live-scan-shortlist", "--run-id", run_id, "--tickers", "AAPL",
              "--usage-out", str(usage)])
    capsys.readouterr()
    assert _summary(db_path, tmp_path, usage) == 1
    out = capsys.readouterr().out
    assert "## Look-ahead: WYKRYTY" in out
    assert "NARUSZENIE: filtr dokumentów SEC w tym przebiegu = WYŁĄCZONY" in out


def test_validation_summary_counts_calls_without_usage_and_complete_ranking(tmp_path, monkeypatch, capsys):
    """Błąd API bez usage (np. ucięta odpowiedź) to też wywołanie -- raport
    je liczy i ostrzega, zamiast zaniżać koszt. Po uzupełnieniu obu spółek
    ranking jest kompletny technicznie."""
    db_path, conn, run_id = _two_failed_candidates(tmp_path, monkeypatch, capsys, fail_tickers={"MSFT"})
    usage = tmp_path / "usage.json"
    cli.main(["--db", str(db_path), "analyze-live-scan-shortlist", "--run-id", run_id,
              "--sources-until-run-date", "--usage-out", str(usage)])
    capsys.readouterr()
    assert json.loads(usage.read_text(encoding="utf-8"))["companies"]["MSFT"]["calls_without_usage"] == 1
    _summary(db_path, tmp_path, usage)
    assert "UWAGA: 1 wywołań bez usage z API" in capsys.readouterr().out

    _use_counting_claude(monkeypatch)
    monkeypatch.setattr(cli, "FMPClient", _TwoTickerFMPClient)
    cli.main(["--db", str(db_path), "analyze-live-scan-shortlist", "--run-id", run_id,
              "--sources-until-run-date", "--usage-out", str(usage)])
    capsys.readouterr()
    assert _summary(db_path, tmp_path, usage) == 0
    out = capsys.readouterr().out
    assert "Ranking kompletny technicznie: TAK" in out and "2/2 COMPLETE" in out

"""Kontrola świeżości i kompletności danych przed pełnym skanem
(2026-10-23). Zero sieci: atrapy FMP/SEC/Claude z test_cli.py. Ostatnie
notowanie atrap to 2024-09-18 -- to jest "sesja" w tych testach."""

from __future__ import annotations

import json

import pytest

from buffett_scanner import cli
from buffett_scanner.data_quality import (
    DataQuality,
    DataQualityThresholds,
    changed_fields,
    last_bar_problem,
    session_volume_ratio,
)
from buffett_scanner.providers.fmp import FMPError

from tests import test_cli as t

SESSION = "2024-09-18"


def _bars(n=25, last_volume=1_000_000, last_date=SESSION, close=100.0):
    rows = [{"date": f"2024-08-{i + 1:02d}", "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1_000_000}
            for i in range(n - 1)]
    rows.append({"date": last_date, "open": 1, "high": 1, "low": 1, "close": close, "volume": last_volume})
    return rows


# --- funkcje czyste ---------------------------------------------------


def test_last_bar_problem_detects_stale_missing_close_and_volume():
    assert last_bar_problem(_bars(), SESSION) is None
    assert "oczekiwano 2024-09-18" in last_bar_problem(_bars(last_date="2024-09-17"), SESSION)
    assert last_bar_problem(_bars(close=None), SESSION) == "brak ceny zamknięcia sesji"
    assert last_bar_problem(_bars(last_volume=0), SESSION) == "brak wolumenu sesji"
    assert last_bar_problem([], SESSION) == "brak notowań"


def test_session_volume_ratio_and_changed_fields():
    assert session_volume_ratio(_bars(last_volume=500_000)) == pytest.approx(0.5)
    assert session_volume_ratio(_bars(n=10)) is None
    a = {"open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 100}
    assert changed_fields(a, dict(a)) == []
    assert changed_fields(a, {**a, "volume": 120, "close": 1.6}) == ["close", "volume"]
    assert changed_fields(a, None) == ["brak notowania sesji"]


def test_price_checks_error_below_coverage_and_on_partial_volume():
    dq = DataQuality(session_date=SESSION, universe_size=100, price_ok=[f"T{i}" for i in range(97)],
                     price_problems={"X": "brak notowań"}, volume_ratios=[1.0] * 97)
    assert dq.check_prices(DataQualityThresholds()) is False  # 97% < 98%
    assert any("Pokrycie cen" in e for e in dq.errors)
    assert any("X (brak notowań)" in w for w in dq.warnings)  # pominięte spółki zawsze wymienione

    # Niski wolumen to tylko ostrzeżenie: tak wyglądają prawidłowe sesje
    # skrócone/świąteczne (historia: 0,29-0,41), finalizację sprawdza test stabilności.
    low = DataQuality(session_date=SESSION, universe_size=10, price_ok=[f"T{i}" for i in range(10)],
                      volume_ratios=[0.3] * 10)
    assert low.check_prices(DataQualityThresholds()) is True
    assert not low.errors and any("niska" in w for w in low.warnings)


def test_period_availability_uses_filing_date_and_10k_deadline():
    from buffett_scanner.data_quality import filter_available_fundamentals, period_availability_problem

    assert period_availability_problem("2024-06-30", "2024-08-15", SESSION) is None
    assert "po dniu sesji" in period_availability_problem("2024-06-30", "2024-09-19 16:05:00", SESSION)
    assert period_availability_problem("2024-06-30", "2024-09-18 16:05:00", SESSION) is None  # ten sam dzień
    # Data złożenia = koniec okresu (FMP po spin-offie) -> niewiarygodna; przyjęta tylko po terminie 10-K.
    assert period_availability_problem("2023-12-31", "2023-12-31", SESSION) is None
    assert "niewiarygodna" in period_availability_problem("2024-08-31", "2024-08-31", SESSION)
    assert "brak daty złożenia" in period_availability_problem("2024-07-31", None, SESSION)
    rows = [{"fiscal_period": "2023-FY", "period_end_date": "2023-12-31", "filed_date": "2024-02-01"},
            {"fiscal_period": "2024-FY", "period_end_date": "2024-12-31", "filed_date": "2025-02-01"}]
    kept, dropped = filter_available_fundamentals(rows, SESSION)
    assert [r["fiscal_period"] for r in kept] == ["2023-FY"] and list(dropped) == ["2024-FY"]


def test_input_gaps_and_dcf_absence_kind():
    from buffett_scanner.data_quality import dcf_absence_kind, input_gaps
    from buffett_scanner.valuation import ValuationResult

    from tests.test_live_scan import _period

    full = dict(revenue=1, net_income=1, ebitda=1, operating_cash_flow=1, capital_expenditure=1,
                total_debt=1, cash_and_equivalents=1, total_current_assets=1, total_current_liabilities=1,
                dividends_paid=0, share_buybacks=0, diluted_shares_outstanding=1)
    periods = [_period("FY2023", **full), _period("FY2024", **full)]
    assert input_gaps(periods) == []
    rule = ValuationResult(sector_profile="GENERAL", method="dcf_owner_earnings", implemented=False, reason="x")
    assert dcf_absence_kind([], rule) == "REGUŁA_WYCENY"
    gap = input_gaps([_period("FY2023", **full), _period("FY2024", **{**full, "total_debt": None})])
    assert gap == ["total_debt (najnowszy okres FY2024)"]
    assert dcf_absence_kind(gap, rule) == "BRAK_DANYCH"
    assert input_gaps(periods[:1]) == ["za mało okresów finansowych (1, potrzeba co najmniej 2)"]


def test_fundamentals_check_warns_or_errors_by_threshold():
    dq = DataQuality(session_date=SESSION, surfaced=100, fundamentals_problems={"A": "błąd FMP"})
    assert dq.check_fundamentals(DataQualityThresholds()) is True and dq.warnings
    dq = DataQuality(session_date=SESSION, surfaced=10, fundamentals_problems={"A": "x", "B": "y"})
    assert dq.check_fundamentals(DataQualityThresholds()) is False and dq.errors


# --- run-live-scan -----------------------------------------------------


class _SecBeforeSession(t._FakeSecEdgarClient):
    def get_filings(self, cik):
        return [{"form": "10-K", "accession_number": "0000320193-24-000001", "filing_date": "2024-08-01",
                 "report_date": "2024-06-29", "primary_document": "aapl10k.htm"}]


def _shift_back_a_year(rows):
    """Okresy atrapy przesunięte o rok (FY2022/FY2023) z datą złożenia 45 dni
    po końcu okresu -- spójne z sesją 2024-09-18 (bez danych z przyszłości)."""
    import datetime as _dt

    out = []
    for r in rows:
        end = _dt.date.fromisoformat(r["date"]).replace(year=int(r["date"][:4]) - 1)
        out.append({**r, "date": end.isoformat(), "fiscalYear": r["fiscalYear"] - 1,
                    "filingDate": (end + _dt.timedelta(days=45)).isoformat()})
    return out


class _SessionConsistentFMP(t._FakeFMPClient):
    def get_income_statement(self, symbol):
        return _shift_back_a_year(super().get_income_statement(symbol))

    def get_balance_sheet_statement(self, symbol):
        return _shift_back_a_year(super().get_balance_sheet_statement(symbol))

    def get_cash_flow_statement(self, symbol):
        return _shift_back_a_year(super().get_cash_flow_statement(symbol))


def _setup(monkeypatch, fmp=None):
    fmp = fmp or _SessionConsistentFMP
    t._use_counting_claude(monkeypatch)
    monkeypatch.setattr(cli, "FMPClient", fmp)
    monkeypatch.setattr(cli, "SecEdgarClient", _SecBeforeSession)
    monkeypatch.setattr(cli, "_sleep", lambda seconds: None)


def _scan(tmp_path, *extra):
    db = tmp_path / "scan.db"
    dq = tmp_path / "dq.json"
    code = cli.main(["--db", str(db), "run-live-scan", "--sample", "AAPL", "--min-universe-size", "1",
                     "--data-quality-out", str(dq), "--usage-out", str(tmp_path / "usage.json"), *extra])
    return code, db, (json.loads(dq.read_text(encoding="utf-8")) if dq.exists() else None)


def _runs(db):
    from buffett_scanner.db import connect

    return [dict(r) for r in connect(db).execute("SELECT run_id, run_date, status FROM live_scan_runs")]


def test_fresh_complete_data_passes_and_scan_date_is_session_date(tmp_path, monkeypatch, capsys):
    _setup(monkeypatch)
    code, db, dq = _scan(tmp_path, "--session-date", SESSION, "--max-claude-calls", "5")
    out = capsys.readouterr().out

    assert code == 0
    assert dq["passed"] is True and dq["price_coverage_pct"] == 100.0
    assert [s["etap"] for s in dq["stability"]] == ["przed skanem", "po pobraniu cen"]
    assert _runs(db)[0]["run_date"] == SESSION  # nie data zegara serwera
    assert t._CountingClaudeClient.call_count["n"] == 1
    assert "Wywołania Claude w tym przebiegu (pełne + naprawy): 1 / limit 5" in out
    assert json.loads((tmp_path / "usage.json").read_text(encoding="utf-8"))["sources_filed_on_or_before"] == SESSION


def test_stale_session_aborts_before_any_claude_call(tmp_path, monkeypatch, capsys):
    """Skan na sesję, której dane jeszcze nie istnieją (ostatnie notowanie
    to dzień wcześniej) -> wyraźny błąd, zero Claude, zero wyniku skanu."""
    _setup(monkeypatch)
    code, db, dq = _scan(tmp_path, "--session-date", "2024-09-19")
    out = capsys.readouterr().out

    assert code == 1
    assert dq["passed"] is False
    assert "::error title=Dane niekompletne::" in out
    assert t._CountingClaudeClient.call_count["n"] == 0
    assert _runs(db) == []


class _ChangingFMP(_SessionConsistentFMP):
    """Notowanie sesji jeszcze się zmienia: wolumen rośnie przy każdym pobraniu."""

    calls = {"n": 0}

    def get_historical_prices(self, symbol, *, from_date, to_date):
        type(self).calls["n"] += 1
        rows = t._flat_then_drop_price_rows()
        rows[-1] = {**rows[-1], "volume": rows[-1]["volume"] + type(self).calls["n"]}
        return rows


def test_session_bar_still_changing_aborts(tmp_path, monkeypatch, capsys):
    _setup(monkeypatch, _ChangingFMP)
    code, db, dq = _scan(tmp_path, "--session-date", SESSION)
    capsys.readouterr()
    assert code == 1
    assert "Test stabilności (przed skanem)" in dq["errors"][0] and "volume" in dq["errors"][0]
    assert t._CountingClaudeClient.call_count["n"] == 0 and _runs(db) == []


class _PartialVolumeFMP(_SessionConsistentFMP):
    def get_historical_prices(self, symbol, *, from_date, to_date):
        rows = t._flat_then_drop_price_rows()
        rows[-1] = {**rows[-1], "volume": 100_000}  # 0,1 średniej -> niepełny dzień
        return rows


def test_low_session_volume_is_a_warning_not_an_abort(tmp_path, monkeypatch, capsys):
    _setup(monkeypatch, _PartialVolumeFMP)
    code, db, dq = _scan(tmp_path, "--session-date", SESSION, "--stability-wait-minutes", "0")
    capsys.readouterr()
    assert code == 0 and dq["passed"] is True
    assert any("niska" in w for w in dq["warnings"])
    assert any("pominięty" in w for w in dq["warnings"])  # pominięty test stabilności jest jawny


def test_scan_before_minimum_time_after_close_aborts(tmp_path, monkeypatch, capsys):
    import datetime as _dt

    _setup(monkeypatch)
    # 2024-09-18 16:00 New York = 20:00 UTC; 3 h po zamknięciu = 23:00 UTC.
    monkeypatch.setattr(cli, "_now", lambda: _dt.datetime(2024, 9, 18, 22, 30, tzinfo=_dt.timezone.utc))
    code, db, dq = _scan(tmp_path, "--session-date", SESSION)
    capsys.readouterr()
    assert code == 1
    assert "Za wcześnie: skan sesji 2024-09-18 najwcześniej od 2024-09-18 23:00 UTC" in dq["errors"][0]
    assert t._CountingClaudeClient.call_count["n"] == 0


class _LateFilingFMP(_SessionConsistentFMP):
    """Najnowszy okres złożony dzień PO sesji -- nie może trafić do skanu."""

    def _late(self, rows):
        return [{**r, "filingDate": "2024-09-19"} if r["fiscalYear"] == 2023 else r for r in rows]

    def get_income_statement(self, symbol):
        return self._late(super().get_income_statement(symbol))

    def get_balance_sheet_statement(self, symbol):
        return self._late(super().get_balance_sheet_statement(symbol))

    def get_cash_flow_statement(self, symbol):
        return self._late(super().get_cash_flow_statement(symbol))


def test_fundamentals_filed_after_session_are_dropped_and_reported(tmp_path, monkeypatch, capsys):
    """Po odrzuceniu okresu złożonego po sesji zostaje 1 okres -> spółka z
    shortlisty bez kompletnych danych -> skan przerwany przed Claude."""
    _setup(monkeypatch, _LateFilingFMP)
    code, db, dq = _scan(tmp_path, "--session-date", SESSION)
    capsys.readouterr()
    assert dq["dropped_periods"] == {"AAPL": {"2023-FY": "złożony 2024-09-19, po dniu sesji"}}
    assert code == 1
    assert "Spółki z shortlisty bez kompletnych danych wejściowych: AAPL (za mało okresów" in dq["errors"][0]
    assert t._CountingClaudeClient.call_count["n"] == 0 and _runs(db) == []


def test_call_cap_must_cover_worst_case_of_whole_shortlist(tmp_path, monkeypatch, capsys):
    _setup(monkeypatch)
    code, db, dq = _scan(tmp_path, "--session-date", SESSION, "--max-claude-calls", "2")
    capsys.readouterr()
    assert code == 1
    assert "Limit wywołań Claude 2 nie pokrywa najgorszego przypadku shortlisty: 1 spółek x 3 = 3" in dq["errors"][0]
    assert t._CountingClaudeClient.call_count["n"] == 0 and _runs(db) == []


class _NoFundamentalsFMP(_SessionConsistentFMP):
    def get_income_statement(self, symbol):
        raise FMPError("500 Internal Server Error")


def test_missing_fundamentals_for_surfaced_companies_aborts(tmp_path, monkeypatch, capsys):
    _setup(monkeypatch, _NoFundamentalsFMP)
    code, db, dq = _scan(tmp_path, "--session-date", SESSION)
    capsys.readouterr()
    assert code == 1
    assert dq["fundamentals_problems"] == {"AAPL": "błąd FMP: 500 Internal Server Error"}
    assert t._CountingClaudeClient.call_count["n"] == 0 and _runs(db) == []


def test_too_small_universe_aborts_on_full_scan(tmp_path, monkeypatch, capsys):
    _setup(monkeypatch)
    db = tmp_path / "scan.db"
    code = cli.main(["--db", str(db), "run-live-scan", "--session-date", SESSION])
    out = capsys.readouterr().out
    assert code == 1
    assert "Uniwersum ma 1 spółek, minimum 480" in out
    assert t._CountingClaudeClient.call_count["n"] == 0


def test_full_scan_ignores_sec_filings_after_session_date(tmp_path, monkeypatch, capsys):
    """Dokument SEC złożony po dniu sesji (atrapa: 2024-11-01) nie trafia do
    analizy -- bez innych źródeł spółka kończy jako FAILED, bez wywołania Claude."""
    _setup(monkeypatch)
    monkeypatch.setattr(cli, "SecEdgarClient", t._FakeSecEdgarClient)
    code, db, dq = _scan(tmp_path, "--session-date", SESSION)
    capsys.readouterr()
    assert code == 0 and dq["passed"] is True
    assert t._CountingClaudeClient.call_count["n"] == 0
    from buffett_scanner.db import connect

    row = connect(db).execute("SELECT llm_status, llm_error FROM live_scan_candidates").fetchone()
    assert (row["llm_status"], row["llm_error"]) == ("FAILED", "brak zweryfikowanych źródeł")


def _report(tmp_path, db):
    return cli.main(["--db", str(db), "scan-report", "--data-quality-json", str(tmp_path / "dq.json"),
                     "--usage-json", str(tmp_path / "usage.json"), "--price-input-per-mtok", "2",
                     "--price-output-per-mtok", "10", "--report-out", str(tmp_path / "reports")])


def test_scan_report_covers_data_ranking_analyses_cost_and_methodology(tmp_path, monkeypatch, capsys):
    _setup(monkeypatch)
    code, db, _ = _scan(tmp_path, "--session-date", SESSION)
    capsys.readouterr()
    assert code == 0
    assert _report(tmp_path, db) == 0
    report = (tmp_path / "reports" / "scan_report.md").read_text(encoding="utf-8")
    for expected in (
        f"## Dane rynkowe -- sesja {SESSION}: OK",
        "- Ceny i wolumen sesji: 1/1 (100.0%)",
        "- Test stabilności notowań: przed skanem: 1 spółek, zmiany: 0; po pobraniu cen: 1 spółek, zmiany: 0",
        "- Dane finansowe wytypowanych spółek: 1/1",
        "### Wszystkie wykluczenia i ich przyczyny",
        "Brak wykluczonych spółek.",
        "- W rankingu: 1, na shortliście: 1",
        "- Status skanu: COMPLETE",
        "- Wywołania Claude w tym przebiegu: 1",
        "- Koszt:",
        "Ranking kompletny technicznie: TAK",
        "Spółki bez DCF",
        "### Look-ahead: BRAK",
        "## Ostrzeżenia metodologiczne (bez zmian w metodologii)",
        "Wzrost w scenariuszu BASE na suficie 20%",
        "**Wynik: OK -- gotowy do Twojej kontroli.** Publikacja nie jest automatyczna",
    ):
        assert expected in report, expected


def test_scan_report_after_data_gate_abort_says_scan_stopped(tmp_path, monkeypatch, capsys):
    _setup(monkeypatch)
    code, db, _ = _scan(tmp_path, "--session-date", "2024-09-19")
    capsys.readouterr()
    assert code == 1
    assert _report(tmp_path, db) == 1
    report = (tmp_path / "reports" / "scan_report.md").read_text(encoding="utf-8")
    assert "## Dane rynkowe -- sesja 2024-09-19: NIEKOMPLETNE" in report
    assert "- BŁĄD: Notowanie sesji 2024-09-19 dostępne dla 0/1 spółek próbki" in report
    assert "PRZERWANY przed zapisaniem wyniku" in report

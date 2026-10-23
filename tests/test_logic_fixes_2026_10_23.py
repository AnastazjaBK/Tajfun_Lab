"""Testy regresyjne czterech poprawek błędów logicznych (decyzja właścicielki
2026-10-23): klasyfikacja sektorowa w skanie na żywo, stany zerowego CAPEX,
komunikat o braku DCF zgodny z regułą, remisy w rankingu. Zero sieci."""

from __future__ import annotations

import json
from types import SimpleNamespace

from buffett_scanner import cli
from buffett_scanner.config import load_config
from buffett_scanner.data_quality import (
    CAPEX_CONFIRMED_ZERO,
    CAPEX_SUSPICIOUS,
    CAPEX_UNVERIFIED_ACCEPTED,
    capex_zero_state,
    sec_annual_value,
)
from buffett_scanner.db import connect, get_live_scan_candidates
from buffett_scanner.live_scan_pipeline import competition_ranks
from buffett_scanner.providers.sec_edgar import SecEdgarError
from buffett_scanner.valuation import compute_valuation
from tests import test_cli as t
from tests import test_live_scan_data_gate as g
from tests.test_live_scan import _period

SESSION = g.SESSION


def _facts(values: dict[str, float], tag="PaymentsToAcquirePropertyPlantAndEquipment"):
    """Minimalny payload SEC company-facts: roczne fakty {koniec okresu: wartość}."""
    entries = [{"start": f"{end[:4]}-01-01", "end": end, "val": v, "filed": f"{int(end[:4]) + 1}-02-15",
                "fy": end[:4], "fp": "FY", "form": "10-K", "accn": "x"} for end, v in values.items()]
    return {"facts": {"us-gaap": {tag: {"units": {"USD": entries}}}}}


def _rows(db):
    conn = connect(db)
    run_id = conn.execute("SELECT run_id FROM live_scan_runs").fetchone()["run_id"]
    return conn, {r["ticker"]: r for r in get_live_scan_candidates(conn, run_id)}


# --- 1. Klasyfikacja sektorowa ---------------------------------------------------


class _InsurerSec(g._SecBeforeSession):
    sic = "6311"  # Life insurance -> INSURER


def test_live_scan_applies_backtest_sector_classification(tmp_path, monkeypatch, capsys):
    g._setup(monkeypatch)
    monkeypatch.setattr(cli, "SecEdgarClient", _InsurerSec)
    code, db, dq = g._scan(tmp_path, "--session-date", SESSION)
    capsys.readouterr()
    assert code == 0
    assert dq["sector_profiles"] == {"AAPL": "INSURER"}
    conn, rows = _rows(db)
    assert conn.execute("SELECT sector_profile FROM companies WHERE cik = ?",
                        (rows["AAPL"]["cik"],)).fetchone()[0] == "INSURER"
    # Profil bez metody wyceny -> brak DCF (wcześniej dostawał DCF jak GENERAL).
    assert rows["AAPL"]["valuation_score"] is None
    assert "valuation" in json.loads(rows["AAPL"]["missing_components_json"])


class _SicFailsSec(g._SecBeforeSession):
    def get_sic_classification(self, cik):
        raise SecEdgarError("503 Service Unavailable")


def test_sec_failure_is_never_silently_general(tmp_path, monkeypatch, capsys):
    g._setup(monkeypatch)
    monkeypatch.setattr(cli, "SecEdgarClient", _SicFailsSec)
    code, db, dq = g._scan(tmp_path, "--session-date", SESSION)
    capsys.readouterr()
    assert code == 1  # 1/1 spółek bez klasyfikacji > limit 5% -> skan przerwany przed Claude
    assert dq["sector_problems"] == {"AAPL": "brak klasyfikacji sektorowej (błąd SEC: 503 Service Unavailable)"}
    assert t._CountingClaudeClient.call_count["n"] == 0


class _NoSicSec(g._SecBeforeSession):
    sic = None


def test_missing_sic_follows_backtest_rule_but_is_reported(tmp_path, monkeypatch, capsys):
    g._setup(monkeypatch)
    monkeypatch.setattr(cli, "SecEdgarClient", _NoSicSec)
    code, db, dq = g._scan(tmp_path, "--session-date", SESSION)
    capsys.readouterr()
    assert code == 0
    assert dq["sector_profiles"] == {"AAPL": "GENERAL"} and dq["sic_missing"] == ["AAPL"]
    assert any("Brak kodu SIC w SEC" in w for w in dq["warnings"])


# --- 2. Zerowy CAPEX ----------------------------------------------------------------


def test_capex_zero_states():
    assert capex_zero_state("GENERAL", 0.0)[0] == CAPEX_CONFIRMED_ZERO
    state, why = capex_zero_state("GENERAL", 1_500_000.0)
    assert state == CAPEX_SUSPICIOUS and "1,500,000" in why
    assert capex_zero_state("GENERAL", None)[0] == CAPEX_SUSPICIOUS
    assert capex_zero_state("REIT", None)[0] == CAPEX_UNVERIFIED_ACCEPTED
    assert capex_zero_state("BANK", 2.0)[0] == CAPEX_SUSPICIOUS  # sprzeczność z SEC zawsze podejrzana


def test_sec_annual_value_matches_period_and_respects_session_date():
    facts = _facts({"2022-12-31": 0.0, "2023-12-31": 7.0})
    assert sec_annual_value(facts, "capital_expenditure", "2022-12-31", SESSION) == 0.0
    assert sec_annual_value(facts, "capital_expenditure", "2023-12-30", SESSION) == 7.0  # +-7 dni
    assert sec_annual_value(facts, "capital_expenditure", "2023-12-31", "2024-01-31") is None  # złożony po sesji
    assert sec_annual_value({}, "capital_expenditure", "2023-12-31", SESSION) is None


class _ZeroCapexFMP(g._SessionConsistentFMP):
    def get_cash_flow_statement(self, symbol):
        return [{**r, "capitalExpenditure": 0.0} for r in super().get_cash_flow_statement(symbol)]


def _capex_scan(tmp_path, monkeypatch, sec_cls):
    g._setup(monkeypatch, _ZeroCapexFMP)
    monkeypatch.setattr(cli, "SecEdgarClient", sec_cls)
    code, db, dq = g._scan(tmp_path, "--session-date", SESSION)
    conn = connect(db)
    values = [r[0] for r in conn.execute(
        "SELECT value FROM fundamentals_raw WHERE line_item = 'capital_expenditure' ORDER BY period_end_date")]
    return code, dq, values


class _SecConfirmsZero(g._SecBeforeSession):
    company_facts = _facts({"2022-12-31": 0.0, "2023-12-31": 0.0})


class _SecContradicts(g._SecBeforeSession):
    company_facts = _facts({"2022-12-31": 4_000_000.0, "2023-12-31": 5_000_000.0})


class _InsurerNoFacts(g._SecBeforeSession):
    sic = "6311"


def test_capex_zero_confirmed_by_sec_stays_zero(tmp_path, monkeypatch, capsys):
    code, dq, values = _capex_scan(tmp_path, monkeypatch, _SecConfirmsZero)
    capsys.readouterr()
    assert values == [0.0, 0.0]
    assert all(v.startswith(CAPEX_CONFIRMED_ZERO) for v in dq["capex_zero"]["AAPL"].values())


def test_capex_zero_contradicted_by_sec_becomes_missing_and_stops_shortlist(tmp_path, monkeypatch, capsys):
    code, dq, values = _capex_scan(tmp_path, monkeypatch, _SecContradicts)
    capsys.readouterr()
    assert values == [None, None]  # nie jest prawdziwym zerem -> brak danych
    assert "sprzeczne z SEC XBRL (5,000,000 USD)" in dq["capex_zero"]["AAPL"]["2023-FY"]
    # Konsekwencja istniejącej reguły z 23.10: spółka z shortlisty bez kompletu
    # danych -> skan zatrzymany przed Claude (do decyzji: patrz raport).
    assert code == 1 and "capital_expenditure" in dq["errors"][0]


def test_capex_zero_without_confirmation_for_insurer_is_kept_and_flagged(tmp_path, monkeypatch, capsys):
    code, dq, values = _capex_scan(tmp_path, monkeypatch, _InsurerNoFacts)
    capsys.readouterr()
    assert code == 0 and values == [0.0, 0.0]
    assert all(v.startswith(CAPEX_UNVERIFIED_ACCEPTED) for v in dq["capex_zero"]["AAPL"].values())


# --- 3. Komunikat o braku DCF ------------------------------------------------------


def _full(**kw):
    base = dict(revenue=100.0, net_income=10.0, ebitda=20.0, operating_cash_flow=30.0, capital_expenditure=5.0,
                total_debt=10.0, cash_and_equivalents=5.0, total_current_assets=50.0,
                total_current_liabilities=20.0, dividends_paid=0.0, share_buybacks=0.0,
                diluted_shares_outstanding=10.0)
    base.update(kw)
    return base


def test_no_dcf_message_describes_the_first_and_last_period_rule():
    cfg = load_config()
    periods = [_period("FY2021", **_full(operating_cash_flow=-10.0)), _period("FY2022", **_full()),
               _period("FY2023", **_full()), _period("FY2024", **_full())]
    reason = compute_valuation("GENERAL", periods, current_price=10.0, config=cfg.valuation).reason
    assert "wyłącznie między pierwszym a ostatnim okresem" in reason
    assert "pierwszy okres (FY2021: -15 USD)" in reason
    assert "Lata pośrednie nie są brane pod uwagę" in reason
    assert ">=2 okresów" not in reason  # stary, niezgodny z regułą opis
    single = compute_valuation("GENERAL", periods[-1:], current_price=10.0, config=cfg.valuation).reason
    assert single.startswith("Tylko jeden okres finansowy")


# --- 4. Remisy --------------------------------------------------------------------


def _cand(ticker, pct):
    return SimpleNamespace(ticker=ticker, score=SimpleNamespace(deterministic_score_pct=pct))


def test_equal_scores_share_a_position():
    ranked = [_cand("AAA", 100.0), _cand("ZZZ", 100.0), _cand("MMM", 90.0), _cand("BBB", 90.0),
              _cand("CCC", 80.0), _cand("NNN", None)]
    assert competition_ranks(ranked) == [1, 1, 3, 3, 5, 6]


class _TiedFMP(t._TwoTickerFMPClient):
    FINAL_CLOSE = {"AAPL": 60.0, "MSFT": 60.0}  # identyczne dane -> identyczny wynik


def test_tied_companies_get_equal_rank_in_db_and_report(tmp_path, monkeypatch, capsys):
    t._use_counting_claude(monkeypatch)
    monkeypatch.setattr(cli, "FMPClient", _TiedFMP)
    db = tmp_path / "scan.db"
    assert cli.main(["--db", str(db), "run-live-scan", "--sample", "AAPL,MSFT", "--rank-only"]) == 0
    out = capsys.readouterr().out
    _, rows = _rows(db)
    assert rows["AAPL"]["deterministic_score_pct"] == rows["MSFT"]["deterministic_score_pct"]
    assert rows["AAPL"]["rank"] == rows["MSFT"]["rank"] == 1
    assert "| 1= | AAPL |" in out and "| 1= | MSFT |" in out

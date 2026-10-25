"""rerank-live-scan (2026-10-25): korekta istniejącego skanu po poprawce
kontroli dywidend -- gotowe analizy zostają, nowe spółki na shortliście
dostają PENDING. Atrapy FMP/SEC z tests/test_cli.py, zero sieci i Claude."""

from __future__ import annotations

import pytest

from buffett_scanner import cli
from tests import test_cli as t


class _FMP(t._TwoTickerFMPClient):
    """MSFT: FMP netPreferredStockIssuance != 0 (jak QCOM), AAPL bez śladu;
    te same ceny i dane, więc po korekcie oba wyniki są równe."""
    FINAL_CLOSE = {"AAPL": 70.0, "MSFT": 70.0}
    operating_cash_flow_2024 = 170.0

    def get_cash_flow_statement(self, symbol):
        rows = super().get_cash_flow_statement(symbol)
        rows[1] = {**rows[1], "operatingCashFlow": self.operating_cash_flow_2024}
        if symbol == "MSFT":
            rows[0] = {**rows[0], "netPreferredStockIssuance": -955.0}
        return rows


def _zero_preferred_facts():
    return {"facts": {"us-gaap": {"PreferredStockValue": {"units": {"USD": [
        {"end": end, "val": 0, "filed": "2025-02-15", "form": "10-K", "fy": 2024, "fp": "FY", "accn": "x"}
        for end in ("2023-12-31", "2024-12-31")]}}}}}


@pytest.fixture
def scanned(tmp_path, monkeypatch):
    """Skan (tylko ranking) jak 23.10: SEC bez faktu o akcjach uprzywilejowanych
    -> MSFT dywidendy NIEZNANE; AAPL na shortliście z gotową analizą."""
    t._set_live_scan_env(monkeypatch)
    _FMP.operating_cash_flow_2024 = 170.0
    monkeypatch.setattr(cli, "FMPClient", _FMP)
    monkeypatch.setattr(cli, "SecEdgarClient", t._FakeSecEdgarClient)
    monkeypatch.setattr(t._FakeSecEdgarClient, "company_facts", {})
    db = tmp_path / "scan.db"
    assert cli.main(["--db", str(db), "run-live-scan", "--sample", "AAPL,MSFT", "--rank-only",
                     "--shortlist-limit", "1"]) == 0
    from buffett_scanner.db import connect

    conn = connect(db)
    run_id = conn.execute("SELECT run_id FROM live_scan_runs").fetchone()["run_id"]
    rows = {r["ticker"]: r for r in conn.execute("SELECT * FROM live_scan_candidates")}
    assert rows["AAPL"]["in_shortlist"] == 1 and rows["MSFT"]["in_shortlist"] == 0
    assert rows["MSFT"]["dividend_score"] < rows["AAPL"]["dividend_score"]
    conn.execute("UPDATE live_scan_candidates SET llm_status = 'COMPLETE' WHERE ticker = 'AAPL'")
    conn.commit()
    return db, run_id


def _rows(db):
    from buffett_scanner.db import connect

    return {r["ticker"]: r for r in connect(db).execute("SELECT * FROM live_scan_candidates")}


def test_rerank_restores_dividends_and_adds_only_new_entrant(scanned, monkeypatch, tmp_path):
    db, run_id = scanned
    monkeypatch.setattr(t._FakeSecEdgarClient, "company_facts", _zero_preferred_facts())
    assert cli.main(["--db", str(db), "rerank-live-scan", "--run-id", run_id,
                     "--report-out", str(tmp_path / "r")]) == 0
    rows = _rows(db)
    assert rows["MSFT"]["dividend_score"] == rows["AAPL"]["dividend_score"]
    assert rows["MSFT"]["in_shortlist"] == 1 and rows["MSFT"]["llm_status"] == "PENDING"  # remis na granicy
    assert rows["AAPL"]["llm_status"] == "COMPLETE"  # gotowa analiza zostaje
    from buffett_scanner.db import connect

    run = connect(db).execute("SELECT * FROM live_scan_runs").fetchone()
    assert (run["shortlist_size"], run["status"]) == (2, "INCOMPLETE_LLM_ANALYSIS")
    assert "nowe (do analizy Claude): MSFT" in (tmp_path / "r" / "rerank.md").read_text()


def test_rerank_stops_when_fmp_data_changed_since_scan(scanned, monkeypatch):
    db, run_id = scanned
    before = _rows(db)
    monkeypatch.setattr(t._FakeSecEdgarClient, "company_facts", _zero_preferred_facts())
    _FMP.operating_cash_flow_2024 = 171.0
    with pytest.raises(SystemExit, match="dane FMP zmieniły się od skanu"):
        cli.main(["--db", str(db), "rerank-live-scan", "--run-id", run_id])
    after = _rows(db)
    assert {k: dict(v) for k, v in after.items()} == {k: dict(v) for k, v in before.items()}


def test_rerank_stops_when_completed_analysis_score_would_change(scanned, monkeypatch):
    db, run_id = scanned
    from buffett_scanner.db import connect

    conn = connect(db)
    conn.execute("UPDATE live_scan_candidates SET llm_status = 'COMPLETE' WHERE ticker = 'MSFT'")
    conn.commit()
    monkeypatch.setattr(t._FakeSecEdgarClient, "company_facts", _zero_preferred_facts())
    with pytest.raises(SystemExit, match="gotową analizą \\(MSFT\\)"):
        cli.main(["--db", str(db), "rerank-live-scan", "--run-id", run_id])

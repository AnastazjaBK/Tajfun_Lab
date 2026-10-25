"""Diagnostyka dywidend uprzywilejowanych -- logika offline (bez sieci)."""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import diag_preferred_dividends as d  # noqa: E402


def _conn():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE live_scan_candidates (ticker TEXT, cik TEXT)")
    conn.execute("CREATE TABLE fundamentals_raw (cik TEXT, fiscal_period TEXT, period_end_date TEXT, "
                 "line_item TEXT, value REAL)")
    conn.execute("INSERT INTO live_scan_candidates VALUES ('QCOM', '0000804328')")
    conn.executemany("INSERT INTO fundamentals_raw VALUES ('0000804328', ?, ?, ?, ?)", [
        ("2025-FY", "2025-09-28", "dividends_paid", None),
        ("2025-FY", "2025-09-28", "preferred_stock_issuance_net", 5.0e8),
    ])
    return conn


def _facts(**tags):
    return {"facts": {"us-gaap": {t: {"units": {"USD": rows}} for t, rows in tags.items()}}}


def test_reports_which_condition_gave_preferred_evidence():
    facts = _facts(PaymentsOfDividends=[{"start": "2024-09-30", "end": "2025-09-28", "val": 3.8e9,
                                          "filed": "2025-11-05", "form": "10-K", "fy": 2025, "fp": "FY"}])
    fmp = {"QCOM": [{"date": "2025-09-28", "commonDividendsPaid": -3.8e9, "netPreferredStockIssuance": 5.0e8}]}
    [r] = [x for x in d.diagnose(_conn(), {"QCOM": facts}, fmp, "2026-10-23") if x["ticker"] == "QCOM"]
    [p] = r["periods"]
    assert p["evidence"]["fmp_preferred_rows_up_to_period"] == [("2025-09-28", "preferred_stock_issuance_net", 5.0e8)]
    assert p["evidence"]["sec_preferred_stock_value_gt_0"] is False
    assert p["sec_total"] == 3.8e9 and p["sec_common"] is None
    assert p["result"]["state"] == "BEZ_UPRZYWILEJOWANYCH"  # emisja z FMP nie jest śladem (2026-10-25)
    assert "PaymentsOfDividends" in r["sec_facts"]["tags"]


def test_missing_ticker_is_reported_not_skipped():
    out = {x["ticker"]: x for x in d.diagnose(_conn(), {}, {}, "2026-10-23")}
    assert out["JBL"] == {"ticker": "JBL", "error": "brak w skanie"}

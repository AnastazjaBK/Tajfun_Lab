"""Testy offline skryptu diagnostycznego SIC i liczebności (zero sieci)."""

from __future__ import annotations

import importlib.util
import json
import sqlite3
from pathlib import Path

_PATH = Path(__file__).resolve().parents[1] / "scripts" / "diag_sic_and_sample_sizes.py"
_spec = importlib.util.spec_from_file_location("diag_sic", _PATH)
d = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(d)

SGML = """<SEC-HEADER>
<FILER>
<COMPANY-DATA>
<CONFORMED-NAME>OTHER CO
<CIK>0000000111
<ASSIGNED-SIC>6798
</COMPANY-DATA>
</FILER>
<FILER>
<COMPANY-DATA>
<CONFORMED-NAME>TARGET CO
<CIK>0000000222
<ASSIGNED-SIC>2400
</COMPANY-DATA>
</FILER>"""

TEXT = """FILER:
	COMPANY DATA:
		COMPANY CONFORMED NAME:			TARGET CO
		CENTRAL INDEX KEY:			0000000222
		STANDARD INDUSTRIAL CLASSIFICATION:	REAL ESTATE INVESTMENT TRUSTS [6798]
"""


def test_header_parser_picks_sic_of_matching_filer():
    assert d.parse_header_sic(SGML, "222") == ("2400", "OK")
    assert d.parse_header_sic(SGML, "111") == ("6798", "OK")
    assert d.parse_header_sic(TEXT, "0000000222") == ("6798", "OK")
    assert d.parse_header_sic(html_escaped(SGML), "222") == ("2400", "OK")
    assert d.parse_header_sic(SGML, "999") == (None, "BRAK_DOPASOWANIA_CIK")
    assert d.parse_header_sic("<SEC-HEADER><CIK>222", "222") == (None, "BRAK_SIC_W_NAGLOWKU")


def html_escaped(s):
    return s.replace("<", "&lt;").replace(">", "&gt;")


def test_missing_sic_is_unknown_not_general():
    assert d.profile_of(None) == "NIEZNANY"
    assert d.profile_of("") == "NIEZNANY"
    assert d.profile_of("6798") == "REIT"
    assert d.profile_of("3571") == "GENERAL"


def test_point_in_time_sic_uses_latest_header_filed_by_decision_date():
    hs = [{"filing_date": "2012-02-20", "sic": "2400", "status": "OK"},
          {"filing_date": "2013-02-20", "sic": None, "status": "BRAK_SIC_W_NAGLOWKU"},
          {"filing_date": "2016-02-20", "sic": "6798", "status": "OK"}]
    assert d.pit_sic(hs, "2012-01-01") is False  # nic złożonego przed datą
    assert d.pit_sic(hs, "2015-12-01") == "2400"
    assert d.pit_sic(hs, "2016-02-20") == "6798"


def test_annual_filings_merges_recent_and_older_pages_without_duplicates():
    recent = {"filings": {"recent": {"form": ["10-K", "8-K", "10-K/A"], "accessionNumber": ["a2", "x", "y"],
                                     "filingDate": ["2020-02-01", "2020-03-01", "2020-04-01"]}}}
    older = {"form": ["10-K", "10-K"], "accessionNumber": ["a1", "a2"], "filingDate": ["2019-02-01", "2020-02-01"]}
    assert [f["accession"] for f in d.annual_filings([recent, older])] == ["a1", "a2"]


def test_sample_sets_follow_calibration_definitions():
    rows = [("2016-01-01", "0000000222", 50.0, 10.0, 3.0),   # pełna + wycena
            ("2016-02-01", "222", 50.0, None, 3.0),          # pełna, bez wyceny
            ("2016-03-01", "333", 50.0, 10.0, 3.0),          # brak benchmarku -> tylko wycena
            ("2016-04-01", "333", 50.0, 10.0, None),         # brak zwrotu -> nigdzie
            ("2015-01-01", "222", 50.0, 10.0, 3.0)]          # rok rozgrzewki -> nigdzie
    bench = {"2016-01-01": 1.0, "2016-02-01": 1.0, "2015-01-01": 1.0}
    full, val = d.sample_sets(rows, bench)
    assert d.per_year(full)[2016] == (2, 1)
    assert d.per_year(val)[2016] == (2, 2)


class _Resp:
    def __init__(self, status, payload=None, text=""):
        self.status_code, self._payload, self.text = status, payload, text

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self):
        self.urls = []

    def _get(self, url):
        self.urls.append(url)
        if url.endswith("CIK0000000222.json"):
            return _Resp(200, {"sic": "6798", "sicDescription": "REIT", "name": "TARGET CO", "filings": {
                "recent": {"form": ["10-K", "10-K"], "accessionNumber": ["0000000222-12-000001", "0000000222-23-000001"],
                           "filingDate": ["2012-02-20", "2023-02-20"]}, "files": []}})
        if url.endswith("CIK0000000333.json"):
            return _Resp(200, {"sic": "", "name": "NO SIC CO", "filings": {"recent": {}, "files": []}})
        if url.endswith("CIK0000000444.json"):
            return _Resp(404)
        if "000000022212000001" in url and url.endswith(".hdr.sgml"):
            return _Resp(200, text=SGML)
        if "000000022223000001" in url and url.endswith(".hdr.sgml"):
            return _Resp(404)
        if "000000022223000001" in url and url.endswith("-index-headers.html"):
            return _Resp(200, text=html_escaped(TEXT))
        return _Resp(404)


def _db(path, ddl, rows_by_table):
    conn = sqlite3.connect(path)
    for stmt in ddl:
        conn.execute(stmt)
    for table, rows in rows_by_table.items():
        for r in rows:
            conn.execute(f"INSERT INTO {table} VALUES ({','.join('?' * len(r))})", r)
    conn.commit()
    conn.close()


def test_end_to_end_with_fake_sec(tmp_path, monkeypatch, capsys):
    cal, snap, out = tmp_path / "cal.db", tmp_path / "snap.db", tmp_path / "out.json"
    _db(cal, ["CREATE TABLE universe_membership (cik TEXT)",
              "CREATE TABLE backtest_candidates (run_id TEXT, decision_date TEXT, cik TEXT, deterministic_score_pct REAL,"
              " margin_of_safety_base_pct REAL, return_6m_pct REAL)",
              "CREATE TABLE backtest_benchmark (run_id TEXT, decision_date TEXT, ew_pit_universe_return_6m_pct REAL)",
              "CREATE TABLE sec_company_facts_cache (cik TEXT, raw_json TEXT)"],
        {"sec_company_facts_cache": [("222", json.dumps(_facts()))],
         "universe_membership": [("222",), ("333",)],
         "backtest_candidates": [("r", "2016-06-01", "222", 50.0, None, 1.0), ("r", "2016-06-01", "333", 50.0, None, 1.0)],
         "backtest_benchmark": [("r", "2016-06-01", 0.5)]})
    _db(snap, ["CREATE TABLE companies (cik TEXT)", "CREATE TABLE live_scan_candidates (cik TEXT, ticker TEXT)",
               "CREATE TABLE fundamentals_raw (cik TEXT, period_end_date TEXT, line_item TEXT, value REAL)"],
        {"companies": [("0000000222",), ("0000000444",)], "live_scan_candidates": [("0000000222", "TGT")],
         "fundamentals_raw": [("0000000222", "2025-12-31", "dividends_paid", 331e6),
                              ("0000000222", "2024-12-31", "dividends_paid", 100e6)]})
    fake = _FakeClient()
    monkeypatch.setattr(d, "SecEdgarClient", lambda ua, **kw: _Ctx(fake))
    monkeypatch.delenv("FMP_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert d.main(["--calibration-db", str(cal), "--snapshot-db", str(snap), "--out", str(out)]) == 0
    text = capsys.readouterr().out
    assert "brak SIC: CIK=333 NO SIC CO" in text
    assert "błąd SEC: CIK=444 HTTP 404" in text
    assert "CIK=222 TARGET CO: 2400(2012-02-20) -> 6798(2023-02-20) | bieżący 6798 [PROFIL]" in text
    assert "TGT;222;6798;REIT;REIT" in text
    # Pełna próba 2016: 2 obserwacje; jedna spółka (333) bez SIC -> NIEZNANY;
    # 222 w dacie decyzji 2016-06 miała w nagłówku SIC 2400 (GENERAL), dziś REIT.
    assert "nieznany: 2016: 1/1" in text
    assert "pit_inny_profil: 2016: 1/1" in text
    assert "'REIT->GENERAL': 1" in text
    # FY2025: FMP 331 mln, SEC common = 0 (dywidenda uprzywilejowana) -> niezgodność.
    assert "niezgodne: ('TGT', '2025-12-31', 331000000.0, 0.0, 'różnica > 5%')" in text
    assert "PaymentsOfDividendsCommonStock: CIK z danymi 2016-2021 0 | FY2025 1" in text
    # Tylko SEC i lokalne bazy.
    assert all(u.startswith(("https://data.sec.gov/", "https://www.sec.gov/Archives/")) for u in fake.urls)


def test_refuses_to_run_with_paid_api_keys(tmp_path, monkeypatch):
    monkeypatch.setenv("FMP_API_KEY", "x")
    assert d.main(["--calibration-db", "a", "--snapshot-db", "b", "--out", "c"]) == 2


class _Ctx:
    def __init__(self, client):
        self.client = client

    def __enter__(self):
        return self.client

    def __exit__(self, *exc):
        return False


def _fact(end, val, start=None, form="10-K"):
    return {"start": start or f"{end[:4]}-01-01", "end": end, "val": val, "filed": f"{int(end[:4]) + 1}-02-15", "form": form}


def _facts():
    return {"facts": {"us-gaap": {
        "PaymentsOfDividendsCommonStock": {"units": {"USD": [_fact("2025-12-31", 0.0), _fact("2024-12-31", 100e6)]}},
        "DividendsPreferredStock": {"units": {"USD": [_fact("2025-12-31", 331e6)]}},
        "ShareBasedCompensation": {"units": {"USD": [_fact("2025-12-31", 5e6, start="2025-10-01"),  # kwartał
                                                       _fact("2018-12-31", 4e6, form="10-Q")]}},
    }}}


def test_annual_facts_keeps_only_full_year_10k_values():
    cf = _facts()
    assert d.annual_facts(cf, "PaymentsOfDividendsCommonStock") == {"2025-12-31": 0.0, "2024-12-31": 100e6}
    assert d.annual_facts(cf, "ShareBasedCompensation") == {}
    assert d.annual_facts(cf, "Missing") == {}

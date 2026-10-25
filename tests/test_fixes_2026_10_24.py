"""Testy regresyjne poprawek błędów (decyzje właścicielki 2026-10-24):
6 -- znak dźwigni przy EBITDA <= 0; 7 -- dywidendy uprzywilejowane
przypisane do akcji zwykłych; 8 -- SIC 6500 poza REIT; 9 -- błąd SEC lub
brak SIC -> NIEZNANY, nigdy GENERAL; 13 -- SIC point-in-time w backteście.
Zero sieci."""

from __future__ import annotations

import pytest

from buffett_scanner.fundamentals import low_leverage, net_debt_to_ebitda
from buffett_scanner.scoring import financial_quality_score
from tests.test_fundamentals import make_period
from tests.test_scoring import _app_config

# --- 6. Znak dźwigni ---------------------------------------------------------------


@pytest.mark.parametrize("debt,cash,ebitda,ratio,ok", [
    (167.6, 23.4, -4.58, None, False),   # F 2025: dług netto 144 mld, EBITDA ujemna -> NIE niska dźwignia
    (5.5, 2.3, -0.11, None, False),      # CVNA 2025
    (0.5, 0.87, -6.88, None, True),      # LITE: gotówka netto -> spełnia mimo ujemnej EBITDA
    (500.0, 200.0, 150.0, 2.0, True),    # granica progu włącznie
    (500.0, 200.0, 100.0, 3.0, False),
    (100.0, 150.0, 220.0, -50 / 220, True),
    (500.0, 200.0, 0.0, None, False),
])
def test_leverage_is_never_low_because_of_a_negative_ebitda(debt, cash, ebitda, ratio, ok):
    p = make_period("FY2025", total_debt=debt, cash_and_equivalents=cash, ebitda=ebitda)
    assert net_debt_to_ebitda(p) == (pytest.approx(ratio) if ratio is not None else None)
    assert low_leverage(p, 2.0) is ok


def test_leverage_missing_debt_data_gives_no_credit():
    assert low_leverage(make_period("FY2025", ebitda=100.0), 2.0) is False


def test_safety_score_no_longer_credits_net_debt_with_negative_ebitda():
    p = make_period("FY2025", revenue=187.3, net_income=-8.18, ebitda=-4.58, operating_cash_flow=21.28,
                    capital_expenditure=8.81, total_debt=167.6, cash_and_equivalents=23.4,
                    total_current_assets=100.0, total_current_liabilities=90.0)
    assert financial_quality_score([p], _app_config()).breakdown["low_leverage"] is False


# --- 8-9. Klasyfikacja sektorowa ------------------------------------------------------

from buffett_scanner import cli  # noqa: E402
from buffett_scanner.db import connect, init_db, upsert_company, upsert_universe_membership  # noqa: E402
from buffett_scanner.providers.sec_edgar import SecEdgarError  # noqa: E402
from tests import test_live_scan_data_gate as g  # noqa: E402
from tests import test_logic_fixes_2026_10_23 as lf  # noqa: E402


class _RealEstateServicesSec(g._SecBeforeSession):
    sic = "6500"  # CBRE: usługi nieruchomościowe, nie REIT


def test_live_scan_sic_6500_is_general_with_review_note(tmp_path, monkeypatch, capsys):
    g._setup(monkeypatch)
    monkeypatch.setattr(cli, "SecEdgarClient", _RealEstateServicesSec)
    code, db, dq = g._scan(tmp_path, "--session-date", g.SESSION)
    capsys.readouterr()
    assert code == 0
    assert dq["sector_profiles"] == {"AAPL": "GENERAL"}
    assert "SIC 6500" in dq["profile_review"]["AAPL"]
    assert any(w.startswith("Profil do weryfikacji") for w in dq["warnings"])


class _BacktestSec:
    def __init__(self, *a, **kw):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_sic_classification(self, cik):
        if cik == "111":
            raise SecEdgarError("503")
        return {"sic": None if cik == "222" else "6500", "sic_description": None}


def test_backtest_classification_sec_error_and_missing_sic_are_unknown(tmp_path, monkeypatch, capsys):
    path = tmp_path / "bt.db"
    conn = init_db(path)
    for cik in ("111", "222", "333"):
        upsert_company(conn, cik=cik, name=cik)
        upsert_universe_membership(conn, cik=cik, index_name=cli.UNIVERSE_MEMBERSHIP_INDEX_NAME,
                                   start_date="2012-01-01", source="test", source_snapshot_ref="test",
                                   cik_resolution_method="DIRECT")
    conn.commit()
    monkeypatch.setenv("SEC_EDGAR_USER_AGENT", "Test test@example.com")
    monkeypatch.setattr(cli, "SecEdgarClient", _BacktestSec)
    assert cli.main(["--db", str(path), "classify-sector-profiles"]) == 0
    out = capsys.readouterr().out
    profiles = {r[0]: r[1] for r in connect(path).execute("SELECT cik, sector_profile FROM companies")}
    assert profiles == {"111": "NIEZNANY", "222": "NIEZNANY", "333": "GENERAL"}
    assert "profil NIEZNANY" in out


def test_old_database_is_migrated_to_accept_unknown_profile_without_data_loss(tmp_path):
    import sqlite3
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.executescript("""
        CREATE TABLE companies (
            cik TEXT PRIMARY KEY, name TEXT NOT NULL, sector TEXT, industry TEXT, sub_industry TEXT,
            sector_profile TEXT NOT NULL DEFAULT 'GENERAL'
                CHECK (sector_profile IN ('GENERAL','BANK','INSURER','REIT','BIOTECH')),
            is_active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL DEFAULT (datetime('now')));
        INSERT INTO companies (cik, name, sector_profile) VALUES ('1', 'A', 'REIT'), ('2', 'B', 'GENERAL');
    """)
    old.commit()
    old.close()
    conn = init_db(path)
    assert [tuple(r) for r in conn.execute("SELECT cik, name, sector_profile FROM companies ORDER BY cik")] == [
        ("1", "A", "REIT"), ("2", "B", "GENERAL")]
    conn.execute("UPDATE companies SET sector_profile = 'NIEZNANY' WHERE cik = '2'")
    conn.commit()
    init_db(path)  # idempotentnie
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE companies SET sector_profile = 'COS_INNEGO' WHERE cik = '1'")


# --- 13. SIC point-in-time w backteście -------------------------------------------

from types import SimpleNamespace  # noqa: E402

from buffett_scanner.db import get_sector_profile_history, replace_sector_profile_history  # noqa: E402
from buffett_scanner.sic_history import PointInTimeProfiles, fetch_sic_history  # noqa: E402

_HDR = "<SEC-HEADER>\n<FILER>\n<COMPANY-DATA>\n<CIK>{cik:010d}\n<ASSIGNED-SIC>{sic}\n</COMPANY-DATA>\n</FILER>"


def _h(date, sic, status="OK"):
    return {"filing_date": date, "sic": sic, "status": status, "accession": f"a-{date}", "form": "10-K"}


def test_profile_as_of_decision_date_never_uses_later_sic():
    """EQIX: SIC 4813 w nagłówkach do 2015, 6798 od 2016-02-26 (diagnostyka 2026-10-24)."""
    pit = PointInTimeProfiles({"1101239": [_h("2011-02-25", "4813"), _h("2015-02-27", "4813"),
                                           _h("2016-02-26", "6798")]})
    assert pit.profile_at("0001101239", "2011-01-01") == "NIEZNANY"  # brak nagłówka sprzed daty
    assert pit.profile_at("1101239", "2015-12-01") == "GENERAL"
    assert pit.profile_at("1101239", "2016-02-26") == "REIT"
    assert pit.profile_at("999", "2016-03-01") == "NIEZNANY"  # brak historii (np. błąd SEC)


def test_header_without_sic_falls_back_to_previous_header_not_to_current_sic():
    pit = PointInTimeProfiles({"1": [_h("2012-02-01", "6022"), _h("2013-02-01", None, "BRAK_SIC_W_NAGLOWKU")]})
    assert pit.profile_at("1", "2013-06-01") == "BANK"


class _HistorySec:
    calls: list = []

    def __init__(self, *a, **kw):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_submissions_pages(self, cik, *, filed_from):
        if cik == "111":
            raise SecEdgarError("503")
        recent = {"form": ["10-K", "10-K", "10-K/A", "8-K"], "accessionNumber": ["x1", "x2", "x3", "x4"],
                  "filingDate": ["2008-03-01", "2016-02-26", "2016-05-01", "2016-06-01"]}
        older = {"form": ["10-K"], "accessionNumber": ["x0"], "filingDate": ["2011-02-25"]}
        return [{"filings": {"recent": recent}}, older], []

    def get_filing_header(self, cik, accession):
        self.calls.append(accession)
        sic = {"x0": 4813, "x2": 6798}[accession]
        return _HDR.format(cik=int(cik), sic=sic), ".hdr.sgml"


def test_fetch_sic_history_reads_annual_headers_from_all_pages_since_cutoff():
    rows, errors = fetch_sic_history(_HistorySec(), "333", filed_from="2009-01-01")
    assert [(r["accession"], r["sic"], r["status"]) for r in rows] == [("x0", "4813", "OK"), ("x2", "6798", "OK")]
    assert errors == []


def test_build_history_command_and_backtest_resolver(tmp_path, monkeypatch, capsys):
    path = tmp_path / "bt.db"
    conn = init_db(path)
    for cik in ("111", "333"):
        upsert_company(conn, cik=cik, name=cik)
        upsert_universe_membership(conn, cik=cik, index_name=cli.UNIVERSE_MEMBERSHIP_INDEX_NAME,
                                   start_date="2012-01-01", source="test", source_snapshot_ref="test",
                                   cik_resolution_method="DIRECT")
    conn.commit()
    monkeypatch.setenv("SEC_EDGAR_USER_AGENT", "Test test@example.com")
    monkeypatch.setattr(cli, "SecEdgarClient", _HistorySec)
    assert cli.main(["--db", str(path), "build-sector-profile-history"]) == 0
    out = capsys.readouterr().out
    assert "BŁĘDY SEC: 1 CIK: ['111']" in out
    history = get_sector_profile_history(connect(path))
    assert [r["sic"] for r in sorted(history["333"], key=lambda r: r["filing_date"])] == ["4813", "6798"]
    resolve, label = cli._backtest_profile_resolver(connect(path), "point-in-time")
    assert "point-in-time" in label
    assert (resolve("333", "2015-01-01"), resolve("333", "2016-03-01"), resolve("111", "2016-03-01")) == (
        "GENERAL", "REIT", "NIEZNANY")


def test_backtest_without_history_refuses_point_in_time_instead_of_using_current_sic(tmp_path):
    path = tmp_path / "bt.db"
    init_db(path).close()
    with pytest.raises(SystemExit, match="build-sector-profile-history"):
        cli.main(["--db", str(path), "run-calibration-candidate", "--round", "1", "--candidate", "baseline"])


def test_calibration_uses_profile_as_of_each_date_and_excludes_unknown(tmp_path, monkeypatch, capsys):
    path = tmp_path / "bt.db"
    conn = init_db(path)
    upsert_company(conn, cik="333", name="Tower Co")
    upsert_universe_membership(conn, cik="333", index_name=cli.UNIVERSE_MEMBERSHIP_INDEX_NAME,
                               start_date="2012-01-01", source="test", source_snapshot_ref="test",
                               cik_resolution_method="DIRECT")
    replace_sector_profile_history(conn, cik="333", rows=[_h("2014-02-20", "4899"), _h("2016-02-26", "6798")])
    conn.commit()
    seen = []

    def fake_eval(**kw):
        seen.append((kw["decision_date"], kw["sector_profile"]))
        return SimpleNamespace(stage="NO_DECLINE_SIGNAL", candidate=None)

    monkeypatch.setattr(cli, "get_sec_company_facts_cache", lambda conn, cik: {})
    monkeypatch.setattr(cli, "build_annual_fundamentals_periods_as_of", lambda cf, d: [])
    monkeypatch.setattr(cli, "classify_data_sufficiency", lambda bars, periods: (True, True))
    monkeypatch.setattr(cli, "evaluate_candidate_at_date", fake_eval)
    assert cli.main(["--db", str(path), "run-calibration-candidate", "--round", "1", "--candidate", "baseline"]) == 0
    out = capsys.readouterr().out
    profiles = dict(seen)
    assert "2014-01-01" not in profiles                      # przed pierwszym nagłówkiem -> NIEZNANY, poza oceną
    assert profiles["2015-01-01"] == "GENERAL" and profiles["2016-03-01"] == "REIT"
    assert "Profil sektorowy: SIC point-in-time" in out
    assert "profil NIEZNANY" in out and "333 (26)" in out    # 2012-01..2014-02: 26 dat przed nagłówkiem z 2014-02-20


# --- 7. Dywidendy uprzywilejowane przypisane do akcji zwykłych ------------------------

from buffett_scanner.dividend_verification import (  # noqa: E402
    DIV_NO_PREFERRED,
    DIV_SEC_COMMON,
    DIV_SEC_DERIVED,
    DIV_UNKNOWN,
    resolve_common_dividends,
    verify_with_sec,
)
from buffett_scanner.pit_fundamentals import build_annual_fundamentals_periods_as_of  # noqa: E402


def _fact(end, val, *, start=True, filed=None):
    f = {"end": end, "val": val, "filed": filed or f"{int(end[:4]) + 1}-02-15", "form": "10-K",
         "fy": int(end[:4]), "fp": "FY", "accn": "x"}
    if start:
        import datetime as _dt
        f["start"] = (_dt.date.fromisoformat(end) - _dt.timedelta(days=364)).isoformat()
    return f


def _facts(**tags):
    return {"facts": {"us-gaap": {tag: {"units": {"USD": entries}} for tag, entries in tags.items()}}}


def test_ba_preferred_dividend_reported_as_common_becomes_unknown():
    """BA FY2025: FMP common 331 mln, SEC tylko suma 331 mln, brak tagu akcji
    zwykłych i uprzywilejowanych; emisja uprzywilejowanych 2024 (ślad z FMP)."""
    facts = _facts(PaymentsOfDividends=[_fact("2025-12-31", 331e6)])
    value, state, why = verify_with_sec(reported=331e6, facts=facts, period_end="2025-12-31", as_of="2026-10-22",
                                        source_preferred_evidence=True)
    assert (value, state) == (None, DIV_UNKNOWN) and "nieznane" in why


def test_avgo_total_including_preferred_is_corrected_to_sec_common():
    facts = _facts(PaymentsOfDividendsCommonStock=[_fact("2021-10-31", 5913e6)],
                   PaymentsOfDividendsPreferredStockAndPreferenceStock=[_fact("2021-10-31", 299e6)])
    value, state, why = verify_with_sec(reported=6212e6, facts=facts, period_end="2021-10-31", as_of="2026-10-22")
    assert (value, state) == (5913e6, DIV_SEC_COMMON) and "skorygowane" in why


def test_total_minus_preferred_and_no_preferred_cases():
    assert resolve_common_dividends(reported=1000.0, preferred_evidence=True, sec_common=None, sec_total=1000.0,
                                    sec_preferred=60.0)[:2] == (940.0, DIV_SEC_DERIVED)
    assert resolve_common_dividends(reported=1000.0, preferred_evidence=False, sec_common=None, sec_total=None,
                                    sec_preferred=None)[:2] == (1000.0, DIV_NO_PREFERRED)
    assert resolve_common_dividends(reported=0.0, preferred_evidence=True, sec_common=None, sec_total=None,
                                    sec_preferred=None)[0] == 0.0  # brak wypłaty: nic do weryfikacji


def test_sec_facts_filed_after_session_are_not_used():
    facts = _facts(PaymentsOfDividendsCommonStock=[_fact("2025-12-31", 5e6, filed="2026-11-01")])
    assert verify_with_sec(reported=7e6, facts=facts, period_end="2025-12-31", as_of="2026-10-22",
                           source_preferred_evidence=True)[1] == DIV_UNKNOWN


def _annual(tag, values):
    return [_fact(end, v) for end, v in values.items()]


def test_backtest_total_dividend_tag_is_split_when_preferred_dividends_are_tagged():
    ends = {"2022-12-31": 1.0, "2023-12-31": 1.0}
    facts = _facts(
        NetIncomeLoss=_annual("n", {e: 100.0 for e in ends}),
        PaymentsOfDividends=_annual("d", {"2022-12-31": 50.0, "2023-12-31": 55.0}),
        DividendsPreferredStock=_annual("p", {"2023-12-31": 5.0}),
    )
    periods = build_annual_fundamentals_periods_as_of(facts, "2025-01-01")
    assert [p.dividends_paid for p in periods] == [50.0, 50.0]  # 2022 bez śladów; 2023: 55 - 5


def test_backtest_total_dividend_with_preferred_stock_but_no_split_is_unknown():
    facts = _facts(
        NetIncomeLoss=_annual("n", {"2023-12-31": 100.0}),
        PaymentsOfDividends=_annual("d", {"2023-12-31": 55.0}),
        PreferredStockValue=[_fact("2023-12-31", 1000.0, start=False)],
    )
    assert build_annual_fundamentals_periods_as_of(facts, "2025-01-01")[0].dividends_paid is None


def test_backtest_common_dividend_tag_is_used_as_is():
    facts = _facts(
        NetIncomeLoss=_annual("n", {"2023-12-31": 100.0}),
        PaymentsOfDividendsCommonStock=_annual("d", {"2023-12-31": 55.0}),
        DividendsPreferredStock=_annual("p", {"2023-12-31": 5.0}),
    )
    assert build_annual_fundamentals_periods_as_of(facts, "2025-01-01")[0].dividends_paid == 55.0


class _PreferredFMP(g._SessionConsistentFMP):
    """FMP: są wypłaty dywidend uprzywilejowanych, więc `commonDividendsPaid`
    może zawierać część uprzywilejowaną (jak BA)."""

    def get_cash_flow_statement(self, symbol):
        rows = super().get_cash_flow_statement(symbol)
        return [{**r, "preferredDividendsPaid": -3.0 if i == 0 else 0} for i, r in enumerate(rows)]


class _IssuanceOnlyFMP(g._SessionConsistentFMP):
    """QCOM 23.10: jedynym „śladem” jest emisja akcji uprzywilejowanych w FMP."""

    def get_cash_flow_statement(self, symbol):
        rows = super().get_cash_flow_statement(symbol)
        return [{**r, "preferredDividendsPaid": 0, "netPreferredStockIssuance": -955.0 if i == 0 else 0}
                for i, r in enumerate(rows)]


def test_live_scan_fmp_preferred_issuance_alone_keeps_fmp_dividends(tmp_path, monkeypatch, capsys):
    g._setup(monkeypatch, _IssuanceOnlyFMP)
    code, db, dq = g._scan(tmp_path, "--session-date", g.SESSION)
    capsys.readouterr()
    assert code == 0
    values = [r[0] for r in connect(db).execute(
        "SELECT value FROM fundamentals_raw WHERE line_item = 'dividends_paid' ORDER BY period_end_date")]
    assert values == [10.0, 12.0] and dq["dividend_unknown"] == []


def test_live_scan_unconfirmed_common_dividends_are_unknown_reported_and_do_not_stop_scan(
        tmp_path, monkeypatch, capsys):
    g._setup(monkeypatch, _PreferredFMP)
    code, db, dq = g._scan(tmp_path, "--session-date", g.SESSION)
    capsys.readouterr()
    assert code == 0  # nie zatrzymuje skanu
    values = [r[0] for r in connect(db).execute(
        "SELECT value FROM fundamentals_raw WHERE line_item = 'dividends_paid' ORDER BY period_end_date")]
    assert values == [None, None]  # SEC (atrapa: brak faktów) nie potwierdza wypłat na akcje zwykłe
    assert dq["dividend_unknown"] == ["AAPL"]
    assert all(v.startswith(DIV_UNKNOWN) for v in dq["dividend_checks"]["AAPL"].values())


def test_live_scan_without_preferred_traces_keeps_fmp_dividends(tmp_path, monkeypatch, capsys):
    g._setup(monkeypatch)
    code, db, dq = g._scan(tmp_path, "--session-date", g.SESSION)
    capsys.readouterr()
    assert code == 0
    values = [r[0] for r in connect(db).execute(
        "SELECT value FROM fundamentals_raw WHERE line_item = 'dividends_paid' ORDER BY period_end_date")]
    assert values == [10.0, 12.0] and dq["dividend_checks"] == {}


# --- Kwalifikacja (decyzje 1, 3, 4, 5) -- moduł niepodłączony do skanu -------------------

from buffett_scanner import qualification as q  # noqa: E402


def _p(fy, *, ocf=100.0, capex=10.0, ni=50.0, ebitda=80.0, debt=50.0, cash=20.0):
    return make_period(f"FY{fy}", operating_cash_flow=ocf, capital_expenditure=capex, net_income=ni, ebitda=ebitda,
                       total_debt=debt, cash_and_equivalents=cash, revenue=500.0)


def _three(**last):
    return [_p(2023), _p(2024), _p(2025, **last)]


def test_core_solvency_passes_and_dcf_needs_mos():
    kw = dict(sic="3571", leverage_threshold=2.0, min_margin_of_safety_pct=0.0)
    assert q.qualify(group="Z_DCF", periods=_three(), margin_of_safety_base_pct=12.0, **kw).status == q.QUALIFIED
    assert q.qualify(group="Z_DCF", periods=_three(), margin_of_safety_base_pct=0.0, **kw).status == q.QUALIFIED
    not_cheap = q.qualify(group="Z_DCF", periods=_three(), margin_of_safety_base_pct=-0.1, **kw)
    assert not_cheap.status == q.NOT_QUALIFIED and "MoS BASE" in not_cheap.reasons[0]


def test_company_without_dcf_is_qualitative_only_with_explicit_label():
    r = q.qualify(group="BEZ_DCF", periods=_three(), margin_of_safety_base_pct=None, sic="7372",
                  leverage_threshold=2.0, min_margin_of_safety_pct=0.0)
    assert r.status == q.QUALIFIED_NO_PRICE and r.label == "jakość bez potwierdzonej ceny"


def test_negative_ebitda_with_debt_goes_to_manual_review_not_silent_rejection():
    """F 2025: EBITDA ujemna przez odpisy, przepływ operacyjny 21 mld."""
    r = q.qualify(group="Z_DCF", periods=_three(ebitda=-4.58, debt=167.6, cash=23.4), margin_of_safety_base_pct=63.0,
                  sic="3711", leverage_threshold=2.0, min_margin_of_safety_pct=0.0)
    assert r.status == q.MANUAL_REVIEW
    assert "dług netto przy EBITDA <= 0" in r.reasons and any("odpisy" in x for x in r.reasons)


def test_negative_fcf_with_profits_goes_to_manual_review():
    periods = [_p(2023, ocf=-5.3, capex=2.4), _p(2024, ocf=-2.5, capex=2.6), _p(2025, ocf=4.2, capex=3.0)]
    r = q.qualify(group="BEZ_DCF", periods=periods, margin_of_safety_base_pct=None, sic="4911",
                  leverage_threshold=2.0, min_margin_of_safety_pct=0.0)
    assert r.status == q.MANUAL_REVIEW and any("klasyfikacji przepływów" in x for x in r.reasons)


def test_negative_fcf_from_heavy_capex_is_a_separate_review_reason():
    periods = [_p(2023, ocf=10.0, capex=15.0), _p(2024, ocf=12.0, capex=20.0), _p(2025, ocf=14.0, capex=30.0)]
    r = q.qualify(group="BEZ_DCF", periods=periods, margin_of_safety_base_pct=None, sic="4931",
                  leverage_threshold=2.0, min_margin_of_safety_pct=0.0)
    assert r.status == q.MANUAL_REVIEW and any("CAPEX > przepływ operacyjny" in x for x in r.reasons)


def test_ordinary_failures_are_not_qualified_with_reasons():
    r = q.qualify(group="Z_DCF", periods=_three(debt=500.0, cash=10.0), margin_of_safety_base_pct=80.0,
                  sic="3714", leverage_threshold=2.0, min_margin_of_safety_pct=0.0)
    assert r.status == q.NOT_QUALIFIED and r.reasons == ["dług netto/EBITDA 6.12 > 2"]
    losses = [_p(2023, ni=-1.0), _p(2024, ni=-2.0), _p(2025, ni=11.0)]
    r = q.qualify(group="Z_DCF", periods=losses, margin_of_safety_base_pct=70.0, sic="3572",
                  leverage_threshold=2.0, min_margin_of_safety_pct=0.0)
    assert r.reasons == ["zysk netto > 0 w mniej niż 2 z 3 lat"]


def test_financial_services_and_real_estate_failures_go_to_manual_review():
    kw = dict(margin_of_safety_base_pct=None, leverage_threshold=2.0, min_margin_of_safety_pct=0.0)
    ares = q.qualify(group="BEZ_DCF", periods=_three(debt=500.0, cash=10.0), sic="6282", **kw)
    cbre = q.qualify(group="Z_DCF", periods=_three(debt=500.0, cash=10.0), sic="6500", **kw)
    assert ares.status == q.MANUAL_REVIEW and any("usługi finansowe" in x for x in ares.reasons)
    assert cbre.status == q.MANUAL_REVIEW and any("SIC 6500" in x for x in cbre.reasons)


def test_groups_without_method_or_with_incomplete_data_are_never_qualified():
    kw = dict(periods=_three(), margin_of_safety_base_pct=90.0, sic="6311", leverage_threshold=2.0,
              min_margin_of_safety_pct=0.0)
    assert q.qualify(group="BEZ_METODY", **kw).status == q.NO_METHOD
    assert q.qualify(group="NIEKOMPLETNE", **kw).status == q.INCOMPLETE


def test_call_limit_stops_instead_of_truncating():
    assert q.worst_case_calls(45, 2) == 135
    assert q.within_call_limit(25, max_calls=75, max_repair_attempts=2)
    assert not q.within_call_limit(26, max_calls=75, max_repair_attempts=2)


# --- 2026-10-25: przyczyny z diagnostyki skanu 23.10 (run 40180283457) ----------------

def _instant(end, val):
    return {"end": end, "val": val, "filed": f"{int(end[:4]) + 1}-02-15", "form": "10-K",
            "fy": int(end[:4]), "fp": "FY", "accn": "x"}


def test_qcom_without_preferred_dividends_or_sec_balance_keeps_fmp_amount():
    """QCOM FY2023: jedynym „śladem” była emisja z FMP (-955 mln, pole błędne;
    SEC PreferredStockValue = 0). Bez wypłat dywidend uprzywilejowanych i bez
    salda w SEC -> brak akcji uprzywilejowanych, kwota z FMP bez zmian."""
    facts = _facts(PreferredStockValue=[_instant("2023-09-24", 0)])
    value, state, _ = verify_with_sec(reported=3462e6, facts=facts, period_end="2023-09-30", as_of="2026-10-23")
    assert (value, state) == (3462e6, DIV_NO_PREFERRED)


def test_ba_preferred_dividends_in_sec_remain_evidence():
    """BA FY2025 (przypadek, od którego zaczęła się kontrola): SEC
    DividendsPreferredStockCash 345 mln -> nadal NIEZNANE bez śladu z FMP."""
    facts = _facts(PaymentsOfDividends=[_fact("2025-12-31", 331e6)],
                   DividendsPreferredStockCash=[_fact("2025-12-31", 345e6)])
    assert verify_with_sec(reported=331e6, facts=facts, period_end="2025-12-31",
                           as_of="2026-10-23")[1] == DIV_UNKNOWN


def test_crh_declared_dividends_never_replace_cash_paid():
    """CRH: SEC ma tylko zadeklarowane dywidendy (DividendsCommonStock 2024 = 956 mln),
    FMP wypłacone 1706 mln; akcje uprzywilejowane istnieją (1 mln). Zadeklarowane nie
    zastępują wypłaconych (wcześniej: 956, przesunięcie między latami) -> NIEZNANE."""
    facts = _facts(DividendsCommonStock=[_fact("2024-12-31", 956e6)],
                   DividendsPreferredStock=[_fact("2024-12-31", 1e6)],
                   PreferredStockValue=[_instant("2024-12-31", 1e6)])
    value, state, _ = verify_with_sec(reported=1706e6, facts=facts, period_end="2024-12-31", as_of="2026-10-23")
    assert (value, state) == (None, DIV_UNKNOWN)

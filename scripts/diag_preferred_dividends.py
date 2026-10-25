"""Diagnostyka kontroli dywidend uprzywilejowanych (zgoda właścicielki
2026-10-25). SEC companyfacts + FMP cash flow (w abonamencie), baza skanu
live-scan-2026-10-24T220005090685Z (tylko odczyt). Bez Claude.

Dla każdej spółki i okresu: surowe pola FMP, fakty SEC wszystkich tagów
używanych przez `dividend_verification`, który warunek dał „ślad akcji
uprzywilejowanych” i jaki stan wyszedł -- tak samo jak w skanie.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from buffett_scanner import dividend_verification as dv  # noqa: E402
from buffett_scanner.point_in_time import extract_fact_history  # noqa: E402

TICKERS = ("QCOM", "JBL", "CHRW", "DPZ", "SBAC", "ARES", "BA", "COHR", "GE", "SKYD",
           "CRH", "APO", "AVGO", "BE", "GLW", "KKR", "MPWR", "PCG", "ROL")
FMP_FIELDS = ("date", "fiscalYear", "period", "filingDate", "commonDividendsPaid", "preferredDividendsPaid",
              "netDividendsPaid", "netPreferredStockIssuance", "netCommonStockIssuance")
SEC_TAGS = (dv.COMMON_DIVIDEND_TAGS + (dv.TOTAL_DIVIDEND_TAG,) + dv.PREFERRED_DIVIDEND_TAGS
            + dv.PREFERRED_STOCK_INSTANT_TAGS)


def _facts_dump(facts: dict | None, since: str) -> dict:
    out = {}
    for tag in SEC_TAGS:
        rows = [
            {"start": f.start, "end": f.end, "val": f.val, "form": f.form, "fy": f.fiscal_year,
             "fp": f.fiscal_period, "filed": f.filed, "accn": f.accession_number}
            for f in extract_fact_history(facts or {}, tag) if f.end >= since
        ]
        if rows:
            out[tag] = rows
    taxonomies = sorted((facts or {}).get("facts", {}).keys())
    return {"taxonomies": taxonomies, "tags": out}


def diagnose(conn, facts_by_ticker: dict, fmp_by_ticker: dict, run_date: str) -> list[dict]:
    """Odtworzenie decyzji `_verify_common_dividends` per okres, z przyczyną śladu."""
    results = []
    for ticker in TICKERS:
        row = conn.execute("SELECT cik FROM live_scan_candidates WHERE ticker = ?", (ticker,)).fetchone()
        if row is None:
            results.append({"ticker": ticker, "error": "brak w skanie"})
            continue
        cik = row[0]
        facts = facts_by_ticker.get(ticker)
        db_rows = conn.execute(
            "SELECT fiscal_period, period_end_date, line_item, value FROM fundamentals_raw WHERE cik = ? "
            "AND line_item IN ('dividends_paid', 'preferred_dividends_paid', 'preferred_stock_issuance_net') "
            "ORDER BY period_end_date, line_item", (cik,),
        ).fetchall()
        fmp = {str(r.get("date"))[:10]: r for r in fmp_by_ticker.get(ticker, [])}
        periods = []
        for fiscal_period, end in sorted({(r[0], r[1]) for r in db_rows}, key=lambda x: x[1]):
            fmp_row = fmp.get(end, {})
            reported = abs(fmp_row["commonDividendsPaid"]) if fmp_row.get("commonDividendsPaid") else (
                0.0 if fmp_row.get("commonDividendsPaid") == 0 else None)
            fmp_pref = [(r[1], r[2], r[3]) for r in db_rows
                        if r[2] != "dividends_paid" and r[3] not in (None, 0) and r[1] <= end]
            sec_pref_div = dv.sec_annual_tag_value(facts, dv.PREFERRED_DIVIDEND_TAGS, end, run_date)
            sec_stock = dv.sec_preferred_stock_present(facts, end, run_date)
            value, state, why = (None, "BRAK_FMP", "") if reported is None else dv.verify_with_sec(
                reported=reported, facts=facts, period_end=end, as_of=run_date,
                source_preferred_evidence=bool(fmp_pref),
            )
            periods.append({
                "fiscal_period": fiscal_period, "period_end": end,
                "fmp_raw": {k: fmp_row.get(k) for k in FMP_FIELDS},
                "db_after_scan": {r[2]: r[3] for r in db_rows if r[0] == fiscal_period},
                "evidence": {
                    "fmp_preferred_rows_up_to_period": fmp_pref,
                    "sec_preferred_dividends": sec_pref_div,
                    "sec_preferred_stock_value_gt_0": sec_stock,
                },
                "sec_common": dv.sec_annual_tag_value(facts, dv.COMMON_DIVIDEND_TAGS, end, run_date),
                "sec_total": dv.sec_annual_tag_value(facts, (dv.TOTAL_DIVIDEND_TAG,), end, run_date),
                "result": {"value": value, "state": state, "why": why},
            })
        results.append({"ticker": ticker, "cik": cik, "periods": periods,
                        "sec_facts": _facts_dump(facts, "2020-01-01")})
    return results


def _print_summary(results: list[dict]) -> None:
    for r in results:
        if "error" in r:
            print(f"== {r['ticker']}: {r['error']}")
            continue
        print(f"== {r['ticker']} (CIK {r['cik']}) taksonomie SEC: {r['sec_facts']['taxonomies']}")
        for tag, rows in r["sec_facts"]["tags"].items():
            annual = [x for x in rows if x["start"] is None or x["fp"] == "FY" or x["form"] in ("10-K", "20-F")]
            print(f"   SEC {tag}: " + "; ".join(
                f"{x['start'] or ''}..{x['end']}={x['val']:,.0f} ({x['form']} {x['filed']})" for x in annual[-12:]))
        for p in r["periods"]:
            e = p["evidence"]
            f = p["fmp_raw"]
            print(f"   {p['fiscal_period']} {p['period_end']}: FMP common={f.get('commonDividendsPaid')} "
                  f"pref={f.get('preferredDividendsPaid')} netPrefIssuance={f.get('netPreferredStockIssuance')} "
                  f"| ślad: FMP={e['fmp_preferred_rows_up_to_period']} SECprefDiv={e['sec_preferred_dividends']} "
                  f"SECprefStock>0={e['sec_preferred_stock_value_gt_0']} | SEC common={p['sec_common']} "
                  f"total={p['sec_total']} -> {p['result']['state']} {p['result']['value']}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scan-db", required=True)
    ap.add_argument("--run-date", default="2026-10-23")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    if os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit("STOP: diagnostyka nie może mieć dostępu do Claude API.")

    from buffett_scanner.providers.fmp import FMPClient
    from buffett_scanner.providers.sec_edgar import SecEdgarClient

    conn = sqlite3.connect(f"file:{args.scan_db}?mode=ro", uri=True)
    facts_by_ticker, fmp_by_ticker = {}, {}
    with SecEdgarClient(os.environ["SEC_EDGAR_USER_AGENT"]) as sec, FMPClient(os.environ["FMP_API_KEY"]) as fmp:
        for ticker in TICKERS:
            row = conn.execute("SELECT cik FROM live_scan_candidates WHERE ticker = ?", (ticker,)).fetchone()
            if row is None:
                continue
            facts_by_ticker[ticker] = sec.get_company_facts(row[0])
            fmp_by_ticker[ticker] = fmp.get_cash_flow_statement(ticker, period="annual", limit=6)
    results = diagnose(conn, facts_by_ticker, fmp_by_ticker, args.run_date)
    Path(args.out).write_text(json.dumps(results, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    _print_summary(results)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

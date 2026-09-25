"""CLI — Faza 0 + Faza 1 + Faza 2 + Faza 3 + Faza 4.

    python -m buffett_scanner.cli init-db
    python -m buffett_scanner.cli ingest-universe
    python -m buffett_scanner.cli ingest-prices AAPL MSFT ... [--days 400]
    python -m buffett_scanner.cli scan AAPL MSFT ...
    python -m buffett_scanner.cli ingest-fundamentals AAPL MSFT ...
    python -m buffett_scanner.cli prefilter AAPL MSFT ...
    python -m buffett_scanner.cli build-source-packet AAPL MSFT ...
    python -m buffett_scanner.cli analyze AAPL MSFT ...
    python -m buffett_scanner.cli score AAPL MSFT ... [--markdown-out DIR]

Bez dopracowanego UI — zgodnie z Fazą 0 ("NO polished dashboard
required. Goal: prove that the analysis pipeline works.").
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

from buffett_scanner.analysis_schema import AnalysisOutput, AnalysisValidationError, validate_analysis_output
from buffett_scanner.config import load_config
from buffett_scanner.db import (
    get_fundamentals_periods,
    get_price_series,
    init_db,
    insert_analysis,
    insert_analysis_sources,
    insert_fundamentals_rows,
    insert_price_rows,
    upsert_company,
    upsert_derived_metric,
    upsert_scoring_model_version,
    upsert_ticker_history,
)
from buffett_scanner.fundamentals import compute_metrics, evaluate_prefilter
from buffett_scanner.prompt import build_analysis_prompt
from buffett_scanner.providers.claude import ClaudeClient, ClaudeError
from buffett_scanner.providers.fmp import FMPClient, FMPError, normalize_fundamentals_rows
from buffett_scanner.providers.sec_edgar import SecEdgarClient
from buffett_scanner.report import render_markdown_report
from buffett_scanner.scanner import PriceBar, compute_price_changes, evaluate_decline_flags
from buffett_scanner.scoring import compute_score
from buffett_scanner.sources import VerifiedSource, build_sec_source_packet

DEFAULT_DB_PATH = "buffett_scanner.db"
PREFILTER_CALC_VERSION = "0.1.0-phase1"


def cmd_init_db(args: argparse.Namespace) -> int:
    init_db(args.db)
    print(f"Baza zainicjalizowana: {args.db}")
    return 0


def cmd_ingest_universe(args: argparse.Namespace) -> int:
    config = load_config()
    api_key = config.data_provider.resolve_api_key()
    conn = init_db(args.db)
    today = dt.date.today().isoformat()

    with FMPClient(api_key) as client:
        try:
            constituents = client.get_sp500_constituents()
        except FMPError as exc:
            print(f"BŁĄD pobierania uniwersum: {exc}", file=sys.stderr)
            return 1

    n = 0
    for row in constituents:
        cik = row.get("cik")
        symbol = row.get("symbol")
        name = row.get("name")
        if not cik or not symbol or not name:
            print(f"POMINIĘTO (brak cik/symbol/name): {row}", file=sys.stderr)
            continue
        upsert_company(
            conn,
            cik=cik,
            name=name,
            sector=row.get("sector"),
            sub_industry=row.get("subSector"),
        )
        upsert_ticker_history(conn, cik=cik, ticker=symbol, start_date=today)
        n += 1
    conn.commit()
    print(f"Zaingestowano {n} spółek do companies/ticker_history.")
    return 0


def _resolve_cik(conn, ticker: str) -> str | None:
    row = conn.execute(
        "SELECT cik FROM ticker_history WHERE ticker = ? AND end_date IS NULL",
        (ticker,),
    ).fetchone()
    return row["cik"] if row else None


def cmd_ingest_prices(args: argparse.Namespace) -> int:
    config = load_config()
    api_key = config.data_provider.resolve_api_key()
    conn = init_db(args.db)

    to_date = dt.date.today()
    from_date = to_date - dt.timedelta(days=args.days)

    with FMPClient(api_key) as client:
        for ticker in args.tickers:
            cik = _resolve_cik(conn, ticker)
            if cik is None:
                # spółka spoza uniwersum (np. ticker testowy) — pobierz profil,
                # żeby mieć CIK, i zarejestruj ją minimalnie
                try:
                    profile = client.get_company_profile(ticker)
                except FMPError as exc:
                    print(f"POMINIĘTO {ticker}: {exc}", file=sys.stderr)
                    continue
                cik = profile.get("cik")
                if not cik:
                    print(f"POMINIĘTO {ticker}: profil FMP nie zawiera CIK.", file=sys.stderr)
                    continue
                upsert_company(
                    conn,
                    cik=cik,
                    name=profile.get("companyName", ticker),
                    sector=profile.get("sector"),
                    industry=profile.get("industry"),
                )
                upsert_ticker_history(conn, cik=cik, ticker=ticker, start_date=to_date.isoformat())

            try:
                rows = client.get_historical_prices(
                    ticker, from_date=from_date.isoformat(), to_date=to_date.isoformat()
                )
            except FMPError as exc:
                print(f"BŁĄD pobierania cen dla {ticker}: {exc}", file=sys.stderr)
                continue
            n = insert_price_rows(conn, cik, source="fmp", rows=rows)
            conn.commit()
            print(f"{ticker} ({cik}): zapisano {n} sesji.")
    return 0


def cmd_scan(args: argparse.Namespace) -> int:
    config = load_config()
    conn = init_db(args.db)
    thresholds = config.decline_scanner.thresholds

    for ticker in args.tickers:
        cik = _resolve_cik(conn, ticker)
        if cik is None:
            print(f"{ticker}: brak w bazie (uruchom najpierw ingest-prices).")
            continue
        rows = get_price_series(conn, cik)
        if not rows:
            print(f"{ticker}: brak danych cenowych.")
            continue
        bars = [
            PriceBar(
                date=r["date"],
                open=r["open"],
                high=r["high"],
                low=r["low"],
                close=r["close"],
                adj_close=r["adj_close"],
                volume=r["volume"],
            )
            for r in rows
        ]
        snapshot = compute_price_changes(bars)
        flags = evaluate_decline_flags(snapshot, thresholds)
        print(f"\n{ticker} ({cik}) — {snapshot.as_of_date}")
        print(f"  daily={snapshot.daily_pct}  week={snapshot.week_pct}  "
              f"month={snapshot.month_pct}  quarter={snapshot.quarter_pct}")
        print(f"  ytd={snapshot.ytd_pct}  year={snapshot.year_pct}  "
              f"drawdown_52w={snapshot.drawdown_from_52w_high_pct}  "
              f"rel_volume={snapshot.relative_volume}")
        triggered = [k for k, v in flags.items() if v]
        status = ", ".join(triggered) if triggered else "brak przekroczonych progów"
        print(f"  progi (UNCALIBRATED — patrz Faza 5): {status}")
    return 0


def cmd_ingest_fundamentals(args: argparse.Namespace) -> int:
    config = load_config()
    api_key = config.data_provider.resolve_api_key()
    conn = init_db(args.db)

    with FMPClient(api_key) as client:
        for ticker in args.tickers:
            cik = _resolve_cik(conn, ticker)
            if cik is None:
                print(
                    f"POMINIĘTO {ticker}: brak w bazie "
                    "(uruchom najpierw ingest-prices, które rejestruje CIK).",
                    file=sys.stderr,
                )
                continue
            try:
                income = client.get_income_statement(ticker)
                balance = client.get_balance_sheet_statement(ticker)
                cashflow = client.get_cash_flow_statement(ticker)
            except FMPError as exc:
                print(f"BŁĄD pobierania fundamentów dla {ticker}: {exc}", file=sys.stderr)
                continue
            rows = normalize_fundamentals_rows(income, balance, cashflow)
            if not rows:
                print(f"{ticker} ({cik}): 0 wierszy fundamentalnych (nieoczekiwany kształt odpowiedzi?)")
                continue
            n = insert_fundamentals_rows(conn, cik, source="fmp", rows=rows)
            conn.commit()
            print(f"{ticker} ({cik}): zapisano {n} wierszy fundamentals_raw.")
    return 0


def cmd_prefilter(args: argparse.Namespace) -> int:
    config = load_config()
    conn = init_db(args.db)

    for ticker in args.tickers:
        cik = _resolve_cik(conn, ticker)
        if cik is None:
            print(f"{ticker}: brak w bazie (uruchom najpierw ingest-prices).")
            continue
        periods = get_fundamentals_periods(conn, cik)
        if not periods:
            print(f"{ticker}: brak danych fundamentalnych (uruchom najpierw ingest-fundamentals).")
            continue
        metrics = compute_metrics(periods)
        as_of_date = periods[-1].period_end_date
        for metric_name, value in metrics.items():
            upsert_derived_metric(
                conn, cik=cik, as_of_date=as_of_date, metric_name=metric_name,
                value=value, calc_version=PREFILTER_CALC_VERSION,
            )
        conn.commit()

        result = evaluate_prefilter(metrics, config.prefilter)
        print(f"\n{ticker} ({cik}) — okres {periods[-1].fiscal_period} ({as_of_date})")
        print(f"  metryki: {metrics}")
        if result.excludes:
            print(f"  EXCLUDE: {result.excludes}")
        elif result.flags:
            print(f"  FLAG (nie blokuje — patrz BLOCKER 5): {result.flags}")
        else:
            print("  brak przekroczonych progów prefiltra (UNCALIBRATED — patrz Faza 5)")
    return 0


def cmd_build_source_packet(args: argparse.Namespace) -> int:
    config = load_config()
    user_agent = config.sources.sec_edgar.resolve_user_agent()
    conn = init_db(args.db)
    forms = tuple(f.strip() for f in args.forms.split(","))

    with SecEdgarClient(user_agent) as client:
        for ticker in args.tickers:
            cik = _resolve_cik(conn, ticker)
            if cik is None:
                print(f"{ticker}: brak w bazie (uruchom najpierw ingest-prices).")
                continue
            row = conn.execute("SELECT name FROM companies WHERE cik = ?", (cik,)).fetchone()
            issuer = row["name"] if row else ticker
            packet = build_sec_source_packet(
                client, cik=cik, issuer=issuer, forms=forms, limit_per_form=args.limit_per_form,
            )
            print(f"\n{ticker} ({cik}) — {len(packet)} źródeł w source packet")
            for src in packet:
                if src.verified:
                    print(f"  [OK] {src.title} — {src.url}")
                    print(f"       hash={src.content_hash[:16]}...")
                else:
                    print(f"  [SOURCE NOT VERIFIED] {src.title}: {src.reason}")
    return 0


def _run_llm_analysis(
    conn, edgar_client, claude_client, config, *, cik: str, ticker: str, periods,
) -> tuple[AnalysisOutput, list[VerifiedSource]] | None:
    """Wspólna ścieżka dla `analyze` i `score`: wskaźniki (Faza 1) +
    source packet (Faza 2) -> prompt -> Claude API -> walidacja
    deterministyczna (Faza 3). Zwraca None (i wypisuje powód) przy
    dowolnym niepowodzeniu — wołający decyduje, co dalej."""
    metrics = compute_metrics(periods)
    prefilter_result = evaluate_prefilter(metrics, config.prefilter)

    row = conn.execute("SELECT name FROM companies WHERE cik = ?", (cik,)).fetchone()
    issuer = row["name"] if row else ticker
    packet = build_sec_source_packet(edgar_client, cik=cik, issuer=issuer)
    verified_sources = [s for s in packet if s.verified]
    if not verified_sources:
        print(f"{ticker}: brak zweryfikowanych źródeł, pomijam analizę LLM.")
        return None

    prompt, source_id_map = build_analysis_prompt(
        ticker=ticker, metrics=metrics,
        prefilter_flags=prefilter_result.flags, sources=verified_sources,
    )
    try:
        result = claude_client.generate_analysis(prompt)
    except ClaudeError as exc:
        print(f"BŁĄD LLM dla {ticker}: {exc}")
        return None

    try:
        validate_analysis_output(
            result, allowed_source_ids=set(source_id_map), pdf_paginated_source_ids=set(),
        )
    except AnalysisValidationError as exc:
        print(f"ODRZUCONO (walidacja deterministyczna) dla {ticker}: {exc}")
        return None

    return result, packet


def cmd_analyze(args: argparse.Namespace) -> int:
    """Faza 3, punkt 3.2: dry-run diagnostyczny. NIE zapisuje do bazy —
    do tego służy `score` (Faza 4), które robi to samo i dodatkowo
    liczy/persystuje pełny wynik."""
    config = load_config()
    user_agent = config.sources.sec_edgar.resolve_user_agent()
    claude_key = config.llm.resolve_api_key()
    conn = init_db(args.db)

    with SecEdgarClient(user_agent) as edgar_client, ClaudeClient(
        claude_key, model=config.llm.model, max_output_tokens=config.llm.max_output_tokens,
    ) as claude_client:
        for ticker in args.tickers:
            cik = _resolve_cik(conn, ticker)
            if cik is None:
                print(f"{ticker}: brak w bazie (uruchom najpierw ingest-prices).")
                continue
            periods = get_fundamentals_periods(conn, cik)
            if not periods:
                print(f"{ticker}: brak danych fundamentalnych (uruchom najpierw ingest-fundamentals).")
                continue

            outcome = _run_llm_analysis(
                conn, edgar_client, claude_client, config, cik=cik, ticker=ticker, periods=periods,
            )
            if outcome is None:
                continue
            result, _packet = outcome

            print(f"\n{ticker} — analiza OK (schema_version={result.schema_version})")
            print(f"  business_understandability: {result.business_understandability.score}/"
                  f"{result.business_understandability.max_score} "
                  f"({result.business_understandability.confidence})")
            print(f"  moat: {result.moat.score}/{result.moat.max_score} ({result.moat.confidence})")
            print(f"  management_capital_allocation: {result.management_capital_allocation.score}/"
                  f"{result.management_capital_allocation.max_score}")
            print(f"  fear_analysis: {result.fear_analysis.classification} "
                  f"({result.fear_analysis.confidence}) — {result.fear_analysis.trigger}")
            print(f"  dividend_trap_alert: {result.dividend_trap_alert.triggered}")
            print(f"  biggest_unknown: {result.biggest_unknown}")
            print(f"  cited_source_ids: {result.cited_source_ids}")
            print(f"  hard_flag_candidates: {len(result.hard_flag_candidates)}")
    return 0


def cmd_score(args: argparse.Namespace) -> int:
    """Faza 4 (punkty 4.1-4.3): pełny pipeline — analiza LLM (jak
    `analyze`) + silnik scoringu (business_quality/financial_safety/
    valuation/fear_opportunity/dividend_shareholder_return) + hard
    gates + zapis do `analyses`/`analysis_sources` (IMMUTABLE, zawsze
    nowy wiersz) + raport CLI/Markdown."""
    config = load_config()
    user_agent = config.sources.sec_edgar.resolve_user_agent()
    claude_key = config.llm.resolve_api_key()
    conn = init_db(args.db)

    upsert_scoring_model_version(
        conn,
        version=config.scoring.version,
        description=f"status={config.scoring.status}",
        weights_json=json.dumps(config.scoring.weights.model_dump()),
        gates_json=json.dumps(config.hard_gates.model_dump()),
    )
    conn.commit()

    markdown_dir = Path(args.markdown_out) if args.markdown_out else None
    if markdown_dir:
        markdown_dir.mkdir(parents=True, exist_ok=True)

    with SecEdgarClient(user_agent) as edgar_client, ClaudeClient(
        claude_key, model=config.llm.model, max_output_tokens=config.llm.max_output_tokens,
    ) as claude_client:
        for ticker in args.tickers:
            cik = _resolve_cik(conn, ticker)
            if cik is None:
                print(f"{ticker}: brak w bazie (uruchom najpierw ingest-prices).")
                continue
            periods = get_fundamentals_periods(conn, cik)
            if not periods:
                print(f"{ticker}: brak danych fundamentalnych (uruchom najpierw ingest-fundamentals).")
                continue
            price_rows = get_price_series(conn, cik)
            if not price_rows:
                print(f"{ticker}: brak danych cenowych (uruchom najpierw ingest-prices).")
                continue
            current_price = price_rows[-1]["close"]
            run_date = price_rows[-1]["date"]

            company_row = conn.execute(
                "SELECT sector_profile FROM companies WHERE cik = ?", (cik,)
            ).fetchone()
            sector_profile = company_row["sector_profile"] if company_row else "GENERAL"

            outcome = _run_llm_analysis(
                conn, edgar_client, claude_client, config, cik=cik, ticker=ticker, periods=periods,
            )
            if outcome is None:
                continue
            analysis, packet = outcome

            score = compute_score(
                analysis=analysis, periods=periods, sector_profile=sector_profile,
                current_price=current_price, config=config,
            )

            base_scenario = (
                score.valuation_result.scenarios.get("base")
                if score.valuation_result.implemented else None
            )
            bear_scenario = (
                score.valuation_result.scenarios.get("bear")
                if score.valuation_result.implemented else None
            )
            bull_scenario = (
                score.valuation_result.scenarios.get("bull")
                if score.valuation_result.implemented else None
            )

            analysis_id = insert_analysis(
                conn,
                cik=cik, run_date=run_date, price_at_analysis=current_price,
                scoring_model_version=config.scoring.version,
                business_quality_score=score.business_quality_score,
                moat_score=score.moat_score,
                financial_quality_score=score.financial_quality_score,
                management_score=score.management_score,
                safety_score=score.safety_score,
                valuation_score=score.valuation_score,
                fear_score=score.fear_score,
                dividend_score=score.dividend_score,
                total_score=score.total_score,
                hard_flags=json.dumps(score.hard_gate_result.triggered),
                hard_gates_passed=int(score.hard_gate_result.passed),
                valuation_range_low=bear_scenario.intrinsic_value_per_share if bear_scenario else None,
                valuation_range_base=base_scenario.intrinsic_value_per_share if base_scenario else None,
                valuation_range_high=bull_scenario.intrinsic_value_per_share if bull_scenario else None,
                margin_of_safety_pct=base_scenario.margin_of_safety_pct if base_scenario else None,
                margin_of_safety_bear_pct=bear_scenario.margin_of_safety_pct if bear_scenario else None,
                margin_of_safety_bull_pct=bull_scenario.margin_of_safety_pct if bull_scenario else None,
                fear_classification=analysis.fear_analysis.classification,
                fear_confidence=analysis.fear_analysis.confidence,
                llm_model_id=config.llm.model,
                llm_schema_version=analysis.schema_version,
                llm_raw_output=json.dumps(analysis.model_dump()),
            )
            insert_analysis_sources(conn, analysis_id, packet)
            conn.commit()

            report = render_markdown_report(
                ticker=ticker, cik=cik, run_date=run_date, current_price=current_price,
                analysis=analysis, score=score, config=config,
            )
            print(f"\n{report}")
            if markdown_dir:
                out_path = markdown_dir / f"{ticker}_{run_date}.md"
                out_path.write_text(report, encoding="utf-8")
                print(f"(zapisano raport: {out_path})")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="buffett_scanner")
    parser.add_argument("--db", default=DEFAULT_DB_PATH, help="Ścieżka do pliku SQLite.")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init-db").set_defaults(func=cmd_init_db)

    sub.add_parser("ingest-universe").set_defaults(func=cmd_ingest_universe)

    p_prices = sub.add_parser("ingest-prices")
    p_prices.add_argument("tickers", nargs="+")
    p_prices.add_argument("--days", type=int, default=400)
    p_prices.set_defaults(func=cmd_ingest_prices)

    p_scan = sub.add_parser("scan")
    p_scan.add_argument("tickers", nargs="+")
    p_scan.set_defaults(func=cmd_scan)

    p_fund = sub.add_parser("ingest-fundamentals")
    p_fund.add_argument("tickers", nargs="+")
    p_fund.set_defaults(func=cmd_ingest_fundamentals)

    p_prefilter = sub.add_parser("prefilter")
    p_prefilter.add_argument("tickers", nargs="+")
    p_prefilter.set_defaults(func=cmd_prefilter)

    p_source_packet = sub.add_parser("build-source-packet")
    p_source_packet.add_argument("tickers", nargs="+")
    p_source_packet.add_argument("--forms", default="10-K,10-Q")
    p_source_packet.add_argument("--limit-per-form", type=int, default=2)
    p_source_packet.set_defaults(func=cmd_build_source_packet)

    p_analyze = sub.add_parser("analyze")
    p_analyze.add_argument("tickers", nargs="+")
    p_analyze.set_defaults(func=cmd_analyze)

    p_score = sub.add_parser("score")
    p_score.add_argument("tickers", nargs="+")
    p_score.add_argument("--markdown-out", default=None, help="Katalog na raporty .md")
    p_score.set_defaults(func=cmd_score)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

"""CLI — Faza 0 + Faza 1 + Faza 2 + Faza 3 + Faza 4 + Faza 5.

    python -m buffett_scanner.cli init-db
    python -m buffett_scanner.cli ingest-universe
    python -m buffett_scanner.cli ingest-prices AAPL MSFT ... [--days 400]
    python -m buffett_scanner.cli scan AAPL MSFT ...
    python -m buffett_scanner.cli ingest-fundamentals AAPL MSFT ...
    python -m buffett_scanner.cli prefilter AAPL MSFT ...
    python -m buffett_scanner.cli build-source-packet AAPL MSFT ...
    python -m buffett_scanner.cli analyze AAPL MSFT ...
    python -m buffett_scanner.cli score AAPL MSFT ... [--markdown-out DIR]
    python -m buffett_scanner.cli pit-prototype AAPL MSFT ... [--as-of YYYY-MM-DD]
    python -m buffett_scanner.cli analyze-sp500-history [--cutoff YYYY-MM-DD]
    python -m buffett_scanner.cli build-universe-membership [--cutoff YYYY-MM-DD]
    python -m buffett_scanner.cli backfill-walk-forward-data [--target prices|fundamentals|both]
        [--cutoff YYYY-MM-DD] [--refresh] [--sample CIK1,CIK2,...]
    python -m buffett_scanner.cli classify-sector-profiles [--sample CIK1,CIK2,...]
    python -m buffett_scanner.cli fetch-spy-benchmark-prices [--cutoff YYYY-MM-DD]
    python -m buffett_scanner.cli run-baseline-walk-forward [--window-start YYYY-MM-DD]
        [--window-end YYYY-MM-DD] [--sample CIK1,CIK2,...]
    python -m buffett_scanner.cli run-live-scan [--limit N] [--price-days N]
        [--sample TICK1,TICK2,...] [--skip-universe-refresh] [--markdown-out DIR]

Bez dopracowanego UI — zgodnie z Fazą 0 ("NO polished dashboard
required. Goal: prove that the analysis pipeline works.").
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import statistics
import sys
from pathlib import Path

from buffett_scanner.analysis_schema import AnalysisOutput, AnalysisValidationError, validate_analysis_output
from buffett_scanner.backfill import (
    backfill_fundamentals_for_cik,
    backfill_prices_for_cik,
    derive_price_fetch_ticker_universe,
)
from buffett_scanner.backtest_harness import (
    attach_forward_returns,
    classify_data_sufficiency,
    evaluate_candidate_at_date,
    generate_rebalance_dates,
)
from buffett_scanner.benchmark import compute_benchmark_snapshot
from buffett_scanner.calibration import (
    CALIBRATION_WINDOW_END,
    CALIBRATION_WINDOW_START,
    OOS_FOLD_YEARS,
    PRIMARY_HORIZON_MONTHS,
    evaluate_candidate_configuration,
    evaluate_candidate_configuration_spearman,
)
from buffett_scanner.calibration_round1 import ROUND_1_CANDIDATES
from buffett_scanner.calibration_round2a import ROUND_2A_CANDIDATES
from buffett_scanner.calibration_round2b import ROUND_2B_CANDIDATES
from buffett_scanner.config import DEFAULT_CONFIG_PATH, load_config
from buffett_scanner.db import (
    clear_universe_membership_for_rebuild,
    get_cik_for_active_ticker,
    get_companies_sector_profiles,
    get_fundamentals_periods,
    get_price_series,
    get_sec_company_facts_cache,
    get_universe_membership_as_of,
    init_db,
    insert_analysis,
    insert_analysis_sources,
    insert_backtest_benchmark,
    insert_backtest_candidate,
    insert_backtest_coverage,
    insert_calibration_run,
    insert_fundamentals_rows,
    insert_price_rows,
    insert_unresolved_ticker,
    insert_universe_membership_conflict,
    list_active_tickers,
    list_universe_membership_ciks,
    update_company_sector_profile,
    upsert_company,
    upsert_derived_metric,
    upsert_scoring_model_version,
    upsert_ticker_history,
    upsert_universe_membership,
)
from buffett_scanner.fmp_sp500_events import (
    ChangeEvent,
    collect_fmp_ticker_names,
    fmp_change_events,
    fmp_change_events_by_date_added,
    parse_fmp_events,
    reconstruct_membership_backward,
    resolve_fmp_tickers,
)
from buffett_scanner.fundamentals import compute_metrics, evaluate_prefilter
from buffett_scanner.live_scan import LiveCandidate, rank_candidates, render_live_scan_report
from buffett_scanner.pit_fundamentals import build_annual_fundamentals_periods_as_of
from buffett_scanner.point_in_time import find_first_matching_tag, value_as_of
from buffett_scanner.price_history_plan import build_price_fetch_plan
from buffett_scanner.prompt import build_analysis_prompt
from buffett_scanner.providers.claude import ClaudeClient, ClaudeError
from buffett_scanner.providers.fmp import FMPClient, FMPError, normalize_fundamentals_rows
from buffett_scanner.providers.sec_edgar import SecEdgarClient, SecEdgarError
from buffett_scanner.providers.sp500_history import Sp500HistoryError, fetch_components_csv
from buffett_scanner.report import render_markdown_report
from buffett_scanner.scanner import PriceBar, compute_price_changes, evaluate_decline_flags
from buffett_scanner.scoring import compute_score
from buffett_scanner.sector_classification import classify_sic_to_sector_profile
from buffett_scanner.sources import VerifiedSource, build_sec_source_packet
from buffett_scanner.universe_cik_reconciliation import (
    MATCH_ALGORITHM_VERSION,
    change_events_to_cik_events,
    match_cik_events_with_tolerance,
    pick_plateau_tolerance,
    tolerance_impact_curve,
)
from buffett_scanner.universe_history import (
    build_ticker_intervals,
    compare_ticker_sets,
    distinct_tickers,
    parse_components_csv,
    resolve_tickers_to_cik,
    tickers_as_of,
    window_from_cutoff,
)
from buffett_scanner.universe_membership_build import (
    attach_validation_status,
    build_cik_membership_intervals,
    build_conflicts,
    membership_as_of,
    merge_adjacent_same_cik_intervals,
)
from buffett_scanner.universe_ticker_rename_allowlist import apply_curated_allowlist
from buffett_scanner.walk_forward_coverage import CoverageSnapshot, aggregate_coverage

DEFAULT_DB_PATH = "buffett_scanner.db"
PREFILTER_CALC_VERSION = "0.1.0-phase1"
UNIVERSE_MEMBERSHIP_INDEX_NAME = "SP500"
UNIVERSE_MEMBERSHIP_TOLERANCE_RANGE = range(0, 11)  # 0..10 dni — patrz v1.34


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
                analysis=analysis, score=score, config=config, source_packet=packet,
            )
            print(f"\n{report}")
            if markdown_dir:
                out_path = markdown_dir / f"{ticker}_{run_date}.md"
                out_path.write_text(report, encoding="utf-8")
                print(f"(zapisano raport: {out_path})")
    return 0


def cmd_run_live_scan(args: argparse.Namespace) -> int:
    """Faza 6 — LIVE END-TO-END RUN na aktualnym rynku (domknięcie MVP
    V0, Decyzja właścicielki 2026-10-05, po formalnym zamknięciu Fazy
    5.4/5.6). CURRENT MARKET -> current universe -> fundamentals ->
    decline/opportunity screening -> deterministic scoring + hard
    gates -> valuation -> Claude qualitative analysis ->
    anti-confirmation-bias layer -> source assembly/validation ->
    final candidate report (0-5 kandydatów, "No qualifying
    opportunities today" jest prawidłowym wynikiem).

    W przeciwieństwie do `scan`/`score`/`analyze` (jawna lista
    tickerów) ten command operuje na CAŁYM aktualnym uniwersum S&P 500
    automatycznie — `--sample` ogranicza zakres tylko do małego testu.
    Ten live run jest testem operacyjnym MVP, NIE kolejną rundą
    kalibracji — wynik nigdy nie zmienia `config/config.yaml` ani
    metodologii scoringu/wyceny/hard gates/prefiltra/decline
    thresholds."""
    config = load_config()
    fmp_key = config.data_provider.resolve_api_key()
    user_agent = config.sources.sec_edgar.resolve_user_agent()
    claude_key = config.llm.resolve_api_key()
    conn = init_db(args.db)
    thresholds = config.decline_scanner.thresholds
    run_date = dt.date.today().isoformat()

    if not args.skip_universe_refresh:
        with FMPClient(fmp_key) as client:
            try:
                constituents = client.get_sp500_constituents()
            except FMPError as exc:
                print(f"BŁĄD pobierania uniwersum: {exc}", file=sys.stderr)
                return 1
        for row in constituents:
            cik, symbol, name = row.get("cik"), row.get("symbol"), row.get("name")
            if not cik or not symbol or not name:
                continue
            upsert_company(conn, cik=cik, name=name, sector=row.get("sector"), sub_industry=row.get("subSector"))
            upsert_ticker_history(conn, cik=cik, ticker=symbol, start_date=run_date)
        conn.commit()

    tickers = list_active_tickers(conn)
    if args.sample:
        sample = {t.strip().upper() for t in args.sample.split(",")}
        tickers = [t for t in tickers if t in sample]
    print(f"Uniwersum: {len(tickers)} tickerów.")

    to_date = dt.date.today()
    from_date = to_date - dt.timedelta(days=args.price_days)

    surfaced: list[tuple[str, str, object, dict[str, bool]]] = []
    with FMPClient(fmp_key) as client:
        for ticker in tickers:
            cik = _resolve_cik(conn, ticker)
            if cik is None:
                continue
            try:
                rows = client.get_historical_prices(
                    ticker, from_date=from_date.isoformat(), to_date=to_date.isoformat()
                )
            except FMPError as exc:
                print(f"{ticker}: BŁĄD pobierania cen: {exc}", file=sys.stderr)
                continue
            if not rows:
                continue
            insert_price_rows(conn, cik, source="fmp", rows=rows)
            conn.commit()
            price_rows = get_price_series(conn, cik)
            if not price_rows:
                continue
            bars = [
                PriceBar(
                    date=r["date"], open=r["open"], high=r["high"], low=r["low"],
                    close=r["close"], adj_close=r["adj_close"], volume=r["volume"],
                )
                for r in price_rows
            ]
            snapshot = compute_price_changes(bars)
            flags = evaluate_decline_flags(snapshot, thresholds)
            if any(flags.values()):
                surfaced.append((ticker, cik, snapshot, flags))
                print(f"  WYTYPOWANO {ticker}: {[k for k, v in flags.items() if v]}")

    print(f"Decline/opportunity screening: {len(surfaced)}/{len(tickers)} wytypowanych.")

    prefilter_excluded = 0
    survivors: list[tuple[str, str, object, dict[str, bool]]] = []
    with FMPClient(fmp_key) as client:
        for ticker, cik, snapshot, flags in surfaced:
            try:
                income = client.get_income_statement(ticker)
                balance = client.get_balance_sheet_statement(ticker)
                cashflow = client.get_cash_flow_statement(ticker)
            except FMPError as exc:
                print(f"{ticker}: BŁĄD pobierania fundamentów: {exc}", file=sys.stderr)
                continue
            fund_rows = normalize_fundamentals_rows(income, balance, cashflow)
            if not fund_rows:
                continue
            insert_fundamentals_rows(conn, cik, source="fmp", rows=fund_rows)
            conn.commit()
            periods = get_fundamentals_periods(conn, cik)
            if not periods:
                continue
            metrics = compute_metrics(periods)
            prefilter_result = evaluate_prefilter(metrics, config.prefilter)
            if prefilter_result.excludes:
                prefilter_excluded += 1
                print(f"  WYKLUCZONO {ticker} (prefilter): {prefilter_result.excludes}")
                continue
            survivors.append((ticker, cik, snapshot, flags))

    print(f"Prefilter: {len(survivors)} przeszło, {prefilter_excluded} wykluczonych.")

    candidates: list[LiveCandidate] = []
    analysis_failed = 0
    with SecEdgarClient(user_agent) as edgar_client, ClaudeClient(
        claude_key, model=config.llm.model, max_output_tokens=config.llm.max_output_tokens,
    ) as claude_client:
        for ticker, cik, snapshot, flags in survivors:
            periods = get_fundamentals_periods(conn, cik)
            outcome = _run_llm_analysis(
                conn, edgar_client, claude_client, config, cik=cik, ticker=ticker, periods=periods,
            )
            if outcome is None:
                analysis_failed += 1
                continue
            analysis, packet = outcome

            price_rows = get_price_series(conn, cik)
            current_price = price_rows[-1]["close"]

            company_row = conn.execute(
                "SELECT sector_profile FROM companies WHERE cik = ?", (cik,)
            ).fetchone()
            sector_profile = company_row["sector_profile"] if company_row else "GENERAL"

            score = compute_score(
                analysis=analysis, periods=periods, sector_profile=sector_profile,
                current_price=current_price, config=config,
            )

            base_scenario = (
                score.valuation_result.scenarios.get("base") if score.valuation_result.implemented else None
            )
            bear_scenario = (
                score.valuation_result.scenarios.get("bear") if score.valuation_result.implemented else None
            )
            bull_scenario = (
                score.valuation_result.scenarios.get("bull") if score.valuation_result.implemented else None
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

            candidates.append(LiveCandidate(
                ticker=ticker, cik=cik, run_date=run_date, current_price=current_price,
                decline_snapshot=snapshot, triggered_decline_flags=flags,
                analysis=analysis, score=score, source_packet=packet,
            ))

    ranked = rank_candidates(candidates, limit=args.limit)
    report = render_live_scan_report(
        run_date=run_date, universe_size=len(tickers), decline_surfaced=len(surfaced),
        prefilter_excluded=prefilter_excluded, analysis_failed=analysis_failed,
        candidates=ranked, config=config,
    )
    print(f"\n{report}")
    if args.markdown_out:
        out_dir = Path(args.markdown_out)
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"live_scan_{run_date}.md"
        out_path.write_text(report, encoding="utf-8")
        print(f"(zapisano raport: {out_path})")
    return 0


def cmd_pit_prototype(args: argparse.Namespace) -> int:
    """Faza 5, punkt 5.1 (OPEN BLOCKER 1): prototyp warstwy point-in-time
    na SEC XBRL company-facts. Pobiera historię faktów XBRL dla
    net_income/revenue, wykonuje przykładowe zapytanie PIT ("jaka była
    ostatnia wartość X filed na dzień <= D") i porównuje najnowszą
    wartość PIT z danymi "as reported" z FMP (Faza 1, fundamentals_raw)
    jako sanity-check. NIE oczekujemy dokładnej równości (różne modele
    danych/okresy sprawozdawcze) — tylko tego samego rzędu wielkości."""
    config = load_config()
    user_agent = config.sources.sec_edgar.resolve_user_agent()
    conn = init_db(args.db)
    as_of_date = args.as_of or dt.date.today().isoformat()

    with SecEdgarClient(user_agent) as client:
        for ticker in args.tickers:
            cik = _resolve_cik(conn, ticker)
            if cik is None:
                print(f"{ticker}: brak w bazie (uruchom najpierw ingest-prices).")
                continue
            try:
                company_facts = client.get_company_facts(cik)
            except SecEdgarError as exc:
                print(f"BŁĄD pobierania company facts dla {ticker}: {exc}")
                continue

            print(f"\n{ticker} ({cik}) — prototyp PIT (SEC XBRL), as_of={as_of_date}")
            for concept in ("net_income", "revenue"):
                found = find_first_matching_tag(company_facts, concept)
                if found is None:
                    print(f"  {concept}: brak żadnego z kandydujących tagów XBRL")
                    continue
                tag, history = found
                latest = value_as_of(history, as_of_date)
                print(f"  {concept} (tag XBRL={tag}, {len(history)} faktów w historii):")
                if latest:
                    print(f"    PIT jako-znane-na-{as_of_date}: {latest.val} "
                          f"(end={latest.end}, filed={latest.filed}, form={latest.form})")
                else:
                    print(f"    brak wartości PIT na {as_of_date} (nic jeszcze niezłożone)")

                row = conn.execute(
                    "SELECT value, period_end_date FROM fundamentals_raw "
                    "WHERE cik = ? AND line_item = ? ORDER BY period_end_date DESC LIMIT 1",
                    (cik, concept),
                ).fetchone()
                if row:
                    print(f"    FMP as-reported (Faza 1, dzisiejszy widok): {row['value']} "
                          f"(period_end_date={row['period_end_date']})")
                else:
                    print("    (brak danych FMP do porównania — uruchom najpierw ingest-fundamentals)")
    return 0


def cmd_analyze_sp500_history(args: argparse.Namespace) -> int:
    """Faza 5, punkt 5.2 (OPEN BLOCKER 2): analiza jakości źródła
    `fja05680/sp500`, ograniczona do okna `--cutoff` (domyślnie 2012-01-01,
    Decyzja D14). WYŁĄCZNIE DIAGNOSTYCZNE — nie zapisuje do
    `universe_membership`, to osobna decyzja właściciela (plan Fazy 5.2,
    v1.21). Raportuje: pokrycie/odstępy w danych źródłowych, liczbę
    przedziałów członkostwa, i rozwiązanie ticker->CIK względem
    dzisiejszego mapowania SEC — z jawnym `CIK_UNRESOLVED` zamiast
    zgadywania (zaakceptowane przez właściciela)."""
    config = load_config()
    user_agent = config.sources.sec_edgar.resolve_user_agent()
    cutoff = args.cutoff

    try:
        csv_text = fetch_components_csv()
    except Sp500HistoryError as exc:
        print(f"BŁĄD pobierania fja05680/sp500: {exc}")
        return 1

    rows = parse_components_csv(csv_text)
    print(f"fja05680/sp500: {len(rows)} wierszy źródłowych, zakres {rows[0].date}..{rows[-1].date}")

    window = window_from_cutoff(rows, cutoff)
    if not window:
        print(f"BŁĄD: źródło nie ma żadnego wiersza <= {cutoff} — nie da się ustalić baseline'u okna.")
        return 1
    print(f"Okno [{cutoff}, {rows[-1].date}]: baseline={window[0].date}, {len(window)} wierszy w oknie")

    tickers = distinct_tickers(window)
    intervals = build_ticker_intervals(window, cutoff_date=cutoff)
    still_open = [iv for iv in intervals if iv.end_date is None]
    reentries = len(intervals) - len(tickers)
    print(f"Dystynktywnych tickerów w oknie: {len(tickers)}")
    print(f"Przedziałów członkostwa: {len(intervals)} (w tym {reentries} przedziałów z ponownym wejściem)")
    print(f"Wciąż otwartych na koniec źródła ({rows[-1].date}): {len(still_open)}")

    try:
        with SecEdgarClient(user_agent) as client:
            sec_map = client.get_company_tickers()
    except SecEdgarError as exc:
        print(f"BŁĄD pobierania mapowania SEC ticker->CIK: {exc}")
        return 1

    result = resolve_tickers_to_cik(tickers, sec_map)
    direct_count = len(result.resolved) - len(result.resolved_via_format_variant)
    print(f"\nRozwiązanie ticker->CIK (mapowanie SEC AKTUALNE NA DZIŚ, nie point-in-time):")
    print(f"  RESOLVED: {len(result.resolved)}/{len(tickers)} "
          f"({direct_count} bezpośrednio, {len(result.resolved_via_format_variant)} przez wariant formatu)")
    if result.resolved_via_format_variant:
        pairs = ", ".join(f"{t}->{v}" for t, v in sorted(result.resolved_via_format_variant.items()))
        print(f"    Rozwiązane przez wariant formatu (kropka/myślnik): {pairs}")
    print(f"  CIK_UNRESOLVED: {len(result.unresolved)}/{len(tickers)}")

    still_open_tickers = {iv.ticker for iv in still_open}
    unresolved_still_open = [t for t in result.unresolved if t in still_open_tickers]
    unresolved_historical_only = [t for t in result.unresolved if t not in still_open_tickers]
    print(f"    z tego wciąż aktywne dziś (w {len(still_open)} otwartych): {len(unresolved_still_open)}")
    print(f"    z tego tylko historyczne (opuściły okno przed końcem źródła): {len(unresolved_historical_only)}")
    if unresolved_still_open:
        print(f"  Nierozwiązane, a wciąż aktywne (priorytet do naprawy): {', '.join(sorted(unresolved_still_open))}")
    if unresolved_historical_only:
        print(f"  Nierozwiązane, tylko historyczne: {', '.join(sorted(unresolved_historical_only))}")
    return 0


def _pick_validation_field(curve_date: list[dict], curve_date_added: list[dict]) -> str:
    """Wybiera pole daty FMP ('date' albo 'dateAdded') na podstawie
    empirycznej dominacji krzywej tolerancji (>= liczba dopasowań PRZY
    KAŻDEJ testowanej tolerancji) — nigdy nie zgadywane z góry. Przy
    braku jednoznacznej dominacji (krzywe się przecinają) domyślnie
    'dateAdded' — dwa niezależne realne uruchomienia (v1.34, 2026-09-30)
    pokazały jego stabilną przewagę przy niskiej tolerancji; to jawnie
    oznaczony domyślny wybór, nie ślepe założenie."""
    a_dominates = all(a["matched_count"] >= b["matched_count"] for a, b in zip(curve_date, curve_date_added))
    b_dominates = all(b["matched_count"] >= a["matched_count"] for a, b in zip(curve_date, curve_date_added))
    if a_dominates and not b_dominates:
        return "date"
    return "dateAdded"


def cmd_build_universe_membership(args: argparse.Namespace) -> int:
    """Faza 5.2, domknięcie OPEN BLOCKER 2 (v1.35, projekt zatwierdzony
    2026-09-30) — finalny build `universe_membership`. fja05680 jest
    JEDYNYM źródłem membership; FMP jest niezależnym walidatorem, nigdy
    nie nadpisuje cik/start_date/end_date. Wymaga FMP_API_KEY i
    SEC_EDGAR_USER_AGENT. Zapisuje do `universe_membership`,
    `universe_membership_conflicts`, `universe_membership_unresolved_
    tickers` — nigdy nie zgaduje CIK, nigdy nie ukrywa rozbieżności."""
    config = load_config()
    try:
        api_key = config.data_provider.resolve_api_key()
        user_agent = config.sources.sec_edgar.resolve_user_agent()
    except RuntimeError as exc:
        print(f"BŁĄD: {exc}", file=sys.stderr)
        return 1

    cutoff = args.cutoff
    index_name = UNIVERSE_MEMBERSHIP_INDEX_NAME
    run_id = dt.datetime.utcnow().strftime("build-%Y-%m-%dT%H%M%SZ")
    conn = init_db(args.db)

    print("== Krok 1: SEC company_tickers_full ==")
    with SecEdgarClient(user_agent) as sec_client:
        try:
            sec_full = sec_client.get_company_tickers_full()
        except SecEdgarError as exc:
            print(f"BŁĄD pobierania SEC company_tickers.json: {exc}", file=sys.stderr)
            return 1
    sec_ticker_map = {t: info["cik"] for t, info in sec_full.items()}
    sec_titles = {t: info["title"] for t, info in sec_full.items()}
    print(f"SEC: {len(sec_full)} tickerów.")

    print("\n== Krok 2: fja05680/sp500 (KANONICZNE) ==")
    try:
        fja_csv = fetch_components_csv()
    except Sp500HistoryError as exc:
        print(f"BŁĄD pobierania fja05680/sp500: {exc}", file=sys.stderr)
        return 1
    fja_snapshot_ref = f"fja05680:{hashlib.sha256(fja_csv.encode()).hexdigest()[:16]}"
    fja_rows = parse_components_csv(fja_csv)
    fja_window = window_from_cutoff(fja_rows, cutoff)
    if not fja_window:
        print(f"BŁĄD: fja05680 nie ma żadnego wiersza <= {cutoff}.", file=sys.stderr)
        return 1
    fja_intervals = build_ticker_intervals(fja_window, cutoff_date=cutoff)
    fja_all_tickers = distinct_tickers(fja_window)
    fja_resolution = resolve_tickers_to_cik(fja_all_tickers, sec_ticker_map)
    print(
        f"fja05680: {len(fja_all_tickers)} tickerów w oknie {cutoff}+, "
        f"rozwiązanych={len(fja_resolution.resolved)}, UNRESOLVED={len(fja_resolution.unresolved)}"
    )

    print("\n== Krok 3: FMP (WALIDATOR) ==")
    with FMPClient(api_key) as fmp_client:
        try:
            current_rows = fmp_client.get_sp500_constituents()
        except FMPError as exc:
            print(f"BŁĄD pobierania bieżącego składu FMP: {exc}", file=sys.stderr)
            return 1
        current_members = {r["symbol"] for r in current_rows if r.get("symbol")}
        path, raw_rows, attempts = fmp_client.get_historical_sp500_constituents()
        if path is None or not raw_rows:
            print("BŁĄD: historical-sp500-constituent niedostępny lub pusty.", file=sys.stderr)
            return 1
    fmp_snapshot_ref = f"FMP:historical-sp500-constituent:{hashlib.sha256(str(raw_rows).encode()).hexdigest()[:16]}"

    fmp_events_all = parse_fmp_events(raw_rows)
    fmp_names_by_ticker = collect_fmp_ticker_names(fmp_events_all)
    for t in current_members:
        fmp_names_by_ticker.setdefault(t, "")
    fmp_resolution = resolve_fmp_tickers(fmp_names_by_ticker, sec_ticker_map, sec_titles)
    print(
        f"FMP: {len(fmp_names_by_ticker)} tickerów w pełnym logu, "
        f"rozwiązanych={len(fmp_resolution.resolved)}, UNRESOLVED={len(fmp_resolution.unresolved)}"
    )

    print(f"\n== Krok 4: zdarzenia CIK-poziomu w oknie {cutoff}+ i wybór pola daty FMP ==")
    fja_events_set: set[ChangeEvent] = set()
    for iv in fja_intervals:
        if iv.start_date > cutoff:
            fja_events_set.add(ChangeEvent(date=iv.start_date, ticker=iv.ticker, action="ADD"))
        if iv.end_date is not None:
            fja_events_set.add(ChangeEvent(date=iv.end_date, ticker=iv.ticker, action="REMOVE"))
    fja_events_window = frozenset(fja_events_set)
    fja_cik_conv = change_events_to_cik_events(fja_events_window, fja_resolution.resolved)

    fmp_events_window_date = fmp_change_events(fmp_events_all, cutoff_date=cutoff)
    fmp_events_window_date_added, _ = fmp_change_events_by_date_added(fmp_events_all, cutoff_date=cutoff)
    fmp_cik_conv_date = change_events_to_cik_events(fmp_events_window_date, fmp_resolution.resolved)
    fmp_cik_conv_date_added = change_events_to_cik_events(fmp_events_window_date_added, fmp_resolution.resolved)

    curve_date = tolerance_impact_curve(
        fja_cik_conv.events, fmp_cik_conv_date.events, tolerance_range_days=UNIVERSE_MEMBERSHIP_TOLERANCE_RANGE,
    )
    curve_date_added = tolerance_impact_curve(
        fja_cik_conv.events, fmp_cik_conv_date_added.events, tolerance_range_days=UNIVERSE_MEMBERSHIP_TOLERANCE_RANGE,
    )
    chosen_field = _pick_validation_field(curve_date, curve_date_added)
    chosen_curve = curve_date if chosen_field == "date" else curve_date_added
    chosen_conv = fmp_cik_conv_date if chosen_field == "date" else fmp_cik_conv_date_added
    chosen_tolerance = pick_plateau_tolerance(chosen_curve)
    print(
        f"Wybrane empirycznie: pole={chosen_field!r}, tolerancja (plateau)={chosen_tolerance}d, "
        f"reguła={MATCH_ALGORITHM_VERSION}"
    )

    match_result = match_cik_events_with_tolerance(
        fja_cik_conv.events, chosen_conv.events, tolerance_days=chosen_tolerance,
    )
    print(
        f"Dopasowane={len(match_result.matched)} tylko_kanoniczne={len(match_result.only_canonical)} "
        f"tylko_walidator={len(match_result.only_validator)}"
    )

    print(
        "\n== Krok 5: kuratorowana allowlista rename (Faza 5.3, LIMITED_BUT_HONEST) "
        "+ budowa przedziałów CIK-poziomu + scalanie zmian tickera bez opuszczenia indeksu =="
    )
    # Allowlista stosowana TYLKO tutaj (nie w Kroku 3/4, FMP reconciliation) —
    # rozszerzenie fja_resolution.resolved przed Krokiem 4 wprowadzałoby
    # sztuczny ADD+REMOVE tego samego CIK w tym samym dniu (ticker rename
    # widziany jako dwa osobne zdarzenia), co zniekształcałoby krzywą
    # tolerancji empirycznie wybieraną dla CAŁEGO builda. Krok 4 (walidacja
    # fja05680 vs FMP) musi pozostać oparty wyłącznie na SEC-direct
    # rozwiązaniu, zgodnie z oryginalnym projektem Fazy 5.2.
    allowlist_result = apply_curated_allowlist(fja_resolution.resolved, fja_resolution.unresolved)
    print(
        f"Allowlista: +{len(allowlist_result.resolved_via_curated_allowlist)} tickerów odzyskanych "
        f"({sorted(allowlist_result.resolved_via_curated_allowlist)})"
    )
    membership_intervals, unresolved_fja = build_cik_membership_intervals(
        fja_intervals, allowlist_result.resolved, fja_resolution.resolved_via_format_variant,
        index_name=index_name, source="fja05680", source_snapshot_ref=fja_snapshot_ref,
        resolved_via_curated_allowlist=allowlist_result.resolved_via_curated_allowlist,
    )
    pre_merge_intervals = membership_intervals
    pre_merge_count = len(pre_merge_intervals)
    membership_intervals = merge_adjacent_same_cik_intervals(membership_intervals)
    membership_intervals = attach_validation_status(
        membership_intervals, match_result, date_field=chosen_field,
        validation_rule_version=MATCH_ALGORITHM_VERSION, validation_run_id=run_id,
    )
    conflicts = build_conflicts(
        match_result, index_name=index_name, date_field=chosen_field,
        validation_rule_version=MATCH_ALGORITHM_VERSION, validation_run_id=run_id,
    )
    unique_ciks = {iv.cik for iv in membership_intervals}
    merged_away = pre_merge_count - len(membership_intervals)
    print(
        f"Przedziałów członkostwa: {len(membership_intervals)} "
        f"(przed scaleniem: {pre_merge_count}, scalono {merged_away} par tego samego CIK -- "
        f"rename bez opuszczenia indeksu LUB nakładające się dual-class tickery)"
    )

    # Sanity check PO scaleniu (Decyzja właścicielki 2026-10-04, po realnym
    # znalezisku -- dual-class share tickery dawały nakładające się, nie
    # tylko sąsiadujące, przedziały tego samego CIK): skoro
    # merge_adjacent_same_cik_intervals ma teraz scalać WSZYSTKIE
    # nakładające się przedziały, każdy CIK z >1 segmentem PO scaleniu musi
    # reprezentować genuine exit/re-entry (dodatnia przerwa) -- jeśli
    # którykolwiek pozostały >1-segmentowy CIK nadal nakłada się, to błąd w
    # samej funkcji merge, nie coś do cichego naprawienia tutaj.
    post_merge_by_cik: dict[str, list] = {}
    for iv in membership_intervals:
        post_merge_by_cik.setdefault(iv.cik, []).append(iv)
    multi_segment_after_merge = {cik: ivs for cik, ivs in post_merge_by_cik.items() if len(ivs) > 1}
    overlapping_pairs_after_merge = []
    for cik, ivs in multi_segment_after_merge.items():
        ivs_sorted = sorted(ivs, key=lambda iv: iv.start_date)
        for i in range(len(ivs_sorted) - 1):
            a_end = ivs_sorted[i].end_date
            b_start = ivs_sorted[i + 1].start_date
            if a_end is None or b_start <= a_end:
                overlapping_pairs_after_merge.append((cik, ivs_sorted[i], ivs_sorted[i + 1]))
    print(
        f"Sanity check po scaleniu: CIK z >1 segmentem = {len(multi_segment_after_merge)} "
        f"(oczekiwane: wszystkie to genuine exit/re-entry), nakładające się pary PO scaleniu = "
        f"{len(overlapping_pairs_after_merge)} (musi być 0)"
    )
    if overlapping_pairs_after_merge:
        print(
            "BŁĄD: merge_adjacent_same_cik_intervals nie scaliło wszystkich nakładających "
            "się przedziałów -- to błąd w samej funkcji, nie coś do cichego naprawienia tutaj:",
            file=sys.stderr,
        )
        for cik, a, b in overlapping_pairs_after_merge:
            print(f"  CIK={cik}: [{a.start_date}, {a.end_date}) x [{b.start_date}, {b.end_date})", file=sys.stderr)
        return 1

    # Diagnostyka (Faza 5.3): rozbicie scaleń na te pochodzące z 7
    # rekordów allowlisty vs pozostałe (nieznane/naturalne DIRECT-DIRECT
    # rename, niezwiązane z naszą zmianą) — żeby jawnie zweryfikować, że
    # allowlista scaliła DOKŁADNIE tyle par, ile ma rekordów, i nic więcej.
    allowlist_ciks = {allowlist_result.resolved[t] for t in allowlist_result.resolved_via_curated_allowlist}
    pre_by_cik: dict[str, int] = {}
    for iv in pre_merge_intervals:
        pre_by_cik[iv.cik] = pre_by_cik.get(iv.cik, 0) + 1
    post_by_cik: dict[str, int] = {}
    for iv in membership_intervals:
        post_by_cik[iv.cik] = post_by_cik.get(iv.cik, 0) + 1
    merges_in_allowlist_ciks = sum(
        pre_by_cik.get(cik, 0) - post_by_cik.get(cik, 0) for cik in allowlist_ciks
    )
    merges_elsewhere = merged_away - merges_in_allowlist_ciks
    print(
        f"  z czego w 7 CIK-ach allowlisty: {merges_in_allowlist_ciks}, "
        f"gdzie indziej (niezwiązane z allowlistą): {merges_elsewhere}"
    )
    if merges_elsewhere:
        other_merged_ciks = sorted(
            cik for cik in pre_by_cik
            if cik not in allowlist_ciks and pre_by_cik[cik] > post_by_cik.get(cik, 0)
        )
        print(f"  CIK-i spoza allowlisty, które się scaliły: {other_merged_ciks}")
    multi_segment_allowlist_ciks = sorted(cik for cik in allowlist_ciks if pre_by_cik.get(cik, 0) > 2)
    if multi_segment_allowlist_ciks:
        print(
            f"  UWAGA: {len(multi_segment_allowlist_ciks)} CIK-(ów) allowlisty ma >2 segmenty "
            f"(więcej niż sam stary+nowy ticker) — pełny łańcuch tickerów:"
        )
        for cik in multi_segment_allowlist_ciks:
            chain = sorted(
                (iv.ticker, iv.start_date, iv.end_date)
                for iv in fja_intervals
                if allowlist_result.resolved.get(iv.ticker) == cik
            )
            print(f"    CIK={cik}: {chain}")
    print(f"Unikalnych CIK: {len(unique_ciks)}")
    print(f"Unresolved (fja05680, nie generują wiersza): {len(unresolved_fja)}")
    print(
        f"Konflikty (audyt, nie modyfikują membership): {len(conflicts)} "
        f"({sum(1 for c in conflicts if c.conflict_type == 'ONLY_CANONICAL')} ONLY_CANONICAL, "
        f"{sum(1 for c in conflicts if c.conflict_type == 'ONLY_VALIDATOR')} ONLY_VALIDATOR)"
    )

    # FMP-side unresolved w oknie istotnym dla D14 (patrz poprawka zakresu
    # v1.34) — tylko do logu unresolved_tickers, nigdy nie wpływa na membership.
    fmp_relevant_tickers = set(
        collect_fmp_ticker_names([e for e in fmp_events_all if e.date >= cutoff])
    ) | current_members
    fmp_unresolved_in_window = sorted(t for t in fmp_resolution.unresolved if t in fmp_relevant_tickers)

    print(f"\n== Krok 6: zapis do bazy ({args.db}) ==")
    # Decyzja właścicielki 2026-10-04: pełne zastąpienie, nie dopisanie --
    # ponowny build (np. po naprawie overlapping dual-class intervals) na
    # już istniejącej bazie NIE może zostawiać starych, osieroconych
    # wierszy, których nowy wynik już nie produkuje.
    clear_universe_membership_for_rebuild(conn, index_name)
    cik_to_name: dict[str, str] = {}
    for ticker in sorted(fja_resolution.resolved):
        cik = fja_resolution.resolved[ticker]
        if cik in cik_to_name:
            continue
        lookup_ticker = fja_resolution.resolved_via_format_variant.get(ticker, ticker)
        title = sec_titles.get(lookup_ticker) or sec_titles.get(ticker) or ""
        cik_to_name[cik] = title or f"CIK {cik}"

    for iv in membership_intervals:
        upsert_company(conn, cik=iv.cik, name=cik_to_name.get(iv.cik, f"CIK {iv.cik}"))
        upsert_universe_membership(
            conn, cik=iv.cik, index_name=iv.index_name, start_date=iv.start_date,
            end_date=iv.end_date, source=iv.source, source_snapshot_ref=iv.source_snapshot_ref,
            cik_resolution_method=iv.cik_resolution_method,
            cik_resolution_note=iv.cik_resolution_note,
            entry_validation_status=iv.entry_validation_status,
            entry_validation_day_diff=iv.entry_validation_day_diff,
            exit_validation_status=iv.exit_validation_status,
            exit_validation_day_diff=iv.exit_validation_day_diff,
            validation_tolerance_days=iv.validation_tolerance_days,
            validation_date_field=iv.validation_date_field,
            validation_rule_version=iv.validation_rule_version,
            validation_run_id=iv.validation_run_id,
            overlap_merge_note=iv.overlap_merge_note,
        )
    for c in conflicts:
        insert_universe_membership_conflict(
            conn, cik=c.cik, index_name=c.index_name, event_date=c.event_date, action=c.action,
            conflict_type=c.conflict_type, tolerance_days=c.tolerance_days, date_field=c.date_field,
            validation_rule_version=c.validation_rule_version, validation_run_id=c.validation_run_id,
        )
    for t in unresolved_fja:
        insert_unresolved_ticker(
            conn, source="fja05680", ticker=t, index_name=index_name,
            source_snapshot_ref=fja_snapshot_ref, run_id=run_id,
        )
    for t in fmp_unresolved_in_window:
        insert_unresolved_ticker(
            conn, source="FMP", ticker=t, index_name=index_name,
            source_snapshot_ref=fmp_snapshot_ref, run_id=run_id,
        )
    conn.commit()
    print(
        f"Zapisano {len(membership_intervals)} przedziałów, {len(conflicts)} konfliktów, "
        f"{len(unresolved_fja) + len(fmp_unresolved_in_window)} unresolved tickerów (run_id={run_id})."
    )

    print(f"\n== Krok 7: rekonstrukcja na reprezentatywnych datach ({cutoff}..dziś) ==")
    sample_dates = ["2012-01-31", "2018-12-31", dt.date.today().isoformat()]
    for date in sample_dates:
        in_memory = membership_as_of(membership_intervals, date)
        from_db = set(get_universe_membership_as_of(conn, index_name, date))
        if in_memory != from_db:
            print(f"BŁĄD: rozjazd między budową w pamięci a zapisem w bazie dla {date}.", file=sys.stderr)
            return 1

        fmp_snapshot = reconstruct_membership_backward(fmp_events_all, current_members, date)
        fmp_cik_snapshot = {fmp_resolution.resolved[t] for t in fmp_snapshot if t in fmp_resolution.resolved}
        snap_cmp = compare_ticker_sets(from_db, fmp_cik_snapshot)
        print(
            f"  {date}: universe_membership={snap_cmp.count_a} CIK, "
            f"FMP (niezależna rekonstrukcja)={snap_cmp.count_b} CIK, "
            f"wspólne={snap_cmp.intersection_count}, "
            f"tylko_universe_membership={len(snap_cmp.only_in_a)}, tylko_FMP={len(snap_cmp.only_in_b)}"
        )

    return 0


def cmd_backfill_walk_forward_data(args: argparse.Namespace) -> int:
    """Faza 5.3b — backfill 626 CIK / 2012+ dla walk-forward backtestu,
    projekt zatwierdzony przez właścicielkę 2026-10-03. Wymaga, żeby
    `universe_membership` było JUŻ zbudowane (`build-universe-membership`)
    w tym samym `--db` — backfill WYŁĄCZNIE czyta zresolved CIK z tej
    tabeli, nigdy jej nie przebudowuje/nie modyfikuje. Pełna resumability
    (patrz `backfill.py`): domyślnie pomija CIK/task już COMPLETE,
    `--refresh` wymusza ponowne pobranie. `--sample` ogranicza zakres do
    podanej listy CIK (mały Proof Run przed pełnym runem)."""
    config = load_config()
    try:
        api_key = config.data_provider.resolve_api_key()
        user_agent = config.sources.sec_edgar.resolve_user_agent()
    except RuntimeError as exc:
        print(f"BŁĄD: {exc}", file=sys.stderr)
        return 1

    index_name = UNIVERSE_MEMBERSHIP_INDEX_NAME
    cutoff = args.cutoff
    today = dt.date.today().isoformat()
    run_id = "backfill-" + dt.datetime.utcnow().strftime("%Y-%m-%dT%H%M%SZ")
    conn = init_db(args.db)

    all_ciks = list_universe_membership_ciks(conn, index_name)
    if args.sample:
        sample_set = {c.strip() for c in args.sample.split(",") if c.strip()}
        all_ciks = [c for c in all_ciks if c in sample_set]
    if not all_ciks:
        print(
            "BŁĄD: zero CIK w zakresie (sprawdź --sample / czy universe_membership "
            "jest już zbudowane w tym --db).",
            file=sys.stderr,
        )
        return 1
    print(f"Zakres backfillu: {len(all_ciks)} CIK (index={index_name}, cutoff={cutoff}, run_id={run_id}).")

    fundamentals_results = []
    price_results = []

    if args.target in ("fundamentals", "both"):
        print("\n== Fundamentals (SEC company_facts -> sec_company_facts_cache) ==")
        with SecEdgarClient(user_agent) as sec_client:
            for i, cik in enumerate(all_ciks, 1):
                result = backfill_fundamentals_for_cik(
                    sec_client, conn, cik=cik, run_id=run_id, refresh=args.refresh,
                )
                conn.commit()
                fundamentals_results.append(result)
                print(f"  [{i}/{len(all_ciks)}] CIK={cik}: {result.status} — {result.detail}")

    if args.target in ("prices", "both"):
        print("\n== Prices (price_history_plan -> price_daily) ==")
        print("  Derivacja (ticker_intervals, resolved) z fja05680 + SEC ticker map ...")
        with SecEdgarClient(user_agent) as sec_client:
            try:
                sec_ticker_map = sec_client.get_company_tickers()
            except SecEdgarError as exc:
                print(f"BŁĄD pobierania SEC company_tickers.json: {exc}", file=sys.stderr)
                return 1
        try:
            fja_csv = fetch_components_csv()
        except Sp500HistoryError as exc:
            print(f"BŁĄD pobierania fja05680/sp500: {exc}", file=sys.stderr)
            return 1
        ticker_intervals, resolved = derive_price_fetch_ticker_universe(
            sec_ticker_map=sec_ticker_map, fja_csv=fja_csv, cutoff=cutoff, in_scope_ciks=set(all_ciks),
        )
        tasks, _unresolved_in_plan = build_price_fetch_plan(
            ticker_intervals, resolved, cutoff_date=cutoff, today=today,
        )
        tasks_by_cik: dict[str, list] = {}
        for t in tasks:
            tasks_by_cik.setdefault(t.cik, []).append(t)
        print(f"  {len(tasks)} zadań cenowych dla {len(tasks_by_cik)}/{len(all_ciks)} CIK w zakresie.")

        with FMPClient(api_key) as fmp_client:
            for i, cik in enumerate(all_ciks, 1):
                result = backfill_prices_for_cik(
                    fmp_client, conn, cik=cik, tasks=tasks_by_cik.get(cik, []),
                    run_id=run_id, refresh=args.refresh,
                )
                conn.commit()
                price_results.append(result)
                print(f"  [{i}/{len(all_ciks)}] CIK={cik}: {result.status} — {result.detail}")

    print("\n== Podsumowanie ==")
    for label, results in (("FUNDAMENTALS", fundamentals_results), ("PRICES", price_results)):
        if not results:
            continue
        counts: dict[str, int] = {}
        for r in results:
            counts[r.status] = counts.get(r.status, 0) + 1
        print(f"  {label}: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))

    return 0


def cmd_classify_sector_profiles(args: argparse.Namespace) -> int:
    """Faza 5.3c — klasyfikacja `sector_profile` z kodu SIC (Decyzja
    właścicielki 2026-10-04): `sector_profile` nigdy nie był realnie
    wyliczany (wszystkie 615 CIK domyślnie 'GENERAL'), co powodowało
    błędne stosowanie `dcf_owner_earnings` do banków/ubezpieczycieli w
    datasetcie. Czyta CIK z `universe_membership` (już zbudowane w tym
    `--db`), pyta SEC Submissions API o `sic`/`sicDescription` per CIK,
    mapuje czystą funkcją `classify_sic_to_sector_profile` (patrz
    `sector_classification.py`), zapisuje WYŁĄCZNIE `sector_profile`
    (`update_company_sector_profile` — nigdy nie nadpisuje name/sector/
    industry). Idempotentne — bezpiecznie powtarzalne."""
    config = load_config()
    try:
        user_agent = config.sources.sec_edgar.resolve_user_agent()
    except RuntimeError as exc:
        print(f"BŁĄD: {exc}", file=sys.stderr)
        return 1

    index_name = UNIVERSE_MEMBERSHIP_INDEX_NAME
    conn = init_db(args.db)
    all_ciks = list_universe_membership_ciks(conn, index_name)
    if args.sample:
        sample_set = {c.strip() for c in args.sample.split(",") if c.strip()}
        all_ciks = [c for c in all_ciks if c in sample_set]
    if not all_ciks:
        print("BŁĄD: zero CIK w zakresie (sprawdź --sample / universe_membership).", file=sys.stderr)
        return 1
    print(f"Klasyfikacja SIC -> sector_profile dla {len(all_ciks)} CIK ...")

    counts: dict[str, int] = {}
    errors: list[str] = []
    with SecEdgarClient(user_agent) as sec_client:
        for i, cik in enumerate(all_ciks, 1):
            try:
                sic_info = sec_client.get_sic_classification(cik)
            except SecEdgarError as exc:
                print(f"  [{i}/{len(all_ciks)}] CIK={cik}: BŁĄD SEC ({exc}) — sector_profile niezmieniony.")
                errors.append(cik)
                continue
            sector_profile = classify_sic_to_sector_profile(sic_info["sic"])
            update_company_sector_profile(conn, cik=cik, sector_profile=sector_profile)
            counts[sector_profile] = counts.get(sector_profile, 0) + 1
            if i % 50 == 0 or i == len(all_ciks):
                conn.commit()
                print(f"  [{i}/{len(all_ciks)}] CIK={cik}: SIC={sic_info['sic']!r} -> {sector_profile}")
    conn.commit()

    print("\n== Podsumowanie ==")
    print("  " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    if errors:
        print(f"  BŁĘDY SEC (sector_profile niezmieniony, zachowany poprzedni stan): {len(errors)} CIK: {errors}")

    return 0


def cmd_fetch_spy_benchmark_prices(args: argparse.Namespace) -> int:
    """Faza 5.3c — pobiera realną historię cen SPY, SECONDARY benchmark
    (Decyzja właścicielki 2026-10-04: "ta sama konwencja forward price
    return jak dla kandydatów, bez dywidend/reinwestycji"). SPY NIE jest
    i nie staje się częścią `universe_membership`/PIT universe — to
    wyłącznie instrument porównawczy. CIK rozwiązany przez SEC
    `company_tickers.json` (nigdy nie hardkodowany z pamięci, zgodnie z
    zasadą "tożsamość = CIK, nigdy ticker" z sekcji 5) i zapisany w
    `ticker_history`, żeby `run-baseline-walk-forward` mógł go odczytać
    offline (zero sieci, patrz `get_cik_for_active_ticker`)."""
    config = load_config()
    try:
        api_key = config.data_provider.resolve_api_key()
        user_agent = config.sources.sec_edgar.resolve_user_agent()
    except RuntimeError as exc:
        print(f"BŁĄD: {exc}", file=sys.stderr)
        return 1

    cutoff = args.cutoff
    today = dt.date.today().isoformat()
    conn = init_db(args.db)

    print("== Rozwiązanie CIK dla SPY (SEC company_tickers.json) ==")
    with SecEdgarClient(user_agent) as sec_client:
        try:
            sec_full = sec_client.get_company_tickers_full()
        except SecEdgarError as exc:
            print(f"BŁĄD pobierania SEC company_tickers.json: {exc}", file=sys.stderr)
            return 1
    if "SPY" not in sec_full:
        print("BŁĄD: SEC company_tickers.json nie zawiera tickera SPY.", file=sys.stderr)
        return 1
    spy_cik = sec_full["SPY"]["cik"]
    spy_title = sec_full["SPY"]["title"] or "SPY"
    print(f"SPY -> CIK={spy_cik} ({spy_title})")

    upsert_company(conn, cik=spy_cik, name=spy_title)
    upsert_ticker_history(conn, cik=spy_cik, ticker="SPY", start_date=cutoff)
    conn.commit()

    print(f"\n== Pobieranie cen SPY ({cutoff}..{today}, FMP) ==")
    with FMPClient(api_key) as fmp_client:
        try:
            rows = fmp_client.get_historical_prices("SPY", from_date=cutoff, to_date=today)
        except FMPError as exc:
            print(f"BŁĄD pobierania cen SPY z FMP: {exc}", file=sys.stderr)
            return 1
    n = insert_price_rows(conn, spy_cik, source="fmp", rows=rows)
    conn.commit()
    print(f"Zapisano/zaktualizowano {n} wierszy cen SPY (CIK={spy_cik}, {len(rows)} dni z FMP).")
    return 0


def cmd_run_baseline_walk_forward(args: argparse.Namespace) -> int:
    """Faza 5.3c — pełny BASELINE walk-forward (Decyzja właścicielki
    2026-10-04). Orkiestracja WYŁĄCZNIE już istniejących, przetestowanych
    funkcji (`backtest_harness.py`) na danych już zebranych przez
    backfill (Faza 5.3b) — zero zmiany scoring weights/thresholds/hard
    gates/valuation assumptions/`deterministic_score_pct` methodology,
    zero sieci (czyta WYŁĄCZNIE z `--db`). Dla KAŻDEJ decision_date
    mierzy coverage NIEZALEŻNIE od liczby kandydatów (Decyzja
    właścicielki: missingness nie musi być losowy, więc sama liczba
    kandydatów nie wystarcza — patrz `walk_forward_coverage.py`)."""
    config = load_config()
    config_text = Path(DEFAULT_CONFIG_PATH).read_text(encoding="utf-8")
    config_version = f"config.yaml:{hashlib.sha256(config_text.encode()).hexdigest()[:16]}"
    run_id = "walk-forward-baseline-" + dt.datetime.utcnow().strftime("%Y-%m-%dT%H%M%SZ")
    conn = init_db(args.db)

    index_name = UNIVERSE_MEMBERSHIP_INDEX_NAME
    window_start = args.window_start
    window_end = args.window_end or dt.date.today().isoformat()
    decision_dates = generate_rebalance_dates(window_start, window_end, "MONTHLY")
    print(f"Decision dates: {len(decision_dates)} ({window_start}..{window_end}), run_id={run_id}")

    all_ciks = list_universe_membership_ciks(conn, index_name)
    sample_set: set[str] | None = None
    if args.sample:
        sample_set = {c.strip() for c in args.sample.split(",") if c.strip()}
        all_ciks = [c for c in all_ciks if c in sample_set]
    print(f"CIK w zakresie (universe_membership, kiedykolwiek): {len(all_ciks)}")

    sector_profiles = get_companies_sector_profiles(conn)

    print("Wczytywanie cen i fundamentals per CIK (raz, z lokalnej bazy) ...")
    price_bars_by_cik: dict[str, list[PriceBar]] = {}
    company_facts_by_cik: dict[str, dict] = {}
    for cik in all_ciks:
        rows = get_price_series(conn, cik)
        price_bars_by_cik[cik] = [
            PriceBar(
                date=r["date"], open=r["open"], high=r["high"], low=r["low"],
                close=r["close"], adj_close=r["adj_close"], volume=r["volume"],
            )
            for r in rows
        ]
        cf = get_sec_company_facts_cache(conn, cik)
        if cf is not None:
            company_facts_by_cik[cik] = cf
    print(f"  {len(price_bars_by_cik)} CIK z cenami, {len(company_facts_by_cik)} CIK z SEC cache.")

    # SECONDARY benchmark (Decyzja właścicielki 2026-10-04): SPY, jeśli
    # `fetch-spy-benchmark-prices` już go zapisał w tym `--db`. Brak nie
    # jest błędem tego runu -- `compute_benchmark_snapshot` daje wtedy
    # po prostu spy_return_*_pct=None (jawnie, nigdy zgadywane), run
    # kontynuuje z samym PRIMARY benchmarkiem.
    spy_cik = get_cik_for_active_ticker(conn, "SPY")
    spy_bars: list[PriceBar] | None = None
    if spy_cik is not None:
        spy_rows = get_price_series(conn, spy_cik)
        spy_bars = [
            PriceBar(
                date=r["date"], open=r["open"], high=r["high"], low=r["low"],
                close=r["close"], adj_close=r["adj_close"], volume=r["volume"],
            )
            for r in spy_rows
        ]
        print(f"  SPY (CIK={spy_cik}): {len(spy_bars)} barów cenowych -- SECONDARY benchmark aktywny.")
    else:
        print("  SPY nieznaleziony w ticker_history -- SECONDARY benchmark będzie None (uruchom fetch-spy-benchmark-prices).")

    coverage_snapshots: list[CoverageSnapshot] = []
    benchmark_snapshots: list = []
    n_candidates = 0
    stage_totals = {"NO_DECLINE_SIGNAL": 0, "EXCLUDED_BY_PREFILTER": 0, "HARD_GATE_FAILED": 0, "CANDIDATE": 0}

    print(f"\n== Walk-forward: {len(decision_dates)} dat x PIT universe ==")
    for d_idx, decision_date in enumerate(decision_dates, 1):
        pit_ciks = get_universe_membership_as_of(conn, index_name, decision_date)
        if len(pit_ciks) != len(set(pit_ciks)):
            dupes = sorted({c for c in pit_ciks if pit_ciks.count(c) > 1})
            raise RuntimeError(
                f"FAIL FAST: universe_membership_as_of({decision_date!r}) zwróciło "
                f"duplikat CIK {dupes} -- to oznacza nakładające się przedziały membership "
                f"dla tego samego CIK w universe_membership (patrz universe_membership_build."
                f"merge_adjacent_same_cik_intervals -- ten build musi być uruchomiony PO "
                f"naprawie z 2026-10-04). Celowo nie naprawiam tego przez DISTINCT -- to by "
                f"ukryło realny problem danych, zamiast go sygnalizować."
            )
        if sample_set is not None:
            pit_ciks = [c for c in pit_ciks if c in sample_set]

        sufficient_price = sufficient_fund = scanned = 0
        excl_price = excl_fund = 0
        stage_counts = {"NO_DECLINE_SIGNAL": 0, "EXCLUDED_BY_PREFILTER": 0, "HARD_GATE_FAILED": 0, "CANDIDATE": 0}
        pit_ciks_with_sufficient_price: list[str] = []

        for cik in pit_ciks:
            full_bars = price_bars_by_cik.get(cik, [])
            bars = [b for b in full_bars if b.date <= decision_date]
            cf = company_facts_by_cik.get(cik)
            periods = build_annual_fundamentals_periods_as_of(cf, decision_date) if cf is not None else []

            has_price, has_fund = classify_data_sufficiency(bars=bars, periods=periods)
            if has_price:
                sufficient_price += 1
                pit_ciks_with_sufficient_price.append(cik)
            else:
                excl_price += 1
            if has_fund:
                sufficient_fund += 1
            else:
                excl_fund += 1
            if not (has_price and has_fund):
                continue
            scanned += 1

            result = evaluate_candidate_at_date(
                cik=cik, ticker_as_of_date=cik, decision_date=decision_date,
                bars=bars, periods=periods, sector_profile=sector_profiles.get(cik, "GENERAL"),
                config=config, run_id=run_id, config_version=config_version,
                universe_provenance="universe_membership_as_of",
            )
            if result.stage in stage_counts:
                stage_counts[result.stage] += 1
                stage_totals[result.stage] += 1
            if result.stage == "CANDIDATE":
                candidate = attach_forward_returns(result.candidate, full_bars)
                insert_backtest_candidate(conn, run_id=run_id, candidate=candidate)
                n_candidates += 1

        snapshot = CoverageSnapshot(
            decision_date=decision_date, pit_universe_count=len(pit_ciks),
            sufficient_price_count=sufficient_price, sufficient_fundamentals_count=sufficient_fund,
            scanned_count=scanned, excluded_missing_price_count=excl_price,
            excluded_missing_fundamentals_count=excl_fund,
            stage_no_decline_signal=stage_counts["NO_DECLINE_SIGNAL"],
            stage_excluded_by_prefilter=stage_counts["EXCLUDED_BY_PREFILTER"],
            stage_hard_gate_failed=stage_counts["HARD_GATE_FAILED"],
            stage_candidate=stage_counts["CANDIDATE"],
        )
        coverage_snapshots.append(snapshot)
        insert_backtest_coverage(conn, run_id=run_id, snapshot=snapshot)

        benchmark_snapshot = compute_benchmark_snapshot(
            decision_date=decision_date,
            pit_universe_ciks_with_sufficient_price=pit_ciks_with_sufficient_price,
            price_bars_by_cik=price_bars_by_cik,
            spy_bars=spy_bars,
        )
        benchmark_snapshots.append(benchmark_snapshot)
        insert_backtest_benchmark(conn, run_id=run_id, snapshot=benchmark_snapshot)

        if d_idx % 12 == 0 or d_idx == len(decision_dates):
            conn.commit()
            cov_pct = f"{snapshot.coverage_pct:.1f}%" if snapshot.coverage_pct is not None else "n/a"
            print(
                f"  [{d_idx}/{len(decision_dates)}] {decision_date}: pit={len(pit_ciks)} "
                f"scanned={scanned} coverage={cov_pct} candidates_this_date={stage_counts['CANDIDATE']} "
                f"candidates_total={n_candidates}"
            )

    conn.commit()

    agg = aggregate_coverage(coverage_snapshots)
    print("\n== Coverage (agregat) ==")
    print(f"  Decision dates: {agg.n_decision_dates}")
    print(f"  Suma obserwacji PIT universe: {agg.total_pit_universe_observations}")
    print(f"  Suma faktycznie przeskanowanych: {agg.total_scanned_observations}")
    if agg.overall_coverage_pct is not None:
        print(f"  Overall coverage_pct (ważony obserwacjami): {agg.overall_coverage_pct:.2f}%")
    if agg.coverage_pct_median is not None:
        print(
            f"  coverage_pct min/p10/p25/median/p75/p90/max: "
            f"{agg.coverage_pct_min:.1f} / {agg.coverage_pct_p10:.1f} / {agg.coverage_pct_p25:.1f} / "
            f"{agg.coverage_pct_median:.1f} / {agg.coverage_pct_p75:.1f} / {agg.coverage_pct_p90:.1f} / "
            f"{agg.coverage_pct_max:.1f}"
        )
    print("  Najgorzej pokryte decision dates:")
    for d, pct in agg.worst_decision_dates:
        print(f"    {d}: {pct:.1f}%")

    print("\n== Funnel (suma po wszystkich decision dates x CIK) ==")
    for stage in ("NO_DECLINE_SIGNAL", "EXCLUDED_BY_PREFILTER", "HARD_GATE_FAILED", "CANDIDATE"):
        print(f"  {stage}: {stage_totals[stage]}")

    print("\n== Benchmark (PRIMARY=equal_weighted_pit_universe, SECONDARY=SPY) ==")
    print("  Uwaga: TYLKO sanity-check (średnia prosta po decision_dates, ignorując None).")
    print("  Pełna analiza (median/percentyle/hit rate vs kandydaci) — w raporcie końcowym, nie tutaj.")
    for h in (1, 3, 6, 12):
        ew_field = f"ew_pit_universe_return_{h}m_pct"
        spy_field = f"spy_return_{h}m_pct"
        ew_vals = [getattr(s, ew_field) for s in benchmark_snapshots if getattr(s, ew_field) is not None]
        spy_vals = [getattr(s, spy_field) for s in benchmark_snapshots if getattr(s, spy_field) is not None]
        ew_mean = f"{statistics.mean(ew_vals):.2f}%" if ew_vals else "n/a"
        spy_mean = f"{statistics.mean(spy_vals):.2f}%" if spy_vals else "n/a"
        print(
            f"  {h}m: equal_weighted_pit_universe mean={ew_mean} (n_dates={len(ew_vals)}), "
            f"SPY mean={spy_mean} (n_dates={len(spy_vals)})"
        )

    print(f"\nrun_id={run_id} — wyniki w backtest_coverage/backtest_candidates/backtest_benchmark ({args.db}).")
    print(f"Łącznie kandydatów (CANDIDATE): {n_candidates}")

    return 0


_CALIBRATION_ROUND_REGISTRIES = {
    "1": ROUND_1_CANDIDATES,
    "2a": ROUND_2A_CANDIDATES,
    "2b": ROUND_2B_CANDIDATES,
}


def cmd_run_calibration_candidate(args: argparse.Namespace) -> int:
    """Faza 5.4 — protokół kalibracji zatwierdzony przez właścicielkę
    2026-10-05 (z poprawkami, patrz docs/buffett-scanner-design-review.md,
    sekcja "Faza 5.4"/"Faza 5.4b"). Uruchamia JEDEN kandydat konfiguracji
    na OKNIE KALIBRACYJNYM (2012-01-01..2021-12-01) — okno jest TU ZAWSZE
    HARDKODOWANE z `calibration.py`, NIGDY nie brane z `--window-end`
    użytkownika — to jest fizyczne zablokowanie holdoutu 2022-2026 przed
    przypadkowym dotknięciem w trakcie kalibracji (punkt 1 protokołu).
    Zero zmiany `config/config.yaml` na dysku — kandydat modyfikuje
    WYŁĄCZNIE głęboką kopię configu w pamięci (`CandidateConfig.apply`).
    Persystuje PEŁNE wyniki (backtest_candidates/coverage/benchmark pod
    własnym `run_id=calibration_run_id`) ORAZ zagregowaną ewaluację do
    `calibration_runs` (NIGDY nie usuwana — audytowalność, punkt 11).

    Round 2 (2A/2B, Faza 5.4b) wymaga `--subround a|b` — PRIMARY metric
    tam to Spearman(`deterministic_score_pct`, forward return 6m), NIE
    `pooled_median_excess_return_pct` (ta jest matematycznie niezależna
    od wag scoringu w obecnym harnessie — znalezisko zgłoszone i
    zatwierdzone PRZED napisaniem tego kodu, patrz Faza 5.4b punkt 0);
    stara metryka nadal liczona/zapisana jako DIAGNOSTIC."""
    if args.round == 2:
        if args.subround not in ("a", "b"):
            print("BŁĄD: Round 2 wymaga --subround a|b (2A=SAFETY+DIVIDEND, 2B=VALUATION).", file=sys.stderr)
            return 1
        registry_key = f"2{args.subround}"
    else:
        registry_key = str(args.round)
    registry = _CALIBRATION_ROUND_REGISTRIES.get(registry_key)
    if registry is None:
        print(f"BŁĄD: nieznana runda kalibracji {registry_key} (dostępne: {sorted(_CALIBRATION_ROUND_REGISTRIES)})", file=sys.stderr)
        return 1
    candidate = next((c for c in registry if c.name == args.candidate), None)
    if candidate is None:
        print(f"BŁĄD: nieznany kandydat {args.candidate!r} w rundzie {registry_key} "
              f"(dostępne: {[c.name for c in registry]})", file=sys.stderr)
        return 1

    base_config = load_config()
    config = candidate.apply(base_config)
    config_text = Path(DEFAULT_CONFIG_PATH).read_text(encoding="utf-8")
    config_hash = f"config.yaml:{hashlib.sha256(config_text.encode()).hexdigest()[:16]}"
    config_json = config.model_dump_json()
    calibration_run_id = f"calib-r{registry_key}-{candidate.name}-" + dt.datetime.utcnow().strftime("%Y-%m-%dT%H%M%SZ")

    conn = init_db(args.db)
    index_name = UNIVERSE_MEMBERSHIP_INDEX_NAME
    window_start, window_end = CALIBRATION_WINDOW_START, CALIBRATION_WINDOW_END
    decision_dates = generate_rebalance_dates(window_start, window_end, "MONTHLY")
    print(f"Round {registry_key}, kandydat={candidate.name!r} — {candidate.description}")
    print(f"Okno kalibracyjne (HARDKODOWANE, holdout 2022-2026 zablokowany): {window_start}..{window_end}, "
          f"{len(decision_dates)} decision dates, calibration_run_id={calibration_run_id}")

    all_ciks = list_universe_membership_ciks(conn, index_name)
    if args.sample:
        sample_set = {c.strip() for c in args.sample.split(",") if c.strip()}
        all_ciks = [c for c in all_ciks if c in sample_set]
        print(f"  --sample ograniczenie: {len(all_ciks)} CIK.")
    sector_profiles = get_companies_sector_profiles(conn)
    price_bars_by_cik: dict[str, list[PriceBar]] = {}
    company_facts_by_cik: dict[str, dict] = {}
    for cik in all_ciks:
        rows = get_price_series(conn, cik)
        price_bars_by_cik[cik] = [
            PriceBar(date=r["date"], open=r["open"], high=r["high"], low=r["low"],
                      close=r["close"], adj_close=r["adj_close"], volume=r["volume"])
            for r in rows
        ]
        cf = get_sec_company_facts_cache(conn, cik)
        if cf is not None:
            company_facts_by_cik[cik] = cf

    spy_cik = get_cik_for_active_ticker(conn, "SPY")
    spy_bars: list[PriceBar] | None = None
    if spy_cik is not None:
        spy_rows = get_price_series(conn, spy_cik)
        spy_bars = [
            PriceBar(date=r["date"], open=r["open"], high=r["high"], low=r["low"],
                      close=r["close"], adj_close=r["adj_close"], volume=r["volume"])
            for r in spy_rows
        ]

    all_candidates: list = []
    benchmark_snapshots = []
    for d_idx, decision_date in enumerate(decision_dates, 1):
        pit_ciks = get_universe_membership_as_of(conn, index_name, decision_date)
        if len(pit_ciks) != len(set(pit_ciks)):
            dupes = sorted({c for c in pit_ciks if pit_ciks.count(c) > 1})
            raise RuntimeError(f"FAIL FAST: universe_membership_as_of({decision_date!r}) zwróciło duplikat CIK {dupes}")
        if args.sample:
            pit_ciks = [c for c in pit_ciks if c in all_ciks]

        stage_counts = {"NO_DECLINE_SIGNAL": 0, "EXCLUDED_BY_PREFILTER": 0, "HARD_GATE_FAILED": 0, "CANDIDATE": 0}
        pit_ciks_with_sufficient_price: list[str] = []
        for cik in pit_ciks:
            full_bars = price_bars_by_cik.get(cik, [])
            bars = [b for b in full_bars if b.date <= decision_date]
            cf = company_facts_by_cik.get(cik)
            periods = build_annual_fundamentals_periods_as_of(cf, decision_date) if cf is not None else []
            has_price, has_fund = classify_data_sufficiency(bars=bars, periods=periods)
            if has_price:
                pit_ciks_with_sufficient_price.append(cik)
            if not (has_price and has_fund):
                continue
            result = evaluate_candidate_at_date(
                cik=cik, ticker_as_of_date=cik, decision_date=decision_date,
                bars=bars, periods=periods, sector_profile=sector_profiles.get(cik, "GENERAL"),
                config=config, run_id=calibration_run_id, config_version=config_hash,
                universe_provenance="calibration",
            )
            if result.stage in stage_counts:
                stage_counts[result.stage] += 1
            if result.stage == "CANDIDATE":
                cwf = attach_forward_returns(result.candidate, full_bars)
                insert_backtest_candidate(conn, run_id=calibration_run_id, candidate=cwf)
                all_candidates.append(cwf)

        benchmark_snapshot = compute_benchmark_snapshot(
            decision_date=decision_date, pit_universe_ciks_with_sufficient_price=pit_ciks_with_sufficient_price,
            price_bars_by_cik=price_bars_by_cik, spy_bars=spy_bars,
        )
        benchmark_snapshots.append(benchmark_snapshot)
        insert_backtest_benchmark(conn, run_id=calibration_run_id, snapshot=benchmark_snapshot)
        if d_idx % 24 == 0 or d_idx == len(decision_dates):
            conn.commit()
            print(f"  [{d_idx}/{len(decision_dates)}] {decision_date}: candidates_total={len(all_candidates)}")

    conn.commit()
    print(f"Łącznie kandydatów na oknie kalibracyjnym: {len(all_candidates)}")

    evaluation = evaluate_candidate_configuration(
        candidate_name=candidate.name, round=candidate.round, description=candidate.description,
        candidates=all_candidates, benchmark_snapshots=benchmark_snapshots,
    )

    spearman_evaluation = None
    if args.round == 2:
        spearman_evaluation = evaluate_candidate_configuration_spearman(
            candidate_name=candidate.name, round=candidate.round, subround=registry_key,
            description=candidate.description, candidates=all_candidates,
            require_valuation=(args.subround == "b"),
        )

    insert_calibration_run(
        conn, calibration_run_id=calibration_run_id, evaluation=evaluation,
        config_hash=config_hash, config_json=config_json,
        training_window_start=window_start, training_window_end=window_end,
        oos_fold_years=OOS_FOLD_YEARS, spearman_evaluation=spearman_evaluation,
    )
    conn.commit()

    if spearman_evaluation is not None:
        print(f"\n== PRIMARY metric Round {registry_key} (Faza 5.4b): Spearman(deterministic_score_pct, "
              f"forward return {PRIMARY_HORIZON_MONTHS}m), populacja={spearman_evaluation.population} ==")
        print(f"  A. Pooled OOS: n={spearman_evaluation.pooled_n} spearman={spearman_evaluation.pooled_spearman} "
              f"low_sample={spearman_evaluation.pooled_low_sample}")
        print(f"  B. Fold stability:")
        for m in spearman_evaluation.fold_metrics:
            print(f"     {m.fold_year}: n={m.n} spearman={m.spearman} low_sample={m.low_sample}")
        print(f"     median_of_fold_spearman={spearman_evaluation.median_of_fold_spearman} "
              f"min={spearman_evaluation.min_fold_spearman} max={spearman_evaluation.max_fold_spearman} "
              f"n_positive_folds={spearman_evaluation.n_positive_folds}/{spearman_evaluation.n_folds_with_data}")

        print(f"\n== DIAGNOSTIC (Round 1 primary metric, NIE decyduje w Round 2 — "
              f"matematycznie niezależna od wag, Faza 5.4b punkt 0) ==")
        print(f"  Pooled OOS: n={evaluation.pooled_n} median_excess={evaluation.pooled_median_excess_return_pct} "
              f"low_sample={evaluation.pooled_low_sample}")
    else:
        print(f"\n== PRIMARY metric (horyzont {PRIMARY_HORIZON_MONTHS}m, vs equal_weighted_pit_universe) ==")
        print(f"  A. Pooled OOS: n={evaluation.pooled_n} median_excess={evaluation.pooled_median_excess_return_pct} "
              f"low_sample={evaluation.pooled_low_sample}")
        print(f"  B. Fold stability:")
        for m in evaluation.fold_metrics:
            print(f"     {m.fold_year}: n={m.n} median_excess={m.median_excess_return_pct} low_sample={m.low_sample}")
        print(f"     median_of_fold_medians={evaluation.median_of_fold_medians_pct} "
              f"min={evaluation.min_fold_median_pct} max={evaluation.max_fold_median_pct} "
              f"n_positive_folds={evaluation.n_positive_folds}/{evaluation.n_folds_with_data}")

    print(f"\n== SECONDARY diagnostics (nigdy nie decydują o wyborze) ==")
    for s in evaluation.secondary:
        print(f"  {s.horizon_months}m: hit_rate_vs_ew={s.hit_rate_vs_ew_pct} hit_rate_vs_spy={s.hit_rate_vs_spy_pct} "
              f"median_excess_vs_ew={s.median_excess_vs_ew_pct} median_excess_vs_spy={s.median_excess_vs_spy_pct} "
              f"spearman={s.spearman_score_vs_return} n={s.n_vs_ew} low_sample={s.low_sample}")

    print(f"\ncalibration_run_id={calibration_run_id} — zapisane w calibration_runs, status='candidate' ({args.db}).")
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

    p_live_scan = sub.add_parser("run-live-scan")
    p_live_scan.add_argument(
        "--limit", type=int, default=5, help="Maks. liczba finalnych kandydatów (domyślnie 5).",
    )
    p_live_scan.add_argument(
        "--price-days", type=int, default=400, help="Okno historii cen do decline scanningu (domyślnie 400).",
    )
    p_live_scan.add_argument(
        "--sample", default=None,
        help="Lista tickerów po przecinku — ogranicza zakres (mały test przed pełnym runem na całym S&P 500).",
    )
    p_live_scan.add_argument(
        "--skip-universe-refresh", action="store_true",
        help="Nie odpytuj FMP o aktualne S&P 500 — użyj już zapisanego ticker_history.",
    )
    p_live_scan.add_argument("--markdown-out", default=None, help="Katalog na finalny raport .md")
    p_live_scan.set_defaults(func=cmd_run_live_scan)

    p_pit = sub.add_parser("pit-prototype")
    p_pit.add_argument("tickers", nargs="+")
    p_pit.add_argument("--as-of", default=None, help="Data zapytania PIT (YYYY-MM-DD), domyślnie dziś.")
    p_pit.set_defaults(func=cmd_pit_prototype)

    p_sp500_hist = sub.add_parser("analyze-sp500-history")
    p_sp500_hist.add_argument(
        "--cutoff", default="2012-01-01", help="Początek okna analizy (YYYY-MM-DD, domyślnie D14: 2012-01-01)."
    )
    p_sp500_hist.set_defaults(func=cmd_analyze_sp500_history)

    p_build_membership = sub.add_parser("build-universe-membership")
    p_build_membership.add_argument(
        "--cutoff", default="2012-01-01", help="Początek okna budowy (YYYY-MM-DD, domyślnie D14: 2012-01-01)."
    )
    p_build_membership.set_defaults(func=cmd_build_universe_membership)

    p_backfill = sub.add_parser("backfill-walk-forward-data")
    p_backfill.add_argument(
        "--target", choices=("prices", "fundamentals", "both"), default="both",
        help="Który backfill uruchomić (domyślnie both).",
    )
    p_backfill.add_argument(
        "--cutoff", default="2012-01-01",
        help="Początek okna cen (YYYY-MM-DD, domyślnie D14: 2012-01-01).",
    )
    p_backfill.add_argument(
        "--refresh", action="store_true",
        help="Wymusza ponowne pobranie nawet dla CIK już COMPLETE (domyślnie pominięte, resumability).",
    )
    p_backfill.add_argument(
        "--sample", default=None,
        help="Lista CIK po przecinku — ogranicza zakres (np. mały Proof Run na 10-20 CIK przed pełnym runem).",
    )
    p_backfill.set_defaults(func=cmd_backfill_walk_forward_data)

    p_sector_profiles = sub.add_parser("classify-sector-profiles")
    p_sector_profiles.add_argument(
        "--sample", default=None,
        help="Lista CIK po przecinku — ogranicza zakres (np. mały test przed pełnym runem).",
    )
    p_sector_profiles.set_defaults(func=cmd_classify_sector_profiles)

    p_spy = sub.add_parser("fetch-spy-benchmark-prices")
    p_spy.add_argument(
        "--cutoff", default="2012-01-01",
        help="Początek okna cen SPY (YYYY-MM-DD, domyślnie D14: 2012-01-01, zgodny z resztą backfillu).",
    )
    p_spy.set_defaults(func=cmd_fetch_spy_benchmark_prices)

    p_baseline = sub.add_parser("run-baseline-walk-forward")
    p_baseline.add_argument(
        "--window-start", default="2012-01-01",
        help="Pierwsza decision_date (YYYY-MM-DD, domyślnie D14: 2012-01-01).",
    )
    p_baseline.add_argument(
        "--window-end", default=None,
        help="Ostatnia decision_date (YYYY-MM-DD, domyślnie dziś).",
    )
    p_baseline.add_argument(
        "--sample", default=None,
        help="Lista CIK po przecinku — ogranicza zakres (np. mały test przed pełnym runem).",
    )
    p_baseline.set_defaults(func=cmd_run_baseline_walk_forward)

    p_calibration = sub.add_parser("run-calibration-candidate")
    p_calibration.add_argument(
        "--round", type=int, required=True,
        help="Numer rundy kalibracji (Faza 5.4) — ustala rejestr dostępnych kandydatów.",
    )
    p_calibration.add_argument(
        "--candidate", required=True,
        help="Nazwa kandydata z rejestru tej rundy (patrz calibration_round<N>.py).",
    )
    p_calibration.add_argument(
        "--subround", choices=("a", "b"), default=None,
        help="Wymagane dla --round 2 (Faza 5.4b): a=2A SAFETY+DIVIDEND, b=2B VALUATION.",
    )
    p_calibration.add_argument(
        "--sample", default=None,
        help="Lista CIK po przecinku — ogranicza zakres (mały test przed pełnym kandydatem).",
    )
    p_calibration.set_defaults(func=cmd_run_calibration_candidate)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

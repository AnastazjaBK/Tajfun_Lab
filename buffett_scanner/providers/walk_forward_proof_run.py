"""Tani Proof Run walk-forward backtest harnessu (Faza 5.3, sekcja 13) —
zatwierdzony przez właścicielkę 2026-10-01, PRZED pełnym backfillem.

Mała, reprezentatywna próbka: 3 dobrze znane, stabilne tożsamościowo
spółki (AAPL/MSFT/KO — bez rename/delisting w badanym oknie, celowo,
żeby pierwszy Proof Run harnessu nie mieszał ryzyka nowego mechanizmu z
ryzykiem tożsamości spółki) × 6 dat decyzji rozpiętych na znanym okresie
zmienności rynkowej (spokój przed COVID, krach COVID 2020, odbicie,
bessa 2022) — celowo, żeby naturalnie przejść zarówno ścieżkę
NO_DECLINE_SIGNAL jak i CANDIDATE bez fabrykowania danych.

Sprawdza WPROST (nie tylko przez brak wyjątku):
  1. point-in-time: KAŻDY użyty fakt fundamentalny ma filed_date <= D,
     KAŻDY użyty bar cenowy ma date <= D (asercja, nie tylko print).
  2. brak look-ahead: forward returns liczone WYŁĄCZNIE w osobnym kroku
     (attach_forward_returns), po sfinalizowaniu kandydata.
  3. pełny funnel: decline scanner -> prefilter -> deterministic score
     -> hard gates -> candidate, z jawnym rozbiciem per etap.
  4. forward returns 1m/3m/6m/12m.
  5. pełny decision snapshot + run_id + wersje configu/scoringu.

CELOWO WĄSKI ZAKRES DANYCH FUNDAMENTALNYCH (patrz `pit_fundamentals.py`):
tylko net_income/revenue z rocznych (10-K) faktów SEC XBRL — reszta pól
None. Oznacza to, że scores w tym Proof Run są SYSTEMATYCZNIE niższe niż
będą po pełnym backfillu (więcej pól = więcej możliwych punktów) — to
NIE jest ocena jakości tych spółek, tylko ograniczenie zakresu danych
tego konkretnego etapu.

WYŁĄCZNIE DIAGNOSTYCZNE — nic nie zapisuje do bazy.

    python -m buffett_scanner.providers.walk_forward_proof_run

Wymaga FMP_API_KEY i SEC_EDGAR_USER_AGENT."""

from __future__ import annotations

import datetime as dt
import hashlib
import sys
from pathlib import Path

from buffett_scanner.backtest_harness import attach_forward_returns, evaluate_candidate_at_date
from buffett_scanner.config import DEFAULT_CONFIG_PATH, load_config
from buffett_scanner.pit_fundamentals import build_annual_fundamentals_periods_as_of
from buffett_scanner.providers.fmp import FMPClient, FMPError
from buffett_scanner.providers.sec_edgar import SecEdgarClient, SecEdgarError
from buffett_scanner.scanner import PriceBar

SAMPLE_TICKERS = ("AAPL", "MSFT", "KO")
SECTOR_PROFILE = "GENERAL"  # wszystkie 3 spolki -- trafna klasyfikacja, nie bankowa/ubezpieczeniowa/REIT

# Rozpiete na znanym okresie zmiennosci (spokoj -> krach COVID -> odbicie
# -> bessa 2022) -- celowo, zeby naturalnie przejsc obie sciezki funnelu
# (NO_DECLINE_SIGNAL i CANDIDATE) bez fabrykowania danych. Najpozniejsza
# data zostawia >=12mc miejsca na forward returns przed "dzis" (2026-10-01).
DECISION_DATES = (
    "2019-10-01",
    "2020-02-01",
    "2020-04-01",
    "2020-07-01",
    "2022-01-01",
    "2022-10-01",
)

PRICE_FETCH_FROM = "2018-01-01"
PRICE_FETCH_TO = "2023-12-31"  # >= ostatnia decision_date + 12mc, zapas na forward returns


def _build_price_bars(rows: list[dict]) -> list[PriceBar]:
    return [
        PriceBar(
            date=r["date"], open=r["open"], high=r["high"], low=r["low"],
            close=r["close"], adj_close=r["adj_close"], volume=r["volume"],
        )
        for r in rows
    ]


def main() -> int:
    config = load_config()
    try:
        api_key = config.data_provider.resolve_api_key()
        user_agent = config.sources.sec_edgar.resolve_user_agent()
    except RuntimeError as exc:
        print(f"BŁĄD: {exc}", file=sys.stderr)
        return 1

    config_text = Path(DEFAULT_CONFIG_PATH).read_text(encoding="utf-8")
    config_version = f"config.yaml:{hashlib.sha256(config_text.encode()).hexdigest()[:16]}"
    run_id = "walk-forward-proof-run-" + dt.datetime.utcnow().strftime("%Y-%m-%dT%H%M%SZ")

    print("== Krok 1: rozwiązanie tickerów na CIK przez realną mapę SEC (nigdy zgadywane) ==")
    with SecEdgarClient(user_agent) as sec_client:
        try:
            sec_map = sec_client.get_company_tickers()
        except SecEdgarError as exc:
            print(f"BŁĄD: {exc}", file=sys.stderr)
            return 1
        cik_by_ticker: dict[str, str] = {}
        for ticker in SAMPLE_TICKERS:
            cik = sec_map.get(ticker)
            if cik is None:
                print(f"BŁĄD: {ticker} nierozwiązany w dzisiejszej mapie SEC — nieoczekiwane.", file=sys.stderr)
                return 1
            cik_by_ticker[ticker] = cik
            print(f"  {ticker} -> CIK {cik}")

        print("\n== Krok 2: pobranie company_facts (SEC) i historii cen (FMP) dla próbki ==")
        company_facts_by_ticker: dict[str, dict] = {}
        bars_by_ticker: dict[str, list[PriceBar]] = {}
        try:
            for ticker, cik in cik_by_ticker.items():
                company_facts_by_ticker[ticker] = sec_client.get_company_facts(cik)
        except SecEdgarError as exc:
            print(f"BŁĄD pobierania company_facts: {exc}", file=sys.stderr)
            return 1

        with FMPClient(api_key) as fmp_client:
            try:
                for ticker in SAMPLE_TICKERS:
                    rows = fmp_client.get_historical_prices(
                        ticker, from_date=PRICE_FETCH_FROM, to_date=PRICE_FETCH_TO,
                    )
                    bars_by_ticker[ticker] = _build_price_bars(rows)
                    print(f"  {ticker}: {len(rows)} barów cenowych {PRICE_FETCH_FROM}..{PRICE_FETCH_TO}")
            except FMPError as exc:
                print(f"BŁĄD pobierania cen: {exc}", file=sys.stderr)
                return 1

        print(f"\n== Krok 3: walk-forward dla {len(SAMPLE_TICKERS)} spółek x {len(DECISION_DATES)} dat ==")
        stage_counts: dict[str, int] = {}
        candidates = []
        pit_violations: list[str] = []

        for ticker in SAMPLE_TICKERS:
            cik = cik_by_ticker[ticker]
            all_bars = bars_by_ticker[ticker]
            company_facts = company_facts_by_ticker[ticker]

            for decision_date in DECISION_DATES:
                bars_truncated = sorted(
                    (b for b in all_bars if b.date <= decision_date), key=lambda b: b.date
                )
                periods_truncated = build_annual_fundamentals_periods_as_of(company_facts, decision_date)

                # Jawna, programowa kontrola point-in-time (nie tylko wizualna).
                for p in periods_truncated:
                    if p.filed_date is not None and p.filed_date > decision_date:
                        pit_violations.append(
                            f"{ticker}@{decision_date}: fundamentals filed_date={p.filed_date} > decision_date!"
                        )
                for b in bars_truncated:
                    if b.date > decision_date:
                        pit_violations.append(f"{ticker}@{decision_date}: bar date={b.date} > decision_date!")

                result = evaluate_candidate_at_date(
                    cik=cik, ticker_as_of_date=ticker, decision_date=decision_date,
                    bars=bars_truncated, periods=periods_truncated, sector_profile=SECTOR_PROFILE,
                    config=config, run_id=run_id, config_version=config_version,
                    universe_provenance="PROOF_RUN_SAMPLE_NOT_FROM_UNIVERSE_MEMBERSHIP",
                )
                stage_counts[result.stage] = stage_counts.get(result.stage, 0) + 1
                print(
                    f"  {ticker}@{decision_date}: stage={result.stage}"
                    + (f" periods={len(periods_truncated)} (najnowszy filed={periods_truncated[-1].filed_date})"
                       if periods_truncated else " periods=0")
                )
                if result.stage == "CANDIDATE":
                    candidate_with_future = attach_forward_returns(result.candidate, all_bars)
                    candidates.append(candidate_with_future)

        print("\n== Krok 4: kontrola point-in-time (jawna asercja, nie tylko log) ==")
        if pit_violations:
            print("BŁĄD KRYTYCZNY — naruszenie point-in-time / look-ahead:", file=sys.stderr)
            for v in pit_violations:
                print(f"  {v}", file=sys.stderr)
            return 1
        print(f"  Zero naruszeń point-in-time na {len(SAMPLE_TICKERS) * len(DECISION_DATES)} parach (ticker, data).")

        print("\n== Krok 5: rozbicie funnelu ==")
        for stage in ("NO_FUNDAMENTALS", "NO_DECLINE_SIGNAL", "EXCLUDED_BY_PREFILTER", "HARD_GATE_FAILED", "CANDIDATE"):
            print(f"  {stage}: {stage_counts.get(stage, 0)}")

        print(f"\n== Krok 6: pełny decision snapshot dla {len(candidates)} kandydatów ==")
        for c in candidates:
            print(f"  -- {c.ticker_as_of_date} @ {c.decision_date} (CIK={c.cik}, run_id={c.run_id}) --")
            print(f"     decline_flags={c.decline_flags}")
            print(f"     PIT fundamentals: period_end={c.pit_fundamentals_period_end} filed={c.pit_fundamentals_filed_date}")
            print(f"     financial_quality_breakdown={c.financial_quality_breakdown}")
            print(
                f"     safety={c.safety_score:.2f} valuation={c.valuation_score} dividend={c.dividend_score:.2f} "
                f"full_score={c.full_score} deterministic_partial={c.deterministic_partial_score:.2f} "
                f"deterministic_pct={c.deterministic_score_pct}"
            )
            print(f"     available={c.available_components} missing={c.missing_components}")
            print(f"     hard_gate_passed={c.hard_gate_passed} triggered={c.hard_gate_triggered}")
            print(f"     margin_of_safety_base_pct={c.margin_of_safety_base_pct}")
            print(f"     decision_price={c.decision_price} config_version={c.config_version} scoring_version={c.scoring_version}")
            fr = c.forward_returns
            print(
                f"     forward_returns: 1m={fr.return_1m_pct} 3m={fr.return_3m_pct} "
                f"6m={fr.return_6m_pct} 12m={fr.return_12m_pct}"
            )

        print(
            "\nUWAGA: deterministic_score w tym Proof Run pokrywa WYŁĄCZNIE net_income/revenue "
            "(PIT z SEC XBRL rocznych 10-K) — reszta pól fundamentalnych jest None. Scores są "
            "systematycznie niższe niż będą po pełnym backfillu; to ograniczenie zakresu tego etapu, "
            "nie ocena jakości tych spółek. full_score jest zawsze None (brak historycznego LLM, "
            "zgodnie z decyzją właścicielki) — nigdy nie prezentować jako pełnego wyniku."
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

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

ROZSZERZONY ZAKRES DANYCH FUNDAMENTALNYCH (Faza 5.3b, dependency audit
2026-10-01/02, patrz `pit_fundamentals.py`): 11 z 12 wymaganych pól z
rocznych (10-K) faktów SEC XBRL, włącznie z kompozytem EBITDA
(OperatingIncomeLoss + D&A, zasady 1-5 zatwierdzone przez właścicielkę
2026-10-02). `total_debt` jest jawnie None (brak jednego uniwersalnego
tagu SEC XBRL — decyzja o kompozycie current/noncurrent jeszcze
nierozstrzygnięta) — to NIE jest ocena jakości tych spółek, tylko znana
granica tego etapu.

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
from buffett_scanner.pit_fundamentals import (
    DURATION_CONCEPTS,
    EBITDA_COMPONENT_CONCEPTS,
    INSTANT_CONCEPTS,
    _is_annual_duration,
    build_annual_fundamentals_periods_as_of,
    fact_duration_days,
)
from buffett_scanner.providers.fmp import FMPClient, FMPError
from buffett_scanner.providers.sec_edgar import SecEdgarClient, SecEdgarError
from buffett_scanner.point_in_time import CANDIDATE_TAGS, find_first_matching_tag, value_as_of
from buffett_scanner.scanner import PriceBar

# 12 pol FundamentalsPeriod wymaganych przez istniejacy deterministic
# pipeline (dependency audit 2026-10-01/02) -- total_debt swiadomie
# wylaczone z tej listy, patrz komentarz w _diagnose_fields_for_period.
SIMPLE_FIELD_CONCEPTS = DURATION_CONCEPTS + INSTANT_CONCEPTS

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


def _diagnose_one_concept(
    company_facts: dict, concept: str, *, period_end: str, as_of_date: str, is_instant: bool
) -> dict:
    """Jeden wiersz diagnostyki dla jednego konceptu XBRL: znaleziony
    tag, start/end/filed/duration/wartość albo jawny powód braku.
    `is_instant=True` pomija walidację duration (koncepty bilansowe nie
    mają `start` z definicji — patrz pit_fundamentals.py)."""
    found = find_first_matching_tag(company_facts, concept)
    if found is None:
        return {"concept": concept, "tag": None, "missing": True, "reason": "brak kandydackiego tagu w danych spółki"}
    tag, history = found
    if not is_instant:
        history = [f for f in history if _is_annual_duration(f)]
    facts_for_end = [f for f in history if f.end == period_end]
    fact = value_as_of(facts_for_end, as_of_date)
    if fact is None:
        reason = (
            "brak faktu dla tego period_end on/before as_of_date"
            if is_instant
            else "brak faktu dla tego period_end on/before as_of_date PO filtrze duration (350-380 dni)"
        )
        return {"concept": concept, "tag": tag, "missing": True, "reason": reason}
    return {
        "concept": concept, "tag": tag, "missing": False,
        "start": fact.start, "end": fact.end, "filed": fact.filed,
        "duration_days": fact_duration_days(fact), "val": fact.val,
    }


def _print_field_row(row: dict) -> None:
    if row["missing"]:
        tag_part = f"tag={row['tag']}" if row["tag"] else "tag=ŻADEN_KANDYDAT"
        print(f"      {row['concept']:<28} {tag_part:<45} MISSING ({row['reason']})")
    else:
        print(
            f"      {row['concept']:<28} tag={row['tag']:<40} "
            f"start={row['start']} end={row['end']} filed={row['filed']} "
            f"duration_days={row['duration_days']} val={row['val']}"
        )


def _diagnose_raw_tags_matching_keywords(company_facts: dict, *, keywords: tuple[str, ...]) -> None:
    """Krok 2c: surowy dump WSZYSTKICH tagów us-gaap, których nazwa
    semantycznie zawiera jedno ze `keywords` (case-insensitive) — każdy
    wpis z tagiem/unit/start/end/duration/filed/form/val. Cel: ustalić z
    REALNYCH danych, czy spółka taguje dany koncept pod innym, nieujętym
    jeszcze w CANDIDATE_TAGS standardowym tagiem, zamiast zgadywać z
    pamięci które tagi 'zwykle' istnieją."""
    us_gaap = company_facts.get("facts", {}).get("us-gaap", {})
    matching_tags = sorted(tag for tag in us_gaap if any(kw in tag.lower() for kw in keywords))
    if not matching_tags:
        print(f"  ŻADEN tag us-gaap nie zawiera semantycznie {keywords} dla tej spółki.")
        return
    for tag in matching_tags:
        units = us_gaap[tag].get("units", {})
        for unit_name, entries in units.items():
            print(f"  tag={tag} unit={unit_name} ({len(entries)} wpisów)")
            for e in entries:
                start, end = e.get("start"), e.get("end")
                duration_days = None
                if start and end:
                    try:
                        duration_days = (dt.date.fromisoformat(end) - dt.date.fromisoformat(start)).days
                    except ValueError:
                        duration_days = None
                print(
                    f"    start={start} end={end} duration_days={duration_days} "
                    f"filed={e.get('filed')} form={e.get('form')} val={e.get('val')}"
                )


def _diagnose_fields_for_period(company_facts: dict, *, period_end: str, as_of_date: str) -> None:
    """Krok 2b: dla jednego (period_end, as_of_date) pokazuje per-pole
    tag/PIT/duration/wartość/missing dla wszystkich 12 wymaganych pól
    FundamentalsPeriod (dependency audit 2026-10-01/02) + oba składniki
    EBITDA z osobnym provenance przed złożeniem wyniku (zasady 1-5,
    zatwierdzone 2026-10-02)."""
    print(f"    -- period_end={period_end} as_of_date={as_of_date} --")
    for concept in DURATION_CONCEPTS:
        _print_field_row(_diagnose_one_concept(company_facts, concept, period_end=period_end, as_of_date=as_of_date, is_instant=False))
    for concept in INSTANT_CONCEPTS:
        _print_field_row(_diagnose_one_concept(company_facts, concept, period_end=period_end, as_of_date=as_of_date, is_instant=True))
    print(
        "      total_debt                   tag=N/A — NOT_IMPLEMENTED: SEC XBRL nie ma jednego "
        "uniwersalnego tagu total debt (current/noncurrent/short-term borrowings dzielone różnie "
        "między spółkami); kompozyt wymaga osobnej decyzji właścicielki (dependency audit "
        "2026-10-02, jeszcze nierozstrzygnięte) — jawnie None, nigdy zgadywane."
    )
    print("      -- składniki EBITDA (kompozyt, zasady 1-5) --")
    component_rows = {}
    for concept in EBITDA_COMPONENT_CONCEPTS:
        row = _diagnose_one_concept(company_facts, concept, period_end=period_end, as_of_date=as_of_date, is_instant=False)
        component_rows[concept] = row
        _print_field_row(row)
    oi_row = component_rows["operating_income_loss"]
    da_row = component_rows["depreciation_and_amortization"]
    if oi_row["missing"] or da_row["missing"]:
        print("      ebitda (złożone)            = None (co najmniej jeden składnik MISSING — zero substytutu/fallbacku)")
    else:
        ebitda = oi_row["val"] + da_row["val"]
        print(f"      ebitda (złożone)            = {ebitda} (operating_income_loss {oi_row['val']} + D&A {da_row['val']}, ten sam period_end)")


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

        print(
            "\n== Krok 2a: SUROWA diagnostyka SEC XBRL (dodane po realnym run 2026-10-01: "
            "periods=42-54 zamiast oczekiwanych ~10, PRZED zaufaniem wynikom) =="
        )
        diag_facts = sec_client.get_company_facts(cik_by_ticker["AAPL"])
        for concept in ("net_income", "revenue"):
            found = None
            for tag in CANDIDATE_TAGS.get(concept, []):
                try:
                    entries = diag_facts["facts"]["us-gaap"][tag]["units"]["USD"]
                except (KeyError, TypeError):
                    continue
                found = (tag, entries)
                break
            if found is None:
                print(f"  AAPL {concept}: ŻADEN kandydacki tag nie znaleziony.")
                continue
            tag, entries = found
            fy_entries = [e for e in entries if e.get("fp") == "FY"]
            distinct_ends = sorted({e.get("end") for e in fy_entries})
            print(f"  AAPL {concept} (tag={tag}): {len(entries)} wpisów razem, {len(fy_entries)} z fp=='FY', "
                  f"{len(distinct_ends)} odrębnych 'end'.")
            print(f"    Wszystkie klucze obecne w pierwszym wpisie fp=='FY': {sorted(fy_entries[0].keys()) if fy_entries else '(brak)'}")
            # Dla jednej konkretnej daty 'end' pokaż WSZYSTKIE surowe wpisy (pełne pola) —
            # jeśli jest ich wiele dla tego samego end, to klucz do zagadki.
            if distinct_ends:
                sample_end = distinct_ends[len(distinct_ends) // 2]
                same_end_entries = [e for e in fy_entries if e.get("end") == sample_end]
                print(f"    Przykład: wszystkie wpisy fp=='FY' dla end={sample_end!r} ({len(same_end_entries)} szt.):")
                for e in same_end_entries:
                    print(f"      {e}")

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

        print(
            "\n== Krok 2b: diagnostyka pokrycia 12 wymaganych pól (dependency audit "
            "2026-10-01/02), najnowszy roczny okres jako-of ostatniej daty decyzyjnej =="
        )
        last_decision_date = DECISION_DATES[-1]
        for ticker in SAMPLE_TICKERS:
            company_facts = company_facts_by_ticker[ticker]
            periods_for_diag = build_annual_fundamentals_periods_as_of(company_facts, last_decision_date)
            print(f"  -- {ticker} (as_of_date={last_decision_date}) --")
            if not periods_for_diag:
                print("     brak żadnego rozpoznanego rocznego okresu (net_income/revenue) — pomijam diagnostykę pól.")
                continue
            latest_period_end = periods_for_diag[-1].period_end_date
            _diagnose_fields_for_period(company_facts, period_end=latest_period_end, as_of_date=last_decision_date)

        print(
            "\n== Krok 2c: SUROWA diagnostyka tagów MSFT zawierających Depreciation/Depletion/"
            "Amortization (dodane po realnym run 2026-10-02: D&A MISSING u MSFT — żaden z 3 "
            "kandydackich tagów nie pasuje; sprawdzamy, czy MSFT taguje D&A pod innym standardowym "
            "tagiem, zamiast zgadywać z pamięci) =="
        )
        _diagnose_raw_tags_matching_keywords(
            company_facts_by_ticker["MSFT"], keywords=("depreciation", "depletion", "amortization")
        )

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
            "\nUWAGA: deterministic_score w tym Proof Run pokrywa 11 z 12 wymaganych pól "
            "(dependency audit 2026-10-01/02) — PIT z SEC XBRL rocznych 10-K, włącznie z "
            "kompozytem EBITDA (OperatingIncomeLoss + D&A). `total_debt` jest jawnie None "
            "(brak jednego uniwersalnego tagu SEC XBRL — decyzja o kompozycie current/noncurrent "
            "jeszcze nierozstrzygnięta), co obniża net_debt_to_ebitda/net_debt do None tam, gdzie "
            "total_debt byłby potrzebny. Scores mogą być niższe niż po ostatecznym rozstrzygnięciu "
            "total_debt; to znana granica tego etapu, nie ocena jakości tych spółek. full_score "
            "jest zawsze None (brak historycznego LLM, zgodnie z decyzją właścicielki) — nigdy nie "
            "prezentować jako pełnego wyniku."
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

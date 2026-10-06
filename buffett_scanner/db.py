"""Warstwa bazy danych — Faza 0 + Faza 1.

Faza 0 (sekcja 15, punkty 0.2/0.3/0.5 planu implementacji): companies,
ticker_history, price_daily, users. Faza 1 (punkt 1.1): fundamentals_raw
(format long, surowe dane "as reported"), derived_metrics (wyliczone
wskaźniki, wersjonowane przez calc_version). Tożsamość spółki to CIK,
nigdy ticker (patrz sekcja 5 design review — ryzyko "ticker recycling").
Pozostałe tabele ze zaprojektowanego schematu (analyses, moduł
BIOTECH, ...) należą do późniejszych faz i nie są tu tworzone — nie
rozszerzamy MVP przed czasem.

Faza 7 (UI + PORTFOLIO V0, 2026-10-06): `user_decisions`/`positions`/
`purchase_transactions`/`sale_transactions`/`purchase_thesis`/
`holding_user_actions` — dokładnie schemat z sekcji 1.1/16 design
review, z dwoma punktowymi rozszerzeniami zatwierdzonymi przez
właścicielkę (patrz komentarze przy każdej tabeli): `broker`/
`acquisition_type` na transakcjach, `positions.cik` NULLABLE.
`watchlist` celowo NIE tworzone w V0 — żadna funkcja UI jej dziś nie
wymaga (decyzje kandydatów w pełni pokryte przez `user_decisions`);
dodać dopiero, gdy pojawi się realna potrzeba (added_price/next_review_
trigger), nie z góry.

SQLite teraz, Postgres/Supabase od V1 (Decyzja D5) — typy i DDL
poniżej celowo unikają konstrukcji specyficznych dla SQLite, żeby
migracja nie wymagała przeprojektowania modelu danych.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from buffett_scanner.fundamentals import FundamentalsPeriod
from buffett_scanner.providers.claude import ClaudeUsage

# Kanoniczne nazwy line_item używane przy zapisie/odczycie fundamentals_raw
# — muszą być spójne między ingestem (cli.py) a pivotowaniem tutaj.
_INCOME_STATEMENT_ITEMS = {"revenue", "net_income", "ebitda", "diluted_shares_outstanding"}
_BALANCE_SHEET_ITEMS = {
    "total_debt", "cash_and_equivalents",
    "total_current_assets", "total_current_liabilities",
}
_CASH_FLOW_ITEMS = {"operating_cash_flow", "capital_expenditure", "dividends_paid", "share_buybacks"}

LINE_ITEM_STATEMENT_TYPE = {
    **{k: "INCOME_STATEMENT" for k in _INCOME_STATEMENT_ITEMS},
    **{k: "BALANCE_SHEET" for k in _BALANCE_SHEET_ITEMS},
    **{k: "CASH_FLOW" for k in _CASH_FLOW_ITEMS},
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS companies (
    cik             TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    sector          TEXT,
    industry        TEXT,
    sub_industry    TEXT,
    sector_profile  TEXT NOT NULL DEFAULT 'GENERAL'
                    CHECK (sector_profile IN ('GENERAL','BANK','INSURER','REIT','BIOTECH')),
    is_active       INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS ticker_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    cik         TEXT NOT NULL REFERENCES companies(cik),
    ticker      TEXT NOT NULL,
    start_date  TEXT NOT NULL,
    end_date    TEXT,
    UNIQUE (cik, ticker, start_date)
);
CREATE INDEX IF NOT EXISTS idx_ticker_history_ticker ON ticker_history(ticker);

CREATE TABLE IF NOT EXISTS price_daily (
    cik         TEXT NOT NULL REFERENCES companies(cik),
    date        TEXT NOT NULL,
    open        REAL,
    high        REAL,
    low         REAL,
    close       REAL,
    adj_close   REAL,
    volume      INTEGER,
    source      TEXT NOT NULL,
    ingested_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (cik, date)
);

-- Minimalna, bez auth — fundament pod user_id w Fazach 6/7/9
-- (sekcja 1.1 design review). Nie rozszerza zakresu Fazy 0 o UI/logowanie.
CREATE TABLE IF NOT EXISTS users (
    user_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    display_name TEXT NOT NULL,
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Faza 1 — surowe dane fundamentalne, format long: korekty/restatements
-- NIE nadpisują wartości "as reported" (nowy wiersz, nie UPDATE).
-- filed_date krytyczne dla point-in-time (sekcja 13 design review).
CREATE TABLE IF NOT EXISTS fundamentals_raw (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    cik             TEXT NOT NULL REFERENCES companies(cik),
    fiscal_period   TEXT NOT NULL,
    period_end_date TEXT NOT NULL,
    filed_date      TEXT,
    statement_type  TEXT NOT NULL
                    CHECK (statement_type IN ('INCOME_STATEMENT','BALANCE_SHEET','CASH_FLOW')),
    line_item       TEXT NOT NULL,
    value           REAL,
    unit            TEXT,
    source          TEXT NOT NULL,
    source_doc_id   TEXT,
    ingested_at     TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (cik, fiscal_period, statement_type, line_item, source)
);
CREATE INDEX IF NOT EXISTS idx_fundamentals_raw_cik_period
    ON fundamentals_raw(cik, fiscal_period);

-- Faza 1 — wskaźniki wyliczone z fundamentals_raw. calc_version pozwala
-- przeliczyć historię bez utraty poprzednich wyników (sekcja 10/11).
CREATE TABLE IF NOT EXISTS derived_metrics (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    cik          TEXT NOT NULL REFERENCES companies(cik),
    as_of_date   TEXT NOT NULL,
    metric_name  TEXT NOT NULL,
    value        REAL,
    calc_version TEXT NOT NULL,
    inputs_hash  TEXT,
    ingested_at  TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (cik, as_of_date, metric_name, calc_version)
);

-- Faza 4 — wersjonowanie modelu scoringu (sekcja 11 design review):
-- każdy wiersz `analyses` wskazuje na ZAMROŻONY snapshot wag/bramek tu
-- zapisany, nie na "aktualny" config — v1.3 configu nie może nadpisać
-- wyników policzonych pod v1.2.
CREATE TABLE IF NOT EXISTS scoring_model_versions (
    version        TEXT PRIMARY KEY,
    description    TEXT,
    weights_json   TEXT NOT NULL,
    gates_json     TEXT NOT NULL,
    effective_from TEXT NOT NULL DEFAULT (datetime('now')),
    effective_to   TEXT,
    created_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Faza 4 — wyniki analiz. IMMUTABLE: ponowna ocena spółki = nowy
-- wiersz (INSERT), nigdy UPDATE (sekcja 11). `input_dataset_snapshot_id`
-- z projektu schematu (sekcja 5) celowo pominięty na razie — pełna
-- infrastruktura data_snapshots/run_log nie jest jeszcze zbudowana
-- (poza zakresem "silnik scoringu + hard gates + raport" z sekcji 15).
-- margin_of_safety_bear/bull_pct: rozszerzenie względem pierwotnego
-- projektu schematu — zatwierdzony design (2026-09-25) wymaga widoczności
-- wszystkich trzech scenariuszy w raporcie, nie tylko BASE.
CREATE TABLE IF NOT EXISTS analyses (
    analysis_id               INTEGER PRIMARY KEY AUTOINCREMENT,
    cik                       TEXT NOT NULL REFERENCES companies(cik),
    run_date                  TEXT NOT NULL,
    price_at_analysis         REAL,
    scoring_model_version     TEXT NOT NULL REFERENCES scoring_model_versions(version),
    business_quality_score    REAL,
    moat_score                REAL,
    financial_quality_score   REAL,
    management_score          REAL,
    safety_score              REAL,
    valuation_score           REAL,
    fear_score                REAL,
    dividend_score            REAL,
    total_score               REAL,
    hard_flags                TEXT,     -- JSON
    hard_gates_passed         INTEGER,
    valuation_range_low       REAL,     -- BEAR intrinsic value/akcję
    valuation_range_base      REAL,     -- BASE intrinsic value/akcję
    valuation_range_high      REAL,     -- BULL intrinsic value/akcję
    margin_of_safety_pct      REAL,     -- BASE — używany przez hard gate
    margin_of_safety_bear_pct REAL,
    margin_of_safety_bull_pct REAL,
    fear_classification       TEXT,
    fear_confidence           TEXT,
    llm_model_id              TEXT,
    llm_schema_version        TEXT,
    llm_raw_output            TEXT,     -- JSON
    -- Faza 6e (2026-10-06) — telemetria realnego `response`/`response.
    -- usage` z `anthropic==1.8.0` (zweryfikowane przez inspekcję
    -- zainstalowanego SDK, nigdy nie zakładane). `llm_response_model`
    -- to RZECZYWISTY `response.model` (ground truth), odrębny od
    -- `llm_model_id` (configu) -- oba powinny się zgadzać, ale nie
    -- ufamy temu bez weryfikacji. Brak liczonego kosztu $ -- NIE mamy
    -- dziś zweryfikowanego cennika per-token (COST AUDIT, Faza 6d).
    llm_response_model              TEXT,
    llm_input_tokens                INTEGER,
    llm_output_tokens               INTEGER,
    llm_cache_creation_input_tokens INTEGER,
    llm_cache_read_input_tokens     INTEGER,
    llm_thinking_tokens             INTEGER,
    llm_service_tier                TEXT,
    -- Faza 6h (2026-10-06, TARGETED FIELD REPAIR) — usage ODRĘBNEGO,
    -- minimalnego repair call (`repair_thesis_invalidation`), gdy pełna
    -- analiza miała jedyny semantycznie puste `thesis_invalidation`.
    -- NULL, gdy repair nie był potrzebny (pełna analiza przeszła od
    -- razu) -- nigdy nie wymyślamy wartości. Odrębne od llm_* powyżej
    -- (usage pełnego analysis call), żeby audyt mógł rozróżnić
    -- full_analysis_call od thesis_invalidation_repair_call.
    llm_repair_response_model              TEXT,
    llm_repair_input_tokens                INTEGER,
    llm_repair_output_tokens               INTEGER,
    llm_repair_cache_creation_input_tokens INTEGER,
    llm_repair_cache_read_input_tokens     INTEGER,
    llm_repair_thinking_tokens             INTEGER,
    llm_repair_service_tier                TEXT,
    created_at                TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_analyses_cik_run_date ON analyses(cik, run_date);

-- Faza 4 — źródła przypięte do konkretnej analizy (domyka lukę z Fazy 2:
-- VerifiedSource nie miał gdzie trafić, bo analysis_id nie istniał).
-- WYŁĄCZNIE realnie pobrane i zweryfikowane (BLOCKER 3, sekcja 9) —
-- ta tabela nigdy nie jest zapisywana na podstawie twierdzenia LLM.
CREATE TABLE IF NOT EXISTS analysis_sources (
    source_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    analysis_id       INTEGER NOT NULL REFERENCES analyses(analysis_id),
    source_type       TEXT NOT NULL
                      CHECK (source_type IN ('SEC_FILING','IR_DOC','PRESS_RELEASE','EARNINGS_CALL','OTHER')),
    title             TEXT,
    issuer            TEXT,
    doc_date          TEXT,
    url               TEXT,
    accession_number  TEXT,
    section           TEXT,
    page              INTEGER,
    content_hash      TEXT,
    verified          INTEGER NOT NULL,
    reason            TEXT,
    question          TEXT
);
CREATE INDEX IF NOT EXISTS idx_analysis_sources_analysis_id ON analysis_sources(analysis_id);

-- Faza 5.2 — domknięcie OPEN BLOCKER 2 (v1.35, projekt zatwierdzony
-- 2026-09-30). fja05680 jest JEDYNYM źródłem tej tabeli (kolumna
-- `source`, na razie zawsze 'fja05680') — FMP jest niezależnym
-- walidatorem, nigdy nie nadpisuje cik/start_date/end_date, tylko
-- opisuje zgodność przez kolumny entry_validation_*/exit_validation_*.
-- end_date WYŁĄCZNY (pierwszy dzień potwierdzonej nieobecności) —
-- ten sam wzorzec co `value_as_of`/`tickers_as_of` (sekcja 13/5.1/5.2).
CREATE TABLE IF NOT EXISTS universe_membership (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    cik                         TEXT NOT NULL REFERENCES companies(cik),
    index_name                  TEXT NOT NULL,
    start_date                  TEXT NOT NULL,
    end_date                    TEXT,
    source                      TEXT NOT NULL DEFAULT 'fja05680',
    source_snapshot_ref         TEXT NOT NULL,
    cik_resolution_method       TEXT NOT NULL
                                CHECK (cik_resolution_method IN ('DIRECT','FORMAT_VARIANT','CURATED_ALLOWLIST')),
    -- Faza 5.3 (LIMITED_BUT_HONEST, v1.39, zatwierdzone 2026-10-01):
    -- pełna nota provenance (old/new ticker, run_id, rule_version,
    -- evidence) dla wierszy cik_resolution_method='CURATED_ALLOWLIST'.
    -- NULL dla DIRECT/FORMAT_VARIANT. Patrz universe_ticker_rename_allowlist.py.
    cik_resolution_note         TEXT,
    entry_validation_status     TEXT NOT NULL DEFAULT 'NOT_VALIDATED'
                                CHECK (entry_validation_status IN ('MATCHED','ONLY_CANONICAL','NOT_VALIDATED')),
    entry_validation_day_diff   INTEGER,
    exit_validation_status      TEXT
                                CHECK (exit_validation_status IS NULL
                                       OR exit_validation_status IN ('MATCHED','ONLY_CANONICAL','NOT_VALIDATED')),
    exit_validation_day_diff    INTEGER,
    validation_tolerance_days   INTEGER,
    validation_date_field       TEXT CHECK (validation_date_field IS NULL OR validation_date_field IN ('date','dateAdded')),
    -- Wersja LOGIKI dopasowania (np. 'cik_tolerance_match_v1'), ODRĘBNA
    -- od parametrów (validation_tolerance_days/validation_date_field) —
    -- pozwala historycznie odróżnić wynik policzony starym algorytmem od
    -- nowego, nawet przy tych samych parametrach (wymóg właścicielki,
    -- 2026-09-30, przed implementacją tej tabeli).
    validation_rule_version     TEXT,
    validation_run_id           TEXT,
    -- Decyzja właścicielki 2026-10-04: audytowalny ślad, że ten wiersz
    -- company-level jest wynikiem unii >1 NAKŁADAJĄCYCH SIĘ (nie tylko
    -- sąsiadujących) source intervals tego samego CIK -- typowo
    -- dual-class share tickery (GOOGL/GOOG, UAA/UA, NWSA/NWS, FOXA/FOX).
    -- NULL dla zwykłego, jednego interwału albo zero-gap rename
    -- (adjacency) -- to nie jest "nowa" normalizacja wymagająca noty.
    -- Patrz universe_membership_build.merge_adjacent_same_cik_intervals.
    overlap_merge_note          TEXT,
    created_at                  TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (cik, index_name, start_date)
);
CREATE INDEX IF NOT EXISTS idx_universe_membership_index_dates
    ON universe_membership(index_name, start_date, end_date);

-- Audytowalny log rozbieżności fja05680 (kanoniczne) vs FMP (walidator)
-- po CIK i tolerancji dat — WYŁĄCZNIE do ręcznego przeglądu, nigdy nie
-- modyfikuje universe_membership. Obejmuje też ONLY_VALIDATOR, dla
-- którego nie istnieje żaden wiersz w universe_membership (fja05680 go
-- nie potwierdził), więc ten log jest jedynym miejscem, gdzie taki
-- przypadek jest widoczny.
CREATE TABLE IF NOT EXISTS universe_membership_conflicts (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    cik                      TEXT NOT NULL,
    index_name               TEXT NOT NULL,
    event_date               TEXT NOT NULL,
    action                   TEXT NOT NULL CHECK (action IN ('ADD','REMOVE')),
    conflict_type            TEXT NOT NULL CHECK (conflict_type IN ('ONLY_CANONICAL','ONLY_VALIDATOR')),
    tolerance_days           INTEGER NOT NULL,
    date_field                TEXT NOT NULL CHECK (date_field IN ('date','dateAdded')),
    validation_rule_version  TEXT NOT NULL,
    validation_run_id        TEXT NOT NULL,
    review_note              TEXT,   -- ręczna adnotacja po przeglądzie, nigdy automatyczna
    created_at                TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_universe_membership_conflicts_cik ON universe_membership_conflicts(cik);

-- Tickery z kanonicznego źródła, które NIE dostały CIK (CIK_UNRESOLVED)
-- — nie generują wiersza w universe_membership, ale zostają jawnie
-- widoczne tutaj, nigdy nie znikają bez śladu.
CREATE TABLE IF NOT EXISTS universe_membership_unresolved_tickers (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    source                TEXT NOT NULL,
    ticker                TEXT NOT NULL,
    index_name            TEXT NOT NULL,
    source_snapshot_ref   TEXT NOT NULL,
    run_id                TEXT NOT NULL,
    created_at            TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (source, ticker, index_name, run_id)
);

-- Faza 5.3b (walk-forward backtest, dependency audit 2026-10-02/03) --
-- cache WYLACZNIE surowego SEC Company Facts JSON, zeby kolejne
-- backtesty nie wymagaly ponownego pelnego pobierania z SEC EDGAR.
-- Przechowuje SOURCE DATA as-is, NIGDY wyliczonych historycznych
-- fundamentals ani snapshotow as_of -- rekonstrukcja PIT
-- (`pit_fundamentals.build_annual_fundamentals_periods_as_of`) dzieje
-- sie identycznie przy KAZDYM wywolaniu, niezaleznie od tego, czy JSON
-- przyszedl z sieci czy z tego cache (zero zmiany logiki PIT).
-- `fetched_at` opisuje WYLACZNIE moment pobrania kopii do cache --
-- NIGDY dostepnosci historycznego faktu (to wynika z `filed` w samym
-- JSON, patrz point_in_time.py). Calkowicie niezalezna od
-- `fundamentals_raw` (ta zostaje bez zmian, sciezka FMP/live-scan).
CREATE TABLE IF NOT EXISTS sec_company_facts_cache (
    cik             TEXT PRIMARY KEY REFERENCES companies(cik),
    raw_json        TEXT NOT NULL,
    source          TEXT NOT NULL DEFAULT 'sec_edgar',
    payload_sha256  TEXT NOT NULL,
    fetched_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Faza 5.3b (backfill 626 CIK, zatwierdzony projekt 2026-10-03) --
-- jawny status kazdego (cik, task_type) na potrzeby resumability.
-- Latwa obecnosc wierszy w price_daily/sec_company_facts_cache NIE
-- jest dowodem kompletnosci (Decyzja wlascicielki: PARTIAL musi byc
-- rozpoznawalne od COMPLETE) -- stad osobna, jawna klasyfikacja per
-- CIK/task, nadpisywana (najnowszy status wygrywa) przy kazdym
-- przebiegu/wznowieniu backfillu. `run_id` to OSTATNI run, ktory
-- zaktualizowal ten wiersz -- audyt, nie historia wszystkich przebiegow.
CREATE TABLE IF NOT EXISTS backfill_status (
    cik           TEXT NOT NULL REFERENCES companies(cik),
    task_type     TEXT NOT NULL CHECK (task_type IN ('PRICES','FUNDAMENTALS')),
    status        TEXT NOT NULL CHECK (status IN ('COMPLETE','PARTIAL','FAILED','NOT_ATTEMPTED')),
    detail        TEXT,
    run_id        TEXT NOT NULL,
    updated_at    TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (cik, task_type)
);

-- Faza 5.3c (pelny baseline walk-forward, Decyzja wlascicielki
-- 2026-10-04) -- jeden wiersz per decision_date, MIERZONY NIEZALEZNIE
-- od tego, czy ktokolwiek zostal kandydatem. "Brak danych... moze
-- powodowac selection/coverage bias, poniewaz missingness nie musi byc
-- losowe" -- stad explicit coverage, nigdy tylko liczba kandydatow.
CREATE TABLE IF NOT EXISTS backtest_coverage (
    run_id                              TEXT NOT NULL,
    decision_date                       TEXT NOT NULL,
    pit_universe_count                  INTEGER NOT NULL,
    sufficient_price_count              INTEGER NOT NULL,
    sufficient_fundamentals_count       INTEGER NOT NULL,
    scanned_count                       INTEGER NOT NULL,
    excluded_missing_price_count        INTEGER NOT NULL,
    excluded_missing_fundamentals_count INTEGER NOT NULL,
    stage_no_decline_signal             INTEGER NOT NULL,
    stage_excluded_by_prefilter         INTEGER NOT NULL,
    stage_hard_gate_failed              INTEGER NOT NULL,
    stage_candidate                     INTEGER NOT NULL,
    created_at                          TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (run_id, decision_date)
);

-- Faza 5.3c -- jeden wiersz per (run_id, decision_date, cik) ktory
-- osiagnal stage=CANDIDATE. full_score NIE jest kolumna -- zawsze
-- None w tym trybie (brak historycznego LLM), nie fabrykujemy kolumny
-- sugerujacej jego istnienie.
CREATE TABLE IF NOT EXISTS backtest_candidates (
    run_id                      TEXT NOT NULL,
    decision_date                TEXT NOT NULL,
    cik                          TEXT NOT NULL,
    ticker_as_of_date            TEXT,
    decision_price               REAL NOT NULL,
    pit_fundamentals_period_end  TEXT,
    pit_fundamentals_filed_date  TEXT,
    safety_score                 REAL NOT NULL,
    valuation_score               REAL,
    dividend_score                REAL NOT NULL,
    deterministic_partial_score   REAL NOT NULL,
    deterministic_score_pct       REAL,
    available_components          TEXT NOT NULL,
    missing_components            TEXT NOT NULL,
    margin_of_safety_base_pct     REAL,
    config_version                 TEXT NOT NULL,
    scoring_version                 TEXT NOT NULL,
    return_1m_pct                   REAL,
    return_3m_pct                   REAL,
    return_6m_pct                   REAL,
    return_12m_pct                  REAL,
    created_at                       TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (run_id, decision_date, cik)
);

-- Faza 5.3c -- dualny benchmark (Decyzja wlascicielki 2026-10-04): jeden
-- wiersz per (run_id, decision_date), oba benchmarki osobno, nigdy
-- zmieszane w jedna kolumne. PRIMARY = equal_weighted_pit_universe
-- (WSZYSTKIE spolki z PIT universe z wystarczajacymi cenami, nie tylko
-- kandydaci), SECONDARY = SPY, ta sama konwencja forward price return
-- (bez dywidend) co kandydaci. ew_*_n_* = liczba spolek z nie-None
-- forward return na danym horyzoncie (moze sie roznic miedzy
-- horyzontami -- dalszy horyzont ma mniej dostepnych przyszlych cen).
CREATE TABLE IF NOT EXISTS backtest_benchmark (
    run_id                        TEXT NOT NULL,
    decision_date                 TEXT NOT NULL,
    ew_pit_universe_return_1m_pct REAL,
    ew_pit_universe_return_3m_pct REAL,
    ew_pit_universe_return_6m_pct REAL,
    ew_pit_universe_return_12m_pct REAL,
    ew_pit_universe_n_1m          INTEGER NOT NULL,
    ew_pit_universe_n_3m          INTEGER NOT NULL,
    ew_pit_universe_n_6m          INTEGER NOT NULL,
    ew_pit_universe_n_12m         INTEGER NOT NULL,
    spy_return_1m_pct             REAL,
    spy_return_3m_pct             REAL,
    spy_return_6m_pct             REAL,
    spy_return_12m_pct            REAL,
    created_at                    TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (run_id, decision_date)
);

-- Faza 5.4 (protokol kalibracji, Decyzja wlascicielki 2026-10-05) --
-- jeden wiersz per (calibration_run_id) = jeden przetestowany kandydat
-- konfiguracji. NIGDY usuwane (punkt 11/9.5 protokolu: przegrywajace
-- konfiguracje zostaja, audytowalnosc). `metrics_json` niesie caly
-- CalibrationEvaluation (pooled + per-fold + secondary) -- jedna
-- kolumna TEXT/JSON, zeby nie przebudowywac schematu przy kazdej nowej
-- metryce diagnostycznej; pola uzywane do filtrowania/sortowania (round,
-- candidate_name, pooled primary metric) sa tez osobnymi kolumnami.
CREATE TABLE IF NOT EXISTS calibration_runs (
    calibration_run_id      TEXT NOT NULL PRIMARY KEY,
    round                    INTEGER NOT NULL,
    candidate_name           TEXT NOT NULL,
    description              TEXT NOT NULL,
    config_hash              TEXT NOT NULL,
    config_json              TEXT NOT NULL,
    training_window_start    TEXT NOT NULL,
    training_window_end      TEXT NOT NULL,
    oos_fold_years           TEXT NOT NULL,
    n_total_candidates       INTEGER NOT NULL,
    pooled_n                 INTEGER NOT NULL,
    pooled_median_excess_return_pct REAL,
    pooled_low_sample        INTEGER NOT NULL,
    median_of_fold_medians_pct REAL,
    min_fold_median_pct      REAL,
    max_fold_median_pct      REAL,
    n_positive_folds         INTEGER NOT NULL,
    n_folds_with_data        INTEGER NOT NULL,
    metrics_json             TEXT NOT NULL,
    status                   TEXT NOT NULL DEFAULT 'candidate'
                              CHECK (status IN ('candidate', 'frozen_winner')),
    created_at                TEXT NOT NULL DEFAULT (datetime('now')),
    -- Faza 5.4b: PRIMARY metric Round 2A/2B (Spearman score-vs-forward-
    -- return) -- NULL dla Round 1 (gdzie pooled_median_excess_return_pct
    -- powyżej pozostaje PRIMARY, bez zmian). pooled_median_excess_*
    -- powyżej staje się DIAGNOSTIC-only w Round 2, nadal liczone/zapisane.
    subround                 TEXT,
    population               TEXT,
    pooled_spearman          REAL,
    pooled_spearman_low_sample INTEGER,
    median_of_fold_spearman  REAL,
    min_fold_spearman        REAL,
    max_fold_spearman        REAL,
    n_positive_spearman_folds INTEGER,
    n_spearman_folds_with_data INTEGER
);
CREATE INDEX IF NOT EXISTS idx_calibration_runs_round ON calibration_runs(round);

-- Faza 6c (2026-10-06, Decyzja właścicielki OPCJA 3, po realnym
-- znalezisku: pełna analiza Claude dla WSZYSTKICH decline-surfaced
-- kandydatów jest kosztowo/czasowo niewykonalna w jednym przebiegu —
-- patrz docs „Faza 6c"). Dwa jasne etapy: (1) deterministyczny ranking
-- WSZYSTKICH przefiltrowanych kandydatów (zero LLM, `backtest_harness.
-- compute_deterministic_score`/`evaluate_deterministic_hard_gates` —
-- ten sam frozen kod co kalibracja/holdout, zero nowego proxy score),
-- (2) pełna analiza Claude WYŁĄCZNIE dla shortlisty (operacyjny/
-- kosztowy budget, NIE nowy próg inwestycyjny). `live_scan_candidates.
-- llm_status` umożliwia RESUME (po uzupełnieniu kredytu analizuje
-- tylko PENDING/FAILED, nigdy ponownie COMPLETE) i cache (`cache_key`
-- identyczny -> `analysis_id` skopiowany bez nowego wywołania API).
CREATE TABLE IF NOT EXISTS live_scan_runs (
    run_id              TEXT PRIMARY KEY,
    run_date            TEXT NOT NULL,
    config_version      TEXT NOT NULL,
    universe_size       INTEGER NOT NULL,
    decline_surfaced    INTEGER NOT NULL,
    prefilter_excluded  INTEGER NOT NULL,
    shortlist_limit     INTEGER NOT NULL,
    shortlist_size      INTEGER NOT NULL,
    status              TEXT NOT NULL DEFAULT 'RANKED'
                         CHECK (status IN ('RANKED', 'INCOMPLETE_LLM_ANALYSIS', 'COMPLETE')),
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS live_scan_candidates (
    run_id                      TEXT NOT NULL REFERENCES live_scan_runs(run_id),
    cik                         TEXT NOT NULL REFERENCES companies(cik),
    ticker                      TEXT NOT NULL,
    rank                        INTEGER NOT NULL,
    current_price               REAL NOT NULL,
    decline_flags_json          TEXT NOT NULL,
    deterministic_score_pct     REAL,
    deterministic_partial_score REAL NOT NULL,
    available_components_json   TEXT NOT NULL,
    missing_components_json     TEXT NOT NULL,
    safety_score                REAL NOT NULL,
    valuation_score             REAL,
    dividend_score               REAL NOT NULL,
    margin_of_safety_base_pct   REAL,
    hard_gate_passed_deterministic    INTEGER NOT NULL,
    hard_gate_triggered_deterministic_json TEXT NOT NULL,
    in_shortlist                INTEGER NOT NULL,
    llm_status                  TEXT NOT NULL DEFAULT 'NOT_SHORTLISTED'
                                 CHECK (llm_status IN
                                 ('NOT_SHORTLISTED', 'PENDING', 'COMPLETE', 'FAILED')),
    llm_error                   TEXT,
    cache_key                   TEXT,
    analysis_id                 INTEGER REFERENCES analyses(analysis_id),
    -- Faza 6e (2026-10-06) — telemetria PER-KANDYDAT (per próba
    -- wywołania Claude API w TYM run_id). W przeciwieństwie do kolumn
    -- usage w `analyses` (zapisywanych tylko dla faktycznie udanej,
    -- persystowanej analizy) te kolumny są wypełniane dla KAŻDEGO
    -- wyniku: realne wywołanie zakończone sukcesem, odmowa/niesparsowalny
    -- JSON (FAILED, ale realna odpowiedź/usage istniała), błąd API bez
    -- odpowiedzi (FAILED, NULL -- nigdy nie zgadujemy), i CACHE HIT
    -- (COMPLETE, NULL -- zero nowego wywołania w TYM run_id, zero
    -- nowego kosztu). To właśnie ta tabela (nie `analyses`) jest
    -- źródłem agregatu per-run -- płaski SUM po `run_id`, bez JOIN-a,
    -- więc cache hit nigdy nie jest liczony jako nowy koszt.
    llm_response_model              TEXT,
    llm_input_tokens                INTEGER,
    llm_output_tokens               INTEGER,
    llm_cache_creation_input_tokens INTEGER,
    llm_cache_read_input_tokens     INTEGER,
    llm_thinking_tokens             INTEGER,
    llm_service_tier                TEXT,
    -- Faza 6h (2026-10-06, TARGETED FIELD REPAIR) — patrz komentarz przy
    -- tych samych kolumnach w `analyses` wyżej. NULL, gdy ten kandydat
    -- nie potrzebował repair call w TYM run_id.
    llm_repair_response_model              TEXT,
    llm_repair_input_tokens                INTEGER,
    llm_repair_output_tokens               INTEGER,
    llm_repair_cache_creation_input_tokens INTEGER,
    llm_repair_cache_read_input_tokens     INTEGER,
    llm_repair_thinking_tokens             INTEGER,
    llm_repair_service_tier                TEXT,
    PRIMARY KEY (run_id, cik)
);
CREATE INDEX IF NOT EXISTS idx_live_scan_candidates_run_id ON live_scan_candidates(run_id);
CREATE INDEX IF NOT EXISTS idx_live_scan_candidates_cache_key ON live_scan_candidates(cache_key);

-- Faza 7 (UI + PORTFOLIO V0) -- decyzje użytkownika na kandydatach
-- scannera (SHARED analiza spółki, USER-SCOPED decyzja -- sekcja 1.1
-- design review). Append-only (ten sam wzorzec co `analyses`): korekta
-- decyzji to nowy wiersz, nigdy UPDATE. "Aktualny" status = NAJNOWSZY
-- wiersz per (user_id, cik) wg `decided_at`/`decision_id`. Mapowanie
-- przycisków UI (Decyzja właścicielki): ODRZUCAM=REJECT,
-- OBSERWUJĘ=WATCH, SPRAWDZAM=SNOOZE, KUPIŁAM/KUPIŁEM=BOUGHT.
CREATE TABLE IF NOT EXISTS user_decisions (
    decision_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL REFERENCES users(user_id),
    cik          TEXT NOT NULL REFERENCES companies(cik),
    analysis_id  INTEGER REFERENCES analyses(analysis_id),
    status       TEXT NOT NULL CHECK (status IN ('WATCH','REJECT','SNOOZE','BOUGHT')),
    decided_at   TEXT NOT NULL DEFAULT (datetime('now')),
    note         TEXT
);
CREATE INDEX IF NOT EXISTS idx_user_decisions_user_cik ON user_decisions(user_id, cik);

-- Pozycja = jeden "round trip" posiadania danej spółki PRZEZ JEDNEGO
-- użytkownika (sekcja 1.1/16 design review). `user_id` jest korzeniem
-- własności -- ta sama spółka może mieć wiele niezależnych, jednoczesnych
-- wierszy `positions` dla różnych `user_id`.
--
-- `cik` jest NULLABLE (Decyzja właścicielki, Faza 7 pkt 5): portfel NIE
-- jest ograniczony do spółek SEC/S&P500 -- np. Schneider Electric
-- (Euronext Paris) może nie mieć CIK wcale. `ticker`/`company_name`/
-- `exchange`/`instrument_currency` są zachowane WPROST na `positions`
-- (nie tylko jako join do `companies`, który jest SHARED i scoped do
-- uniwersum S&P500/spółek kiedyś zeskanowanych) -- to jest tożsamość
-- INSTRUMENTU z perspektywy posiadania, osobna warstwa od tożsamości
-- SHARED używanej przez scanner. Gdy `cik` jest ustawione, UI może
-- DODATKOWO sięgnąć do `companies.name` (SHARED, autorytatywne dla
-- analiz) -- te pola nie są wzajemnie wyłączne, nie duplikują się
-- szkodliwie: różne warstwy, różny cel.
--
-- `shares_held`/`avg_price`/`current_value`/`unrealized_pl` NIE są
-- przechowywane jako mutowalne kolumny -- liczone deterministycznie
-- z transakcji przy każdym odczycie (ui/portfolio.py), żeby wykluczyć
-- rozjazd cache'u z transakcjami (uzasadnienie w design review, sekcja
-- 5: przy tej skali narzut obliczeniowy jest pomijalny).
CREATE TABLE IF NOT EXISTS positions (
    position_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id             INTEGER NOT NULL REFERENCES users(user_id),
    cik                 TEXT REFERENCES companies(cik),
    ticker              TEXT NOT NULL,
    company_name        TEXT NOT NULL,
    exchange            TEXT,
    instrument_currency TEXT,
    status              TEXT NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN','CLOSED')),
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_positions_user_id ON positions(user_id);

-- Transakcje -- WYŁĄCZNIE INSERT, nigdy UPDATE/DELETE (audit trail,
-- sekcja 11 design review: korekta błędu = nowy wiersz + `superseded_by`
-- na starym, nigdy edycja).
--
-- `broker`/`acquisition_type` to rozszerzenia względem oryginalnego
-- projektu sekcji 5 (Decyzja właścicielki, Faza 7 pkt 3/4):
-- `broker` jest właściwością TRANSAKCJI, nie spółki/pozycji -- ta sama
-- spółka może być posiadana jednocześnie na kilku brokerach pod JEDNĄ
-- `position_id` (shares per (position_id, broker) liczone w
-- ui/portfolio.py, PRZED agregacją do łącznej ekspozycji -- SELL na
-- jednym brokerze nigdy nie zmniejsza subpozycji innego brokera).
-- `acquisition_type='BONUS'`: `shares` zwiększają pozycję normalnie,
-- `total_invested=0` (nigdy nie udajemy, że użytkownik zapłacił),
-- `price_per_share` może być NULL (brak realnej ceny zapłaconej).
CREATE TABLE IF NOT EXISTS purchase_transactions (
    transaction_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    position_id       INTEGER NOT NULL REFERENCES positions(position_id),
    broker            TEXT NOT NULL CHECK (broker IN ('TRADE_REPUBLIC','REVOLUT','OTHER')),
    acquisition_type  TEXT NOT NULL CHECK (acquisition_type IN ('BUY','BONUS')),
    purchase_date     TEXT NOT NULL,
    shares            REAL NOT NULL,
    price_per_share   REAL,
    total_invested    REAL NOT NULL,
    currency          TEXT NOT NULL,
    fees              REAL,
    note              TEXT,
    superseded_by     INTEGER REFERENCES purchase_transactions(transaction_id),
    created_at        TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_purchase_transactions_position_id ON purchase_transactions(position_id);

-- Patrz komentarz przy `purchase_transactions` (append-only, `broker`
-- rozszerzenie Fazy 7 pkt 4 -- dla symetrii, żeby SELL wiedział, z
-- którego brokera zmniejsza subpozycję).
CREATE TABLE IF NOT EXISTS sale_transactions (
    transaction_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    position_id     INTEGER NOT NULL REFERENCES positions(position_id),
    broker          TEXT NOT NULL CHECK (broker IN ('TRADE_REPUBLIC','REVOLUT','OTHER')),
    sale_date       TEXT NOT NULL,
    shares          REAL NOT NULL,
    sale_price      REAL NOT NULL,
    currency        TEXT NOT NULL,
    fees            REAL,
    note            TEXT,
    -- Obecne w docelowym schemacie (sekcja 16 design review) --
    -- ZAREZERWOWANE, nieużywane w V0: `ui/portfolio.py` liczy cost
    -- basis WYŁĄCZNIE metodą average-cost (proporcjonalna redukcja
    -- invested przy sprzedaży), nie czyta tej kolumny. Obecna tu, żeby
    -- przyszłe FIFO/LIFO/specific-lot nie wymagało kolejnej migracji.
    cost_basis_method_used TEXT,
    superseded_by   INTEGER REFERENCES sale_transactions(transaction_id),
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_sale_transactions_position_id ON sale_transactions(position_id);

-- Immutable snapshot w momencie BOUGHT (sekcja 16 design review).
-- `analysis_id` NULL = "zakup przed analizą scannera" -- UI pokazuje
-- wtedy "Zakup przed analizą scannera -- teza do uzupełnienia.", nigdy
-- fikcyjną historyczną tezę.
CREATE TABLE IF NOT EXISTS purchase_thesis (
    thesis_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    position_id    INTEGER NOT NULL UNIQUE REFERENCES positions(position_id),
    analysis_id    INTEGER REFERENCES analyses(analysis_id),
    snapshot_json  TEXT,
    created_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Append-only audit trail (ten sam wzorzec co `user_decisions`) --
-- "aktualny" status pozycji na karcie UI = NAJNOWSZY wiersz per
-- `position_id`. `exit_review_report_id` istnieje w docelowym projekcie
-- (sekcja 16) jako FK do `exit_review_reports` -- Exit Review jest poza
-- zakresem Fazy 7 (UI + PORTFOLIO V0), więc ta kolumna jest tu obecna
-- (zgodność ze schematem docelowym) ale ZAWSZE NULL w V0.
CREATE TABLE IF NOT EXISTS holding_user_actions (
    action_id              INTEGER PRIMARY KEY AUTOINCREMENT,
    position_id            INTEGER NOT NULL REFERENCES positions(position_id),
    action                 TEXT NOT NULL CHECK (action IN ('HOLD','REDUCE','SOLD','REVIEW_LATER')),
    decided_at             TEXT NOT NULL DEFAULT (datetime('now')),
    note                   TEXT,
    exit_review_report_id  INTEGER,
    created_at             TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_holding_user_actions_position_id ON holding_user_actions(position_id);
"""


def connect(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.row_factory = sqlite3.Row
    return conn


# `CREATE TABLE IF NOT EXISTS` w SCHEMA tworzy tabelę tylko, gdy jeszcze
# nie istnieje -- NIE dodaje nowych kolumn do tabeli, która już istnieje
# w pliku DB ze starszą wersją schematu (realny błąd znaleziony
# 2026-10-04: workflow ponownie używający już istniejącego artefaktu
# backfillu padł na `sqlite3.OperationalError: table universe_membership
# has no column named overlap_merge_note`, bo ta kolumna została dodana
# do schematu PO tym, jak dany plik DB już miał tabelę `universe_
# membership`). SQLite (tu: 3.45) NIE wspiera `ALTER TABLE ... ADD
# COLUMN IF NOT EXISTS` (zweryfikowane empirycznie -- `sqlite3.
# OperationalError: near "EXISTS"`, mimo że ta sama wersja SQLite
# wspiera `CREATE TABLE IF NOT EXISTS`), więc idempotencja jest
# sprawdzana ręcznie przez `PRAGMA table_info` przed `ADD COLUMN`.
# Projekt nie ma (i na tym etapie nie potrzebuje) formalnego systemu
# migracji — to minimalny, wystarczający mechanizm na SQLite (Decyzja
# D5: Postgres/Supabase od V1, gdzie migracje będą formalne).
_COLUMN_MIGRATIONS: tuple[tuple[str, str, str], ...] = (
    ("universe_membership", "overlap_merge_note", "TEXT"),
    # Faza 6e (2026-10-06) — telemetria Anthropic API usage, dodana PO
    # tym, jak `analyses`/`live_scan_candidates` mogły już istnieć w
    # plikach DB z poprzednich runów (np. ponownie używany artefakt
    # `live_scan_result.db`).
    ("analyses", "llm_response_model", "TEXT"),
    ("analyses", "llm_input_tokens", "INTEGER"),
    ("analyses", "llm_output_tokens", "INTEGER"),
    ("analyses", "llm_cache_creation_input_tokens", "INTEGER"),
    ("analyses", "llm_cache_read_input_tokens", "INTEGER"),
    ("analyses", "llm_thinking_tokens", "INTEGER"),
    ("analyses", "llm_service_tier", "TEXT"),
    ("live_scan_candidates", "llm_response_model", "TEXT"),
    ("live_scan_candidates", "llm_input_tokens", "INTEGER"),
    ("live_scan_candidates", "llm_output_tokens", "INTEGER"),
    ("live_scan_candidates", "llm_cache_creation_input_tokens", "INTEGER"),
    ("live_scan_candidates", "llm_cache_read_input_tokens", "INTEGER"),
    ("live_scan_candidates", "llm_thinking_tokens", "INTEGER"),
    ("live_scan_candidates", "llm_service_tier", "TEXT"),
    # Faza 6h (2026-10-06) — TARGETED FIELD REPAIR usage, dodane PO tym,
    # jak `analyses`/`live_scan_candidates` mogły już istnieć w plikach
    # DB z poprzednich runów (sam wzorzec co Faza 6e powyżej).
    ("analyses", "llm_repair_response_model", "TEXT"),
    ("analyses", "llm_repair_input_tokens", "INTEGER"),
    ("analyses", "llm_repair_output_tokens", "INTEGER"),
    ("analyses", "llm_repair_cache_creation_input_tokens", "INTEGER"),
    ("analyses", "llm_repair_cache_read_input_tokens", "INTEGER"),
    ("analyses", "llm_repair_thinking_tokens", "INTEGER"),
    ("analyses", "llm_repair_service_tier", "TEXT"),
    ("live_scan_candidates", "llm_repair_response_model", "TEXT"),
    ("live_scan_candidates", "llm_repair_input_tokens", "INTEGER"),
    ("live_scan_candidates", "llm_repair_output_tokens", "INTEGER"),
    ("live_scan_candidates", "llm_repair_cache_creation_input_tokens", "INTEGER"),
    ("live_scan_candidates", "llm_repair_cache_read_input_tokens", "INTEGER"),
    ("live_scan_candidates", "llm_repair_thinking_tokens", "INTEGER"),
    ("live_scan_candidates", "llm_repair_service_tier", "TEXT"),
    # Faza 7 (2026-10-06, UI + PORTFOLIO V0) — zarezerwowana na przyszłość
    # kolumna z docelowego schematu (sekcja 16 design review), dodana
    # PO tym, jak `sale_transactions` mogła już istnieć w plikach DB
    # zseedowanych wcześniejszą wersją tej samej migracji w tej fazie.
    ("sale_transactions", "cost_basis_method_used", "TEXT"),
)


def _apply_column_migrations(conn: sqlite3.Connection) -> None:
    for table, column, coltype in _COLUMN_MIGRATIONS:
        existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")


def init_db(db_path: str | Path) -> sqlite3.Connection:
    """Tworzy schemat (idempotentnie) i zwraca otwarte połączenie."""
    conn = connect(db_path)
    conn.executescript(SCHEMA)
    _apply_column_migrations(conn)
    conn.commit()
    return conn


def upsert_company(
    conn: sqlite3.Connection,
    *,
    cik: str,
    name: str,
    sector: str | None = None,
    industry: str | None = None,
    sub_industry: str | None = None,
    sector_profile: str = "GENERAL",
) -> None:
    conn.execute(
        """
        INSERT INTO companies (cik, name, sector, industry, sub_industry, sector_profile)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(cik) DO UPDATE SET
            name = excluded.name,
            sector = excluded.sector,
            industry = excluded.industry,
            sub_industry = excluded.sub_industry,
            sector_profile = excluded.sector_profile
        """,
        (cik, name, sector, industry, sub_industry, sector_profile),
    )


def upsert_ticker_history(
    conn: sqlite3.Connection, *, cik: str, ticker: str, start_date: str
) -> None:
    """Zamyka poprzedni aktywny wpis tickera dla tego CIK (jeśli inny) i
    dodaje nowy — ticker jest atrybutem zmiennym w czasie, nie tożsamością
    (sekcja 5 design review)."""
    conn.execute(
        """
        UPDATE ticker_history
        SET end_date = ?
        WHERE cik = ? AND end_date IS NULL AND ticker != ?
        """,
        (start_date, cik, ticker),
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO ticker_history (cik, ticker, start_date, end_date)
        VALUES (?, ?, ?, NULL)
        """,
        (cik, ticker, start_date),
    )


def get_cik_for_active_ticker(conn: sqlite3.Connection, ticker: str) -> str | None:
    """CIK aktualnie (end_date IS NULL) używający danego tickera w
    `ticker_history`. `None`, jeśli brak takiego wiersza — nigdy nie
    zgaduje CIK dla tickera, którego nie zapisał żaden poprzedni krok
    (Faza 5.3c: `run-baseline-walk-forward` używa tego do odczytania —
    zero sieci — CIK SPY zapisanego wcześniej przez `fetch-spy-
    benchmark-prices`). Jeśli >1 wiersz aktywny dla tego samego tickera
    (nie powinno się zdarzyć — `upsert_ticker_history` zamyka poprzedni
    aktywny wpis TEGO CIK, ale nie chroni przed dwoma różnymi CIK
    współdzielącymi ten sam ticker), podnosi błąd zamiast cichego
    wyboru jednego z nich."""
    rows = conn.execute(
        "SELECT cik FROM ticker_history WHERE ticker = ? AND end_date IS NULL", (ticker,)
    ).fetchall()
    if not rows:
        return None
    if len(rows) > 1:
        raise ValueError(
            f"Wiele aktywnych CIK dla tickera {ticker}: {[r['cik'] for r in rows]} — "
            "niejednoznaczne, nie wybieram jednego."
        )
    return rows[0]["cik"]


def list_active_tickers(conn: sqlite3.Connection) -> list[str]:
    """Wszystkie tickery aktualnie (`end_date IS NULL`) aktywne w
    `ticker_history` — "aktualne uniwersum" dla Fazy 6 (live end-to-end
    run na całym rynku, nie na jawnie podanej liście tickerów jak
    `scan`/`score`/`analyze`). Alfabetycznie, dla deterministycznego
    porządku przetwarzania/raportu."""
    rows = conn.execute(
        "SELECT ticker FROM ticker_history WHERE end_date IS NULL ORDER BY ticker"
    ).fetchall()
    return [r["ticker"] for r in rows]


def insert_price_rows(conn: sqlite3.Connection, cik: str, source: str, rows: list[dict]) -> int:
    """rows: [{date, open, high, low, close, adj_close, volume}, ...]. Zwraca
    liczbę wstawionych/zaktualizowanych wierszy."""
    n = 0
    for r in rows:
        conn.execute(
            """
            INSERT INTO price_daily (cik, date, open, high, low, close, adj_close, volume, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(cik, date) DO UPDATE SET
                open = excluded.open, high = excluded.high, low = excluded.low,
                close = excluded.close, adj_close = excluded.adj_close,
                volume = excluded.volume, source = excluded.source
            """,
            (
                cik,
                r["date"],
                r.get("open"),
                r.get("high"),
                r.get("low"),
                r.get("close"),
                r.get("adj_close"),
                r.get("volume"),
                source,
            ),
        )
        n += 1
    return n


def get_price_series(conn: sqlite3.Connection, cik: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM price_daily WHERE cik = ? ORDER BY date ASC", (cik,)
    ).fetchall()


def create_user(conn: sqlite3.Connection, display_name: str) -> int:
    cur = conn.execute(
        "INSERT INTO users (display_name) VALUES (?)", (display_name,)
    )
    return cur.lastrowid


def insert_fundamentals_rows(
    conn: sqlite3.Connection, cik: str, source: str, rows: list[dict]
) -> int:
    """rows: [{fiscal_period, period_end_date, filed_date, line_item, value,
    unit}, ...]. `statement_type` wyprowadzany z `line_item` przez
    LINE_ITEM_STATEMENT_TYPE — nazwy line_item muszą być kanoniczne (patrz
    moduł). Wartości None (brakujący line item w odpowiedzi providera) są
    zapisywane jako NULL, nigdy jako 0."""
    n = 0
    for r in rows:
        line_item = r["line_item"]
        statement_type = LINE_ITEM_STATEMENT_TYPE.get(line_item)
        if statement_type is None:
            raise ValueError(f"Nieznany kanoniczny line_item: {line_item!r}")
        conn.execute(
            """
            INSERT INTO fundamentals_raw
                (cik, fiscal_period, period_end_date, filed_date,
                 statement_type, line_item, value, unit, source, source_doc_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(cik, fiscal_period, statement_type, line_item, source)
            DO UPDATE SET
                period_end_date = excluded.period_end_date,
                filed_date = excluded.filed_date,
                value = excluded.value,
                unit = excluded.unit,
                source_doc_id = excluded.source_doc_id
            """,
            (
                cik,
                r["fiscal_period"],
                r["period_end_date"],
                r.get("filed_date"),
                statement_type,
                line_item,
                r.get("value"),
                r.get("unit"),
                source,
                r.get("source_doc_id"),
            ),
        )
        n += 1
    return n


def get_fundamentals_periods(conn: sqlite3.Connection, cik: str) -> list[FundamentalsPeriod]:
    """Pivotuje fundamentals_raw (format long) do listy `FundamentalsPeriod`,
    posortowanej rosnąco po period_end_date (konwencja: [-1] = najnowszy,
    patrz fundamentals.py). Brakujący line_item dla danego okresu -> None,
    nigdy 0 — pole po prostu nie trafia do słownika przed przekazaniem do
    FundamentalsPeriod(**{...}), gdzie dataclass ma domyślnie None."""
    rows = conn.execute(
        """
        SELECT fiscal_period, period_end_date, filed_date, line_item, value
        FROM fundamentals_raw
        WHERE cik = ?
        ORDER BY period_end_date ASC
        """,
        (cik,),
    ).fetchall()

    by_period: dict[str, dict] = {}
    order: list[str] = []
    for r in rows:
        fp = r["fiscal_period"]
        if fp not in by_period:
            by_period[fp] = {
                "fiscal_period": fp,
                "period_end_date": r["period_end_date"],
                "filed_date": r["filed_date"],
            }
            order.append(fp)
        by_period[fp][r["line_item"]] = r["value"]

    fields = (
        "revenue", "net_income", "ebitda", "operating_cash_flow",
        "capital_expenditure", "total_debt", "cash_and_equivalents",
        "total_current_assets", "total_current_liabilities",
        "dividends_paid", "share_buybacks", "diluted_shares_outstanding",
    )
    periods = []
    for fp in order:
        data = by_period[fp]
        periods.append(
            FundamentalsPeriod(
                fiscal_period=data["fiscal_period"],
                period_end_date=data["period_end_date"],
                filed_date=data["filed_date"],
                **{f: data.get(f) for f in fields},
            )
        )
    return periods


def upsert_derived_metric(
    conn: sqlite3.Connection,
    *,
    cik: str,
    as_of_date: str,
    metric_name: str,
    value: float | None,
    calc_version: str,
    inputs_hash: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO derived_metrics
            (cik, as_of_date, metric_name, value, calc_version, inputs_hash)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(cik, as_of_date, metric_name, calc_version)
        DO UPDATE SET value = excluded.value, inputs_hash = excluded.inputs_hash
        """,
        (cik, as_of_date, metric_name, value, calc_version, inputs_hash),
    )


def upsert_scoring_model_version(
    conn: sqlite3.Connection,
    *,
    version: str,
    description: str | None,
    weights_json: str,
    gates_json: str,
) -> None:
    """Zamraża snapshot wag/bramek pod daną wersją (sekcja 11 design
    review) — `analyses.scoring_model_version` wskazuje na ten wiersz,
    nie na "aktualny" config, więc zmiana configu nigdy nie zmienia
    znaczenia już policzonych wyników."""
    conn.execute(
        """
        INSERT INTO scoring_model_versions (version, description, weights_json, gates_json)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(version) DO UPDATE SET
            description = excluded.description,
            weights_json = excluded.weights_json,
            gates_json = excluded.gates_json
        """,
        (version, description, weights_json, gates_json),
    )


def insert_analysis(conn: sqlite3.Connection, **fields) -> int:
    """INSERT-only (nigdy UPDATE) — ponowna ocena spółki to zawsze nowy
    wiersz, zgodnie z zasadą immutability z sekcji 11. `fields` to
    dowolny podzbiór kolumn tabeli `analyses` (cik/run_date/
    scoring_model_version wymagane przez NOT NULL w schemacie)."""
    columns = list(fields.keys())
    placeholders = ", ".join("?" for _ in columns)
    cur = conn.execute(
        f"INSERT INTO analyses ({', '.join(columns)}) VALUES ({placeholders})",
        [fields[c] for c in columns],
    )
    return cur.lastrowid


def upsert_universe_membership(conn: sqlite3.Connection, *, cik: str, index_name: str, start_date: str, **fields) -> None:
    """Wiersz `universe_membership` — `cik`/`index_name`/`start_date`
    identyfikują przedział (UNIQUE), reszta pól (end_date, source,
    source_snapshot_ref, cik_resolution_method, entry_validation_*,
    exit_validation_*, validation_*) w `fields`. Upsert: ponowny build
    tego samego przedziału (np. po zmianie tolerancji) aktualizuje
    metadane walidacji, nie duplikuje wiersza."""
    columns = ["cik", "index_name", "start_date", *fields.keys()]
    values = [cik, index_name, start_date, *fields.values()]
    placeholders = ", ".join("?" for _ in columns)
    update_clause = ", ".join(f"{c} = excluded.{c}" for c in fields.keys())
    conn.execute(
        f"""
        INSERT INTO universe_membership ({', '.join(columns)})
        VALUES ({placeholders})
        ON CONFLICT(cik, index_name, start_date) DO UPDATE SET {update_clause}
        """,
        values,
    )


def clear_universe_membership_for_rebuild(conn: sqlite3.Connection, index_name: str) -> None:
    """Usuwa WSZYSTKIE wiersze `universe_membership`/`universe_membership_
    conflicts`/`universe_membership_unresolved_tickers` dla danego
    `index_name` (Decyzja właścicielki 2026-10-04, dodane przy naprawie
    overlapping dual-class intervals). `cmd_build_universe_membership`
    woła to na początku zapisu — bez tego, ponowny build na już
    istniejącej bazie zostawiałby STARE wiersze, których nowy (poprawiony)
    wynik już nie produkuje (np. dla CIK, które po naprawie scaliły się
    do JEDNEGO przedziału — stary, osobny drugi wiersz zostałby cichym,
    osierocionym duplikatem, bo `upsert_universe_membership` tylko
    wstawia/aktualizuje, nigdy nie usuwa). Rebuild = pełne zastąpienie,
    nie dopisanie. UWAGA: usuwa też ręczne `review_note` z konfliktów —
    w tym projekcie nic tam jeszcze nie wpisano ręcznie, ale przyszła
    funkcja, która by to robiła, musiałaby to uwzględnić."""
    conn.execute("DELETE FROM universe_membership WHERE index_name = ?", (index_name,))
    conn.execute("DELETE FROM universe_membership_conflicts WHERE index_name = ?", (index_name,))
    conn.execute("DELETE FROM universe_membership_unresolved_tickers WHERE index_name = ?", (index_name,))


def insert_universe_membership_conflict(conn: sqlite3.Connection, **fields) -> int:
    """INSERT-only (append) — audytowalny log, jeden wiersz per
    rozbieżność per uruchomienie walidacji (`run_id`). `fields`:
    cik, index_name, event_date, action, conflict_type, tolerance_days,
    date_field, validation_rule_version, validation_run_id."""
    columns = list(fields.keys())
    placeholders = ", ".join("?" for _ in columns)
    cur = conn.execute(
        f"INSERT INTO universe_membership_conflicts ({', '.join(columns)}) VALUES ({placeholders})",
        [fields[c] for c in columns],
    )
    return cur.lastrowid


def insert_unresolved_ticker(conn: sqlite3.Connection, **fields) -> None:
    """INSERT OR IGNORE — ticker z kanonicznego źródła bez CIK
    (CIK_UNRESOLVED), zapisany jawnie zamiast cicho pominięty. `fields`:
    source, ticker, index_name, source_snapshot_ref, run_id."""
    columns = list(fields.keys())
    placeholders = ", ".join("?" for _ in columns)
    conn.execute(
        f"INSERT OR IGNORE INTO universe_membership_unresolved_tickers ({', '.join(columns)}) VALUES ({placeholders})",
        [fields[c] for c in columns],
    )


def get_universe_membership_as_of(conn: sqlite3.Connection, index_name: str, as_of_date: str) -> list[str]:
    """CIK-i aktywne w indeksie na `as_of_date` — `start_date <= D <
    end_date` (end_date wyłączny, ten sam wzorzec co `value_as_of`/
    `tickers_as_of`/`membership_as_of`). Punkt-w-czasie rekonstrukcja
    membership — sedno domknięcia OPEN BLOCKER 2."""
    rows = conn.execute(
        """
        SELECT cik FROM universe_membership
        WHERE index_name = ?
          AND start_date <= ?
          AND (end_date IS NULL OR end_date > ?)
        ORDER BY cik
        """,
        (index_name, as_of_date, as_of_date),
    ).fetchall()
    return [r["cik"] for r in rows]


def get_analysis(conn: sqlite3.Connection, analysis_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM analyses WHERE analysis_id = ?", (analysis_id,)
    ).fetchone()


def get_analysis_sources(conn: sqlite3.Connection, analysis_id: int) -> list:
    """Odwraca `insert_analysis_sources` — rekonstruuje
    `sources.VerifiedSource` z już zapisanych wierszy (Faza 6c: resume/
    cache musi móc odtworzyć pełny source packet bez ponownego
    odpytywania SEC EDGAR)."""
    from buffett_scanner.sources import VerifiedSource

    rows = conn.execute(
        "SELECT * FROM analysis_sources WHERE analysis_id = ? ORDER BY source_id", (analysis_id,)
    ).fetchall()
    return [
        VerifiedSource(
            source_type=r["source_type"], title=r["title"], issuer=r["issuer"],
            doc_date=r["doc_date"], url=r["url"], accession_number=r["accession_number"],
            section=r["section"], content_hash=r["content_hash"],
            verified=bool(r["verified"]), reason=r["reason"],
        )
        for r in rows
    ]


def insert_analysis_sources(conn: sqlite3.Connection, analysis_id: int, sources: list) -> int:
    """sources: lista `sources.VerifiedSource`. Jedyny sposób, w jaki
    wiersze tu powstają — nigdy na podstawie twierdzenia LLM (BLOCKER 3).
    Zwraca liczbę wstawionych wierszy."""
    n = 0
    for s in sources:
        conn.execute(
            """
            INSERT INTO analysis_sources
                (analysis_id, source_type, title, issuer, doc_date, url,
                 accession_number, section, page, content_hash, verified, reason, question)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                analysis_id, s.source_type, s.title, s.issuer, s.doc_date, s.url,
                s.accession_number, s.section, None, s.content_hash, int(s.verified),
                s.reason, None,
            ),
        )
        n += 1
    return n


def upsert_sec_company_facts_cache(
    conn: sqlite3.Connection, *, cik: str, company_facts: dict, source: str = "sec_edgar"
) -> str:
    """Zapisuje SUROWY `company_facts` JSON (as-is, dokładnie to, co
    zwraca `SecEdgarClient.get_company_facts`) jako cache na potrzeby
    walk-forward backtestu — NIGDY wyliczonych historycznych
    fundamentals ani snapshotów `as_of` (patrz docstring tabeli w
    SCHEMA). `cik` musi być wcześniej wpisany do `companies` (FK).
    Zwraca `payload_sha256` zapisanego payloadu (audyt/reprodukowalność)."""
    raw_json = json.dumps(company_facts, sort_keys=True)
    payload_sha256 = hashlib.sha256(raw_json.encode("utf-8")).hexdigest()
    conn.execute(
        """
        INSERT INTO sec_company_facts_cache (cik, raw_json, source, payload_sha256, fetched_at)
        VALUES (?, ?, ?, ?, datetime('now'))
        ON CONFLICT(cik) DO UPDATE SET
            raw_json = excluded.raw_json,
            source = excluded.source,
            payload_sha256 = excluded.payload_sha256,
            fetched_at = excluded.fetched_at
        """,
        (cik, raw_json, source, payload_sha256),
    )
    return payload_sha256


def get_sec_company_facts_cache(conn: sqlite3.Connection, cik: str) -> dict | None:
    """Odczytuje surowy `company_facts` JSON z cache, albo `None`, jeśli
    ten CIK nigdy nie był cache'owany — jawny brak danych, NIGDY fallback
    na `fundamentals_raw` (to inna ścieżka, inny provider, inna
    semantyka — patrz docstring tabeli). Zwrócony dict ma IDENTYCZNY
    kształt jak ten, który wejściowo zapisano -- konsumenci (np.
    `pit_fundamentals.build_annual_fundamentals_periods_as_of`) używają
    go bez żadnej różnicy względem świeżo pobranego z SEC."""
    row = conn.execute(
        "SELECT raw_json FROM sec_company_facts_cache WHERE cik = ?", (cik,)
    ).fetchone()
    if row is None:
        return None
    return json.loads(row["raw_json"])


def upsert_backfill_status(
    conn: sqlite3.Connection,
    *,
    cik: str,
    task_type: str,
    status: str,
    run_id: str,
    detail: str | None = None,
) -> None:
    """Zapisuje NAJNOWSZY status (cik, task_type) — nadpisuje poprzedni
    wiersz (resumability: kolejny przebieg musi widzieć aktualny stan,
    nie historię). `status` musi być jednym z COMPLETE/PARTIAL/FAILED/
    NOT_ATTEMPTED (patrz CHECK w SCHEMA) — literówka tutaj jest błędem
    programistycznym, nie danymi wejściowymi, stąd brak walidacji w
    Pythonie: SQLite CHECK sam odrzuci złą wartość."""
    conn.execute(
        """
        INSERT INTO backfill_status (cik, task_type, status, detail, run_id, updated_at)
        VALUES (?, ?, ?, ?, ?, datetime('now'))
        ON CONFLICT(cik, task_type) DO UPDATE SET
            status = excluded.status,
            detail = excluded.detail,
            run_id = excluded.run_id,
            updated_at = excluded.updated_at
        """,
        (cik, task_type, status, detail, run_id),
    )


def get_backfill_status(conn: sqlite3.Connection, cik: str, task_type: str) -> sqlite3.Row | None:
    """`None` = nigdy nie podjęto próby (NOT_ATTEMPTED i `None` to różne
    rzeczy: NOT_ATTEMPTED jest jawnym wierszem zapisanym przez orkiestrację
    po stwierdzeniu braku jakichkolwiek danych; `None` to stan PRZED
    pierwszym przebiegiem backfillu w ogóle — resumability traktuje obie
    sytuacje identycznie, jako „do zrobienia”, ale rozróżnienie ma
    znaczenie dla audytu)."""
    return conn.execute(
        "SELECT * FROM backfill_status WHERE cik = ? AND task_type = ?", (cik, task_type)
    ).fetchone()


def list_backfill_statuses(conn: sqlite3.Connection, task_type: str | None = None) -> list[sqlite3.Row]:
    if task_type is None:
        return conn.execute("SELECT * FROM backfill_status ORDER BY cik, task_type").fetchall()
    return conn.execute(
        "SELECT * FROM backfill_status WHERE task_type = ? ORDER BY cik", (task_type,)
    ).fetchall()


def list_universe_membership_ciks(conn: sqlite3.Connection, index_name: str) -> list[str]:
    """Wszystkie DISTINCT CIK, które kiedykolwiek miały wiersz w
    `universe_membership` dla danego `index_name` — pełny zresolved
    zbiór (626 dla SP500/fja05680), niezależnie od aktualnego "as of"
    membership (backfill potrzebuje WSZYSTKICH historycznych członków,
    nie tylko dzisiejszych — patrz `backfill.py`)."""
    rows = conn.execute(
        "SELECT DISTINCT cik FROM universe_membership WHERE index_name = ? ORDER BY cik",
        (index_name,),
    ).fetchall()
    return [r["cik"] for r in rows]


def insert_backtest_coverage(conn: sqlite3.Connection, *, run_id: str, snapshot) -> None:
    """`snapshot`: `walk_forward_coverage.CoverageSnapshot`. Jeden
    wiersz per (run_id, decision_date) — PRIMARY KEY zapobiega cichemu
    duplikowaniu, jeśli ten sam run zapisze tę samą datę dwa razy
    (błąd wołającego, nie coś, co powinno się zdarzyć w normalnym
    przebiegu)."""
    conn.execute(
        """
        INSERT INTO backtest_coverage (
            run_id, decision_date, pit_universe_count, sufficient_price_count,
            sufficient_fundamentals_count, scanned_count, excluded_missing_price_count,
            excluded_missing_fundamentals_count, stage_no_decline_signal,
            stage_excluded_by_prefilter, stage_hard_gate_failed, stage_candidate
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id, snapshot.decision_date, snapshot.pit_universe_count,
            snapshot.sufficient_price_count, snapshot.sufficient_fundamentals_count,
            snapshot.scanned_count, snapshot.excluded_missing_price_count,
            snapshot.excluded_missing_fundamentals_count, snapshot.stage_no_decline_signal,
            snapshot.stage_excluded_by_prefilter, snapshot.stage_hard_gate_failed,
            snapshot.stage_candidate,
        ),
    )


def insert_backtest_candidate(conn: sqlite3.Connection, *, run_id: str, candidate) -> None:
    """`candidate`: `backtest_harness.BacktestCandidate` (już z
    `forward_returns` dołączonymi przez `attach_forward_returns`, może
    być `None` jeśli wywołujący jeszcze tego nie zrobił — wtedy
    return_*_pct zapisane jako NULL, nigdy zgadywane)."""
    fr = candidate.forward_returns
    conn.execute(
        """
        INSERT INTO backtest_candidates (
            run_id, decision_date, cik, ticker_as_of_date, decision_price,
            pit_fundamentals_period_end, pit_fundamentals_filed_date,
            safety_score, valuation_score, dividend_score, deterministic_partial_score,
            deterministic_score_pct, available_components, missing_components,
            margin_of_safety_base_pct, config_version, scoring_version,
            return_1m_pct, return_3m_pct, return_6m_pct, return_12m_pct
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id, candidate.decision_date, candidate.cik, candidate.ticker_as_of_date,
            candidate.decision_price, candidate.pit_fundamentals_period_end,
            candidate.pit_fundamentals_filed_date, candidate.safety_score,
            candidate.valuation_score, candidate.dividend_score,
            candidate.deterministic_partial_score, candidate.deterministic_score_pct,
            ",".join(candidate.available_components), ",".join(candidate.missing_components),
            candidate.margin_of_safety_base_pct, candidate.config_version,
            candidate.scoring_version,
            fr.return_1m_pct if fr else None, fr.return_3m_pct if fr else None,
            fr.return_6m_pct if fr else None, fr.return_12m_pct if fr else None,
        ),
    )


def get_backtest_coverage(conn: sqlite3.Connection, run_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM backtest_coverage WHERE run_id = ? ORDER BY decision_date", (run_id,)
    ).fetchall()


def get_backtest_candidates(conn: sqlite3.Connection, run_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM backtest_candidates WHERE run_id = ? ORDER BY decision_date, cik", (run_id,)
    ).fetchall()


def insert_backtest_benchmark(conn: sqlite3.Connection, *, run_id: str, snapshot) -> None:
    """`snapshot`: `benchmark.BenchmarkSnapshot` (Faza 5.3c). Jeden
    wiersz per (run_id, decision_date), oba benchmarki (equal_weighted_
    pit_universe + SPY) w tym samym wierszu, ale w ODDZIELNYCH kolumnach
    — nigdy nie mieszane w jedną wartość."""
    conn.execute(
        """
        INSERT INTO backtest_benchmark (
            run_id, decision_date,
            ew_pit_universe_return_1m_pct, ew_pit_universe_return_3m_pct,
            ew_pit_universe_return_6m_pct, ew_pit_universe_return_12m_pct,
            ew_pit_universe_n_1m, ew_pit_universe_n_3m, ew_pit_universe_n_6m, ew_pit_universe_n_12m,
            spy_return_1m_pct, spy_return_3m_pct, spy_return_6m_pct, spy_return_12m_pct
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id, snapshot.decision_date,
            snapshot.ew_pit_universe_return_1m_pct, snapshot.ew_pit_universe_return_3m_pct,
            snapshot.ew_pit_universe_return_6m_pct, snapshot.ew_pit_universe_return_12m_pct,
            snapshot.ew_pit_universe_n_1m, snapshot.ew_pit_universe_n_3m,
            snapshot.ew_pit_universe_n_6m, snapshot.ew_pit_universe_n_12m,
            snapshot.spy_return_1m_pct, snapshot.spy_return_3m_pct,
            snapshot.spy_return_6m_pct, snapshot.spy_return_12m_pct,
        ),
    )


def get_backtest_benchmark(conn: sqlite3.Connection, run_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM backtest_benchmark WHERE run_id = ? ORDER BY decision_date", (run_id,)
    ).fetchall()


def update_company_sector_profile(conn: sqlite3.Connection, *, cik: str, sector_profile: str) -> None:
    """Aktualizuje WYŁĄCZNIE `sector_profile` istniejącej spółki (Faza
    5.3c, klasyfikacja SIC). Celowo nie używa `upsert_company` — to by
    wymagało przekazania `name`/`sector`/`industry`/`sub_industry`
    (inaczej `ON CONFLICT DO UPDATE` ustawiłoby je na NULL, nadpisując
    już zapisane dane niezwiązane z tą zmianą). Brak wiersza dla `cik`
    -> brak efektu (nigdy nie tworzy spółki z samym sector_profile)."""
    conn.execute(
        "UPDATE companies SET sector_profile = ? WHERE cik = ?",
        (sector_profile, cik),
    )


def get_companies_sector_profiles(conn: sqlite3.Connection) -> dict[str, str]:
    """Jedno zapytanie zamiast N — per-CIK `sector_profile` już w
    `companies` (domyślnie `'GENERAL'` dla każdego CIK, bo klasyfikacja
    sektorowa nie była jeszcze wykonana — patrz raport Fazy 5.3c)."""
    rows = conn.execute("SELECT cik, sector_profile FROM companies").fetchall()
    return {r["cik"]: r["sector_profile"] for r in rows}


def insert_calibration_run(
    conn: sqlite3.Connection,
    *,
    calibration_run_id: str,
    evaluation,
    config_hash: str,
    config_json: str,
    training_window_start: str,
    training_window_end: str,
    oos_fold_years: tuple[int, ...],
    spearman_evaluation=None,
) -> None:
    """`evaluation`: `calibration.CalibrationEvaluation` (median-excess
    metric — PRIMARY dla Round 1, DIAGNOSTIC-only dla Round 2A/2B).
    `spearman_evaluation`: opcjonalnie `calibration.
    SpearmanCalibrationEvaluation` (Faza 5.4b) — PRIMARY dla Round 2A/2B,
    `None` dla Round 1 (kolumny `*_spearman*` pozostają NULL). NIGDY
    UPDATE/DELETE na tej tabeli (Faza 5.4, punkt 9.5/11 protokołu —
    przegrywające konfiguracje zostają, audytowalność całego procesu)."""
    metrics = {
        "median_excess_evaluation": {
            "fold_metrics": [
                {
                    "fold_year": m.fold_year, "n": m.n, "low_sample": m.low_sample,
                    "median_excess_return_pct": m.median_excess_return_pct,
                }
                for m in evaluation.fold_metrics
            ],
            "secondary": [
                {
                    "horizon_months": s.horizon_months,
                    "n_vs_ew": s.n_vs_ew, "n_vs_spy": s.n_vs_spy,
                    "hit_rate_vs_ew_pct": s.hit_rate_vs_ew_pct, "hit_rate_vs_spy_pct": s.hit_rate_vs_spy_pct,
                    "median_excess_vs_ew_pct": s.median_excess_vs_ew_pct,
                    "median_excess_vs_spy_pct": s.median_excess_vs_spy_pct,
                    "spearman_score_vs_return": s.spearman_score_vs_return,
                    "low_sample": s.low_sample,
                }
                for s in evaluation.secondary
            ],
        },
    }
    if spearman_evaluation is not None:
        metrics["spearman_evaluation"] = {
            "fold_metrics": [
                {
                    "fold_year": m.fold_year, "n": m.n, "low_sample": m.low_sample,
                    "spearman": m.spearman,
                }
                for m in spearman_evaluation.fold_metrics
            ],
        }
    metrics_json = json.dumps(metrics)

    subround = getattr(spearman_evaluation, "subround", None)
    population = getattr(spearman_evaluation, "population", None)
    pooled_spearman = getattr(spearman_evaluation, "pooled_spearman", None)
    pooled_spearman_low_sample = (
        int(spearman_evaluation.pooled_low_sample) if spearman_evaluation is not None else None
    )
    median_of_fold_spearman = getattr(spearman_evaluation, "median_of_fold_spearman", None)
    min_fold_spearman = getattr(spearman_evaluation, "min_fold_spearman", None)
    max_fold_spearman = getattr(spearman_evaluation, "max_fold_spearman", None)
    n_positive_spearman_folds = getattr(spearman_evaluation, "n_positive_folds", None)
    n_spearman_folds_with_data = getattr(spearman_evaluation, "n_folds_with_data", None)

    conn.execute(
        """
        INSERT INTO calibration_runs (
            calibration_run_id, round, candidate_name, description, config_hash, config_json,
            training_window_start, training_window_end, oos_fold_years,
            n_total_candidates, pooled_n, pooled_median_excess_return_pct, pooled_low_sample,
            median_of_fold_medians_pct, min_fold_median_pct, max_fold_median_pct,
            n_positive_folds, n_folds_with_data, metrics_json,
            subround, population, pooled_spearman, pooled_spearman_low_sample,
            median_of_fold_spearman, min_fold_spearman, max_fold_spearman,
            n_positive_spearman_folds, n_spearman_folds_with_data
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            calibration_run_id, evaluation.round, evaluation.candidate_name, evaluation.description,
            config_hash, config_json, training_window_start, training_window_end,
            json.dumps(list(oos_fold_years)),
            evaluation.n_total_candidates, evaluation.pooled_n, evaluation.pooled_median_excess_return_pct,
            int(evaluation.pooled_low_sample),
            evaluation.median_of_fold_medians_pct, evaluation.min_fold_median_pct, evaluation.max_fold_median_pct,
            evaluation.n_positive_folds, evaluation.n_folds_with_data, metrics_json,
            subround, population, pooled_spearman, pooled_spearman_low_sample,
            median_of_fold_spearman, min_fold_spearman, max_fold_spearman,
            n_positive_spearman_folds, n_spearman_folds_with_data,
        ),
    )


def get_calibration_runs(conn: sqlite3.Connection, *, round: int | None = None) -> list[sqlite3.Row]:
    if round is None:
        return conn.execute("SELECT * FROM calibration_runs ORDER BY round, created_at").fetchall()
    return conn.execute(
        "SELECT * FROM calibration_runs WHERE round = ? ORDER BY created_at", (round,)
    ).fetchall()


def mark_calibration_winner(conn: sqlite3.Connection, calibration_run_id: str) -> None:
    """Oznacza jeden wiersz jako `frozen_winner` TEJ rundy — nie usuwa
    przegrywających, tylko dodaje status (punkt 7 protokołu: zwycięzca
    rundy musi być zamrożony przed przejściem do następnej)."""
    conn.execute(
        "UPDATE calibration_runs SET status = 'frozen_winner' WHERE calibration_run_id = ?",
        (calibration_run_id,),
    )


# ---------------------------------------------------------------------------
# Faza 6c — live scan dwustopniowy pipeline (deterministic ranking +
# resumable/cache'owana analiza Claude WYŁĄCZNIE dla shortlisty)
# ---------------------------------------------------------------------------


def insert_live_scan_run(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    run_date: str,
    config_version: str,
    universe_size: int,
    decline_surfaced: int,
    prefilter_excluded: int,
    shortlist_limit: int,
    shortlist_size: int,
) -> None:
    conn.execute(
        """
        INSERT INTO live_scan_runs (
            run_id, run_date, config_version, universe_size, decline_surfaced,
            prefilter_excluded, shortlist_limit, shortlist_size
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id, run_date, config_version, universe_size, decline_surfaced,
            prefilter_excluded, shortlist_limit, shortlist_size,
        ),
    )


def insert_live_scan_candidate(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    cik: str,
    ticker: str,
    rank: int,
    current_price: float,
    decline_flags: dict[str, bool],
    deterministic_score_pct: float | None,
    deterministic_partial_score: float,
    available_components: tuple[str, ...],
    missing_components: tuple[str, ...],
    safety_score: float,
    valuation_score: float | None,
    dividend_score: float,
    margin_of_safety_base_pct: float | None,
    hard_gate_passed_deterministic: bool,
    hard_gate_triggered_deterministic: tuple[str, ...],
    in_shortlist: bool,
) -> None:
    """Jeden wiersz pełnego deterministycznego rankingu (Faza 6c, etap 1)
    — zapisywany dla WSZYSTKICH kandydatów, którzy przeszli decline
    screening + prefilter, niezależnie od tego, czy wejdą do shortlisty.
    `llm_status` startuje jako `'PENDING'` dla shortlisty, `'NOT_SHORTLISTED'`
    dla resztę — nigdy nie wywołuje Claude tutaj."""
    conn.execute(
        """
        INSERT INTO live_scan_candidates (
            run_id, cik, ticker, rank, current_price, decline_flags_json,
            deterministic_score_pct, deterministic_partial_score,
            available_components_json, missing_components_json,
            safety_score, valuation_score, dividend_score, margin_of_safety_base_pct,
            hard_gate_passed_deterministic, hard_gate_triggered_deterministic_json,
            in_shortlist, llm_status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id, cik, ticker, rank, current_price, json.dumps(decline_flags),
            deterministic_score_pct, deterministic_partial_score,
            json.dumps(list(available_components)), json.dumps(list(missing_components)),
            safety_score, valuation_score, dividend_score, margin_of_safety_base_pct,
            int(hard_gate_passed_deterministic), json.dumps(list(hard_gate_triggered_deterministic)),
            int(in_shortlist), "PENDING" if in_shortlist else "NOT_SHORTLISTED",
        ),
    )


def get_live_scan_run(conn: sqlite3.Connection, run_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM live_scan_runs WHERE run_id = ?", (run_id,)).fetchone()


def get_live_scan_candidates(
    conn: sqlite3.Connection, run_id: str, *, only_shortlist: bool = False,
) -> list[sqlite3.Row]:
    if only_shortlist:
        return conn.execute(
            "SELECT * FROM live_scan_candidates WHERE run_id = ? AND in_shortlist = 1 ORDER BY rank",
            (run_id,),
        ).fetchall()
    return conn.execute(
        "SELECT * FROM live_scan_candidates WHERE run_id = ? ORDER BY rank", (run_id,)
    ).fetchall()


def find_cached_live_scan_analysis(conn: sqlite3.Connection, cache_key: str) -> int | None:
    """Szuka JUŻ ukończonej (`llm_status='COMPLETE'`) analizy z identycznym
    `cache_key`, z JAKIEGOKOLWIEK poprzedniego run_id — zwraca jej
    `analysis_id` do ponownego użycia bez nowego wywołania Claude API,
    albo `None`, jeśli nie ma trafienia (Decyzja właścicielki, Faza 6c:
    "nie wywołuj API ponownie bez potrzeby")."""
    row = conn.execute(
        """
        SELECT analysis_id FROM live_scan_candidates
        WHERE cache_key = ? AND llm_status = 'COMPLETE' AND analysis_id IS NOT NULL
        LIMIT 1
        """,
        (cache_key,),
    ).fetchone()
    return row["analysis_id"] if row else None


def update_live_scan_candidate_llm_status(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    cik: str,
    llm_status: str,
    llm_error: str | None = None,
    cache_key: str | None = None,
    analysis_id: int | None = None,
    usage: ClaudeUsage | None = None,
    repair_usage: ClaudeUsage | None = None,
) -> None:
    """`usage` (Faza 6e): realny `ClaudeUsage` gdy API faktycznie
    odpowiedziało w TYM wywołaniu (sukces, albo FAILED przez refusal/
    nie-sparsowalny JSON) — `None` gdy nie było żadnej odpowiedzi do
    zmierzenia (błąd API bez `response`, brak fundamentals/źródeł) albo
    gdy to CACHE HIT (zero nowego wywołania, więc zero nowego kosztu w
    TYM run_id). Nigdy nie wymyślamy wartości zamiast `None`.

    `repair_usage` (Faza 6h, TARGETED FIELD REPAIR): usage ODRĘBNEGO
    minimalnego repair call (`repair_thesis_invalidation`) — `None`, gdy
    ten kandydat nie potrzebował repair w TYM wywołaniu (pełna analiza
    przeszła od razu, albo repair nie był zasadny). Zapisywany w
    osobnych kolumnach `llm_repair_*`, NIE sumowany z `usage` w bazie —
    audyt/telemetria musi móc rozróżnić full_analysis_call od
    thesis_invalidation_repair_call (specyfikacja właścicielki, Faza 6h,
    punkt 3)."""
    conn.execute(
        """
        UPDATE live_scan_candidates
        SET llm_status = ?, llm_error = ?, cache_key = ?, analysis_id = ?,
            llm_response_model = ?, llm_input_tokens = ?, llm_output_tokens = ?,
            llm_cache_creation_input_tokens = ?, llm_cache_read_input_tokens = ?,
            llm_thinking_tokens = ?, llm_service_tier = ?,
            llm_repair_response_model = ?, llm_repair_input_tokens = ?,
            llm_repair_output_tokens = ?, llm_repair_cache_creation_input_tokens = ?,
            llm_repair_cache_read_input_tokens = ?, llm_repair_thinking_tokens = ?,
            llm_repair_service_tier = ?
        WHERE run_id = ? AND cik = ?
        """,
        (
            llm_status, llm_error, cache_key, analysis_id,
            usage.model if usage else None,
            usage.input_tokens if usage else None,
            usage.output_tokens if usage else None,
            usage.cache_creation_input_tokens if usage else None,
            usage.cache_read_input_tokens if usage else None,
            usage.thinking_tokens if usage else None,
            usage.service_tier if usage else None,
            repair_usage.model if repair_usage else None,
            repair_usage.input_tokens if repair_usage else None,
            repair_usage.output_tokens if repair_usage else None,
            repair_usage.cache_creation_input_tokens if repair_usage else None,
            repair_usage.cache_read_input_tokens if repair_usage else None,
            repair_usage.thinking_tokens if repair_usage else None,
            repair_usage.service_tier if repair_usage else None,
            run_id, cik,
        ),
    )


def update_live_scan_run_status(conn: sqlite3.Connection, run_id: str, status: str) -> None:
    conn.execute("UPDATE live_scan_runs SET status = ? WHERE run_id = ?", (status, run_id))


def get_live_scan_run_usage_summary(conn: sqlite3.Connection, run_id: str) -> dict:
    """Agregat per-run (Faza 6e) — płaski SUM po `live_scan_candidates`
    dla `run_id` (NIE join do `analyses`: cache hit ma tu `NULL` usage,
    więc nigdy nie jest liczony jako nowy koszt TEGO runu, mimo że jego
    `analysis_id` wskazuje na analizę policzoną w innym, wcześniejszym
    run_id). Zwraca surowe sumy tokenów/liczniki — zero wyliczonego $
    (patrz `ClaudeUsage`/COST AUDIT Faza 6d: brak zweryfikowanego
    cennika per-token).

    Faza 6h (TARGETED FIELD REPAIR): `repair_calls`/`total_repair_*`
    liczone i sumowane ODRĘBNIE od `calls_with_usage`/`total_*` (pełny
    analysis call) — audyt musi móc rozróżnić full_analysis_call od
    thesis_invalidation_repair_call. `total_combined_*` sumuje oba, do
    raportowania całkowitego kosztu bez utraty rozróżnienia."""
    row = conn.execute(
        """
        SELECT
            COUNT(*) AS shortlist_size,
            SUM(CASE WHEN llm_input_tokens IS NOT NULL THEN 1 ELSE 0 END) AS calls_with_usage,
            SUM(CASE WHEN llm_status = 'COMPLETE' AND llm_input_tokens IS NULL
                     THEN 1 ELSE 0 END) AS cache_hits,
            SUM(CASE WHEN llm_status = 'FAILED' THEN 1 ELSE 0 END) AS failed,
            SUM(llm_input_tokens) AS total_input_tokens,
            SUM(llm_output_tokens) AS total_output_tokens,
            SUM(llm_cache_creation_input_tokens) AS total_cache_creation_input_tokens,
            SUM(llm_cache_read_input_tokens) AS total_cache_read_input_tokens,
            SUM(llm_thinking_tokens) AS total_thinking_tokens,
            SUM(CASE WHEN llm_repair_input_tokens IS NOT NULL THEN 1 ELSE 0 END) AS repair_calls,
            SUM(llm_repair_input_tokens) AS total_repair_input_tokens,
            SUM(llm_repair_output_tokens) AS total_repair_output_tokens,
            SUM(llm_repair_cache_creation_input_tokens) AS total_repair_cache_creation_input_tokens,
            SUM(llm_repair_cache_read_input_tokens) AS total_repair_cache_read_input_tokens,
            SUM(llm_repair_thinking_tokens) AS total_repair_thinking_tokens
        FROM live_scan_candidates
        WHERE run_id = ? AND in_shortlist = 1
        """,
        (run_id,),
    ).fetchone()
    summary = dict(row) if row else {}
    if summary:
        summary["total_combined_input_tokens"] = (
            (summary["total_input_tokens"] or 0) + (summary["total_repair_input_tokens"] or 0)
        )
        summary["total_combined_output_tokens"] = (
            (summary["total_output_tokens"] or 0) + (summary["total_repair_output_tokens"] or 0)
        )
    return summary


# ---------------------------------------------------------------------------
# Faza 7 (UI + PORTFOLIO V0) — CRUD dla user_decisions/positions/
# purchase_transactions/sale_transactions/purchase_thesis/
# holding_user_actions. Ten sam wzorzec co resztę pliku: proste
# INSERT/SELECT, zero logiki biznesowej (liczenie pozycji "on-read"
# mieszka w ui/portfolio.py, nie tutaj).
# ---------------------------------------------------------------------------


def get_users(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM users ORDER BY user_id").fetchall()


def insert_user_decision(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    cik: str,
    status: str,
    analysis_id: int | None = None,
    note: str | None = None,
) -> int:
    """Append-only (Faza 7) — korekta decyzji to nowy wiersz, nigdy
    UPDATE. `get_latest_user_decision` czyta najnowszy wiersz per
    (user_id, cik)."""
    cur = conn.execute(
        """
        INSERT INTO user_decisions (user_id, cik, analysis_id, status, note)
        VALUES (?, ?, ?, ?, ?)
        """,
        (user_id, cik, analysis_id, status, note),
    )
    return cur.lastrowid


def get_latest_user_decision(conn: sqlite3.Connection, *, user_id: int, cik: str) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT * FROM user_decisions WHERE user_id = ? AND cik = ?
        ORDER BY decision_id DESC LIMIT 1
        """,
        (user_id, cik),
    ).fetchone()


def get_latest_user_decisions_for_user(conn: sqlite3.Connection, user_id: int) -> dict[str, sqlite3.Row]:
    """Najnowsza decyzja PER cik dla tego usera -- `MAX(decision_id)` per
    grupa (SQLite: podzapytanie, nie window function, dla zgodności ze
    starszymi wersjami SQLite używanymi w tym projekcie)."""
    rows = conn.execute(
        """
        SELECT ud.* FROM user_decisions ud
        WHERE ud.user_id = ? AND ud.decision_id = (
            SELECT MAX(decision_id) FROM user_decisions
            WHERE user_id = ud.user_id AND cik = ud.cik
        )
        """,
        (user_id,),
    ).fetchall()
    return {r["cik"]: r for r in rows}


def insert_position(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    ticker: str,
    company_name: str,
    cik: str | None = None,
    exchange: str | None = None,
    instrument_currency: str | None = None,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO positions (user_id, cik, ticker, company_name, exchange, instrument_currency)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (user_id, cik, ticker, company_name, exchange, instrument_currency),
    )
    return cur.lastrowid


def get_positions_for_user(conn: sqlite3.Connection, user_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM positions WHERE user_id = ? ORDER BY created_at", (user_id,)
    ).fetchall()


def get_position(conn: sqlite3.Connection, position_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM positions WHERE position_id = ?", (position_id,)
    ).fetchone()


def insert_purchase_transaction(
    conn: sqlite3.Connection,
    *,
    position_id: int,
    broker: str,
    acquisition_type: str,
    purchase_date: str,
    shares: float,
    total_invested: float,
    currency: str,
    price_per_share: float | None = None,
    fees: float | None = None,
    note: str | None = None,
) -> int:
    """`acquisition_type='BONUS'` -- wołający MUSI przekazać
    `total_invested=0` (Decyzja właścicielki, Faza 7 pkt 3: "nigdy nie
    udawaj, że użytkownik zapłacił za te akcje") -- ta funkcja nie
    wymusza tego sama, bo nie zna semantyki, tylko zapisuje to, co
    dostanie (wołający, `ui/`, jest odpowiedzialny za tę regułę)."""
    cur = conn.execute(
        """
        INSERT INTO purchase_transactions (
            position_id, broker, acquisition_type, purchase_date, shares,
            price_per_share, total_invested, currency, fees, note
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            position_id, broker, acquisition_type, purchase_date, shares,
            price_per_share, total_invested, currency, fees, note,
        ),
    )
    return cur.lastrowid


def get_purchase_transactions(conn: sqlite3.Connection, position_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM purchase_transactions WHERE position_id = ? ORDER BY purchase_date",
        (position_id,),
    ).fetchall()


def insert_sale_transaction(
    conn: sqlite3.Connection,
    *,
    position_id: int,
    broker: str,
    sale_date: str,
    shares: float,
    sale_price: float,
    currency: str,
    fees: float | None = None,
    note: str | None = None,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO sale_transactions (
            position_id, broker, sale_date, shares, sale_price, currency, fees, note
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (position_id, broker, sale_date, shares, sale_price, currency, fees, note),
    )
    return cur.lastrowid


def get_sale_transactions(conn: sqlite3.Connection, position_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM sale_transactions WHERE position_id = ? ORDER BY sale_date",
        (position_id,),
    ).fetchall()


def insert_purchase_thesis(
    conn: sqlite3.Connection,
    *,
    position_id: int,
    analysis_id: int | None = None,
    snapshot_json: str | None = None,
) -> int:
    """`position_id` jest UNIQUE w schemacie -- druga teza dla tej samej
    pozycji rzuci `sqlite3.IntegrityError` (immutable snapshot, sekcja
    16 design review: korekta = nowa pozycja, nie edycja tezy)."""
    cur = conn.execute(
        """
        INSERT INTO purchase_thesis (position_id, analysis_id, snapshot_json)
        VALUES (?, ?, ?)
        """,
        (position_id, analysis_id, snapshot_json),
    )
    return cur.lastrowid


def get_purchase_thesis(conn: sqlite3.Connection, position_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM purchase_thesis WHERE position_id = ?", (position_id,)
    ).fetchone()


def insert_holding_user_action(
    conn: sqlite3.Connection, *, position_id: int, action: str, note: str | None = None,
) -> int:
    cur = conn.execute(
        "INSERT INTO holding_user_actions (position_id, action, note) VALUES (?, ?, ?)",
        (position_id, action, note),
    )
    return cur.lastrowid


def get_latest_holding_user_action(conn: sqlite3.Connection, position_id: int) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT * FROM holding_user_actions WHERE position_id = ?
        ORDER BY action_id DESC LIMIT 1
        """,
        (position_id,),
    ).fetchone()

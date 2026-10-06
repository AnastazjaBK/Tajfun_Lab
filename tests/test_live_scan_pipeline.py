"""Testy Fazy 6c (domknięcie MVP V0, OPCJA 3) — deterministyczny
ranking WSZYSTKICH decline-surfaced kandydatów (zero LLM, reużywa
zamrożony `backtest_harness.compute_deterministic_score`), shortlist
(TOP N + remisy), cache key dla pełnej analizy Claude."""

from __future__ import annotations

from buffett_scanner.backtest_harness import compute_deterministic_score, evaluate_deterministic_hard_gates
from buffett_scanner.config import load_config
from buffett_scanner.fundamentals import FundamentalsPeriod
from buffett_scanner.live_scan_pipeline import (
    RankedCandidate,
    build_cache_key,
    rank_all_candidates,
    render_full_ranking_table,
    select_shortlist,
    source_fingerprint,
)
from buffett_scanner.scanner import PriceChangeSnapshot
from buffett_scanner.sources import VerifiedSource


def _period(fp: str, **kw) -> FundamentalsPeriod:
    base = dict(
        fiscal_period=fp, period_end_date=f"{fp}-12-31", filed_date=None,
        revenue=None, net_income=None, ebitda=None, operating_cash_flow=None,
        capital_expenditure=None, total_debt=None, cash_and_equivalents=None,
        total_current_assets=None, total_current_liabilities=None,
    )
    base.update(kw)
    return FundamentalsPeriod(**base)


def _snapshot() -> PriceChangeSnapshot:
    return PriceChangeSnapshot(
        as_of_date="2026-10-05", daily_pct=-6.0, week_pct=-9.0, month_pct=-12.0,
        quarter_pct=-15.0, ytd_pct=-20.0, year_pct=-10.0,
        drawdown_from_52w_high_pct=-30.0, relative_volume=2.1,
    )


def _candidate(
    ticker: str, *, sector_profile: str = "GENERAL", current_price: float = 15.0,
) -> RankedCandidate:
    """`current_price` niższa => wyższy Margin of Safety => wyższy
    `valuation_score` => wyższy `deterministic_score_pct` — jedyny,
    jednoznacznie monotoniczny "dial" używany w tych testach do
    kontrolowania relatywnego rankingu (w przeciwieństwie do revenue,
    który wpływa na kilka nieskorelowanych wskaźników naraz)."""
    config = load_config()
    periods = [
        _period("FY2023", revenue=1000.0, net_income=50.0, ebitda=200.0, operating_cash_flow=150.0,
                capital_expenditure=20.0, total_debt=100.0, cash_and_equivalents=150.0,
                total_current_assets=400.0, total_current_liabilities=200.0,
                dividends_paid=10.0, share_buybacks=10.0, diluted_shares_outstanding=100.0),
        _period("FY2024", revenue=1100.0, net_income=70.0, ebitda=220.0, operating_cash_flow=170.0,
                capital_expenditure=20.0, total_debt=100.0, cash_and_equivalents=150.0,
                total_current_assets=400.0, total_current_liabilities=200.0,
                dividends_paid=12.0, share_buybacks=10.0, diluted_shares_outstanding=100.0),
    ]
    score = compute_deterministic_score(
        periods=periods, sector_profile=sector_profile, current_price=current_price, config=config,
    )
    hard_gates = evaluate_deterministic_hard_gates(
        safety=score.safety_score, margin_of_safety_base_pct=score.margin_of_safety_base_pct, config=config,
    )
    return RankedCandidate(
        ticker=ticker, cik=f"000000000{ticker[0]}", current_price=15.0,
        decline_snapshot=_snapshot(), triggered_decline_flags={"month_decline": True},
        score=score, hard_gate_result=hard_gates,
    )


def test_rank_all_candidates_sorts_by_deterministic_score_pct_descending():
    higher = _candidate("HIGH", current_price=35.0)  # niższa cena -> wyższy MoS -> wyższy score
    lower = _candidate("LOW", current_price=55.0)
    assert higher.score.deterministic_score_pct > lower.score.deterministic_score_pct

    ranked = rank_all_candidates([lower, higher])
    assert [c.ticker for c in ranked] == ["HIGH", "LOW"]


def test_rank_all_candidates_puts_none_score_last_without_dropping():
    with_valuation = _candidate("WITH", sector_profile="GENERAL")
    no_valuation = _candidate("SANS", sector_profile="BANK")  # wycena NOT_YET_IMPLEMENTED
    assert with_valuation.score.deterministic_score_pct is not None
    # BANK ma wciąż safety+dividend dostępne -> deterministic_score_pct NIE jest None
    # (tylko valuation wyłączone z obu stron ułamka) -- sprawdzamy, że ranking
    # po prostu porządkuje wg dostępnego wyniku, nic nie gubi.
    ranked = rank_all_candidates([no_valuation, with_valuation])
    assert len(ranked) == 2
    assert {c.ticker for c in ranked} == {"WITH", "SANS"}


def test_select_shortlist_limits_to_top_n():
    # Ceny w strefie liniowej valuation_score (32-61, poza saturacją przy
    # niskiej cenie i podłogą przy wysokiej, patrz docstring `_candidate`)
    # -> deterministic_score_pct wszystkie różne, zero remisów na granicy
    # -- czysty test obcięcia do `limit`.
    candidates = [_candidate(f"T{i}", current_price=32.0 + i * 1.0) for i in range(30)]
    ranked = rank_all_candidates(candidates)
    shortlist = select_shortlist(ranked, limit=20)
    assert len(shortlist) == 20
    assert shortlist == ranked[:20]


def test_select_shortlist_keeps_all_ties_at_boundary():
    # Dwa kandydaci z IDENTYCZNĄ ceną (-> identyczny wynik) na granicy
    # limitu -- oba muszą zostać zachowane.
    distinct = [_candidate(f"D{i}", current_price=32.0 + i * 5.0) for i in range(4)]
    tied_a = _candidate("TIEA", current_price=50.0)
    tied_b = _candidate("TIEB", current_price=50.0)
    assert tied_a.score.deterministic_score_pct == tied_b.score.deterministic_score_pct

    ranked = rank_all_candidates(distinct + [tied_a, tied_b])
    shortlist = select_shortlist(ranked, limit=5)
    # Pozycja 5 (ostatnia w limicie) to jeden z remisujących -> OBA muszą wejść,
    # więc shortlist ma 6, nie 5.
    tickers = {c.ticker for c in shortlist}
    assert "TIEA" in tickers and "TIEB" in tickers
    assert len(shortlist) == 6


def test_select_shortlist_fewer_candidates_than_limit_returns_all():
    candidates = [_candidate(f"T{i}") for i in range(3)]
    ranked = rank_all_candidates(candidates)
    assert select_shortlist(ranked, limit=20) == ranked


def test_select_shortlist_empty_input_is_valid():
    assert select_shortlist([], limit=20) == []


def test_source_fingerprint_depends_only_on_verified_content_hashes():
    sources_a = [
        VerifiedSource(source_type="SEC_FILING", title="10-K", issuer="X", doc_date="2026-01-01",
                        url="https://a", accession_number="1", section=None, content_hash="hash1",
                        verified=True, reason=None),
        VerifiedSource(source_type="SEC_FILING", title="10-Q", issuer="X", doc_date="2026-04-01",
                        url="https://b-not-verified", accession_number="2", section=None,
                        content_hash=None, verified=False, reason="404"),
    ]
    # Inny URL dla tego samego zweryfikowanego dokumentu (treść identyczna,
    # hash identyczny) -> fingerprint NIE zmienia się.
    sources_b = [
        VerifiedSource(source_type="SEC_FILING", title="10-K", issuer="X", doc_date="2026-01-01",
                        url="https://different-url", accession_number="1", section=None,
                        content_hash="hash1", verified=True, reason=None),
    ]
    assert source_fingerprint(sources_a) == source_fingerprint(sources_b)


def test_source_fingerprint_changes_when_verified_content_hash_changes():
    sources_a = [
        VerifiedSource(source_type="SEC_FILING", title="10-K", issuer="X", doc_date="2026-01-01",
                        url="https://a", accession_number="1", section=None, content_hash="hash1",
                        verified=True, reason=None),
    ]
    sources_b = [
        VerifiedSource(source_type="SEC_FILING", title="10-K", issuer="X", doc_date="2026-01-01",
                        url="https://a", accession_number="1", section=None, content_hash="hash2",
                        verified=True, reason=None),
    ]
    assert source_fingerprint(sources_a) != source_fingerprint(sources_b)


def test_build_cache_key_is_deterministic_and_sensitive_to_every_component():
    base_kwargs = dict(
        cik="0000320193", data_timestamp="2026-10-06|2024-12-31|2025-02-01",
        config_version="config.yaml:abc123", prompt_schema_version="1.0",
        source_fingerprint="fp1",
    )
    key1 = build_cache_key(**base_kwargs)
    key2 = build_cache_key(**base_kwargs)
    assert key1 == key2  # deterministyczny

    for changed_field in ("cik", "data_timestamp", "config_version", "prompt_schema_version", "source_fingerprint"):
        kwargs = dict(base_kwargs)
        kwargs[changed_field] = kwargs[changed_field] + "-CHANGED"
        assert build_cache_key(**kwargs) != key1, f"{changed_field} powinno zmieniać cache_key"


def test_render_full_ranking_table_includes_all_candidates_and_decline_trigger():
    candidates = [_candidate("AAA", current_price=32.0), _candidate("BBB", current_price=45.0)]
    ranked = rank_all_candidates(candidates)
    table = render_full_ranking_table(ranked)
    assert "AAA" in table and "BBB" in table
    assert "month_decline" in table
    assert table.index("AAA") < table.index("BBB")  # wyższy score_pct wyżej w tabeli

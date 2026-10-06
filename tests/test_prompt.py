"""Testy budowy promptu Fazy 3 (sekcja 15, punkt 3.2) + Faza 6f (BUGFIX
V0 OUTPUT CONTRACT: kontekst ceny/wyceny/decline przekazywany Claude)."""

from __future__ import annotations

from buffett_scanner.prompt import build_analysis_prompt
from buffett_scanner.scanner import PriceChangeSnapshot
from buffett_scanner.sources import VerifiedSource
from buffett_scanner.valuation import ScenarioValuation, ValuationResult


def make_source(n: int, verified: bool = True) -> VerifiedSource:
    return VerifiedSource(
        source_type="SEC_FILING", title=f"10-K ({n})", issuer="Apple Inc.",
        doc_date=f"2024-0{n}-01", url=f"https://www.sec.gov/doc{n}.htm",
        accession_number=f"000032019324-00000{n}", section=None,
        content_hash=f"hash{n}" if verified else None, verified=verified,
        reason=None if verified else "404",
    )


def test_only_verified_sources_are_included_in_prompt():
    sources = [make_source(1, verified=True), make_source(2, verified=False)]
    prompt, source_id_map = build_analysis_prompt(
        ticker="AAPL", metrics={"fcf_ttm": 100.0}, prefilter_flags=[], sources=sources,
    )
    assert len(source_id_map) == 1
    assert "doc1.htm" in prompt
    assert "doc2.htm" not in prompt


def test_source_id_map_uses_sequential_local_ids():
    sources = [make_source(1), make_source(2), make_source(3)]
    _, source_id_map = build_analysis_prompt(
        ticker="AAPL", metrics={}, prefilter_flags=[], sources=sources,
    )
    assert list(source_id_map.keys()) == ["src-1", "src-2", "src-3"]
    assert source_id_map["src-2"].url == "https://www.sec.gov/doc2.htm"


def test_prompt_contains_ticker_and_schema_version_instructions():
    prompt, _ = build_analysis_prompt(
        ticker="MSFT", metrics={}, prefilter_flags=[], sources=[],
    )
    assert '"ticker" w wyjściu musi być dokładnie "MSFT"' in prompt
    assert '"schema_version" w wyjściu musi być dokładnie "1.0"' in prompt


def test_prompt_includes_prefilter_flags_when_present():
    prompt, _ = build_analysis_prompt(
        ticker="AAPL", metrics={}, prefilter_flags=["Niska płynność bieżąca"], sources=[],
    )
    assert "Niska płynność bieżąca" in prompt


def test_prompt_states_no_flags_when_empty():
    prompt, _ = build_analysis_prompt(ticker="AAPL", metrics={}, prefilter_flags=[], sources=[])
    assert "brak (żaden próg nie przekroczony)" in prompt


def test_prompt_with_no_sources_instructs_empty_verification_items():
    prompt, source_id_map = build_analysis_prompt(
        ticker="AAPL", metrics={}, prefilter_flags=[], sources=[],
    )
    assert source_id_map == {}
    assert "verification_items musi być puste" in prompt


def test_prompt_includes_anti_confirmation_bias_instructions():
    """Faza 6 GAP ANALYSIS: `AnalysisOutput` wymusza KSZTAŁT bull_case/
    bear_case/why_market_may_be_right/why_this_may_not_be_a_bargain/
    thesis_invalidation/biggest_unknown od Fazy 3, ale prompt nigdy nie
    instruował modelu, czym te pola są i czego wymagamy -- tylko
    poprawny JSON (output_format), nie treść. Ten test pilnuje, żeby
    instrukcje jawnie wymagały argumentowania PRZECIW własnej tezie,
    nie tylko wypełnienia pól formalnie."""
    prompt, _ = build_analysis_prompt(ticker="AAPL", metrics={}, prefilter_flags=[], sources=[])
    assert "bear_case" in prompt
    assert "why_market_may_be_right" in prompt
    assert "why_this_may_not_be_a_bargain" in prompt
    assert "thesis_invalidation" in prompt
    assert "biggest_unknown" in prompt
    assert "PRZECIW" in prompt


def test_prompt_explicitly_requires_at_least_one_thesis_invalidation_condition():
    """Test 1 (specyfikacja właścicielki, Faza 6g ROOT CAUSE AUDIT):
    LIVE VALIDATION TEST Fazy 6f wykazał 4/5 FAILED z pustym
    `thesis_invalidation` -- root cause: instrukcja promptu nigdy nie
    mówiła wprost "musisz podać co najmniej jeden", w przeciwieństwie
    do why_market_may_be_right/why_this_may_not_be_a_bargain (które mają
    jawny fallback dla niskiej pewności). Ten test pilnuje jawnego
    wymogu kardynalności + jawnego zakazu wymyślonych progów liczbowych."""
    prompt, _ = build_analysis_prompt(ticker="AAPL", metrics={}, prefilter_flags=[], sources=[])
    assert "MUSISZ podać co najmniej JEDEN" in prompt
    assert "TO POLE NIE MOŻE BYĆ PUSTE" in prompt
    assert "bez wymyślonego progu" in prompt


def test_prompt_includes_metric_values():
    prompt, _ = build_analysis_prompt(
        ticker="AAPL", metrics={"fcf_ttm": 12345.0, "current_ratio": None},
        prefilter_flags=[], sources=[],
    )
    assert "fcf_ttm: 12345.0" in prompt
    assert "current_ratio: None" in prompt


# ---------------------------------------------------------------------------
# BUGFIX V0 OUTPUT CONTRACT (Faza 6f, 2026-10-06) -- realny live run
# (live-scan-2026-10-06T083825543395Z): Claude wielokrotnie pisał "nie
# dysponuję danymi o aktualnej cenie/Margin of Safety", mimo że pipeline
# je już policzył deterministycznie PRZED wywołaniem Claude. Root cause:
# `build_analysis_prompt` nigdy nie przekazywał current_price/DCF/MoS/
# decline context -- tylko `metrics` (fundamentals), `prefilter_flags`,
# `sources`. Testy A/B niżej (specyfikacja właścicielki).
# ---------------------------------------------------------------------------


def _valuation_result(*, implemented: bool = True, reason: str | None = None) -> ValuationResult:
    if not implemented:
        return ValuationResult(sector_profile="GENERAL", method=None, implemented=False, reason=reason)
    return ValuationResult(
        sector_profile="GENERAL", method="dcf_owner_earnings", implemented=True,
        owner_earnings_proxy_fcf_latest=50.0, historical_growth_cagr_pct=10.0,
        scenarios={
            "bear": ScenarioValuation(
                scenario="bear", discount_rate_pct=11.0, terminal_growth_rate_pct=1.0,
                projected_growth_rate_pct=10.3, intrinsic_value_per_share=214.78,
                margin_of_safety_pct=-29.2,
            ),
            "base": ScenarioValuation(
                scenario="base", discount_rate_pct=9.0, terminal_growth_rate_pct=2.5,
                projected_growth_rate_pct=20.0, intrinsic_value_per_share=1817.83,
                margin_of_safety_pct=84.3,
            ),
            "bull": ScenarioValuation(
                scenario="bull", discount_rate_pct=7.0, terminal_growth_rate_pct=3.5,
                projected_growth_rate_pct=20.0, intrinsic_value_per_share=1243.76,
                margin_of_safety_pct=77.7,
            ),
        },
    )


def _decline_snapshot() -> PriceChangeSnapshot:
    return PriceChangeSnapshot(
        as_of_date="2026-10-05", daily_pct=2.29, week_pct=9.56, month_pct=-7.05,
        quarter_pct=7.28, ytd_pct=10.55, year_pct=14.90,
        drawdown_from_52w_high_pct=-25.25, relative_volume=1.19,
    )


def test_prompt_includes_current_price_decline_and_valuation_context_when_available():
    """Test A (specyfikacja właścicielki): Claude otrzymuje current_price,
    decline context i deterministyczne DCF/IV/MoS, gdy valuation jest
    dostępna -- odtwarza realny przykład INTU z live runu (current
    price=284.68, BASE IV=1817.83, BASE MoS=84.3%)."""
    prompt, _ = build_analysis_prompt(
        ticker="INTU", metrics={}, prefilter_flags=[], sources=[],
        current_price=284.68, decline_snapshot=_decline_snapshot(),
        valuation_result=_valuation_result(),
    )
    assert "KONTEKST CENY I WYCENY" in prompt
    assert "Aktualna cena: 284.68" in prompt
    assert "BASE: intrinsic value/akcję=1817.83, Margin of Safety=84.3%" in prompt
    assert "BEAR: intrinsic value/akcję=214.78, Margin of Safety=-29.2%" in prompt
    assert "BULL: intrinsic value/akcję=1243.76, Margin of Safety=77.7%" in prompt
    assert "Decline context" in prompt
    assert "1M=-7.05%" in prompt
    assert "Drawdown od 52w high=-25.25%" in prompt
    assert "NIE przeliczaj DCF samodzielnie" in prompt
    # Claude nie ma prawa twierdzić, że nie znał tych danych.
    assert "NIE twierdź, że nie znasz ceny/Margin of Safety" in prompt


def test_prompt_marks_price_and_valuation_explicitly_unavailable_when_not_given():
    """Test B (specyfikacja właścicielki): gdy valuation/current_price nie
    są dostępne (np. `cmd_analyze` dry-run bez pobranej ceny), prompt
    jawnie oznacza to jako niedostępne -- nigdy nie wymyśla wartości."""
    prompt, _ = build_analysis_prompt(
        ticker="AAPL", metrics={}, prefilter_flags=[], sources=[],
    )
    assert "Aktualna cena: NIEDOSTĘPNA w tym wywołaniu" in prompt
    assert "Wycena DCF: NIEDOSTĘPNA w tym wywołaniu" in prompt
    assert "Decline context: NIEDOSTĘPNY w tym wywołaniu" in prompt


def test_prompt_states_valuation_not_implemented_reason_when_dcf_not_applicable():
    """`ValuationResult.implemented=False` (np. BANK/INSURER/REIT, brak
    historii FCF dodatniego) -> prompt podaje POWÓD, nie udaje, że DCF
    po prostu nie zostało podane."""
    prompt, _ = build_analysis_prompt(
        ticker="JPM", metrics={}, prefilter_flags=[], sources=[],
        current_price=150.0,
        valuation_result=_valuation_result(implemented=False, reason="sector_profile BANK: NOT_YET_IMPLEMENTED"),
    )
    assert "Wycena DCF: NIEDOSTĘPNA w tym przebiegu — powód: sector_profile BANK: NOT_YET_IMPLEMENTED" in prompt
    assert "Aktualna cena: 150.0" in prompt


def test_prompt_handles_decline_snapshot_fields_that_are_none():
    """`PriceChangeSnapshot` pola są `None` (nie 0!), gdy historia nie
    wystarcza na dane okno (zasada DATA UNAVAILABLE, scanner.py) --
    formatowanie promptu nie może rzucić i nie może zgadywać 0.0."""
    snapshot = PriceChangeSnapshot(
        as_of_date="2026-10-05", daily_pct=None, week_pct=None, month_pct=-5.0,
        quarter_pct=None, ytd_pct=None, year_pct=None,
        drawdown_from_52w_high_pct=None, relative_volume=None,
    )
    prompt, _ = build_analysis_prompt(
        ticker="AAPL", metrics={}, prefilter_flags=[], sources=[],
        current_price=100.0, decline_snapshot=snapshot,
    )
    assert "1D=N/A" in prompt
    assert "1M=-5.00%" in prompt
    assert "Wolumen względny=N/A" in prompt

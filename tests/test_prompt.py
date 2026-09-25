"""Testy budowy promptu Fazy 3 (sekcja 15, punkt 3.2)."""

from __future__ import annotations

from buffett_scanner.prompt import build_analysis_prompt
from buffett_scanner.sources import VerifiedSource


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


def test_prompt_includes_metric_values():
    prompt, _ = build_analysis_prompt(
        ticker="AAPL", metrics={"fcf_ttm": 12345.0, "current_ratio": None},
        prefilter_flags=[], sources=[],
    )
    assert "fcf_ttm: 12345.0" in prompt
    assert "current_ratio: None" in prompt

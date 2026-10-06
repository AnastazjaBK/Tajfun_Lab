"""Testy klienta Claude API. Warstwa jednostkowa (mock SDK, bez sieci)."""

from __future__ import annotations

from types import SimpleNamespace

import anthropic
import pytest

from buffett_scanner.analysis_schema import AnalysisOutput
from buffett_scanner.providers.claude import ClaudeClient, ClaudeError, ClaudeUsage

VALID_PAYLOAD = {
    "ticker": "AAPL",
    "schema_version": "1.0",
    "business_understandability": {"score": 6, "max_score": 7, "confidence": "HIGH"},
    "moat": {"score": 10, "max_score": 12, "confidence": "MEDIUM"},
    "financial_quality_commentary": {"confidence": "HIGH", "reasoning": "solid"},
    "management_capital_allocation": {"score": 8, "max_score": 10, "confidence": "MEDIUM"},
    "fear_analysis": {
        "classification": "TEMPORARY", "confidence": "MEDIUM", "trigger": "x", "reasoning": "y",
    },
    "dividend_trap_alert": {"triggered": False, "reasoning": ""},
    "cited_source_ids": [],
}


def _fake_usage(**overrides) -> SimpleNamespace:
    """Odtwarza realny kształt `response.usage` zainstalowanego SDK
    (`anthropic==1.8.0`, zweryfikowane 2026-10-06 przez inspekcję
    `anthropic.types.Usage`) — pola: input_tokens, output_tokens,
    cache_creation_input_tokens, cache_read_input_tokens,
    output_tokens_details (z `.thinking_tokens`), service_tier."""
    base = dict(
        input_tokens=1000, output_tokens=200,
        cache_creation_input_tokens=None, cache_read_input_tokens=None,
        output_tokens_details=None, service_tier="standard",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_claude_client_rejects_empty_api_key():
    with pytest.raises(ClaudeError):
        ClaudeClient("", model="claude-sonnet-5")


def test_generate_analysis_returns_parsed_output_and_real_usage(monkeypatch):
    client = ClaudeClient("dummy-key", model="claude-sonnet-5", max_output_tokens=1000)
    parsed = AnalysisOutput.model_validate(VALID_PAYLOAD)
    fake_response = SimpleNamespace(
        stop_reason="end_turn", parsed_output=parsed, model="claude-sonnet-5",
        usage=_fake_usage(input_tokens=1500, output_tokens=300),
    )
    monkeypatch.setattr(client._client.messages, "parse", lambda **kwargs: fake_response)

    result = client.generate_analysis("dummy prompt")
    assert result.output.ticker == "AAPL"
    assert result.output.moat.score == 10
    assert result.usage == ClaudeUsage(
        model="claude-sonnet-5", input_tokens=1500, output_tokens=300,
        cache_creation_input_tokens=None, cache_read_input_tokens=None,
        thinking_tokens=None, service_tier="standard",
    )


def test_generate_analysis_surfaces_thinking_tokens_when_present(monkeypatch):
    """`output_tokens_details.thinking_tokens` (Faza 6e) — jeśli SDK go
    zwróci, musi dotrzeć do `ClaudeUsage.thinking_tokens` bez zmian."""
    client = ClaudeClient("dummy-key", model="claude-sonnet-5")
    parsed = AnalysisOutput.model_validate(VALID_PAYLOAD)
    fake_response = SimpleNamespace(
        stop_reason="end_turn", parsed_output=parsed, model="claude-sonnet-5",
        usage=_fake_usage(output_tokens_details=SimpleNamespace(thinking_tokens=450)),
    )
    monkeypatch.setattr(client._client.messages, "parse", lambda **kwargs: fake_response)

    result = client.generate_analysis("dummy prompt")
    assert result.usage.thinking_tokens == 450


def test_generate_analysis_passes_model_and_max_tokens(monkeypatch):
    client = ClaudeClient("dummy-key", model="claude-sonnet-5", max_output_tokens=1234)
    captured = {}

    def fake_parse(**kwargs):
        captured.update(kwargs)
        parsed = AnalysisOutput.model_validate(VALID_PAYLOAD)
        return SimpleNamespace(
            stop_reason="end_turn", parsed_output=parsed, model="claude-sonnet-5",
            usage=_fake_usage(),
        )

    monkeypatch.setattr(client._client.messages, "parse", fake_parse)
    client.generate_analysis("dummy prompt")

    assert captured["model"] == "claude-sonnet-5"
    assert captured["max_tokens"] == 1234
    assert captured["output_format"] is AnalysisOutput
    assert captured["messages"] == [{"role": "user", "content": "dummy prompt"}]


def test_generate_analysis_raises_on_refusal_but_carries_real_usage(monkeypatch):
    """Refusal to realna odpowiedź API (model faktycznie przetworzył
    wejście i wygenerował tokeny) — w przeciwieństwie do APIStatusError/
    APIConnectionError, `ClaudeError.usage` NIE jest None tutaj."""
    client = ClaudeClient("dummy-key", model="claude-sonnet-5")
    fake_response = SimpleNamespace(
        stop_reason="refusal", parsed_output=None, model="claude-sonnet-5",
        usage=_fake_usage(input_tokens=800, output_tokens=50),
    )
    monkeypatch.setattr(client._client.messages, "parse", lambda **kwargs: fake_response)

    with pytest.raises(ClaudeError, match="refusal") as exc_info:
        client.generate_analysis("dummy prompt")
    assert exc_info.value.usage.input_tokens == 800
    assert exc_info.value.usage.output_tokens == 50


def test_generate_analysis_raises_when_parsed_output_is_none_but_carries_real_usage(monkeypatch):
    client = ClaudeClient("dummy-key", model="claude-sonnet-5")
    fake_response = SimpleNamespace(
        stop_reason="end_turn", parsed_output=None, model="claude-sonnet-5",
        usage=_fake_usage(),
    )
    monkeypatch.setattr(client._client.messages, "parse", lambda **kwargs: fake_response)

    with pytest.raises(ClaudeError, match="parsed_output") as exc_info:
        client.generate_analysis("dummy prompt")
    assert exc_info.value.usage is not None


def test_generate_analysis_wraps_api_connection_error(monkeypatch):
    client = ClaudeClient("dummy-key", model="claude-sonnet-5")

    def raise_connection_error(**kwargs):
        raise anthropic.APIConnectionError(request=SimpleNamespace())

    monkeypatch.setattr(client._client.messages, "parse", raise_connection_error)
    with pytest.raises(ClaudeError, match="sieci") as exc_info:
        client.generate_analysis("dummy prompt")
    assert exc_info.value.usage is None


def test_generate_analysis_wraps_truncated_json_parse_failure(monkeypatch):
    """Odtwarza realny błąd z Phase 3 Proof Run (2026-09-25): odpowiedź
    ucięta przez max_output_tokens sprawia, że SDK rzuca błąd walidacji
    pydantic z niekompletnego JSON-a, nie APIStatusError/
    APIConnectionError — musi zostać złapany i czytelnie opisany."""
    client = ClaudeClient("dummy-key", model="claude-sonnet-5", max_output_tokens=4000)

    def raise_truncated_json_error(**kwargs):
        raise ValueError("Invalid JSON: EOF while parsing a string at line 1 column 4832")

    monkeypatch.setattr(client._client.messages, "parse", raise_truncated_json_error)
    with pytest.raises(ClaudeError, match="max_output_tokens=4000") as exc_info:
        client.generate_analysis("dummy prompt")
    assert exc_info.value.usage is None


def test_generate_analysis_wraps_api_status_error(monkeypatch):
    client = ClaudeClient("dummy-key", model="claude-sonnet-5")

    def raise_status_error(**kwargs):
        resp = SimpleNamespace(status_code=429, headers={}, request=SimpleNamespace())
        raise anthropic.APIStatusError("rate limited", response=resp, body=None)

    monkeypatch.setattr(client._client.messages, "parse", raise_status_error)
    with pytest.raises(ClaudeError, match="429") as exc_info:
        client.generate_analysis("dummy prompt")
    assert exc_info.value.usage is None

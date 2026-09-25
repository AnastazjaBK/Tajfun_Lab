"""Testy klienta Claude API. Warstwa jednostkowa (mock SDK, bez sieci)."""

from __future__ import annotations

from types import SimpleNamespace

import anthropic
import pytest

from buffett_scanner.analysis_schema import AnalysisOutput
from buffett_scanner.providers.claude import ClaudeClient, ClaudeError

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


def test_claude_client_rejects_empty_api_key():
    with pytest.raises(ClaudeError):
        ClaudeClient("", model="claude-sonnet-5")


def test_generate_analysis_returns_parsed_output(monkeypatch):
    client = ClaudeClient("dummy-key", model="claude-sonnet-5", max_output_tokens=1000)
    parsed = AnalysisOutput.model_validate(VALID_PAYLOAD)
    fake_response = SimpleNamespace(stop_reason="end_turn", parsed_output=parsed)
    monkeypatch.setattr(client._client.messages, "parse", lambda **kwargs: fake_response)

    result = client.generate_analysis("dummy prompt")
    assert result.ticker == "AAPL"
    assert result.moat.score == 10


def test_generate_analysis_passes_model_and_max_tokens(monkeypatch):
    client = ClaudeClient("dummy-key", model="claude-sonnet-5", max_output_tokens=1234)
    captured = {}

    def fake_parse(**kwargs):
        captured.update(kwargs)
        parsed = AnalysisOutput.model_validate(VALID_PAYLOAD)
        return SimpleNamespace(stop_reason="end_turn", parsed_output=parsed)

    monkeypatch.setattr(client._client.messages, "parse", fake_parse)
    client.generate_analysis("dummy prompt")

    assert captured["model"] == "claude-sonnet-5"
    assert captured["max_tokens"] == 1234
    assert captured["output_format"] is AnalysisOutput
    assert captured["messages"] == [{"role": "user", "content": "dummy prompt"}]


def test_generate_analysis_raises_on_refusal(monkeypatch):
    client = ClaudeClient("dummy-key", model="claude-sonnet-5")
    fake_response = SimpleNamespace(stop_reason="refusal", parsed_output=None)
    monkeypatch.setattr(client._client.messages, "parse", lambda **kwargs: fake_response)

    with pytest.raises(ClaudeError, match="refusal"):
        client.generate_analysis("dummy prompt")


def test_generate_analysis_raises_when_parsed_output_is_none(monkeypatch):
    client = ClaudeClient("dummy-key", model="claude-sonnet-5")
    fake_response = SimpleNamespace(stop_reason="end_turn", parsed_output=None)
    monkeypatch.setattr(client._client.messages, "parse", lambda **kwargs: fake_response)

    with pytest.raises(ClaudeError, match="parsed_output"):
        client.generate_analysis("dummy prompt")


def test_generate_analysis_wraps_api_connection_error(monkeypatch):
    client = ClaudeClient("dummy-key", model="claude-sonnet-5")

    def raise_connection_error(**kwargs):
        raise anthropic.APIConnectionError(request=SimpleNamespace())

    monkeypatch.setattr(client._client.messages, "parse", raise_connection_error)
    with pytest.raises(ClaudeError, match="sieci"):
        client.generate_analysis("dummy prompt")


def test_generate_analysis_wraps_api_status_error(monkeypatch):
    client = ClaudeClient("dummy-key", model="claude-sonnet-5")

    def raise_status_error(**kwargs):
        resp = SimpleNamespace(status_code=429, headers={}, request=SimpleNamespace())
        raise anthropic.APIStatusError("rate limited", response=resp, body=None)

    monkeypatch.setattr(client._client.messages, "parse", raise_status_error)
    with pytest.raises(ClaudeError, match="429"):
        client.generate_analysis("dummy prompt")

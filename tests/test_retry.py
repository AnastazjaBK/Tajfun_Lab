"""Testy czystej logiki retry/backoff (Faza 5.3b, backfill 626 CIK)."""

from __future__ import annotations

import pytest

from buffett_scanner.providers.retry import RETRYABLE_STATUS_CODES, backoff_seconds, parse_retry_after_seconds


def test_backoff_seconds_doubles_each_attempt():
    assert backoff_seconds(0, base=1.0, cap=100.0) == 1.0
    assert backoff_seconds(1, base=1.0, cap=100.0) == 2.0
    assert backoff_seconds(2, base=1.0, cap=100.0) == 4.0
    assert backoff_seconds(3, base=1.0, cap=100.0) == 8.0


def test_backoff_seconds_capped():
    assert backoff_seconds(10, base=1.0, cap=30.0) == 30.0


def test_backoff_seconds_rejects_negative_attempt():
    with pytest.raises(ValueError):
        backoff_seconds(-1)


def test_parse_retry_after_seconds_valid_value():
    assert parse_retry_after_seconds("5") == 5.0


def test_parse_retry_after_seconds_none_when_absent():
    assert parse_retry_after_seconds(None) is None


def test_parse_retry_after_seconds_none_when_unparseable_never_guesses():
    """Np. format daty HTTP (`Retry-After: Wed, 21 Oct 2026 07:28:00 GMT`)
    -- nie parsujemy dat tutaj, zamiast zgadywać zwracamy None (wołający
    spada na backoff_seconds)."""
    assert parse_retry_after_seconds("Wed, 21 Oct 2026 07:28:00 GMT") is None


def test_parse_retry_after_seconds_never_negative():
    assert parse_retry_after_seconds("-5") == 0.0


def test_retryable_status_codes_include_429_and_5xx_not_other_4xx():
    assert 429 in RETRYABLE_STATUS_CODES
    assert 500 in RETRYABLE_STATUS_CODES
    assert 503 in RETRYABLE_STATUS_CODES
    assert 404 not in RETRYABLE_STATUS_CODES
    assert 402 not in RETRYABLE_STATUS_CODES

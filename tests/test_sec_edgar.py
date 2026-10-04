"""Testy klienta SEC EDGAR. Warstwa jednostkowa (mock httpx, bez sieci)."""

from __future__ import annotations

import hashlib

import pytest

from buffett_scanner.providers.sec_edgar import SecEdgarClient, SecEdgarError


class _FakeResponse:
    def __init__(self, status_code: int, json_payload=None, content: bytes = b""):
        self.status_code = status_code
        self._json_payload = json_payload
        self.content = content

    def json(self):
        return self._json_payload


def test_sec_edgar_client_rejects_user_agent_without_contact_email():
    with pytest.raises(SecEdgarError):
        SecEdgarClient("Tajfun Lab")  # brak "@" -> brak danych kontaktowych


def test_sec_edgar_client_accepts_valid_user_agent():
    client = SecEdgarClient("Tajfun Lab kontakt@example.com")
    assert client is not None


def test_build_filing_url_is_deterministic_and_strips_dashes_and_leading_zeros():
    url = SecEdgarClient.build_filing_url(
        cik="0000320193",
        accession_number="0000320193-24-000123",
        primary_document="aapl-20240928.htm",
    )
    assert url == (
        "https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/aapl-20240928.htm"
    )


def test_get_filings_parses_recent_arrays(monkeypatch):
    client = SecEdgarClient("Tajfun Lab kontakt@example.com")
    fake_payload = {
        "filings": {
            "recent": {
                "form": ["10-K", "10-Q"],
                "accessionNumber": ["0000320193-24-000001", "0000320193-24-000002"],
                "filingDate": ["2024-11-01", "2024-08-01"],
                "reportDate": ["2024-09-28", "2024-06-29"],
                "primaryDocument": ["10k.htm", "10q.htm"],
            }
        }
    }
    monkeypatch.setattr(
        client._client, "get", lambda url: _FakeResponse(200, json_payload=fake_payload)
    )
    filings = client.get_filings("0000320193")
    assert len(filings) == 2
    assert filings[0] == {
        "form": "10-K", "accession_number": "0000320193-24-000001",
        "filing_date": "2024-11-01", "report_date": "2024-09-28",
        "primary_document": "10k.htm",
    }


def test_get_filings_skips_incomplete_rows_without_fabricating(monkeypatch):
    """Wiersz krótszy niż tablica 'form' (brakujące pole krytyczne) jest
    pomijany, nigdy nie uzupełniany zgadywaną wartością."""
    client = SecEdgarClient("Tajfun Lab kontakt@example.com")
    fake_payload = {
        "filings": {
            "recent": {
                "form": ["10-K", "10-Q"],
                "accessionNumber": ["0000320193-24-000001"],  # tylko 1 element
                "filingDate": ["2024-11-01", "2024-08-01"],
                "reportDate": ["2024-09-28", "2024-06-29"],
                "primaryDocument": ["10k.htm", "10q.htm"],
            }
        }
    }
    monkeypatch.setattr(
        client._client, "get", lambda url: _FakeResponse(200, json_payload=fake_payload)
    )
    filings = client.get_filings("0000320193")
    assert len(filings) == 1
    assert filings[0]["form"] == "10-K"


def test_get_filings_raises_on_non_200(monkeypatch):
    client = SecEdgarClient("Tajfun Lab kontakt@example.com")
    monkeypatch.setattr(client._client, "get", lambda url: _FakeResponse(404))
    with pytest.raises(SecEdgarError):
        client.get_filings("0000320193")


def test_fetch_and_hash_document_computes_real_sha256(monkeypatch):
    client = SecEdgarClient("Tajfun Lab kontakt@example.com")
    fake_content = b"<html>przykladowa tresc dokumentu 10-K</html>"
    monkeypatch.setattr(
        client._client, "get", lambda url: _FakeResponse(200, content=fake_content)
    )
    result = client.fetch_and_hash_document("https://www.sec.gov/example.htm")
    assert result["content_hash"] == hashlib.sha256(fake_content).hexdigest()
    assert result["content_length"] == len(fake_content)
    assert result["url"] == "https://www.sec.gov/example.htm"


def test_fetch_and_hash_document_raises_on_non_200_never_fabricates_hash(monkeypatch):
    client = SecEdgarClient("Tajfun Lab kontakt@example.com")
    monkeypatch.setattr(client._client, "get", lambda url: _FakeResponse(404))
    with pytest.raises(SecEdgarError):
        client.fetch_and_hash_document("https://www.sec.gov/nope.htm")


def test_get_company_facts_parses_json(monkeypatch):
    client = SecEdgarClient("Tajfun Lab kontakt@example.com")
    fake_payload = {
        "cik": 320193, "entityName": "Apple Inc.",
        "facts": {"us-gaap": {"NetIncomeLoss": {"units": {"USD": []}}}},
    }
    monkeypatch.setattr(
        client._client, "get", lambda url: _FakeResponse(200, json_payload=fake_payload)
    )
    result = client.get_company_facts("0000320193")
    assert result == fake_payload


def test_get_company_facts_raises_on_non_200(monkeypatch):
    client = SecEdgarClient("Tajfun Lab kontakt@example.com")
    monkeypatch.setattr(client._client, "get", lambda url: _FakeResponse(404))
    with pytest.raises(SecEdgarError):
        client.get_company_facts("0000320193")


def test_get_company_tickers_parses_mapping_and_strips_leading_zeros(monkeypatch):
    client = SecEdgarClient("Tajfun Lab kontakt@example.com")
    fake_payload = {
        "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
        "1": {"cik_str": 789019, "ticker": "MSFT", "title": "Microsoft Corp"},
    }
    monkeypatch.setattr(
        client._client, "get", lambda url: _FakeResponse(200, json_payload=fake_payload)
    )
    mapping = client.get_company_tickers()
    assert mapping == {"AAPL": "320193", "MSFT": "789019"}


def test_get_company_tickers_skips_entries_missing_ticker_or_cik(monkeypatch):
    client = SecEdgarClient("Tajfun Lab kontakt@example.com")
    fake_payload = {
        "0": {"cik_str": 320193, "ticker": "AAPL"},
        "1": {"cik_str": None, "ticker": "BROKEN"},
        "2": {"ticker": "NOCIK"},
        "3": {"cik_str": 1},
    }
    monkeypatch.setattr(
        client._client, "get", lambda url: _FakeResponse(200, json_payload=fake_payload)
    )
    mapping = client.get_company_tickers()
    assert mapping == {"AAPL": "320193"}


def test_get_company_tickers_raises_on_non_200(monkeypatch):
    client = SecEdgarClient("Tajfun Lab kontakt@example.com")
    monkeypatch.setattr(client._client, "get", lambda url: _FakeResponse(404))
    with pytest.raises(SecEdgarError):
        client.get_company_tickers()


def test_get_company_tickers_full_includes_title(monkeypatch):
    client = SecEdgarClient("Tajfun Lab kontakt@example.com")
    fake_payload = {
        "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
        "1": {"cik_str": 789019, "ticker": "MSFT", "title": "MICROSOFT CORP"},
    }
    monkeypatch.setattr(
        client._client, "get", lambda url: _FakeResponse(200, json_payload=fake_payload)
    )
    mapping = client.get_company_tickers_full()
    assert mapping == {
        "AAPL": {"cik": "320193", "title": "Apple Inc."},
        "MSFT": {"cik": "789019", "title": "MICROSOFT CORP"},
    }


def test_get_company_tickers_full_defaults_missing_title_to_empty_string(monkeypatch):
    client = SecEdgarClient("Tajfun Lab kontakt@example.com")
    fake_payload = {"0": {"cik_str": 320193, "ticker": "AAPL"}}
    monkeypatch.setattr(
        client._client, "get", lambda url: _FakeResponse(200, json_payload=fake_payload)
    )
    mapping = client.get_company_tickers_full()
    assert mapping == {"AAPL": {"cik": "320193", "title": ""}}


def test_get_company_tickers_full_skips_entries_missing_ticker_or_cik(monkeypatch):
    client = SecEdgarClient("Tajfun Lab kontakt@example.com")
    fake_payload = {
        "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
        "1": {"cik_str": None, "ticker": "BROKEN", "title": "Broken Co"},
        "2": {"ticker": "NOCIK", "title": "No Cik Co"},
    }
    monkeypatch.setattr(
        client._client, "get", lambda url: _FakeResponse(200, json_payload=fake_payload)
    )
    mapping = client.get_company_tickers_full()
    assert mapping == {"AAPL": {"cik": "320193", "title": "Apple Inc."}}


def test_get_former_names_parses_name_from_to(monkeypatch):
    client = SecEdgarClient("Tajfun Lab kontakt@example.com")
    fake_payload = {
        "formerNames": [
            {"name": "ANTHEM INC", "from": "2001-01-02", "to": "2022-06-27"},
        ]
    }
    monkeypatch.setattr(
        client._client, "get", lambda url: _FakeResponse(200, json_payload=fake_payload)
    )
    result = client.get_former_names("0001156039")
    assert result == [{"name": "ANTHEM INC", "from_date": "2001-01-02", "to_date": "2022-06-27"}]


def test_get_former_names_missing_field_returns_empty_list_not_error(monkeypatch):
    client = SecEdgarClient("Tajfun Lab kontakt@example.com")
    monkeypatch.setattr(
        client._client, "get", lambda url: _FakeResponse(200, json_payload={"cik": 320193})
    )
    assert client.get_former_names("0000320193") == []


def test_get_former_names_skips_entries_missing_name_without_fabricating(monkeypatch):
    client = SecEdgarClient("Tajfun Lab kontakt@example.com")
    fake_payload = {"formerNames": [{"from": "2001-01-02", "to": "2022-06-27"}]}
    monkeypatch.setattr(
        client._client, "get", lambda url: _FakeResponse(200, json_payload=fake_payload)
    )
    assert client.get_former_names("0001156039") == []


def test_get_former_names_raises_on_non_200(monkeypatch):
    client = SecEdgarClient("Tajfun Lab kontakt@example.com")
    monkeypatch.setattr(client._client, "get", lambda url: _FakeResponse(404))
    with pytest.raises(SecEdgarError):
        client.get_former_names("0001156039")


def test_get_sic_classification_parses_sic_and_description(monkeypatch):
    client = SecEdgarClient("Tajfun Lab kontakt@example.com")
    fake_payload = {"sic": "6022", "sicDescription": "State commercial banks"}
    monkeypatch.setattr(
        client._client, "get", lambda url: _FakeResponse(200, json_payload=fake_payload)
    )
    result = client.get_sic_classification("0000019617")
    assert result == {"sic": "6022", "sic_description": "State commercial banks"}


def test_get_sic_classification_missing_field_returns_none_not_error(monkeypatch):
    client = SecEdgarClient("Tajfun Lab kontakt@example.com")
    monkeypatch.setattr(
        client._client, "get", lambda url: _FakeResponse(200, json_payload={"cik": 320193})
    )
    assert client.get_sic_classification("0000320193") == {"sic": None, "sic_description": None}


def test_get_sic_classification_raises_on_non_200(monkeypatch):
    client = SecEdgarClient("Tajfun Lab kontakt@example.com")
    monkeypatch.setattr(client._client, "get", lambda url: _FakeResponse(404))
    with pytest.raises(SecEdgarError):
        client.get_sic_classification("0000320193")


def test_get_company_tickers_is_cik_only_view_of_full_mapping(monkeypatch):
    """`get_company_tickers` musi pozostać zgodny wstecznie po
    refaktoryzacji na `get_company_tickers_full` — sam CIK, bez title."""
    client = SecEdgarClient("Tajfun Lab kontakt@example.com")
    fake_payload = {
        "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
    }
    monkeypatch.setattr(
        client._client, "get", lambda url: _FakeResponse(200, json_payload=fake_payload)
    )
    assert client.get_company_tickers() == {"AAPL": "320193"}


# ---------------------------------------------------------------------------
# Retry/backoff (Faza 5.3b, backfill 626 CIK, Decyzja właścicielki 2026-10-03)
# ---------------------------------------------------------------------------

class _FakeResponseWithHeaders:
    def __init__(self, status_code: int, json_payload=None, headers: dict | None = None):
        self.status_code = status_code
        self._json_payload = json_payload
        self.headers = headers or {}

    def json(self):
        return self._json_payload


def test_get_retries_on_429_then_succeeds_honors_retry_after(monkeypatch):
    sleeps: list[float] = []
    client = SecEdgarClient(
        "Tajfun Lab kontakt@example.com", sleep_fn=lambda s: sleeps.append(s)
    )
    responses = [
        _FakeResponseWithHeaders(429, headers={"Retry-After": "7"}),
        _FakeResponseWithHeaders(200, json_payload={"ok": True}),
    ]
    calls = iter(responses)
    monkeypatch.setattr(client._client, "get", lambda url: next(calls))
    resp = client._get("https://example.com")
    assert resp.status_code == 200
    assert sleeps == [7.0]  # Retry-After honorowany, nie backoff_seconds


def test_get_retries_on_5xx_with_exponential_backoff_when_no_retry_after(monkeypatch):
    sleeps: list[float] = []
    client = SecEdgarClient(
        "Tajfun Lab kontakt@example.com", sleep_fn=lambda s: sleeps.append(s)
    )
    responses = [
        _FakeResponseWithHeaders(503),
        _FakeResponseWithHeaders(503),
        _FakeResponseWithHeaders(200, json_payload={"ok": True}),
    ]
    calls = iter(responses)
    monkeypatch.setattr(client._client, "get", lambda url: next(calls))
    resp = client._get("https://example.com")
    assert resp.status_code == 200
    assert sleeps == [1.0, 2.0]


def test_get_gives_up_after_max_retries_returns_last_response(monkeypatch):
    client = SecEdgarClient(
        "Tajfun Lab kontakt@example.com", max_retries=2, sleep_fn=lambda s: None
    )
    monkeypatch.setattr(client._client, "get", lambda url: _FakeResponseWithHeaders(503))
    resp = client._get("https://example.com")
    assert resp.status_code == 503  # wolajacy (np. get_company_facts) sam podnosi SecEdgarError


def test_get_does_not_retry_on_404_not_a_transient_error(monkeypatch):
    calls = []
    client = SecEdgarClient("Tajfun Lab kontakt@example.com", sleep_fn=lambda s: None)
    def _fake_get(url):
        calls.append(url)
        return _FakeResponseWithHeaders(404)
    monkeypatch.setattr(client._client, "get", _fake_get)
    resp = client._get("https://example.com")
    assert resp.status_code == 404
    assert len(calls) == 1  # zero ponowien


def test_get_company_facts_raises_after_exhausted_retries_on_persistent_429(monkeypatch):
    client = SecEdgarClient(
        "Tajfun Lab kontakt@example.com", max_retries=1, sleep_fn=lambda s: None
    )
    monkeypatch.setattr(client._client, "get", lambda url: _FakeResponseWithHeaders(429))
    with pytest.raises(SecEdgarError):
        client.get_company_facts("0000320193")

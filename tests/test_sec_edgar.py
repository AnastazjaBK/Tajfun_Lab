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

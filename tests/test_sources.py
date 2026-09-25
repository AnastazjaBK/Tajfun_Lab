"""Testy Source Assembly Layer (build_sec_source_packet) — z fałszywym
klientem SEC EDGAR (bez sieci, bez mockowania httpx bezpośrednio)."""

from __future__ import annotations

import pytest

from buffett_scanner.providers.sec_edgar import SecEdgarClient, SecEdgarError
from buffett_scanner.sources import build_sec_source_packet

FILINGS = [
    {"form": "10-K", "accession_number": "0000320193-24-000001",
     "filing_date": "2024-11-01", "report_date": "2024-09-28", "primary_document": "10k.htm"},
    {"form": "10-Q", "accession_number": "0000320193-24-000002",
     "filing_date": "2024-08-01", "report_date": "2024-06-29", "primary_document": "10q1.htm"},
    {"form": "10-Q", "accession_number": "0000320193-24-000003",
     "filing_date": "2024-05-01", "report_date": "2024-03-30", "primary_document": "10q2.htm"},
    {"form": "10-Q", "accession_number": "0000320193-24-000004",
     "filing_date": "2024-02-01", "report_date": "2023-12-30", "primary_document": "10q3.htm"},
    {"form": "8-K", "accession_number": "0000320193-24-000005",
     "filing_date": "2024-10-15", "report_date": None, "primary_document": "8k.htm"},
]


class _FakeClient:
    """Podmienia get_filings/fetch_and_hash_document; build_filing_url
    zostaje prawdziwą (statyczną) implementacją z SecEdgarClient."""

    def __init__(self, filings=FILINGS, fail_urls=None, filings_error=None):
        self._filings = filings
        self._fail_urls = fail_urls or set()
        self._filings_error = filings_error

    def get_filings(self, cik: str) -> list[dict]:
        if self._filings_error:
            raise SecEdgarError(self._filings_error)
        return self._filings

    def fetch_and_hash_document(self, url: str) -> dict:
        if url in self._fail_urls:
            raise SecEdgarError(f"404 dla {url}")
        return {"url": url, "content_hash": "deadbeef" * 8, "content_length": 123}

    build_filing_url = staticmethod(SecEdgarClient.build_filing_url)


def test_build_sec_source_packet_respects_limit_per_form_and_forms_filter():
    client = _FakeClient()
    packet = build_sec_source_packet(
        client, cik="0000320193", issuer="Apple Inc.",
        forms=("10-K", "10-Q"), limit_per_form=2,
    )
    # 1x 10-K + max 2x 10-Q (mimo że są 3 w danych) + 0x 8-K (poza forms)
    forms_in_packet = [s.title.split(" ")[0] for s in packet]
    assert forms_in_packet.count("10-K") == 1
    assert forms_in_packet.count("10-Q") == 2
    assert "8-K" not in forms_in_packet


def test_build_sec_source_packet_verified_sources_have_content_hash():
    client = _FakeClient()
    packet = build_sec_source_packet(
        client, cik="0000320193", issuer="Apple Inc.", forms=("10-K",), limit_per_form=1,
    )
    assert len(packet) == 1
    src = packet[0]
    assert src.verified is True
    assert src.content_hash == "deadbeef" * 8
    assert src.reason is None
    assert src.issuer == "Apple Inc."


def test_build_sec_source_packet_marks_fetch_failure_as_source_not_verified():
    fail_url = SecEdgarClient.build_filing_url(
        "0000320193", "0000320193-24-000001", "10k.htm"
    )
    client = _FakeClient(fail_urls={fail_url})
    packet = build_sec_source_packet(
        client, cik="0000320193", issuer="Apple Inc.", forms=("10-K",), limit_per_form=1,
    )
    assert len(packet) == 1
    src = packet[0]
    assert src.verified is False
    assert src.content_hash is None
    assert "404" in src.reason


def test_build_sec_source_packet_get_filings_failure_returns_single_unverified_entry():
    client = _FakeClient(filings_error="Błąd sieci")
    packet = build_sec_source_packet(client, cik="0000320193", issuer="Apple Inc.")
    assert len(packet) == 1
    assert packet[0].verified is False
    assert "Błąd sieci" in packet[0].reason


def test_build_sec_source_packet_empty_when_no_matching_forms():
    client = _FakeClient()
    packet = build_sec_source_packet(
        client, cik="0000320193", issuer="Apple Inc.", forms=("20-F",), limit_per_form=2,
    )
    assert packet == []

"""Ręczny smoke-test klienta SEC EDGAR — uruchom z ustawionym
SEC_EDGAR_USER_AGENT.

    python -m buffett_scanner.providers.sec_edgar_smoketest

Pobiera realną listę filingów dla AAPL (CIK 0000320193) i buduje +
weryfikuje (pobiera, hashuje) jeden 10-K. Nie zapisuje nic do bazy.
"""

from __future__ import annotations

import sys

from buffett_scanner.config import load_config
from buffett_scanner.providers.sec_edgar import SecEdgarClient, SecEdgarError
from buffett_scanner.sources import build_sec_source_packet

AAPL_CIK = "0000320193"


def main() -> int:
    config = load_config()
    try:
        user_agent = config.sources.sec_edgar.resolve_user_agent()
    except RuntimeError as exc:
        print(f"BŁĄD: {exc}", file=sys.stderr)
        return 1

    with SecEdgarClient(user_agent) as client:
        print(f"== get_filings(AAPL, CIK={AAPL_CIK}) — pierwsze 3 wpisy ==")
        try:
            filings = client.get_filings(AAPL_CIK)
            print(f"Liczba filingów: {len(filings)}")
            for f in filings[:3]:
                print(f)
        except SecEdgarError as exc:
            print(f"NIEZGODNE ZAŁOŻENIE: {exc}")
            return 1

        print("\n== build_sec_source_packet(AAPL, forms=10-K, limit=1) ==")
        packet = build_sec_source_packet(
            client, cik=AAPL_CIK, issuer="Apple Inc.", forms=("10-K",), limit_per_form=1,
        )
        for src in packet:
            print(src)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

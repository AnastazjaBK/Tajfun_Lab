"""Diagnostyka (Faza 5.3, po znalezisku z Price Data Proof Run 2026-09-30):
czy sekwencyjne zmiany tickera (rename bez opuszczenia indeksu, np.
ANTM->ELV, FB->META) są poprawnie scalone w finalnym `universe_
membership`, czy gubią historyczny okres sprzed zmiany? Oraz: czy pole
`reason` w logu zdarzeń FMP `historical-sp500-constituent` zawiera
jawny, potwierdzony opis zmiany tickera, który dałoby się wykorzystać
jako źródło mapowania stary_ticker -> nowy_ticker BEZ zgadywania.

WYŁĄCZNIE DIAGNOSTYCZNE — buduje `universe_membership` dokładnie tak
samo jak `cli.py build-universe-membership` (reużywa tej samej funkcji),
a następnie odpytuje zbudowaną bazę i surowe dane FMP wprost, zamiast
wnioskować.

    python -m buffett_scanner.providers.universe_membership_rename_diagnosis

Wymaga FMP_API_KEY i SEC_EDGAR_USER_AGENT."""

from __future__ import annotations

import argparse
import sqlite3
import sys
import tempfile
from pathlib import Path

from buffett_scanner.cli import cmd_build_universe_membership
from buffett_scanner.config import load_config
from buffett_scanner.fmp_sp500_events import parse_fmp_events
from buffett_scanner.providers.fmp import FMPClient, FMPError

# Znane pary rename (potwierdzone bezpośrednio w cache fja05680 w tej
# sesji, v1.37/v1.37b) — sprawdzamy, czy ich HISTORYCZNA (stara)
# nazwa/ticker trafiła do tego samego CIK w finalnej bazie.
RENAME_CASES = [
    ("Anthem / Elevance Health", "ANTM", "ELV", "Elevance"),
    ("Facebook / Meta Platforms", "FB", "META", "Meta"),
]


def _print_membership_for_name_like(conn: sqlite3.Connection, name_fragment: str) -> None:
    rows = conn.execute(
        """
        SELECT c.cik, c.name,
               MIN(m.start_date) AS earliest_start,
               SUM(CASE WHEN m.end_date IS NULL THEN 1 ELSE 0 END) AS open_intervals,
               COUNT(*) AS n_intervals
        FROM companies c
        LEFT JOIN universe_membership m ON m.cik = c.cik
        WHERE c.name LIKE ?
        GROUP BY c.cik, c.name
        """,
        (f"%{name_fragment}%",),
    ).fetchall()
    if not rows:
        print(f"    BRAK spółki w `companies` z nazwą zawierającą {name_fragment!r} "
              f"(albo nigdy nie rozwiązała się do CIK, albo nazwa SEC jest inna).")
        return
    for r in rows:
        print(f"    cik={r['cik']} name={r['name']!r} "
              f"najwcześniejszy start_date={r['earliest_start']} "
              f"przedziałów={r['n_intervals']} (w tym otwartych={r['open_intervals']})")
        detail = conn.execute(
            "SELECT start_date, end_date, cik_resolution_method, entry_validation_status "
            "FROM universe_membership WHERE cik = ? ORDER BY start_date", (r["cik"],),
        ).fetchall()
        for d in detail:
            print(f"      {d['start_date']}..{d['end_date'] or 'nadal'} "
                  f"(method={d['cik_resolution_method']}, entry_validation={d['entry_validation_status']})")


def main() -> int:
    config = load_config()
    try:
        api_key = config.data_provider.resolve_api_key()
        user_agent = config.sources.sec_edgar.resolve_user_agent()
    except RuntimeError as exc:
        print(f"BŁĄD: {exc}", file=sys.stderr)
        return 1

    print("== Część 1: pole `reason` w logu zdarzeń FMP — czy jawnie opisuje zmianę tickera? ==")
    with FMPClient(api_key) as client:
        path, raw_rows, attempts = client.get_historical_sp500_constituents()
        if path is None or not raw_rows:
            print("BŁĄD: historical-sp500-constituent niedostępny lub pusty.", file=sys.stderr)
            return 1
    events = parse_fmp_events(raw_rows)
    print(f"Wszystkich zdarzeń: {len(events)}")

    unique_reasons = sorted({e.reason for e in events if e.reason})
    print(f"Unikalnych wartości pola `reason` (max 40 pokazanych): {len(unique_reasons)}")
    for r in unique_reasons[:40]:
        print(f"  {r!r}")

    print("\nZdarzenia dotyczące znanych par rename (ANTM/ELV, FB/META) — pełna treść:")
    for label, old_ticker, new_ticker, _ in RENAME_CASES:
        print(f"  -- {label} --")
        matching = [
            e for e in events
            if old_ticker in (e.added_symbol, e.removed_ticker) or new_ticker in (e.added_symbol, e.removed_ticker)
        ]
        if not matching:
            print(f"    BRAK zdarzeń wspominających {old_ticker} ani {new_ticker} w logu FMP.")
        for e in matching:
            print(f"    date={e.date} added={e.added_symbol}({e.added_security!r}) "
                  f"removed={e.removed_ticker}({e.removed_security!r}) reason={e.reason!r}")

    print("\n== Część 2: czy finalny universe_membership ma lukę dla spółek, które zmieniły ticker? ==")
    print("Budowanie universe_membership (identycznie jak `cli.py build-universe-membership`)...")
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "diagnosis.db")
        args = argparse.Namespace(db=db_path, cutoff=config.backtest.window_start)
        rc = cmd_build_universe_membership(args)
        if rc != 0:
            print("BŁĄD: build-universe-membership zwrócił kod błędu — patrz log wyżej.", file=sys.stderr)
            return 1

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        print("\nSprawdzenie per przypadek (oczekiwanie: start_date ~2012, jeśli scalone poprawnie z okresem sprzed zmiany):")
        for label, old_ticker, new_ticker, name_fragment in RENAME_CASES:
            print(f"  -- {label} ({old_ticker}->{new_ticker}) --")
            _print_membership_for_name_like(conn, name_fragment)
        conn.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

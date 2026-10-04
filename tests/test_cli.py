"""Testy CLI na poziomie `cli.main` -- na razie tylko defensywna asercja
Fazy 5.3c (Decyzja właścicielki 2026-10-04, po realnym znalezisku:
dual-class share tickery dawały nakładające się przedziały membership
tego samego CIK w `universe_membership`, co crashowało realny baseline
walk-forward na UNIQUE constraint w `backtest_candidates`)."""

from __future__ import annotations

import pytest

import buffett_scanner.cli as cli
from buffett_scanner.db import init_db, upsert_company, upsert_universe_membership


def test_run_baseline_walk_forward_fails_fast_on_duplicate_cik_in_universe_membership(tmp_path):
    """Jeśli `universe_membership` zawiera (wbrew naprawie z 2026-10-04)
    nakładające się przedziały tego samego CIK -- symulowane tu wprost,
    bez przechodzenia przez builder -- `run-baseline-walk-forward` MUSI
    rzucić czytelny błąd zamiast cicho liczyć zdublowanego kandydata
    (co wcześniej crashowało na UNIQUE constraint w backtest_candidates,
    głębiej w funkcji, z mniej czytelnym komunikatem). Nigdy nie wolno
    "naprawić" tego przez DISTINCT w zapytaniu -- to by ukryło problem."""
    db_path = tmp_path / "test.db"
    conn = init_db(db_path)
    upsert_company(conn, cik="0001652044", name="Alphabet Inc.")
    # Dwa NAKŁADAJĄCE SIĘ przedziały tego samego CIK -- dokładnie kształt
    # realnego błędu (GOOGL/GOOG), wstrzyknięty wprost do bazy, symulując
    # dataset, który nie przeszedł jeszcze przez naprawiony builder.
    upsert_universe_membership(
        conn, cik="0001652044", index_name="SP500", start_date="2012-01-01", end_date=None,
        source="fja05680", source_snapshot_ref="test", cik_resolution_method="DIRECT",
    )
    upsert_universe_membership(
        conn, cik="0001652044", index_name="SP500", start_date="2014-04-03", end_date=None,
        source="fja05680", source_snapshot_ref="test", cik_resolution_method="DIRECT",
    )
    conn.commit()
    conn.close()

    with pytest.raises(RuntimeError, match="FAIL FAST"):
        cli.main([
            "--db", str(db_path), "run-baseline-walk-forward",
            "--window-start", "2015-01-01", "--window-end", "2015-02-01",
        ])

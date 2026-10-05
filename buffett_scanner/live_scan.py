"""LIVE END-TO-END SCAN — Faza 6 (domknięcie MVP V0, Decyzja
właścicielki 2026-10-05, po zamknięciu Fazy 5.4/5.6).

Czyste funkcje (ranking + raport finalny) wyodrębnione z orkiestracji
I/O (`cli.cmd_run_live_scan`) dla testowalności bez sieci/Claude API —
ten sam wzorzec co `report.py` (Faza 4: zero I/O, wołający decyduje co
dalej z wynikiem).

`LiveCandidate` to kandydat, który przeszedł CAŁY funnel: decline/
opportunity screening -> prefilter (brak EXCLUDE) -> zweryfikowane
źródła -> analiza LLM przeszła walidację deterministyczną (Faza 3) ->
deterministyczny scoring + wycena (Faza 4). `rank_candidates` TYLKO
sortuje i obcina do `limit` — 0 kandydatów jest prawidłowym wynikiem
(Decyzja właścicielki, Faza 6: "Nie wymuszaj 5 kandydatów. 0
kandydatów jest prawidłowym wynikiem.") — nigdy nie dopełnia listy.

Live run jest testem operacyjnym MVP, NIE kolejną rundą kalibracji —
wynik tego modułu nigdy nie jest wejściem do zmiany `config/config.yaml`
(Decyzja właścicielki, Faza 6)."""

from __future__ import annotations

from dataclasses import dataclass

from buffett_scanner.analysis_schema import AnalysisOutput
from buffett_scanner.config import AppConfig
from buffett_scanner.report import render_markdown_report
from buffett_scanner.scanner import PriceChangeSnapshot
from buffett_scanner.scoring import ScoreResult
from buffett_scanner.sources import VerifiedSource


@dataclass(frozen=True)
class LiveCandidate:
    ticker: str
    cik: str
    run_date: str
    current_price: float
    decline_snapshot: PriceChangeSnapshot
    triggered_decline_flags: dict[str, bool]
    analysis: AnalysisOutput
    score: ScoreResult
    source_packet: list[VerifiedSource]


def _rank_key(candidate: LiveCandidate) -> tuple[int, float]:
    """Kompletny `total_score` (żaden komponent brakujący) zawsze przed
    PARTIAL — nigdy nie udajemy, że PARTIAL to COMPLETE (ta sama zasada
    co `scoring.py`: "nigdy nie sumujemy częściowych danych w fałszywie
    kompletną liczbę"). W obrębie tej samej kategorii: wyżej = lepiej."""
    if candidate.score.total_score is not None:
        return (0, -candidate.score.total_score)
    partial_sum = sum(
        v for v in (
            candidate.score.business_quality_score,
            candidate.score.safety_score,
            candidate.score.fear_score,
            candidate.score.dividend_score,
        )
        if v is not None
    )
    return (1, -partial_sum)


def rank_candidates(candidates: list[LiveCandidate], *, limit: int = 5) -> list[LiveCandidate]:
    """Sortuje i obcina do `limit`. Nigdy nie dopełnia listy sztucznie —
    mniej niż `limit` (łącznie z 0) jest prawidłowym wynikiem."""
    return sorted(candidates, key=_rank_key)[:limit]


def render_live_scan_report(
    *,
    run_date: str,
    universe_size: int,
    decline_surfaced: int,
    prefilter_excluded: int,
    analysis_failed: int,
    candidates: list[LiveCandidate],
    config: AppConfig,
) -> str:
    """Finalny raport live runu — audit trail funnela + 0..`limit`
    kandydatów, każdy z pełnym raportem Markdown (`report.
    render_markdown_report`, Faza 4+6: decline trigger, scoring, wycena,
    anti-confirmation-bias, źródła z jawnym SOURCE NOT VERIFIED)."""
    lines = [
        f"# Buffett Opportunity Scanner — LIVE SCAN {run_date}",
        "",
        "*Live run jest testem operacyjnym MVP V0, NIE kolejną rundą kalibracji — "
        "wynik nie zmienia `config/config.yaml` ani metodologii scoringu/wyceny "
        "(Decyzja właścicielki, Faza 6).*",
        "",
        "## Podsumowanie przebiegu (audit trail)",
        "",
        f"- Uniwersum (aktualne S&P 500, aktywne tickery): {universe_size}",
        f"- Wytypowane przez decline/opportunity screening "
        f"(>=1 przekroczony próg, UNCALIBRATED): {decline_surfaced}",
        f"- Wykluczone przez prefilter (EXCLUDE rules): {prefilter_excluded}",
        f"- Nieudane (brak zweryfikowanych źródeł / odrzucone przez walidację LLM / "
        f"błąd API): {analysis_failed}",
        f"- Finalni kandydaci w tym raporcie: {len(candidates)}",
        "",
    ]
    if not candidates:
        lines.append("## Wynik: No qualifying opportunities today")
        lines.append("")
        lines.append(
            "0 kandydatów jest prawidłowym wynikiem tego live runu (Decyzja właścicielki, "
            "Faza 6) — nie oznacza błędu pipeline'u. Patrz sekcja audit trail powyżej."
        )
        return "\n".join(lines) + "\n"

    lines.append(f"## Kandydaci ({len(candidates)})")
    lines.append("")
    for i, c in enumerate(candidates, start=1):
        lines.append(f"### Kandydat {i}: {c.ticker}")
        lines.append("")
        lines.append(render_markdown_report(
            ticker=c.ticker, cik=c.cik, run_date=c.run_date, current_price=c.current_price,
            analysis=c.analysis, score=c.score, config=config,
            decline_snapshot=c.decline_snapshot, triggered_decline_flags=c.triggered_decline_flags,
            source_packet=c.source_packet,
        ))
    return "\n".join(lines) + "\n"

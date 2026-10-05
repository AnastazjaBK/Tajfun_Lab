"""Generator raportu — Faza 4, punkt 4.3 (sekcja 15 design review) +
Faza 6 (decline trigger / anti-confirmation-bias / źródła, domknięcie
MVP V0).

Czysta funkcja formatująca `scoring.ScoreResult` do Markdown. Zero I/O —
wołający (cli.py) decyduje, czy wypisać na stdout, zapisać do pliku,
czy oba naraz.

Faza 6 GAP ANALYSIS: `AnalysisOutput` (Faza 3) od początku ma pola
bull_case/bear_case/why_market_may_be_right/why_this_may_not_be_a_bargain/
thesis_invalidation/verification_items, a `score`/`analyze` (Faza 4) od
początku liczy decline snapshot (`scanner.py`) i source packet
(`sources.py`) — ale `render_markdown_report` nigdy ich nie wypisywał.
`decline_snapshot`/`triggered_decline_flags`/`source_packet` są
OPCJONALNE (domyślnie `None`), żeby nie zepsuć istniejących callerów —
gdy podane, dodają sekcje "Dlaczego spółka została wytypowana", "Analiza
jakościowa — anti-confirmation-bias" i "Źródła" (z jawnym `SOURCE NOT
VERIFIED` dla niezweryfikowanych)."""

from __future__ import annotations

from buffett_scanner.analysis_schema import AnalysisOutput
from buffett_scanner.config import AppConfig
from buffett_scanner.scanner import PriceChangeSnapshot
from buffett_scanner.scoring import ScoreResult
from buffett_scanner.sources import VerifiedSource


def _render_decline_trigger(
    decline_snapshot: PriceChangeSnapshot | None,
    triggered_decline_flags: dict[str, bool] | None,
) -> list[str]:
    if decline_snapshot is None:
        return []
    lines = ["", "## Dlaczego spółka została wytypowana (decline trigger)", ""]
    lines.append(f"- Data snapshotu cenowego: {decline_snapshot.as_of_date}")
    lines.append(f"- 1D: {decline_snapshot.daily_pct}%  |  1T: {decline_snapshot.week_pct}%  "
                 f"|  1M: {decline_snapshot.month_pct}%  |  1Q: {decline_snapshot.quarter_pct}%")
    lines.append(f"- YTD: {decline_snapshot.ytd_pct}%  |  1R: {decline_snapshot.year_pct}%  "
                 f"|  Drawdown od 52w high: {decline_snapshot.drawdown_from_52w_high_pct}%  "
                 f"|  Wolumen względny: {decline_snapshot.relative_volume}")
    if triggered_decline_flags:
        triggered = [k for k, v in triggered_decline_flags.items() if v]
        lines.append(f"- Przekroczone progi (UNCALIBRATED): {', '.join(triggered) if triggered else '(brak)'}")
    return lines


def _render_anti_bias_section(analysis: AnalysisOutput) -> list[str]:
    lines = ["", "## Analiza jakościowa — anti-confirmation-bias (Claude API)", ""]

    def _bullets(title: str, items: list[str]) -> None:
        lines.append(f"**{title}:**")
        if items:
            for item in items:
                lines.append(f"- {item}")
        else:
            lines.append("- (brak — model nie podał)")
        lines.append("")

    _bullets("Bull Case", analysis.bull_case)
    _bullets("Bear Case", analysis.bear_case)
    _bullets("Why Market May Be Right", analysis.why_market_may_be_right)
    _bullets("Why Current Price May NOT Be an Opportunity", analysis.why_this_may_not_be_a_bargain)
    _bullets("Thesis Invalidation Conditions", analysis.thesis_invalidation)
    lines.append(f"**Biggest Unknown:** {analysis.biggest_unknown}")
    if analysis.verification_items:
        lines.append("")
        lines.append("**Do ręcznej weryfikacji (verification_items):**")
        for item in analysis.verification_items:
            where = " / ".join(p for p in (item.document, item.section) if p)
            page = f", str. {item.page}" if item.page is not None else ""
            lines.append(f"- [{item.source_id}] {where}{page} — {item.question or item.reason}")
    return lines


def _render_sources_section(source_packet: list[VerifiedSource] | None) -> list[str]:
    if source_packet is None:
        return []
    lines = ["", "## Źródła", ""]
    if not source_packet:
        lines.append("(brak źródeł w source packet)")
        return lines
    for s in source_packet:
        if s.verified:
            lines.append(f"- [OK] {s.title} — {s.url} (hash={s.content_hash[:16] if s.content_hash else '?'}...)")
        else:
            lines.append(f"- **SOURCE NOT VERIFIED**: {s.title} — {s.reason}")
    return lines


def render_markdown_report(
    *,
    ticker: str,
    cik: str,
    run_date: str,
    current_price: float,
    analysis: AnalysisOutput,
    score: ScoreResult,
    config: AppConfig,
    decline_snapshot: PriceChangeSnapshot | None = None,
    triggered_decline_flags: dict[str, bool] | None = None,
    source_packet: list[VerifiedSource] | None = None,
) -> str:
    w = config.scoring.weights
    lines = [
        f"# {ticker} ({cik}) — {run_date}",
        "",
        f"**Cena w dniu analizy:** {current_price:.2f}  ",
        f"**Wersja modelu scoringu:** {config.scoring.version} "
        f"(`status: {config.scoring.status}` — nie traktować jako reguły inwestycyjnej "
        "przed backtestingiem, Faza 5)",
    ]
    lines += _render_decline_trigger(decline_snapshot, triggered_decline_flags)
    lines += [
        "",
        "## Wynik",
        "",
        "| Komponent | Wynik | Waga |",
        "|---|---|---|",
        f"| Business Quality | {score.business_quality_score:.1f} | {w.business_quality} |",
        f"| Financial Safety | {score.safety_score:.1f} "
        f"(raw financial_quality: {score.financial_quality_score:.1f}/16) | {w.financial_safety} |",
        (
            f"| Valuation | {score.valuation_score:.1f} | {w.valuation} |"
            if score.valuation_score is not None
            else f"| Valuation | N/A — {score.valuation_result.reason} | {w.valuation} |"
        ),
        f"| Fear/Opportunity | {score.fear_score:.1f} | {w.fear_opportunity} |",
        f"| Dividend/Shareholder Return | {score.dividend_score:.1f} | {w.dividend_shareholder_return} |",
        (
            f"| **TOTAL** | **{score.total_score:.1f}/100** | |"
            if score.total_score is not None
            else f"| **TOTAL** | **PARTIAL — brakuje: {', '.join(score.missing_components)}** | |"
        ),
        "",
        f"**Hard gates:** {'PASSED' if score.hard_gate_result.passed else 'TRIGGERED'}",
    ]
    if score.hard_gate_result.triggered:
        for t in score.hard_gate_result.triggered:
            lines.append(f"- {t}")

    lines += ["", "## Wycena (DCF na Owner Earnings — proxy FCF)", ""]
    if score.valuation_result.implemented:
        lines.append("| Scenariusz | Discount rate | Terminal growth | Wzrost projekcji | Intrinsic value/akcję | Margin of Safety |")
        lines.append("|---|---|---|---|---|---|")
        for scen_name in ("bear", "base", "bull"):
            sv = score.valuation_result.scenarios[scen_name]
            mos = f"{sv.margin_of_safety_pct:.1f}%" if sv.margin_of_safety_pct is not None else "N/A"
            lines.append(
                f"| {scen_name.upper()} | {sv.discount_rate_pct:.1f}% | "
                f"{sv.terminal_growth_rate_pct:.1f}% | {sv.projected_growth_rate_pct:.1f}% | "
                f"{sv.intrinsic_value_per_share:.2f} | {mos} |"
            )
        lines.append("")
        lines.append(
            "*Hard gate `min_margin_of_safety_pct` sprawdzany względem scenariusza BASE "
            "(Decyzja właściciela 2026-09-25); BEAR/BULL to dodatkowe wskaźniki konserwatywny/optymistyczny.*"
        )
    else:
        lines.append(f"**NOT_YET_IMPLEMENTED:** {score.valuation_result.reason}")

    lines += ["", "## Dividend / Shareholder Return", ""]
    dr = score.dividend_result

    def _fmt(value: float | None, suffix: str = "") -> str:
        return f"{value:.2f}{suffix}" if value is not None else "N/A"

    lines.append(f"- Dividend per share (najnowszy okres): {_fmt(dr.dividend_per_share_latest)}")
    lines.append(f"- Shareholder yield: {_fmt(dr.shareholder_yield_pct_latest, '%')}")
    if dr.payout_ratio is not None and dr.payout_ratio.not_meaningful:
        lines.append("- Payout ratio (vs FCF): NOT_MEANINGFUL (FCF <= 0)")
    else:
        payout_value = dr.payout_ratio.value_pct if dr.payout_ratio else None
        lines.append(f"- Payout ratio (vs FCF): {_fmt(payout_value, '%')}")
    lines.append(f"- Trend liczby akcji: {dr.share_count_trend}")
    lines.append(f"- Brak cięcia dywidendy: {dr.no_dividend_cut}")

    lines += ["", "## Analiza jakościowa (Claude API)", ""]
    lines.append(f"**Fear classification:** {analysis.fear_analysis.classification} "
                 f"({analysis.fear_analysis.confidence}) — {analysis.fear_analysis.trigger}")
    lines.append("")
    lines.append(f"**Dividend trap alert:** {analysis.dividend_trap_alert.triggered}")
    if analysis.hard_flag_candidates:
        lines.append("")
        lines.append("**Hard flag candidates (do ręcznej weryfikacji):**")
        for flag in analysis.hard_flag_candidates:
            lines.append(f"- {flag.type}: {flag.quoted_text}")

    lines += _render_anti_bias_section(analysis)
    lines += _render_sources_section(source_packet)

    lines += ["", "*Progi/wagi tego raportu są `UNCALIBRATED` do czasu backtestingu (Faza 5) — "
              "nie traktować total_score jako gotowej rekomendacji inwestycyjnej.*"]

    return "\n".join(lines) + "\n"

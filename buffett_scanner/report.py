"""Generator raportu — Faza 4, punkt 4.3 (sekcja 15 design review).

Czysta funkcja formatująca `scoring.ScoreResult` do Markdown. Zero I/O —
wołający (cli.py) decyduje, czy wypisać na stdout, zapisać do pliku,
czy oba naraz.
"""

from __future__ import annotations

from buffett_scanner.analysis_schema import AnalysisOutput
from buffett_scanner.config import AppConfig
from buffett_scanner.scoring import ScoreResult


def render_markdown_report(
    *,
    ticker: str,
    cik: str,
    run_date: str,
    current_price: float,
    analysis: AnalysisOutput,
    score: ScoreResult,
    config: AppConfig,
) -> str:
    w = config.scoring.weights
    lines = [
        f"# {ticker} ({cik}) — {run_date}",
        "",
        f"**Cena w dniu analizy:** {current_price:.2f}  ",
        f"**Wersja modelu scoringu:** {config.scoring.version} "
        f"(`status: {config.scoring.status}` — nie traktować jako reguły inwestycyjnej "
        "przed backtestingiem, Faza 5)",
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
    lines.append(f"**Biggest unknown:** {analysis.biggest_unknown}")
    lines.append("")
    lines.append(f"**Dividend trap alert:** {analysis.dividend_trap_alert.triggered}")
    if analysis.hard_flag_candidates:
        lines.append("")
        lines.append("**Hard flag candidates (do ręcznej weryfikacji):**")
        for flag in analysis.hard_flag_candidates:
            lines.append(f"- {flag.type}: {flag.quoted_text}")

    lines += ["", "*Progi/wagi tego raportu są `UNCALIBRATED` do czasu backtestingu (Faza 5) — "
              "nie traktować total_score jako gotowej rekomendacji inwestycyjnej.*"]

    return "\n".join(lines) + "\n"

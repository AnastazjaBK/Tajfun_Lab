"""Silnik wskaźników fundamentalnych — czyste, deterministyczne funkcje.

Zero I/O, zero LLM. Wejście: znormalizowane okresy fundamentalne
(`FundamentalsPeriod`). Konwencja identyczna jak w `scanner.py`:
`periods[-1]` to najnowszy dostępny okres, `periods[0]` najstarszy.

Zasada z §24 design review, zastosowana konsekwentnie: brakująca wartość
wejściowa (None) NIGDY nie jest cicho traktowana jako 0 i NIGDY nie
fabrykuje wyniku ani flagi — wynikiem jest wtedy None / False, nie
zgadywana liczba.
"""

from __future__ import annotations

from dataclasses import dataclass

from buffett_scanner.config import PrefilterConfig, PrefilterRule


@dataclass(frozen=True)
class FundamentalsPeriod:
    """Jeden okres sprawozdawczy (zwykle rok fiskalny — FY), znormalizowany
    z surowych linii `fundamentals_raw` (format long) do jednego rekordu."""

    fiscal_period: str
    period_end_date: str
    filed_date: str | None
    revenue: float | None
    net_income: float | None
    ebitda: float | None
    operating_cash_flow: float | None
    capital_expenditure: float | None  # konwencja: dodatnia kwota wydatku (spend)
    total_debt: float | None
    cash_and_equivalents: float | None
    total_current_assets: float | None
    total_current_liabilities: float | None


def free_cash_flow(period: FundamentalsPeriod) -> float | None:
    if period.operating_cash_flow is None or period.capital_expenditure is None:
        return None
    return period.operating_cash_flow - period.capital_expenditure


def net_debt(period: FundamentalsPeriod) -> float | None:
    if period.total_debt is None or period.cash_and_equivalents is None:
        return None
    return period.total_debt - period.cash_and_equivalents


def net_debt_to_ebitda(period: FundamentalsPeriod) -> float | None:
    nd = net_debt(period)
    if nd is None or period.ebitda is None or period.ebitda == 0:
        return None
    return nd / period.ebitda


def current_ratio(period: FundamentalsPeriod) -> float | None:
    if (
        period.total_current_assets is None
        or period.total_current_liabilities is None
        or period.total_current_liabilities == 0
    ):
        return None
    return period.total_current_assets / period.total_current_liabilities


def fcf_margin_pct(period: FundamentalsPeriod) -> float | None:
    fcf = free_cash_flow(period)
    if fcf is None or period.revenue is None or period.revenue == 0:
        return None
    return fcf / period.revenue * 100.0


def revenue_yoy_growth_pct(
    current: FundamentalsPeriod, prior: FundamentalsPeriod
) -> float | None:
    if current.revenue is None or prior.revenue is None or prior.revenue == 0:
        return None
    return (current.revenue - prior.revenue) / prior.revenue * 100.0


def persistent_negative_fcf(periods: list[FundamentalsPeriod], lookback: int) -> bool:
    """True tylko jeśli mamy >= `lookback` najnowszych okresów i KAŻDY z
    nich ma jednoznacznie ujemny (znany, nie-None) FCF. Brak danych w
    którymkolwiek z badanych okresów -> False (nigdy zgadywanie)."""
    if len(periods) < lookback:
        return False
    window = periods[-lookback:]
    values = [free_cash_flow(p) for p in window]
    if any(v is None for v in values):
        return False
    return all(v < 0 for v in values)


def persistent_net_losses(periods: list[FundamentalsPeriod], lookback: int) -> bool:
    if len(periods) < lookback:
        return False
    window = periods[-lookback:]
    values = [p.net_income for p in window]
    if any(v is None for v in values):
        return False
    return all(v < 0 for v in values)


def compute_metrics(periods: list[FundamentalsPeriod]) -> dict[str, float | None]:
    """Liczy wskaźniki dla najnowszego dostępnego okresu (`periods[-1]`).

    Klucze zwracanego słownika odpowiadają wprost nazwom `metric` używanym
    w `config.yaml` sekcja `prefilter` — patrz `evaluate_prefilter`.
    """
    if not periods:
        raise ValueError("compute_metrics wymaga co najmniej jednego okresu")

    latest = periods[-1]
    metrics: dict[str, float | None] = {
        "fcf_ttm": free_cash_flow(latest),
        "net_debt_to_ebitda": net_debt_to_ebitda(latest),
        "current_ratio": current_ratio(latest),
        "fcf_margin_pct": fcf_margin_pct(latest),
        "revenue_yoy_growth_pct": None,
    }
    if len(periods) >= 2:
        metrics["revenue_yoy_growth_pct"] = revenue_yoy_growth_pct(latest, periods[-2])
    return metrics


@dataclass(frozen=True)
class PrefilterResult:
    flags: list[str]
    excludes: list[str]

    @property
    def passed(self) -> bool:
        """`False` tylko gdy jakaś reguła EXCLUDE się odpaliła. Flagi same
        w sobie NIE blokują (§BLOCKER 5) — służą do review, nie do
        automatycznego odrzucenia."""
        return not self.excludes


def _rule_triggers(rule: PrefilterRule, metrics: dict[str, float | None]) -> bool:
    value = metrics.get(rule.metric)
    if value is None:
        return False
    if rule.condition == "negative":
        return value < 0
    if rule.condition == "positive":
        return value > 0
    if rule.condition == "below":
        assert rule.threshold is not None
        return value < rule.threshold
    if rule.condition == "above":
        assert rule.threshold is not None
        return value > rule.threshold
    raise ValueError(f"Nieznany warunek reguły: {rule.condition!r}")


def evaluate_prefilter(
    metrics: dict[str, float | None], config: PrefilterConfig
) -> PrefilterResult:
    flags = [r.reason for r in config.flag_rules if _rule_triggers(r, metrics)]
    excludes = [r.reason for r in config.exclude_rules if _rule_triggers(r, metrics)]
    return PrefilterResult(flags=flags, excludes=excludes)

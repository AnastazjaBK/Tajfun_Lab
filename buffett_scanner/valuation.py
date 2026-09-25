"""Silnik wyceny — Faza 4, DCF na Owner Earnings (zatwierdzony design
2026-09-25, patrz docs/buffett-scanner-design-review.md).

Metoda wybierana wg `sector_profile` (`config.valuation.
method_by_sector_profile`) — tylko GENERAL ma zaimplementowaną metodę
teraz (`dcf_owner_earnings`); BANK/INSURER/REIT: NOT_YET_IMPLEMENTED
(Faza 10, Decyzja D7); BIOTECH ma odrębny pipeline rNPV (sekcja 18).

Owner Earnings jest tu PROXY = FCF z Fazy 1 (`fundamentals.
free_cash_flow`), nie pełną klasyczną koncepcją Buffetta (która
dodatkowo koryguje o maintenance capex vs growth capex, working capital
normalizację itd.). Nazwane jawnie `owner_earnings_proxy_fcf`, żeby to
uproszczenie nigdy nie było zatarte i dało się later podmienić na
dokładniejszą metodologię bez zmiany znaczenia historycznych wyników
(Decyzja właściciela, punkt 3).

Discount rate i terminal growth rate to założenia inwestora (nie da się
ich wyprowadzić z danych spółki) — WYŁĄCZNIE z configu, nigdy
hardkodowane tutaj. Tempo wzrostu w oknie projekcji NATOMIAST jest
wyprowadzane z historycznej CAGR FCF spółki (dane realne), potem
skalowane mnożnikiem scenariusza z configu i ograniczane sufitem/
podłogą bezpieczeństwa.

Gdy dane nie wystarczają do policzenia sensownej wyceny (brak historii,
ujemny bazowy FCF, brak liczby akcji, brak danych o zadłużeniu) —
`ValuationResult.implemented=False` z jawnym `reason`, NIGDY liczba
"na oko" czy cicha zerowa wartość domyślna.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from buffett_scanner.config import DcfOwnerEarningsConfig, ValuationConfig
from buffett_scanner.fundamentals import FundamentalsPeriod, free_cash_flow, net_debt

SCENARIOS = ("bear", "base", "bull")


def owner_earnings_proxy_fcf(period: FundamentalsPeriod) -> float | None:
    """Owner Earnings PROXY = FCF (patrz docstring modułu — uproszczenie,
    nazwane jawnie, do zastąpienia dokładniejszą metodologią później)."""
    return free_cash_flow(period)


def historical_owner_earnings_cagr_pct(periods: list[FundamentalsPeriod]) -> float | None:
    """CAGR historycznego owner_earnings_proxy_fcf między pierwszym a
    ostatnim dostępnym okresem. None gdy < 2 okresy albo baza/końcówka
    nie są jednoznacznie dodatnie (CAGR niezdefiniowany/mylący dla
    wartości <= 0) — nigdy nie zgadujemy tempa wzrostu."""
    if len(periods) < 2:
        return None
    start = owner_earnings_proxy_fcf(periods[0])
    end = owner_earnings_proxy_fcf(periods[-1])
    if start is None or end is None or start <= 0 or end <= 0:
        return None
    years = len(periods) - 1
    return ((end / start) ** (1.0 / years) - 1.0) * 100.0


@dataclass(frozen=True)
class ScenarioValuation:
    scenario: str
    discount_rate_pct: float
    terminal_growth_rate_pct: float
    projected_growth_rate_pct: float
    intrinsic_value_per_share: float
    margin_of_safety_pct: float | None  # None gdy intrinsic_value_per_share <= 0


@dataclass(frozen=True)
class ValuationResult:
    sector_profile: str
    method: str | None
    implemented: bool
    reason: str | None = None
    owner_earnings_proxy_fcf_latest: float | None = None
    historical_growth_cagr_pct: float | None = None
    scenarios: dict[str, ScenarioValuation] = field(default_factory=dict)


def _not_implemented(sector_profile: str, method: str | None, reason: str) -> ValuationResult:
    return ValuationResult(
        sector_profile=sector_profile, method=method, implemented=False, reason=reason,
    )


def _compute_dcf_owner_earnings(
    periods: list[FundamentalsPeriod],
    *,
    current_price: float,
    dcf_config: DcfOwnerEarningsConfig,
    sector_profile: str,
) -> ValuationResult:
    method = "dcf_owner_earnings"
    if not periods:
        return _not_implemented(sector_profile, method, "Brak danych fundamentalnych.")

    latest = periods[-1]
    latest_oe = owner_earnings_proxy_fcf(latest)
    if latest_oe is None or latest_oe <= 0:
        return _not_implemented(
            sector_profile, method,
            "Najnowszy owner_earnings_proxy_fcf jest None/ujemny — projekcja DCF "
            "z nie-dodatniej bazy byłaby myląca, nie licząca.",
        )

    historical_cagr = historical_owner_earnings_cagr_pct(periods)
    if historical_cagr is None:
        return _not_implemented(
            sector_profile, method,
            "Niewystarczające dane historyczne (potrzeba >=2 okresów z jednoznacznie "
            "dodatnim owner_earnings_proxy_fcf) do wyznaczenia tempa wzrostu bez zgadywania.",
        )

    net_debt_value = net_debt(latest)
    if net_debt_value is None:
        return _not_implemented(
            sector_profile, method,
            "Brak kompletnych danych bilansowych (dług/gotówka) do policzenia net debt — "
            "nie zakładamy cicho zera.",
        )

    diluted_shares = latest.diluted_shares_outstanding
    if diluted_shares is None or diluted_shares <= 0:
        return _not_implemented(
            sector_profile, method,
            "Brak liczby akcji rozwodnionych — nie da się policzyć wartości na akcję.",
        )

    scenarios: dict[str, ScenarioValuation] = {}
    for scenario in SCENARIOS:
        discount_rate_pct = getattr(dcf_config.discount_rate_pct, scenario)
        terminal_growth_pct = getattr(dcf_config.terminal_growth_rate_pct, scenario)
        multiplier = getattr(dcf_config.historical_growth_multiplier, scenario)

        projected_growth_pct = max(
            dcf_config.min_projected_growth_rate_pct,
            min(dcf_config.max_projected_growth_rate_pct, historical_cagr * multiplier),
        )

        discount_rate = discount_rate_pct / 100.0
        terminal_growth = terminal_growth_pct / 100.0
        growth = projected_growth_pct / 100.0

        pv_sum = 0.0
        for t in range(1, dcf_config.projection_years + 1):
            oe_t = latest_oe * (1.0 + growth) ** t
            pv_sum += oe_t / (1.0 + discount_rate) ** t

        oe_final = latest_oe * (1.0 + growth) ** dcf_config.projection_years
        # Model wzrostu Gordona — mianownik > 0 zagwarantowany przez walidację
        # configu (terminal_growth < discount_rate, patrz DcfOwnerEarningsConfig).
        terminal_value = oe_final * (1.0 + terminal_growth) / (discount_rate - terminal_growth)
        pv_terminal = terminal_value / (1.0 + discount_rate) ** dcf_config.projection_years

        enterprise_value = pv_sum + pv_terminal
        equity_value = enterprise_value - net_debt_value
        intrinsic_value_per_share = equity_value / diluted_shares

        margin_of_safety_pct = None
        if intrinsic_value_per_share > 0:
            margin_of_safety_pct = (
                (intrinsic_value_per_share - current_price) / intrinsic_value_per_share * 100.0
            )

        scenarios[scenario] = ScenarioValuation(
            scenario=scenario,
            discount_rate_pct=discount_rate_pct,
            terminal_growth_rate_pct=terminal_growth_pct,
            projected_growth_rate_pct=projected_growth_pct,
            intrinsic_value_per_share=intrinsic_value_per_share,
            margin_of_safety_pct=margin_of_safety_pct,
        )

    return ValuationResult(
        sector_profile=sector_profile, method=method, implemented=True,
        owner_earnings_proxy_fcf_latest=latest_oe,
        historical_growth_cagr_pct=historical_cagr,
        scenarios=scenarios,
    )


def compute_valuation(
    sector_profile: str,
    periods: list[FundamentalsPeriod],
    *,
    current_price: float,
    config: ValuationConfig,
) -> ValuationResult:
    method = config.method_by_sector_profile.get(sector_profile)
    if method is None:
        return _not_implemented(
            sector_profile, None,
            f"Brak zaimplementowanej metody wyceny dla sector_profile={sector_profile!r} "
            "(patrz config.valuation.method_by_sector_profile).",
        )
    if method == "dcf_owner_earnings":
        return _compute_dcf_owner_earnings(
            periods, current_price=current_price,
            dcf_config=config.dcf_owner_earnings, sector_profile=sector_profile,
        )
    raise ValueError(f"Nieznana metoda wyceny w configu: {method!r}")

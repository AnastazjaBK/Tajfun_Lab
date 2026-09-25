"""Config loader — jedno źródło prawdy dla progów i parametrów.

Wczytuje config/config.yaml, waliduje strukturę pydantic-modelami i
rozwiązuje sekret API (nazwę zmiennej środowiskowej wskazuje config,
sama wartość NIGDY nie jest zapisywana w configu ani w repo —
zgodnie z §34 specyfikacji / Decyzją D34).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "config.yaml"


class DeclineScannerThresholds(BaseModel):
    daily_pct: float
    week_pct: float
    month_pct: float
    quarter_pct: float
    drawdown_from_52w_high_pct: float
    relative_volume_multiple: float


class DeclineScannerConfig(BaseModel):
    thresholds: DeclineScannerThresholds
    status: str = "UNCALIBRATED"


class PrefilterRule(BaseModel):
    """Jedna reguła FLAG lub EXCLUDE (§BLOCKER 5 design review).

    `condition="negative"/"positive"` nie potrzebuje progu (`threshold`);
    `condition="below"/"above"` go wymaga. Brak wartości metryki (None) w
    danych NIGDY nie odpala reguły — patrz `fundamentals.evaluate_prefilter`.
    """

    metric: str
    condition: Literal["negative", "positive", "below", "above"]
    threshold: float | None = None
    reason: str

    @model_validator(mode="after")
    def _threshold_required_for_below_above(self) -> "PrefilterRule":
        if self.condition in ("below", "above") and self.threshold is None:
            raise ValueError(
                f"Reguła '{self.metric}' z condition='{self.condition}' wymaga 'threshold'."
            )
        return self


class PrefilterConfig(BaseModel):
    flag_rules: list[PrefilterRule] = Field(default_factory=list)
    exclude_rules: list[PrefilterRule] = Field(default_factory=list)
    status: str = "UNCALIBRATED"


class UniverseConfig(BaseModel):
    name: str
    source: str
    refresh: str


class DataProviderConfig(BaseModel):
    fundamentals_prices: str
    plan: str
    filings: str
    api_key_env_var: str

    def resolve_api_key(self) -> str:
        """Odczytuje klucz API ze zmiennej środowiskowej wskazanej w configu.

        Nigdy nie loguje ani nie zwraca nazwy zmiennej razem z jej
        wartością w komunikatach błędów — tylko fakt, że brakuje.
        """
        key = os.environ.get(self.api_key_env_var)
        if not key:
            raise RuntimeError(
                f"Brak zmiennej środowiskowej '{self.api_key_env_var}' z kluczem API. "
                "Ustaw ją lokalnie (np. w .env, który NIE jest commitowany — patrz "
                ".gitignore) albo jako sekret repozytorium na GitHubie dla Actions."
            )
        return key


class IrAllowlistEntry(BaseModel):
    """Jeden zweryfikowany wpis allowlisty domen Investor Relations
    (Decyzja D9, sekcja 9). `verified=True` wymaga faktycznej weryfikacji
    przeciw oficjalnej stronie tytułowej 10-K danej spółki — nigdy nie
    dodawany na podstawie samych wyników wyszukiwarki."""

    cik: str
    domain: str
    verified: bool
    note: str | None = None


class SecEdgarConfig(BaseModel):
    user_agent_env_var: str

    def resolve_user_agent(self) -> str:
        """Odczytuje dane kontaktowe wymagane przez SEC EDGAR ze zmiennej
        środowiskowej (ten sam wzorzec co `DataProviderConfig.resolve_api_key`).
        SEC wymaga realnych danych kontaktowych w nagłówku User-Agent —
        to nie jest sekret do ukrycia, ale mimo to nie commitujemy go na
        stałe do configu, żeby zmiana nie wymagała zmiany kodu/configu
        w repo."""
        value = os.environ.get(self.user_agent_env_var)
        if not value:
            raise RuntimeError(
                f"Brak zmiennej środowiskowej '{self.user_agent_env_var}' z danymi "
                "kontaktowymi wymaganymi przez SEC EDGAR (np. 'Tajfun Lab "
                "kontakt@example.com' — patrz https://www.sec.gov/os/webmaster-faq#developers). "
                "Ustaw ją lokalnie (.env, niecommitowany) albo jako sekret "
                "repozytorium dla GitHub Actions."
            )
        return value


class SourcesConfig(BaseModel):
    sec_edgar: SecEdgarConfig
    ir_allowlist: list[IrAllowlistEntry] = Field(default_factory=list)


class LlmConfig(BaseModel):
    model: str
    escalation_model: str | None = None
    max_output_tokens: int
    schema_version: str
    reject_on_schema_violation: bool = True
    allow_citations_outside_source_packet: bool = False
    api_key_env_var: str

    def resolve_api_key(self) -> str:
        """Ten sam wzorzec co `DataProviderConfig.resolve_api_key` /
        `SecEdgarConfig.resolve_user_agent` — sekret czytany ze zmiennej
        środowiskowej wskazanej w configu, nigdy zapisany w repo."""
        key = os.environ.get(self.api_key_env_var)
        if not key:
            raise RuntimeError(
                f"Brak zmiennej środowiskowej '{self.api_key_env_var}' z kluczem API "
                "Claude. Ustaw ją lokalnie (.env, niecommitowany) albo jako sekret "
                "repozytorium dla GitHub Actions."
            )
        return key


class ScoringWeights(BaseModel):
    """Wagi 5 komponentów total_score (sekcja 6 design review),
    muszą sumować się do 100."""

    business_quality: float
    financial_safety: float
    valuation: float
    fear_opportunity: float
    dividend_shareholder_return: float

    @model_validator(mode="after")
    def _sums_to_hundred(self) -> "ScoringWeights":
        total = sum(self.model_dump().values())
        if abs(total - 100.0) > 1e-9:
            raise ValueError(f"Wagi scoring muszą sumować się do 100, jest {total}")
        return self


class ScoringConfig(BaseModel):
    version: str
    weights: ScoringWeights
    status: str = "UNCALIBRATED"


class FinancialQualityWeights(BaseModel):
    """Rozbicie deterministycznego financial_quality_score (0-16, sekcja 8:
    "liczbowy score liczony deterministycznie, LLM dostarcza tylko
    komentarz") — muszą sumować się do 16."""

    fcf_positive: float
    fcf_margin_healthy: float
    low_leverage: float
    good_liquidity: float
    positive_revenue_growth: float
    no_persistent_losses: float

    @model_validator(mode="after")
    def _sums_to_sixteen(self) -> "FinancialQualityWeights":
        total = sum(self.model_dump().values())
        if abs(total - 16.0) > 1e-9:
            raise ValueError(f"Wagi financial_quality muszą sumować się do 16, jest {total}")
        return self


class FinancialQualityConfig(BaseModel):
    weights: FinancialQualityWeights
    fcf_margin_healthy_threshold_pct: float
    net_debt_to_ebitda_low_leverage_threshold: float
    current_ratio_good_threshold: float
    persistent_losses_lookback_years: int
    status: str = "UNCALIBRATED"


class FearOpportunityConfig(BaseModel):
    """Punkty (0-10) wg macierzy fear_analysis.classification × confidence
    z Fazy 3 — mapa, nie osobne wagi do zsumowania. UNCALIBRATED."""

    points_by_classification_confidence: dict[str, dict[str, float]]
    status: str = "UNCALIBRATED"

    @model_validator(mode="after")
    def _valid_matrix(self) -> "FearOpportunityConfig":
        required_classifications = {"TEMPORARY", "UNCERTAIN", "STRUCTURAL"}
        required_confidences = {"HIGH", "MEDIUM", "LOW"}
        if set(self.points_by_classification_confidence.keys()) != required_classifications:
            raise ValueError(
                "points_by_classification_confidence musi mieć dokładnie klucze "
                "TEMPORARY/UNCERTAIN/STRUCTURAL"
            )
        for cls, conf_map in self.points_by_classification_confidence.items():
            if set(conf_map.keys()) != required_confidences:
                raise ValueError(
                    f"points_by_classification_confidence['{cls}'] musi mieć dokładnie "
                    "klucze HIGH/MEDIUM/LOW"
                )
            for v in conf_map.values():
                if not (0.0 <= v <= 10.0):
                    raise ValueError(f"Punkty fear_opportunity muszą być w [0,10], jest {v}")
        return self


class DividendShareholderReturnWeights(BaseModel):
    """Rozbicie dividend_shareholder_return_score (0-10) — muszą sumować
    się do 10."""

    positive_shareholder_yield: float
    no_dividend_cut: float
    sustainable_payout_ratio: float
    shrinking_or_flat_share_count: float

    @model_validator(mode="after")
    def _sums_to_ten(self) -> "DividendShareholderReturnWeights":
        total = sum(self.model_dump().values())
        if abs(total - 10.0) > 1e-9:
            raise ValueError(
                f"Wagi dividend_shareholder_return muszą sumować się do 10, jest {total}"
            )
        return self


class DividendShareholderReturnConfig(BaseModel):
    weights: DividendShareholderReturnWeights
    max_sustainable_payout_ratio_pct: float
    min_shareholder_yield_pct: float
    status: str = "UNCALIBRATED"


class ScenarioFloats(BaseModel):
    """Wartość dla trzech scenariuszy wyceny — nigdy jedna stała liczba."""

    bear: float
    base: float
    bull: float


class DcfOwnerEarningsConfig(BaseModel):
    """Parametry DCF na Owner Earnings (proxy: FCF z Fazy 1) — wszystkie
    czytane z configu, nigdy hardkodowane w `valuation.py`. Zatwierdzony
    design (2026-09-25): dyskonto/terminal growth to założenia inwestora
    (nie do wyprowadzenia z danych spółki), tempo wzrostu w oknie
    projekcji jest natomiast DERIVED z historycznej CAGR FCF, nie zgadywane."""

    projection_years: int
    discount_rate_pct: ScenarioFloats
    terminal_growth_rate_pct: ScenarioFloats
    historical_growth_multiplier: ScenarioFloats
    max_projected_growth_rate_pct: float
    min_projected_growth_rate_pct: float
    mos_pct_for_full_score: float  # MoS (BASE) mapujące się na maks. 20 pkt valuation_score

    @model_validator(mode="after")
    def _terminal_growth_below_discount_rate(self) -> "DcfOwnerEarningsConfig":
        # Wymóg matematyczny wzoru Gordona (terminal value), nie preferencja —
        # przy terminal_growth >= discount_rate mianownik <= 0 i wzór diverguje.
        for scenario in ("bear", "base", "bull"):
            terminal = getattr(self.terminal_growth_rate_pct, scenario)
            discount = getattr(self.discount_rate_pct, scenario)
            if terminal >= discount:
                raise ValueError(
                    f"terminal_growth_rate_pct.{scenario} ({terminal}) musi być < "
                    f"discount_rate_pct.{scenario} ({discount}) — inaczej wzór DCF diverguje."
                )
        return self


class ValuationConfig(BaseModel):
    method_by_sector_profile: dict[str, str | None]
    dcf_owner_earnings: DcfOwnerEarningsConfig
    status: str = "UNCALIBRATED"


class HardGatesConfig(BaseModel):
    min_business_quality: float | None = None
    min_financial_safety: float | None = None
    min_margin_of_safety_pct: float | None = None  # sprawdzane względem scenariusza BASE
    status: str = "UNCALIBRATED"


class AppConfig(BaseModel):
    universe: UniverseConfig
    decline_scanner: DeclineScannerConfig
    prefilter: PrefilterConfig
    sources: SourcesConfig
    llm: LlmConfig
    scoring: ScoringConfig
    financial_quality: FinancialQualityConfig
    fear_opportunity: FearOpportunityConfig
    dividend_shareholder_return: DividendShareholderReturnConfig
    valuation: ValuationConfig
    hard_gates: HardGatesConfig
    data_provider: DataProviderConfig


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> AppConfig:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Nie znaleziono pliku konfiguracyjnego: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return AppConfig.model_validate(raw)

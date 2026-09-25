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


class AppConfig(BaseModel):
    universe: UniverseConfig
    decline_scanner: DeclineScannerConfig
    prefilter: PrefilterConfig
    sources: SourcesConfig
    data_provider: DataProviderConfig


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> AppConfig:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Nie znaleziono pliku konfiguracyjnego: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return AppConfig.model_validate(raw)

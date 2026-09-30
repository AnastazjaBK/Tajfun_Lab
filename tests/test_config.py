import os

import pytest
from pydantic import ValidationError

from buffett_scanner.config import DEFAULT_CONFIG_PATH, load_config


def test_default_config_loads_and_validates():
    config = load_config(DEFAULT_CONFIG_PATH)
    assert config.universe.name == "sp500"
    assert config.decline_scanner.status == "UNCALIBRATED"
    assert config.decline_scanner.thresholds.daily_pct == -5.0
    assert config.data_provider.fundamentals_prices == "fmp"
    assert config.data_provider.plan == "free"


def test_missing_config_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "does-not-exist.yaml")


def test_invalid_config_raises_validation_error(tmp_path):
    bad = tmp_path / "config.yaml"
    bad.write_text("universe:\n  name: sp500\n")  # brakuje wymaganych sekcji
    with pytest.raises(ValidationError):
        load_config(bad)


def test_prefilter_config_loads_flag_rules_and_empty_exclude_rules():
    config = load_config(DEFAULT_CONFIG_PATH)
    assert config.prefilter.status == "UNCALIBRATED"
    assert config.prefilter.exclude_rules == []
    assert len(config.prefilter.flag_rules) == 4
    metrics = {r.metric for r in config.prefilter.flag_rules}
    assert metrics == {
        "fcf_ttm", "revenue_yoy_growth_pct", "net_debt_to_ebitda", "current_ratio",
    }


def test_prefilter_rule_with_below_or_above_condition_requires_threshold():
    from pydantic import ValidationError as PydValidationError

    from buffett_scanner.config import PrefilterRule

    with pytest.raises(PydValidationError):
        PrefilterRule(metric="x", condition="below", reason="brak progu")


def test_resolve_api_key_missing_env_var_raises_clear_error(monkeypatch):
    config = load_config(DEFAULT_CONFIG_PATH)
    monkeypatch.delenv(config.data_provider.api_key_env_var, raising=False)
    with pytest.raises(RuntimeError, match="FMP_API_KEY"):
        config.data_provider.resolve_api_key()


def test_resolve_api_key_reads_env_var(monkeypatch):
    config = load_config(DEFAULT_CONFIG_PATH)
    monkeypatch.setenv(config.data_provider.api_key_env_var, "dummy-test-key")
    assert config.data_provider.resolve_api_key() == "dummy-test-key"


def test_sources_config_loads_sec_edgar_and_empty_ir_allowlist():
    config = load_config(DEFAULT_CONFIG_PATH)
    assert config.sources.sec_edgar.user_agent_env_var == "SEC_EDGAR_USER_AGENT"
    assert config.sources.ir_allowlist == []


def test_resolve_user_agent_missing_env_var_raises_clear_error(monkeypatch):
    config = load_config(DEFAULT_CONFIG_PATH)
    monkeypatch.delenv(config.sources.sec_edgar.user_agent_env_var, raising=False)
    with pytest.raises(RuntimeError, match="SEC_EDGAR_USER_AGENT"):
        config.sources.sec_edgar.resolve_user_agent()


def test_resolve_user_agent_reads_env_var(monkeypatch):
    config = load_config(DEFAULT_CONFIG_PATH)
    monkeypatch.setenv(config.sources.sec_edgar.user_agent_env_var, "Tajfun Lab test@example.com")
    assert config.sources.sec_edgar.resolve_user_agent() == "Tajfun Lab test@example.com"


def test_llm_config_loads_expected_defaults():
    config = load_config(DEFAULT_CONFIG_PATH)
    assert config.llm.model == "claude-sonnet-5"
    assert config.llm.schema_version == "1.0"
    assert config.llm.reject_on_schema_violation is True
    assert config.llm.allow_citations_outside_source_packet is False
    assert config.llm.api_key_env_var == "ANTHROPIC_API_KEY"


def test_resolve_llm_api_key_missing_env_var_raises_clear_error(monkeypatch):
    config = load_config(DEFAULT_CONFIG_PATH)
    monkeypatch.delenv(config.llm.api_key_env_var, raising=False)
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        config.llm.resolve_api_key()


def test_resolve_llm_api_key_reads_env_var(monkeypatch):
    config = load_config(DEFAULT_CONFIG_PATH)
    monkeypatch.setenv(config.llm.api_key_env_var, "dummy-claude-key")
    assert config.llm.resolve_api_key() == "dummy-claude-key"


def test_backtest_config_loads_window_and_limited_but_honest_status():
    """Faza 5.3 (sekcja 13, Decyzja D14) — okno 2012+, jawna adnotacja
    LIMITED_BUT_HONEST. Ten config.yaml zapis istniał już przed
    wpięciem BacktestConfig do AppConfig (v1.21+) — ten test potwierdza,
    że load_config faktycznie go teraz waliduje, nie tylko ignoruje
    jako nieznane pole."""
    config = load_config(DEFAULT_CONFIG_PATH)
    assert config.backtest.window_start == "2012-01-01"
    assert config.backtest.window_end is None
    assert config.backtest.status == "LIMITED_BUT_HONEST"


def test_backtest_config_requires_window_start():
    from pydantic import ValidationError as PydValidationError

    from buffett_scanner.config import BacktestConfig

    with pytest.raises(PydValidationError):
        BacktestConfig()

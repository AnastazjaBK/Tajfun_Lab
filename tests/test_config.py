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
    assert config.data_provider.plan == "starter"


def test_missing_config_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "does-not-exist.yaml")


def test_invalid_config_raises_validation_error(tmp_path):
    bad = tmp_path / "config.yaml"
    bad.write_text("universe:\n  name: sp500\n")  # brakuje wymaganych sekcji
    with pytest.raises(ValidationError):
        load_config(bad)


def test_resolve_api_key_missing_env_var_raises_clear_error(monkeypatch):
    config = load_config(DEFAULT_CONFIG_PATH)
    monkeypatch.delenv(config.data_provider.api_key_env_var, raising=False)
    with pytest.raises(RuntimeError, match="FMP_API_KEY"):
        config.data_provider.resolve_api_key()


def test_resolve_api_key_reads_env_var(monkeypatch):
    config = load_config(DEFAULT_CONFIG_PATH)
    monkeypatch.setenv(config.data_provider.api_key_env_var, "dummy-test-key")
    assert config.data_provider.resolve_api_key() == "dummy-test-key"

# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Startup configuration is asserted so a misconfigured service fails fast."""

from __future__ import annotations

import logging

import pytest

from src.config import Config, ConfigError

_WEBHOOK = "https://hooks.slack.example/T0/B0/x"


def test_missing_webhook_url_is_a_config_error() -> None:
    with pytest.raises(ConfigError, match="SLACK_WEBHOOK_URL"):
        Config(slack_webhook_url="", expected_token="")


def test_unknown_log_level_is_a_config_error() -> None:
    with pytest.raises(ConfigError, match="LOG_LEVEL"):
        Config(slack_webhook_url=_WEBHOOK, expected_token="", log_level="LOUD")


def test_empty_token_is_allowed_for_local_dev() -> None:
    config = Config(slack_webhook_url=_WEBHOOK, expected_token="")
    assert config.expected_token == ""


def test_log_level_is_applied_to_the_root_logger() -> None:
    previous = logging.getLogger().level
    try:
        Config(slack_webhook_url=_WEBHOOK, expected_token="", log_level="WARNING")
        assert logging.getLogger().level == logging.WARNING
    finally:
        logging.getLogger().setLevel(previous)


def test_from_env_reads_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SLACK_WEBHOOK_URL", _WEBHOOK)
    monkeypatch.setenv("NEBULA_NOTIFICATIONS_TOKEN", "t0k3n")
    monkeypatch.setenv("LOG_LEVEL", "debug")
    config = Config.from_env()
    assert config.slack_webhook_url == _WEBHOOK
    assert config.expected_token == "t0k3n"
    assert config.log_level == "DEBUG"

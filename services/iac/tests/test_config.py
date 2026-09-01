# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for IaC engine binary resolution in ``Config.from_env``.

Precedence: ``IAC_BINARY`` > ``TERRAFORM_BINARY`` (deprecated, warns) >
``opentofu`` (the default, aliased to the real ``tofu`` executable).
Resolvable-on-PATH is asserted at construction time, so the tests use
``sh`` (always present) as a stand-in binary.
"""

from __future__ import annotations

import pytest

from src.config import Config, ConfigError


def test_iac_binary_takes_precedence(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IAC_BINARY", "sh")
    monkeypatch.setenv("TERRAFORM_BINARY", "env")
    assert Config.from_env().terraform_binary == "sh"


def test_legacy_terraform_binary_fallback_warns(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.delenv("IAC_BINARY", raising=False)
    monkeypatch.setenv("TERRAFORM_BINARY", "sh")
    with caplog.at_level("WARNING", logger="iac.config"):
        config = Config.from_env()
    assert config.terraform_binary == "sh"
    assert any("TERRAFORM_BINARY is deprecated" in r.message for r in caplog.records)


def test_default_engine_is_opentofu(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("IAC_BINARY", raising=False)
    monkeypatch.delenv("TERRAFORM_BINARY", raising=False)
    # The default must resolve even on hosts without OpenTofu installed.
    monkeypatch.setattr("src.config.terraform_available", lambda binary: True)
    # Default is ``opentofu``, aliased to the real ``tofu`` executable.
    assert Config.from_env().terraform_binary == "tofu"


def test_opentofu_alias_resolves_to_tofu(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IAC_BINARY", "opentofu")
    monkeypatch.setattr("src.config.terraform_available", lambda binary: True)
    assert Config.from_env().terraform_binary == "tofu"


def test_unresolvable_binary_fails_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IAC_BINARY", "definitely-not-an-engine-binary")
    with pytest.raises(ConfigError, match="IaC engine binary"):
        Config.from_env()

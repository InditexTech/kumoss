# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""IAC_BINARY selects the IaC engine CLI (OpenTofu or Terraform)."""

from src.config import Config


def test_iac_binary_defaults_to_tofu(monkeypatch) -> None:
    monkeypatch.delenv("IAC_BINARY", raising=False)
    assert Config.from_env().iac_binary == "tofu"


def test_iac_binary_env_selects_terraform(monkeypatch) -> None:
    monkeypatch.setenv("IAC_BINARY", "terraform")
    assert Config.from_env().iac_binary == "terraform"


def test_legacy_terraform_binary_env_is_ignored(monkeypatch) -> None:
    monkeypatch.delenv("IAC_BINARY", raising=False)
    monkeypatch.setenv("TERRAFORM_BINARY", "terraform")
    assert Config.from_env().iac_binary == "tofu"

# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for IaC engine binary resolution in ``Config.from_env``.

``IAC_BINARY`` names the engine CLI to invoke; the default is ``tofu``
(OpenTofu). Resolvable-on-PATH is asserted at construction time, so the
tests use ``sh`` (always present) as a stand-in binary or patch the
availability check.
"""

from __future__ import annotations

import pytest

from src.config import Config, ConfigError


def test_iac_binary_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IAC_BINARY", "sh")
    assert Config.from_env().iac_binary == "sh"


def test_default_engine_is_opentofu(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("IAC_BINARY", raising=False)
    # The default must resolve even on hosts without OpenTofu installed.
    monkeypatch.setattr("src.config.engine_available", lambda binary: True)
    assert Config.from_env().iac_binary == "tofu"


def test_unresolvable_binary_fails_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IAC_BINARY", "definitely-not-an-engine-binary")
    with pytest.raises(ConfigError, match="IaC engine binary"):
        Config.from_env()

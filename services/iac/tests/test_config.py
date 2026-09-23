# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for ``Config.from_env``.

``IAC_BINARY`` names the engine CLI to invoke; the default is ``tofu``
(OpenTofu). Resolvable-on-PATH is asserted at construction time, so the
tests use ``sh`` (always present) as a stand-in binary or patch the
availability check.

``IAC_BACKEND_CONFIG`` names a backend configuration file for `init` to
run with. It is *not* validated at startup: the file normally lives in
the target repository, which is only cloned into a workspace once a job
runs.
"""

from __future__ import annotations

import pytest

from src.config import Config
from src.exceptions import ConfigError


def _always_available(_self: Config, _binary: str) -> bool:
    return True


def test_iac_binary_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IAC_BINARY", "sh")
    assert Config.from_env().iac_binary == "sh"


def test_default_engine_is_opentofu(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("IAC_BINARY", raising=False)
    # The default must resolve even on hosts without OpenTofu installed.
    monkeypatch.setattr(Config, "_engine_available", _always_available)
    assert Config.from_env().iac_binary == "tofu"


def test_unresolvable_binary_fails_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IAC_BINARY", "definitely-not-an-engine-binary")
    with pytest.raises(ConfigError, match="IaC engine binary"):
        _ = Config.from_env()


@pytest.mark.parametrize("raw", ["", "   "])
def test_blank_backend_config_is_unset(
    raw: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("IAC_BACKEND_CONFIG", raw)
    assert Config.from_env().backend_config is None


def test_backend_config_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IAC_BACKEND_CONFIG", "  /etc/nebula/backend.hcl  ")
    assert Config.from_env().backend_config == "/etc/nebula/backend.hcl"


@pytest.mark.parametrize("target", ["backend.hcl", "envs/prod/backend.tfbackend"])
def test_backend_config_need_not_exist_at_startup(
    target: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The file usually ships in the target repository, which is only
    cloned into a workspace once a job runs, so the path is taken as
    given and a wrong one fails on `init` instead."""
    monkeypatch.setenv("IAC_BACKEND_CONFIG", target)
    assert Config.from_env().backend_config == target

# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for ``Config.from_env``.

``IAC_BINARY`` names the engine CLI to invoke; the default is ``tofu``
(OpenTofu). Resolvable-on-PATH is asserted at construction time, so the
tests use ``sh`` (always present) as a stand-in binary or patch the
availability check.

``IAC_BACKEND_CONFIG`` names a backend configuration file for `init` to
run with, and is asserted readable for the same reason.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.config import Config
from src.exceptions import ConfigError


def _always_available(_binary: str) -> bool:
    return True


def test_iac_binary_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IAC_BINARY", "sh")
    assert Config.from_env().iac_binary == "sh"


def test_default_engine_is_opentofu(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("IAC_BINARY", raising=False)
    # The default must resolve even on hosts without OpenTofu installed.
    monkeypatch.setattr("src.config._engine_available", _always_available)
    assert Config.from_env().iac_binary == "tofu"


def test_unresolvable_binary_fails_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IAC_BINARY", "definitely-not-an-engine-binary")
    with pytest.raises(ConfigError, match="IaC engine binary"):
        _ = Config.from_env()


def backend_file(tmp_path: Path) -> Path:
    path = tmp_path / "backend.hcl"
    _ = path.write_text('bucket = "somewhere"\n', encoding="utf-8")
    return path


@pytest.mark.parametrize("raw", ["", "   "])
def test_blank_backend_config_is_unset(
    raw: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("IAC_BACKEND_CONFIG", raw)
    assert Config.from_env().backend_config is None


def test_backend_config_from_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = backend_file(tmp_path)
    monkeypatch.setenv("IAC_BACKEND_CONFIG", f"  {path}  ")
    assert Config.from_env().backend_config == str(path)


@pytest.mark.parametrize("target", ["does-not-exist.hcl", "a-directory"])
def test_unreadable_backend_config_fails_fast(
    target: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Same reason the engine binary is checked at startup: a path that
    is not there is a mounting mistake, and every `init` would fail on
    it anyway."""
    (tmp_path / "a-directory").mkdir()
    monkeypatch.setenv("IAC_BACKEND_CONFIG", str(tmp_path / target))
    with pytest.raises(ConfigError, match="IAC_BACKEND_CONFIG"):
        _ = Config.from_env()

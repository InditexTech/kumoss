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

import os

import pytest

from src.config import Config, ConfigError, materialize_google_credentials


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


# --- materialize_google_credentials ----------------------------------------


def test_no_google_credentials_is_a_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GOOGLE_CREDENTIALS", raising=False)
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    assert materialize_google_credentials() is None
    assert "GOOGLE_APPLICATION_CREDENTIALS" not in os.environ


def test_google_credentials_json_is_materialized_and_pointed_at(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    key_json = '{"type": "service_account", "project_id": "demo"}'
    monkeypatch.setenv("GOOGLE_CREDENTIALS", key_json)
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)

    path = materialize_google_credentials(home=tmp_path)

    assert path == tmp_path / "google-credentials.json"
    assert path.read_text() == key_json
    assert (path.stat().st_mode & 0o777) == 0o600
    assert os.environ["GOOGLE_APPLICATION_CREDENTIALS"] == str(path)


def test_invalid_google_credentials_json_fails_fast(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setenv("GOOGLE_CREDENTIALS", "not json")
    with pytest.raises(ConfigError, match="GOOGLE_CREDENTIALS is not valid JSON"):
        materialize_google_credentials(home=tmp_path)

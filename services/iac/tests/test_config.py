# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Knobs come from ``src.config`` constants; secrets and deployment-specific
values come from the env."""

from src import config as config_module
from src.config import Config


def test_knobs_are_not_read_from_env(monkeypatch) -> None:
    """Operational knobs are edited in src/config.py; the environment
    (including the legacy ``TERRAFORM_BINARY``) is ignored for them."""
    monkeypatch.setenv("IAC_BINARY", "terraform")
    monkeypatch.setenv("TERRAFORM_BINARY", "terraform")
    monkeypatch.setenv("NEBULA_IAC_JOB_TTL", "1")
    monkeypatch.setenv("NEBULA_SUBPROCESS_TIMEOUT", "1")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("CLOUD_LOGIN_REFRESH_MIN", "1")
    monkeypatch.setenv("CLOUD_LOGIN_RETRIES", "9")
    monkeypatch.setenv("CLOUD_LOGIN_RETRY_DELAY_SEC", "9")

    cfg = Config.from_env()

    assert cfg.iac_binary == config_module.IAC_BINARY
    assert cfg.job_ttl == config_module.JOB_TTL_SECONDS
    assert cfg.subprocess_timeout == config_module.SUBPROCESS_TIMEOUT_SECONDS
    assert cfg.log_level == config_module.LOG_LEVEL
    assert cfg.cloud_login_refresh_min == config_module.CLOUD_LOGIN_REFRESH_MIN
    assert cfg.cloud_login_retries == config_module.CLOUD_LOGIN_RETRIES
    assert cfg.cloud_login_retry_delay_sec == config_module.CLOUD_LOGIN_RETRY_DELAY_SEC


def test_env_values_are_read_from_env(monkeypatch) -> None:
    """The variable names are the contract with env.sample: a typo here
    would silently disable a provider login."""
    monkeypatch.setenv("NEBULA_IAC_TOKEN", "tok")
    monkeypatch.setenv("ARM_CLIENT_ID", "az-id")
    monkeypatch.setenv("ARM_CLIENT_SECRET", "az-secret")
    monkeypatch.setenv("ARM_TENANT_ID", "az-tenant")
    monkeypatch.setenv("GOOGLE_CREDENTIALS", "{}")
    monkeypatch.setenv("TF_BACKEND_CONFIG", "backend.hcl")
    monkeypatch.setenv("AWS_TERRAFORM_ROLE_NAME", "role/nebula-terraform")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIA")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "s3cr3t")

    cfg = Config.from_env()

    assert cfg.expected_token == "tok"
    assert cfg.azure_client_id == "az-id"
    assert cfg.azure_client_secret == "az-secret"
    assert cfg.azure_tenant_id == "az-tenant"
    assert cfg.google_credentials == "{}"
    assert cfg.backend_config == "backend.hcl"
    assert cfg.aws_terraform_role_name == "role/nebula-terraform"
    assert cfg.aws_access_key_id == "AKIA"
    assert cfg.aws_secret_access_key == "s3cr3t"


def test_aws_keys_default_empty(monkeypatch) -> None:
    """Unset AWS keys read as empty strings, which the AWS provider treats
    as "not configured" rather than "partially configured"."""
    monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("AWS_SECRET_ACCESS_KEY", raising=False)

    cfg = Config.from_env()

    assert cfg.aws_access_key_id == ""
    assert cfg.aws_secret_access_key == ""

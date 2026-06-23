# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""System-wide configuration loaded from a YAML file.

Single source of truth for every deployment-tunable knob in the core.
Resolved at startup from the path in ``NEBULA_CONFIG``; if unset or
missing, defaults defined here apply (so the OSS distribution boots
without any config file).

Secrets never live in this file. Fields named ``*_env`` carry the name
of an environment variable that holds the actual secret; the value is
read at use time. This keeps the YAML safe to commit (or share in a bug
report) while real secrets stay in env files / Kubernetes Secrets / a
secrets manager.

The annotated yaml configuration file is at ``/config.yaml``.
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, model_validator

from src.shared.constants import LLMProvider


class ConfigError(ValueError):
    """Raised when the resolved system configuration is unusable.

    Surfaced at startup.
    """


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default) if name else default


class OidcConfig(BaseModel):
    """OIDC issuer settings for the React frontend logging in to the core."""

    issuer_url: str = ""
    client_id: str = ""
    audience: str = ""


class AdminConfig(BaseModel):
    """Bootstrap administrator. Granted root-admin role on first run if set."""

    default_root_email: str = ""


class LlmConfig(BaseModel):
    """LLM provider selection + per-provider credential references.

    The core uses two models per workflow: a ``model`` for high-quality
    reasoning steps and a faster/cheaper ``small_model`` for filler work
    (status updates, classifiers, secondary calls). Both temperatures are
    deployer-tunable.

    Provider credentials are referenced indirectly via env-var names so
    nothing sensitive lives in the YAML.
    """

    # `model` and `small_model` are LLMProvider enum names (see
    # core/src/shared/constants.py::LLMProvider). Examples: SONNET_VERTEX,
    # HAIKU_VERTEX, GEMINI_FLASH, SONNET_BEDROCK. The factory resolves
    # the name to the full provider/model/region tuple at startup.
    model: str = "SONNET_VERTEX"
    small_model: str = "HAIKU_VERTEX"
    temperature: float = 0.1
    small_model_temperature: float = 0.1

    aws_region: str = "us-west-2"
    aws_bedrock_access_key_id_env: str = "AWS_ACCESS_KEY_ID"
    aws_bedrock_secret_access_key_env: str = "AWS_SECRET_ACCESS_KEY"
    google_application_credentials_env: str = "GOOGLE_APPLICATION_CREDENTIALS"
    google_sa_secret_env: str = "GOOGLE_SA_SECRET"
    google_vertex_project_env: str = "GOOGLE_VERTEX_ID"

    @property
    def aws_bedrock_access_key_id(self) -> str:
        return _env(self.aws_bedrock_access_key_id_env)

    @property
    def aws_bedrock_secret_access_key(self) -> str:
        return _env(self.aws_bedrock_secret_access_key_env)

    @property
    def google_application_credentials(self) -> str:
        return _env(self.google_application_credentials_env)

    @property
    def google_sa_secret(self) -> str:
        return _env(self.google_sa_secret_env)

    @property
    def google_vertex_project(self) -> str:
        return _env(self.google_vertex_project_env)


class ServiceConfig(BaseModel):
    """Configuration for a single microservice contract.

    ``token_env`` names the environment variable holding the bearer token
    the core sends with every call. Looking the token up indirectly
    keeps secrets out of this file.
    """

    enabled: bool = False
    endpoint: str = ""
    token_env: str = ""

    @property
    def token(self) -> str:
        return _env(self.token_env)


class ServicesConfig(BaseModel):
    notifications: ServiceConfig = Field(default_factory=ServiceConfig)
    mapping: ServiceConfig = Field(default_factory=ServiceConfig)
    authz: ServiceConfig = Field(default_factory=ServiceConfig)
    iac: ServiceConfig = Field(default_factory=ServiceConfig)


class OrchestrationConfig(BaseModel):
    """Iteration limits and batch sizes for the core's orchestration loops."""

    max_drift_reports: int = 3
    max_validation_iteration: int = 5
    max_tool_chain_executions: int = 70
    max_session_events_iteration: int = 2160
    drift_group_operations: int = 8


class PathsConfig(BaseModel):
    """Filesystem paths used by the core."""

    upload_folder: Path = Path("/workspaces")


class TelemetryConfig(BaseModel):
    """Generic OTel telemetry knobs.

    ``collector_url`` is a base URL; the OTLP endpoint is computed from
    it at use time as ``f"{collector_url}v1/traces"``. The OSS-default
    deploy bundles Phoenix as the collector but anything that speaks
    OTLP/HTTP works.
    """

    collector_url: str = "http://localhost:6006/"
    otel_attribute_count_limit: int = 1024
    otel_console_exporter: bool = False


class HttpConfig(BaseModel):
    # The docker-compose stack serves the frontend via nginx on :80, so the
    # browser-facing origin is http://localhost. Add http://localhost:5173 if
    # you run the Vite dev server (npm run dev) outside docker and point it
    # at the API container.
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost"])


class GitConfig(BaseModel):
    """Credentials for `git push` against the remote hosting user repos.

    When `provider` is set and the env vars named by `pat_user_env` /
    `pat_token_env` resolve to non-empty values at boot, the application
    writes ~/.git-credentials and configures the `store` credential
    helper so subsequent `git push` calls authenticate without prompting.
    Leave `provider` empty to disable the credential setup entirely (push
    will then need mounted ~/.git-credentials, SSH keys, or PAT-embedded
    repo_uri). Single-tenant by design (one PAT for all sessions).
    """

    # `provider` is GitProviderName enum names (see
    # core/src/shared/constants.py::GitProviderName). Examples: GITHUB,
    # AZURE_DEVOPS.
    provider: str = "GITHUB"
    pat_user_env: str = "GIT_USER"  # env var name holding the username
    pat_token_env: str = "GIT_TOKEN"  # env var name holding the personal access token

    # git refuses to create a commit without name + email.
    author_name: str = "Nebula"
    author_email: str = "nebula@noreply.invalid"

    @property
    def pat_user(self) -> str:
        return _env(self.pat_user_env)

    @property
    def pat_token(self) -> str:
        return _env(self.pat_token_env)


class SystemConfig(BaseModel):
    environment: str = "development"  # development | staging | production

    oidc: OidcConfig = Field(default_factory=OidcConfig)
    admin: AdminConfig = Field(default_factory=AdminConfig)
    llm: LlmConfig = Field(default_factory=LlmConfig)
    services: ServicesConfig = Field(default_factory=ServicesConfig)
    orchestration: OrchestrationConfig = Field(default_factory=OrchestrationConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)
    telemetry: TelemetryConfig = Field(default_factory=TelemetryConfig)
    http: HttpConfig = Field(default_factory=HttpConfig)
    git: GitConfig = Field(default_factory=GitConfig)

    @model_validator(mode="after")
    def _assert_llm_credentials(self) -> "SystemConfig":
        """Fail-fast on missing LLM credentials for the selected providers.

        Only the providers actually referenced by ``llm.model`` / ``llm.small_model``
        are required.
        """
        selected: list[str] = []
        for field, name in (
            ("model", self.llm.model),
            ("small_model", self.llm.small_model),
        ):
            try:
                selected.append(LLMProvider[name].value["provider"])
            except KeyError as e:
                valid = ", ".join(p.name for p in LLMProvider)
                raise ConfigError(
                    f"llm.{field}={name!r} is not a known LLMProvider. Valid: {valid}"
                ) from e

        missing: list[str] = []
        if "anthropicBedrock" in selected:
            if not self.llm.aws_bedrock_access_key_id:
                missing.append(self.llm.aws_bedrock_access_key_id_env)
            if not self.llm.aws_bedrock_secret_access_key:
                missing.append(self.llm.aws_bedrock_secret_access_key_env)
        if {"anthropicVertex", "google"} & set(selected):
            # ADC: either GOOGLE_APPLICATION_CREDENTIALS (path to a key file)
            # or GOOGLE_SA_SECRET (inline JSON) must resolve.
            if not (
                self.llm.google_application_credentials or self.llm.google_sa_secret
            ):
                missing.append(
                    f"{self.llm.google_application_credentials_env} "
                    + f"or {self.llm.google_sa_secret_env}"
                )
            if not self.llm.google_vertex_project:
                missing.append(self.llm.google_vertex_project_env)

        if missing:
            raise ConfigError(
                "Missing credentials for selected LLM providers "
                + f"({', '.join(sorted(set(selected)))}): "
                + f"set env var(s) {', '.join(missing)}."
            )
        return self

    @model_validator(mode="after")
    def _assert_service_tokens(self) -> "SystemConfig":
        """Every enabled service must have a non-empty bearer token resolved.

        The outbound httpx clients always send ``Authorization: Bearer <token>``
        and httpx rejects an empty bearer as a malformed header. Catching it
        here turns a per-request 500 into a clear boot-time failure.
        """
        missing: list[str] = []
        for name in ("notifications", "mapping", "authz", "iac"):
            svc: ServiceConfig = getattr(self.services, name)
            if svc.enabled and not svc.token:
                missing.append(f"services.{name} → ${svc.token_env}")
        if missing:
            raise ConfigError(
                "Enabled services have no bearer token in the environment: "
                + "; ".join(missing)
                + ". Set the listed env vars or flip the service to enabled: false."
            )
        return self

    @classmethod
    def load(cls, config_path: str | None = None) -> "SystemConfig":
        """Load from YAML if NEBULA_CONFIG points at a real file; else defaults.

        We require the path to be an existing *file* (not a directory) before
        attempting to parse it. This guards against the docker-compose
        foot-gun where mounting a missing host file silently creates an
        empty directory on the container side.
        """
        path = config_path or os.environ.get("NEBULA_CONFIG")
        if path and Path(path).is_file():
            with open(path) as f:
                data = yaml.safe_load(f) or {}
            return cls.model_validate(data)
        return cls()


# Module-level singleton used across the application.
system_config = SystemConfig.load()

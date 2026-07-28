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
import yaml
from typing import ClassVar
from pathlib import Path

from pydantic import BaseModel, Field, field_validator, model_validator

from src.shared.constants import GitProviderName, LLMProvider, ProviderPrefix


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
    # core/src/shared/constants.py::LLMProvider). Examples: CLAUDE_SONNET,
    # CLAUDE_HAIKU, GEMINI_FLASH. The factory resolves
    # the name to the full provider/model/region tuple at startup.
    model: LLMProvider = LLMProvider.CLAUDE_SONNET
    small_model: LLMProvider = LLMProvider.CLAUDE_HAIKU
    temperature: float = 0.1
    small_model_temperature: float = 0.1

    # Maps the model_id prefix to the env vars that hold the credentials for that provider.
    _PROVIDER_ENV: ClassVar[dict[str, dict[str, str]]] = {
        ProviderPrefix.VERTEX_AI.value: {
            "vertex_project": "VERTEXAI_PROJECT",
            "vertex_location": "VERTEXAI_LOCATION",
            "vertex_credentials": "GOOGLE_SA_SECRET",
        },
        ProviderPrefix.BEDROCK.value: {
            "aws_access_key_id": "AWS_ACCESS_KEY_ID",
            "aws_secret_access_key": "AWS_SECRET_ACCESS_KEY",
        },
        ProviderPrefix.OPENAI.value: {
            "api_key": "OPENAI_API_KEY",
        },
        ProviderPrefix.AZURE.value: {
            "api_key": "AZURE_API_KEY",
            "api_base": "AZURE_API_BASE",
            "api_version": "AZURE_API_VERSION",
        },
        ProviderPrefix.AZURE_AI.value: {
            "api_key": "AZURE_AI_API_KEY",
            "api_base": "AZURE_AI_API_BASE",
        },
    }

    @field_validator("model", "small_model", mode="before")
    @classmethod
    def _coerce_model(cls, v: str | LLMProvider):
        if isinstance(v, str):
            try:
                return LLMProvider[v]
            except KeyError:
                return LLMProvider(v)
        return v

    def get_provider_credentials(self, model_id: str) -> dict[str, str]:
        prefix = model_id.split("/")[0]
        if prefix not in self._PROVIDER_ENV:
            raise ConfigError(
                f"Unknown LLM provider prefix '{prefix}' in model_id '{model_id}'"
                + f". Supported prefixes: {list(self._PROVIDER_ENV.keys())}"
            )
        env_map = self._PROVIDER_ENV.get(
            prefix, self._PROVIDER_ENV[ProviderPrefix.VERTEX_AI.value]
        )
        credentials: dict[str, str] = {}
        for key, env_name in env_map.items():
            value = _env(env_name)
            if value:
                credentials[key] = value
        return credentials


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
    max_session_events_iteration: int = 2160  # 3h
    drift_group_operations: int = 8
    pull_request_readiness_seconds: int = 10


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
    Single-tenant by design (one PAT for all sessions).
    """

    # `provider` is GitProviderName enum names (see
    # core/src/shared/constants.py::GitProviderName). Examples: GITHUB,
    # AZURE_DEVOPS.
    provider: GitProviderName = GitProviderName.GITHUB
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

    @field_validator("provider", mode="before")
    @classmethod
    def _coerce_provider(cls, v: str | GitProviderName):
        if isinstance(v, str):
            # Accept enum name or value
            try:
                return GitProviderName[v]
            except KeyError:
                return GitProviderName(v)
        return v


class DatabaseConfig(BaseModel):
    """Credentials for Phoenix collector and Nebula postgres databases"""

    nebula_database_url_env: str = "NEBULA_SQL_DATABASE_URL"
    phoenix_database_url_env: str = "PHOENIX_SQL_DATABASE_URL"

    @property
    def nebula_database_url(self) -> str:
        return _env(self.nebula_database_url_env)

    @property
    def phoenix_database_url(self) -> str:
        return _env(self.phoenix_database_url_env)

    @model_validator(mode="after")
    def _assert_urls(self) -> DatabaseConfig:
        if not self.phoenix_database_url or not self.nebula_database_url:
            raise ConfigError("Missing env variable for phoenix or nebula databases")
        return self


class SystemConfig(BaseModel):
    environment: str = "development"  # development | staging | production
    oidc: OidcConfig = Field(default_factory=OidcConfig)
    admin: AdminConfig = Field(default_factory=AdminConfig)
    llm: LlmConfig = Field(default_factory=LlmConfig)
    services: ServicesConfig = Field(default_factory=ServicesConfig)
    orchestration: OrchestrationConfig = Field(default_factory=OrchestrationConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    telemetry: TelemetryConfig = Field(default_factory=TelemetryConfig)
    http: HttpConfig = Field(default_factory=HttpConfig)
    git: GitConfig = Field(default_factory=GitConfig)

    @model_validator(mode="after")
    def _assert_llm_credentials(self) -> SystemConfig:
        """Fail-fast on missing LLM credentials for the selected providers.

        Derives the required env vars from the ``model_id`` prefix of each
        selected model and checks them against ``LlmConfig._PROVIDER_ENV``.
        """
        missing: list[str] = []
        for field in ("model", "small_model"):
            model_id = getattr(self.llm, field).value["model_id"]
            prefix = model_id.split("/")[0]
            env_map = self.llm._PROVIDER_ENV.get(prefix, {})
            for _, env_name in env_map.items():
                if not _env(env_name):
                    missing.append(env_name)
        if missing:
            raise ConfigError(
                f"Missing LLM credentials: set env var(s) {', '.join(set(missing))}"
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
    def load(cls, config_path: str = "/etc/nebula/config.yaml") -> SystemConfig:
        """Load from YAML if NEBULA_CONFIG points at a real file; else defaults.

        We require the path to be an existing *file* (not a directory) before
        attempting to parse it. This guards against the docker-compose
        foot-gun where mounting a missing host file silently creates an
        empty directory on the container side.
        """
        path = os.environ.get("NEBULA_CONFIG") or config_path
        if path and Path(path).is_file():
            with open(path) as f:
                data = yaml.safe_load(f) or {}
            return cls.model_validate(data)

        return cls()


# Module-level singleton used across the application.
system_config = SystemConfig.load()

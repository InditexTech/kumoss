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
from typing import Any, Literal
import yaml
from pathlib import Path
from urllib.parse import urlparse

import litellm
from litellm.router import Router
from pydantic import BaseModel, Field, field_validator, model_validator

from src.shared.constants import (
    GitProviderName,
    ObjectStorageProvider,
)


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
    """LLM provider selection via LiteLLM Router.

    The core uses two model roles per workflow: ``model`` for high-quality
    reasoning and ``small_model`` for cheaper filler work.  Both are
    LiteLLM model-id strings (``provider/model``) that must match a
    ``model_name`` entry in ``model_list``.

    ``model_list`` follows the LiteLLM Router format.  Credential values
    use the ``os.environ/VAR_NAME`` syntax so secrets stay in env vars;
    the validator checks every such reference at boot.

    When ``model_list`` is empty, minimal entries are auto-generated and
    credentials are resolved by LiteLLM at call time (deferred failure).

    Refer to https://docs.litellm.ai/docs/providers for provider-specific
    credential keys and to https://models.litellm.ai/ for model IDs.
    """

    model: str = "azure_ai/claude-sonnet-5"
    temperature: float = 0.1
    max_output_tokens: int = 32000

    small_model: str = "azure_ai/claude-haiku-4-5"
    small_model_temperature: float = 0.1
    small_model_max_output_tokens: int = 32000

    model_list: list[dict[str, Any]] = Field(default_factory=list)

    @model_validator(mode="after")
    def _assert_llm_credentials(self) -> "LlmConfig":
        """Fail-fast on missing env vars referenced via os.environ/ in model_list."""
        missing: list[str] = []
        for entry in self.model_list:
            if litellm_params := entry.get("litellm_params", {}):
                model = litellm_params.get("model", "")
                result = litellm.validate_environment(model=model)

                if missing_keys := result.get("missing_keys"):
                    missing.extend(missing_keys)

        if missing:
            raise ConfigError(
                "LLM credentials missing from environment: "
                + "; ".join(missing)
                + ". Set the listed env vars or update llm.model_list in config.yaml."
            )
        return self

    def create_router(self) -> Router:
        if self.model_list:
            return Router(model_list=self.model_list)
        seen: set[str] = set()
        entries: list[dict[str, Any]] = []
        for model_id in (self.model, self.small_model):
            if model_id not in seen:
                seen.add(model_id)
                entries.append(
                    {
                        "model_name": model_id,
                        "litellm_params": {"model": model_id},
                    }
                )
        return Router(model_list=entries)


class ServiceConfig(BaseModel):
    """Configuration for a single microservice contract.

    ``token_env`` names the environment variable holding the bearer token
    the core sends with every call. Looking the token up indirectly
    keeps secrets out of this file.

    ``timeout`` is the per-request budget in seconds for outbound HTTP
    calls to the service. Every service call returns promptly (long
    work runs as asynchronous jobs the core polls), so this only needs
    to cover a single request/response round trip.
    """

    enabled: bool = False
    endpoint: str = ""
    token_env: str = ""
    timeout: float = 30.0

    @property
    def token(self) -> str:
        return _env(self.token_env)


class IacServiceConfig(ServiceConfig):
    """IaC service wiring plus its async-job polling knobs.

    The IaC service enqueues one terraform command per job and returns
    a job id immediately; the core then polls ``GET /v1/jobs/{job_id}``
    every ``job_poll_interval`` seconds until the job is terminal.
    ``job_timeout`` bounds the total wait for one job — it must cover
    both the FIFO queue wait (jobs on the same workspace run one at a
    time) and the command itself, so keep it above the service's own
    subprocess budget (2700s in the reference deployment). A validation
    run submits several jobs in sequence (init, validate, plan, and
    show when drift is requested), each with its own ``job_timeout``.
    """

    job_poll_interval: float = 5.0
    job_timeout: float = 3600.0


class ServicesConfig(BaseModel):
    notifications: ServiceConfig = Field(default_factory=ServiceConfig)
    mapping: ServiceConfig = Field(default_factory=ServiceConfig)
    authz: ServiceConfig = Field(default_factory=ServiceConfig)
    iac: IacServiceConfig = Field(default_factory=IacServiceConfig)


class OrchestrationConfig(BaseModel):
    """Iteration limits and batch sizes for the core's orchestration loops."""

    max_drift_reports: int = 3
    max_validation_iteration: int = 5
    max_tool_chain_executions: int = 70
    max_session_events_iteration: int = 2160  # 3h
    drift_group_operations: int = 8
    pull_request_readiness_seconds: int = 10
    enable_compliance_checker: bool = False


class PathsConfig(BaseModel):
    """Filesystem paths used by the core."""

    upload_folder: Path = Path("/workspaces")
    session_plan_filename: str = Field(
        default="session.plan", pattern=r"^[A-Za-z0-9._-]{1,128}$"
    )


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


class RedisConfig(BaseModel):
    """Connection settings for the Redis session store / cache.

    The URL is referenced indirectly via an env-var name so any password
    embedded in it stays out of the YAML. When the env var is unset the
    docker-compose service default is used, so the OSS stack boots without
    extra wiring.

    Timeouts are deliberately aggressive: Redis is a cache, so a slow or
    unreachable server should fail fast and let reads fall through to the
    database instead of stalling requests.
    """

    redis_url_env: str = "NEBULA_REDIS_URL"
    default_url: str = "redis://redis:6379/0"
    max_connections: int = 20
    socket_connect_timeout: float = 2.0
    socket_timeout: float = 2.0
    # Seconds a request may wait for a free pooled connection under a burst.
    pool_timeout: float = 2.0

    @property
    def redis_url(self) -> str:
        return _env(self.redis_url_env) or self.default_url


class StorageConfig(BaseModel):
    """Object storage for generated artifacts (reports, plans, code changes).

    The provider decides how endpoints are resolved (see the object-storage
    factory): RUSTFS — or any custom-endpoint S3-compatible server — uses
    both URLs below; S3 (real AWS S3) ignores them and lets boto3 build
    the regional default endpoint from ``region``; STORAGE_ACCOUNT (a
    public Azure storage account) points both URLs at the account blob
    endpoint ``https://<account>.blob.core.windows.net`` and derives the
    account name from ``endpoint_url`` (``bucket`` then names the blob
    container; ``region`` is ignored).

    Two endpoints exist because SigV4 binds the Host header: ``endpoint_url``
    is what the core's SDK calls hit from inside the compose network, while
    presigned GET URLs handed to the browser must be signed against the
    host the browser will actually fetch, ``public_endpoint_url``. Azure
    account-key SAS has no such Host binding, so for STORAGE_ACCOUNT the
    URLs only differ in emulator-style split setups.
    """

    # `provider` is ObjectStorageProvider enum names (see
    # core/src/shared/constants.py::ObjectStorageProvider).
    provider: ObjectStorageProvider = ObjectStorageProvider.RUSTFS
    bucket: str = "nebula-artifacts"
    endpoint_url: str = "http://object-storage:9000"
    public_endpoint_url: str = "http://localhost:9000"
    region: str = "us-east-1"
    access_key_env: str = "RUSTFS_ACCESS_KEY"
    secret_key_env: str = "RUSTFS_SECRET_KEY"
    account_key_env: str = "STORAGE_ACCOUNT_KEY"
    connect_timeout: float = 3.0
    read_timeout: float = 10.0
    max_attempts: int = 3  # botocore standard-mode retries
    presign_expiry_seconds: int = 172_800  # 48h

    @field_validator("provider", mode="before")
    @classmethod
    def _coerce_provider(cls, v: str | ObjectStorageProvider):
        if isinstance(v, str):
            # Accept enum name or value
            try:
                return ObjectStorageProvider[v]
            except KeyError:
                return ObjectStorageProvider(v)
        return v

    @property
    def access_key(self) -> str:
        default = "rustfsadmin" if self.provider is ObjectStorageProvider.RUSTFS else ""
        return _env(self.access_key_env, default)

    @property
    def secret_key(self) -> str:
        default = "rustfsadmin" if self.provider is ObjectStorageProvider.RUSTFS else ""
        return _env(self.secret_key_env, default)

    @property
    def account_key(self) -> str:
        return _env(self.account_key_env)

    @property
    def storage_account_name(self) -> str:
        """Account name derived from ``endpoint_url`` (STORAGE_ACCOUNT).

        The account is not configured separately — it is redundant with
        the endpoint. Accepted forms: ``https://<account>.blob.<domain>``
        (public clouds, sovereign clouds) and the emulator-style
        path form ``http://<host>:<port>/<account>``.
        """
        parsed = urlparse(self.endpoint_url)
        labels = (parsed.hostname or "").split(".")
        if len(labels) >= 2 and labels[1] == "blob":
            return labels[0]
        path = parsed.path.strip("/")
        if path and "/" not in path:
            return path
        raise ConfigError(
            "storage.endpoint_url must be an account blob endpoint "
            + "(https://<account>.blob.core.windows.net) when "
            + "storage.provider is STORAGE_ACCOUNT; cannot derive an "
            + f"account name from '{self.endpoint_url}'."
        )

    @model_validator(mode="after")
    def _assert_storage_account_config(self) -> StorageConfig:
        # Fail at boot, not on the first artifact write.
        if self.provider is ObjectStorageProvider.STORAGE_ACCOUNT:
            _ = self.storage_account_name  # raises when underivable
            if not self.account_key:
                raise ConfigError(
                    "storage.provider STORAGE_ACCOUNT requires env var "
                    + f"{self.account_key_env}."
                )
        return self

    @model_validator(mode="after")
    def _assert_presign_expiry(self) -> StorageConfig:
        # Floor: 30h > the 24h (+10% jitter) cached finished-session detail
        # that embeds these URLs. Ceiling: SigV4 refuses expiries over 7d.
        if not 108_000 <= self.presign_expiry_seconds <= 604_800:
            raise ConfigError(
                "storage.presign_expiry_seconds must be between 108000 (30h, "
                + "to outlive the cached session detail aggregate) and 604800 "
                + f"(the SigV4 7-day limit); got {self.presign_expiry_seconds}."
            )
        return self


class SystemConfig(BaseModel, frozen=True):
    environment: Literal["development", "staging", "production"] = (
        "development"  # development | staging | production
    )
    oidc: OidcConfig = Field(default_factory=OidcConfig)
    admin: AdminConfig = Field(default_factory=AdminConfig)
    llm: LlmConfig = Field(default_factory=LlmConfig)
    services: ServicesConfig = Field(default_factory=ServicesConfig)
    orchestration: OrchestrationConfig = Field(default_factory=OrchestrationConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    redis: RedisConfig = Field(default_factory=RedisConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    telemetry: TelemetryConfig = Field(default_factory=TelemetryConfig)
    http: HttpConfig = Field(default_factory=HttpConfig)
    git: GitConfig = Field(default_factory=GitConfig)

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

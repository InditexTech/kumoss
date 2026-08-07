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
from typing import Literal
import yaml
from typing import ClassVar
from pathlib import Path
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator, model_validator

from src.shared.constants import (
    GitProviderName,
    LLMProviderPrefix,
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
    """LLM provider selection + per-provider credential references.

    The core uses two models per workflow: a ``model`` for high-quality
    reasoning steps and a faster/cheaper ``small_model`` for filler work
    (status updates, classifiers, secondary calls). Both temperatures are
    deployer-tunable.

    Provider credentials are referenced indirectly via env-var names so
    nothing sensitive lives in the YAML.
    """

    # `model` and `small_model` are LiteLLM model_id strings with a
    # provider prefix. Examples: "vertex_ai/claude-sonnet-4-6",
    # "bedrock/claude-haiku-4-5@20251001", "openai/gpt-5".
    model: str = "vertex_ai/claude-sonnet-4-6"
    small_model: str = "vertex_ai/claude-haiku-4-5@20251001"
    temperature: float = 0.1
    small_model_temperature: float = 0.1
    model_max_tokens: int = 64000
    small_model_max_tokens: int = 32000

    # Maps the model_id prefix to the env vars that hold the credentials for that provider.
    _PROVIDER_ENV: ClassVar[dict[str, dict[str, str]]] = {
        LLMProviderPrefix.VERTEX_AI.value: {
            "vertex_project": "VERTEXAI_PROJECT",
            "vertex_location": "VERTEXAI_LOCATION",
            "vertex_credentials": "GOOGLE_SA_SECRET",
        },
        LLMProviderPrefix.GEMINI.value: {
            "api_key": "GEMINI_API_KEY",
        },
        LLMProviderPrefix.BEDROCK.value: {
            "aws_access_key_id": "AWS_ACCESS_KEY_ID",
            "aws_secret_access_key": "AWS_SECRET_ACCESS_KEY",
            "aws_region_name": "AWS_REGION_NAME",
            # Bearer token is passed as `api_key` to LiteLLM
            "api_key": "AWS_BEARER_TOKEN_BEDROCK",
        },
        LLMProviderPrefix.OPENAI.value: {
            "api_key": "OPENAI_API_KEY",
            "api_base": "OPENAI_API_BASE",
        },
        LLMProviderPrefix.AZURE.value: {
            "api_key": "AZURE_API_KEY",
            "api_base": "AZURE_API_BASE",
            "api_version": "AZURE_API_VERSION",
        },
        LLMProviderPrefix.AZURE_AI.value: {
            "api_key": "AZURE_AI_API_KEY",
            "api_base": "AZURE_AI_API_BASE",
        },
    }

    def get_provider_credentials(self, model_id: str) -> dict[str, str]:
        prefix = model_id.split("/")[0]
        if prefix not in self._PROVIDER_ENV:
            raise ConfigError(
                f"Unknown LLM provider prefix '{prefix}' in model_id '{model_id}'"
                + f". Supported prefixes: {list(self._PROVIDER_ENV.keys())}"
            )
        env_map = self._PROVIDER_ENV.get(
            prefix, self._PROVIDER_ENV[LLMProviderPrefix.VERTEX_AI.value]
        )
        credentials: dict[str, str] = {}
        for key, env_name in env_map.items():
            value = _env(env_name)
            if value:
                credentials[key] = value

        # Bedrock: bearer token (api_key) takes priority over access key / secret
        if prefix == LLMProviderPrefix.BEDROCK.value and "api_key" in credentials:
            credentials.pop("aws_access_key_id", None)
            credentials.pop("aws_secret_access_key", None)

        return credentials


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

    The IaC service enqueues terraform pipelines and returns a job id
    immediately; the core then polls ``GET /v1/jobs/{job_id}`` every
    ``job_poll_interval`` seconds until the job is terminal.
    ``job_timeout`` bounds the total wait for one job — it must cover
    both the FIFO queue wait (jobs on the same workspace run one at a
    time) and the pipeline itself, so keep it above the service's own
    subprocess budget (2700s in the reference deployment).
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
    def _assert_llm_credentials(self) -> SystemConfig:
        """Fail-fast on missing LLM credentials for the selected providers.

        Derives the required env vars from the ``model_id`` prefix of each
        selected model and checks them against ``LlmConfig._PROVIDER_ENV``.

        For Bedrock, the bearer token is an alternative to access key /
        secret — having either set is enough.
        """
        missing: list[str] = []
        for field in ("model", "small_model"):
            model_id = getattr(self.llm, field)
            prefix = model_id.split("/")[0]
            env_map = self.llm._PROVIDER_ENV.get(prefix, {})

            if prefix == LLMProviderPrefix.BEDROCK.value:
                has_bearer = bool(_env("AWS_BEARER_TOKEN_BEDROCK"))
                has_keys = bool(
                    _env("AWS_ACCESS_KEY_ID") and _env("AWS_SECRET_ACCESS_KEY")
                )
                if not has_bearer and not has_keys:
                    missing.append(
                        "AWS_BEARER_TOKEN_BEDROCK or (AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY)"
                    )
                if not _env("AWS_REGION_NAME"):
                    missing.append("AWS_REGION_NAME")
                continue

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

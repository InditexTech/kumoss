# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""System-wide configuration loaded from a YAML file.

Single source of truth for every deployment-tunable knob in the core.
Resolved at startup from the path in ``KUMOSS_CONFIG``; if unset or
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
from typing import Any, ClassVar
import yaml
from pathlib import Path
from urllib.parse import urlparse

import litellm
from litellm.router import Router
from pydantic import BaseModel, Field, field_validator, model_validator

from src.shared.constants import (
    Environment,
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
    """OIDC issuer settings for authenticating requests to the core.

    Blank ``issuer_url`` disables authentication entirely (dev default):
    every request acts as a local developer identity holding the top role
    of both groups. ``audience`` is an optional override for IdPs (e.g.
    Auth0) that issue tokens for a dedicated API identifier; when blank,
    ``client_id`` and ``api://{client_id}`` are accepted as the expected
    token audience. A ``{client_id}`` placeholder in ``scope`` is
    expanded at load time; when ``scope`` is left at its default and the
    issuer is Entra ID, ``api://{client_id}/.default`` is appended
    automatically so the access token is issued for this app instead of
    Microsoft Graph.
    """

    DEFAULT_OIDC_SCOPE: ClassVar[str] = "openid profile email"
    ENTRA_HOST: ClassVar[str] = "login.microsoftonline.com"

    issuer_url: str = ""
    client_id: str = ""
    audience: str = ""
    scope: str = DEFAULT_OIDC_SCOPE
    clock_skew_seconds: int = 60

    @model_validator(mode="after")
    def _validate_and_resolve(self) -> OidcConfig:
        if self.issuer_url and not self.client_id:
            raise ConfigError(
                "oidc.issuer_url is set but oidc.client_id is empty; "
                + "set oidc.client_id (and optionally oidc.audience) in config.yaml."
            )
        if (
            self.scope == self.DEFAULT_OIDC_SCOPE
            and urlparse(self.issuer_url).hostname == self.ENTRA_HOST
        ):
            self.scope = f"{self.DEFAULT_OIDC_SCOPE} api://{{client_id}}/.default"
        if "{client_id}" in self.scope:
            if not self.client_id:
                raise ConfigError(
                    "oidc.scope references {client_id} but oidc.client_id is empty."
                )
            self.scope = self.scope.replace("{client_id}", self.client_id)
        return self


class AdminConfig(BaseModel):
    """Bootstrap administrator.

    The user whose token email matches ``default_root_email`` is elevated
    to the top role of both groups at login time. Elevation is one-way:
    clearing this field later never demotes anyone.
    """

    default_root_email: str = ""


class LlmConfig(BaseModel):
    """LLM provider selection via LiteLLM Router.

    The core uses two model roles per workflow: ``model`` for high-quality
    reasoning and ``small_model`` for cheaper filler work.  Both are
    LiteLLM model-id strings (``provider/model``).  Credentials are
    resolved from the provider's standard env vars (see the provider
    tables at
    https://inditextech.github.io/kumoss/stable/main/reference/llm-providers/);
    the validator fails boot when litellm reports required env vars
    missing.

    ``temperature``, ``max_output_tokens`` and ``timeout`` apply to both
    roles. ``timeout`` is the per-request budget in seconds LiteLLM
    enforces on a single inference call (retries get a fresh budget);
    long reasoning or web-search calls need a generous value.

    ``model_list`` is an advanced escape hatch in the LiteLLM Router
    format (fallbacks, load balancing, custom credential env var names
    via ``os.environ/VAR_NAME``).  When non-empty it is passed to the
    Router verbatim, ``model`` / ``small_model`` must match its
    ``model_name`` entries, and boot validation runs against the listed
    entries instead of the two role models.

    Refer to https://docs.litellm.ai/docs/providers for provider-specific
    credential keys and to https://models.litellm.ai/ for model IDs.
    """

    model: str = "anthropic/claude-sonnet-5"
    small_model: str = "anthropic/claude-haiku-4-5"
    temperature: float = 0.1
    max_output_tokens: int = 32000
    timeout: float = Field(default=600.0, gt=0)

    model_list: list[dict[str, Any]] = Field(default_factory=list)

    def _effective_model_list(self) -> list[dict[str, Any]]:
        if self.model_list:
            return self.model_list
        return [
            {"model_name": model_id, "litellm_params": {"model": model_id}}
            for model_id in dict.fromkeys((self.model, self.small_model))
        ]

    @model_validator(mode="after")
    def _assert_llm_credentials(self) -> LlmConfig:
        """Fail-fast on env vars litellm requires for the configured models."""
        missing: list[str] = []
        for entry in self._effective_model_list():
            if litellm_params := entry.get("litellm_params", {}):
                model = litellm_params.get("model", "")
                result = litellm.validate_environment(model=model)

                if missing_keys := result.get("missing_keys"):
                    missing.extend(missing_keys)

        if missing := list(dict.fromkeys(missing)):
            raise ConfigError(
                "LLM credentials missing from environment: "
                + "; ".join(missing)
                + ". Set the listed env vars or configure llm.model_list in config.yaml."
            )
        return self

    def create_router(self) -> Router:
        return Router(model_list=self._effective_model_list())


class ServiceEndpointConfig(BaseModel):
    """Outbound HTTP wiring shared by every microservice contract.

    ``token_env`` names the environment variable holding the bearer token
    the core sends with every call. Looking the token up indirectly
    keeps secrets out of this file.

    ``timeout`` is the per-request budget in seconds for outbound HTTP
    calls to the service. Every service call returns promptly (long
    work runs as asynchronous jobs the core polls), so this only needs
    to cover a single request/response round trip.
    """

    endpoint: str = ""
    token_env: str = ""
    timeout: float = 30.0

    @property
    def token(self) -> str:
        return _env(self.token_env)


class ServiceConfig(ServiceEndpointConfig):
    """Configuration for an optional microservice contract.

    ``enabled: false`` skips the service entirely: the core never
    contacts it and answers those calls locally (or not at all).
    """

    enabled: bool = False


class IacServiceConfig(ServiceEndpointConfig):
    """IaC service wiring plus its async-job polling knobs.

    The IaC service is mandatory — without it the core cannot validate
    or apply anything — so this config deliberately has no ``enabled``
    flag: ``endpoint`` and ``token_env`` are always required and the
    service is always contacted.

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

    endpoint: str = "http://iac:8082"
    token_env: str = "KUMOSS_IAC_TOKEN"
    job_poll_interval: float = 5.0
    job_timeout: float = 3600.0

    @model_validator(mode="after")
    def _assert_endpoint(self) -> IacServiceConfig:
        if not self.endpoint:
            raise ConfigError(
                "services.iac.endpoint is empty; the IaC service is mandatory. "
                + "Point it at an implementation of the iac contract."
            )
        return self


class ServicesConfig(BaseModel):
    notifications: ServiceConfig = Field(default_factory=ServiceConfig)
    mapping: ServiceConfig = Field(default_factory=ServiceConfig)
    authz: ServiceConfig = Field(default_factory=ServiceConfig)
    iac: IacServiceConfig = Field(default_factory=IacServiceConfig)


class OrchestrationConfig(BaseModel):
    """Iteration limits and batch sizes for the core's orchestration loops."""

    max_drift_reports: int = 3
    max_validation_iteration: int = 8
    max_import_iteration: int = 5
    max_tool_agent_executions: int = 40
    max_session_events_iteration: int = 2160  # 3h
    drift_group_operations: int = 8
    pull_request_readiness_seconds: int = 10
    enable_compliance_checker: bool = False
    block_on_high_impact: bool = False


class PathsConfig(BaseModel):
    """Filesystem paths used by the core."""

    upload_folder: Path = Path("/workspaces")
    session_plan_filename: str = Field(
        default="session.plan", pattern=r"^[A-Za-z0-9._-]{1,128}$"
    )
    # Terraform merges only `*_override.tf` over the configuration, so any
    # other name would be a second backend block rather than a replacement.
    backend_override_filename: str = Field(
        default="backend_override.tf",
        pattern=r"^[A-Za-z0-9._-]{1,128}_override\.tf$",
    )


class TelemetryConfig(BaseModel):
    """Generic OTel telemetry knobs.

    ``collector_url`` is a base URL; the OTLP endpoint is computed from
    it at use time as ``f"{collector_url}v1/traces"``. The default is the
    Phoenix service of the bundled docker-compose stack; anything that
    speaks OTLP/HTTP works. Running the core outside docker needs an
    explicit ``http://localhost:6006/``.
    """

    collector_url: str = "http://phoenix:6006/"
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
    author_name: str = "Kumoss"
    author_email: str = "kumoss@noreply.invalid"

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
    """Credentials for Kumoss postgres database"""

    kumoss_database_url_env: str = "KUMOSS_SQL_DATABASE_URL"

    @property
    def kumoss_database_url(self) -> str:
        return _env(self.kumoss_database_url_env)

    @model_validator(mode="after")
    def _assert_urls(self) -> DatabaseConfig:
        if not self.kumoss_database_url:
            raise ConfigError("Missing env variable for kumoss database")
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

    redis_url_env: str = "KUMOSS_REDIS_URL"
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

    ``terraform_state_bucket`` names a second bucket (blob container on
    STORAGE_ACCOUNT) in the same store, holding the Terraform state of
    the projects Kumoss manages. It is separate from ``bucket`` so that
    state does not inherit whatever lifecycle or presign policy the
    artifacts bucket carries. Empty turns managed state off: no backend
    override is written and each workspace keeps the backend its own
    configuration declares. ``terraform_state_filename`` is the object
    name of each project's state under its ``project_id`` prefix.
    """

    # `provider` is ObjectStorageProvider enum names (see
    # core/src/shared/constants.py::ObjectStorageProvider).
    provider: ObjectStorageProvider = ObjectStorageProvider.RUSTFS
    bucket: str = "kumoss-artifacts"
    terraform_state_bucket: str = "kumoss-terraform-state"
    terraform_state_filename: str = Field(
        default="terraform.tfstate", pattern=r"^[A-Za-z0-9._-]{1,128}$"
    )
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
    def state_bucket(self) -> str:
        """The Terraform state bucket, or "" when state is not managed."""
        return self.terraform_state_bucket.strip()

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
    environment: Environment = "development"  # development | staging | production
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
        """Every service the core will call needs a bearer token resolved."""
        missing: list[str] = []
        if not self.services.iac.token:
            missing.append(f"services.iac → ${self.services.iac.token_env}")
        for name in ("notifications", "mapping", "authz"):
            svc: ServiceConfig = getattr(self.services, name)
            if svc.enabled and not svc.token:
                missing.append(f"services.{name} → ${svc.token_env}")
        if missing:
            raise ConfigError(
                "Services the core calls have no bearer token in the "
                + "environment: "
                + "; ".join(missing)
                + ". Set the listed env vars; the optional sidecars can also "
                + "be flipped to enabled: false (services.iac cannot — it is "
                + "mandatory)."
            )
        return self

    @classmethod
    def load(cls, config_path: str = "/etc/kumoss/config.yaml") -> SystemConfig:
        """Load from YAML if KUMOSS_CONFIG points at a real file; else defaults.

        We require the path to be an existing *file* (not a directory) before
        attempting to parse it. This guards against the docker-compose
        foot-gun where mounting a missing host file silently creates an
        empty directory on the container side.
        """
        path = os.environ.get("KUMOSS_CONFIG") or config_path
        if path and Path(path).is_file():
            with open(path) as f:
                data = yaml.safe_load(f) or {}
            return cls.model_validate(data)

        return cls()


# Module-level singleton used across the application.
system_config = SystemConfig.load()

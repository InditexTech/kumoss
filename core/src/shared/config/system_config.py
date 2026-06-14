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

The annotated reference is at ``examples/config.yaml``.
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import BaseModel, Field


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
    max_file_size_bytes: int = 10 * 1024 * 1024
    repo_cleanup_age_minutes: int = 30


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

    When all three fields resolve at boot, the application writes
    ~/.git-credentials and configures the `store` credential helper so
    subsequent `git push` calls authenticate without prompting. Single-
    tenant by design (one PAT for all sessions); per-user / per-repo
    credential forwarding is explicitly out of scope per the spec.
    """

    host: str = ""  # e.g. "github.com", "gitlab.com", "bitbucket.org"
    pat_user_env: str = ""  # env var name holding the username
    pat_token_env: str = ""  # env var name holding the personal access token

    # Commit author identity stamped on every Nebula-generated commit.
    # Always applied at boot regardless of whether credentials are set —
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
    environment: str = "development"  # dev | staging | production label

    oidc: OidcConfig = Field(default_factory=OidcConfig)
    admin: AdminConfig = Field(default_factory=AdminConfig)
    llm: LlmConfig = Field(default_factory=LlmConfig)
    services: ServicesConfig = Field(default_factory=ServicesConfig)
    orchestration: OrchestrationConfig = Field(default_factory=OrchestrationConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)
    telemetry: TelemetryConfig = Field(default_factory=TelemetryConfig)
    http: HttpConfig = Field(default_factory=HttpConfig)
    git: GitConfig = Field(default_factory=GitConfig)

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

# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Runtime configuration for the IaC reference implementation.

Two kinds of settings, kept apart on purpose:

- **Knobs** (this module's constants): deployment-tunable, not secret.
  Edit them here; they are baked into the image and are *not* read from
  the environment.
- **Environment** (``Config.from_env``): credentials and tokens, plus
  the deployment-specific ``TF_BACKEND_CONFIG`` and
  ``AWS_TERRAFORM_ROLE_NAME``. ``env.sample`` lists them.

Variables the service does not read but the engine and cloud CLIs do
(``AWS_DEFAULT_REGION``, ``AWS_PROFILE``,
``GOOGLE_BACKEND_IMPERSONATE_SERVICE_ACCOUNT``, ...) are neither: they
pass through the process environment unchanged and stay in ``.env``.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass

# --- Deployment-tunable knobs (no secrets) ---------------------------------

# Name or absolute path of the IaC engine CLI to invoke. The bundled
# image ships both OpenTofu and Terraform, so ``tofu`` (the default) or
# ``terraform``; any Terraform-compatible binary on PATH or at an
# absolute path also works. Availability is checked per request (503),
# not at startup.
IAC_BINARY = "terraform"

# Seconds a finished (succeeded/failed) job stays pollable at
# GET /v1/jobs/{job_id} before it is forgotten (polls then return 404).
# Jobs are kept in memory only, so a service restart also forgets them.
JOB_TTL_SECONDS = 3600

# Seconds a single engine command (init/plan/apply/...) may run before
# the job fails with a 504 error and the process is killed. 0 disables.
SUBPROCESS_TIMEOUT_SECONDS = 2700

# Log level for structured logging output. Engine stdout/stderr is never
# logged at any level: it is returned verbatim in the job result, and the
# job layer logs one terminal line per job with the exit code.
LOG_LEVEL = "INFO"

# Minutes between cloud CLI re-logins. Tokens are refreshed lazily by
# the next job once the interval has elapsed.
CLOUD_LOGIN_REFRESH_MIN = 45

# A re-login that fails is retried this many times (only the providers
# that failed), with exponential backoff starting at
# CLOUD_LOGIN_RETRY_DELAY_SEC seconds (2s, 4s, 8s by default). Only if
# every retry fails does the job fail (500); the following job tries
# again. Startup never retries: a broken credential aborts boot.
CLOUD_LOGIN_RETRIES = 3
CLOUD_LOGIN_RETRY_DELAY_SEC = 2.0


@dataclass(frozen=True)
class Config:
    """Resolved at startup: knobs from this module, secrets from the env.

    All cloud credential fields default to empty. A provider with *none*
    of its credential values set is skipped with an info log. A provider
    with *some* but not all of them set is a deployment mistake and
    aborts startup (``cloud_cli.CloudCli.validate_credentials``), as does
    a provider whose complete credentials the CLI rejects
    (``cloud_cli.CloudCli.login``).
    """

    # Environment (secrets and deployment-specific values).
    expected_token: str = ""
    azure_client_id: str = ""
    azure_client_secret: str = ""
    azure_tenant_id: str = ""
    google_credentials: str = ""
    backend_config: str = ""
    aws_terraform_role_name: str = ""
    # Static AWS keys. Both or neither: the CLI and the provider reject a
    # key ID without its secret, so a partial pair aborts startup.
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""

    # Knobs (module constants above).
    iac_binary: str = IAC_BINARY
    job_ttl: int = JOB_TTL_SECONDS
    subprocess_timeout: int = SUBPROCESS_TIMEOUT_SECONDS
    log_level: str = LOG_LEVEL
    cloud_login_refresh_min: int = CLOUD_LOGIN_REFRESH_MIN
    cloud_login_retries: int = CLOUD_LOGIN_RETRIES
    cloud_login_retry_delay_sec: float = CLOUD_LOGIN_RETRY_DELAY_SEC

    @classmethod
    def from_env(cls) -> "Config":
        """Read the environment-supplied values; knobs keep their defaults."""
        return cls(
            expected_token=os.environ.get("NEBULA_IAC_TOKEN", ""),
            azure_client_id=os.environ.get("ARM_CLIENT_ID", ""),
            azure_client_secret=os.environ.get("ARM_CLIENT_SECRET", ""),
            azure_tenant_id=os.environ.get("ARM_TENANT_ID", ""),
            google_credentials=os.environ.get("GOOGLE_CREDENTIALS", ""),
            backend_config=os.environ.get("TF_BACKEND_CONFIG", ""),
            aws_terraform_role_name=os.environ.get("AWS_TERRAFORM_ROLE_NAME", ""),
            aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID", ""),
            aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY", ""),
        )


def engine_available(binary: str) -> bool:
    return shutil.which(binary) is not None

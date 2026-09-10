# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Runtime configuration for the IaC reference implementation."""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path


class ConfigError(ValueError):
    """Raised when the resolved service configuration is unusable."""


@dataclass(frozen=True)
class Config:
    """Resolved from environment at startup.

    - ``expected_token``: bearer token clients must present. If unset,
      the service accepts any (or no) token (intended for local
      development).
    - ``iac_binary``: name or absolute path of the IaC engine CLI to
      invoke, from ``IAC_BINARY``. The bundled image ships both
      engines, so this is ``tofu`` (OpenTofu, the default) or
      ``terraform``; any Terraform-compatible engine works. Lookup
      falls back to PATH so the bundled image needs no override.
      Asserted to be resolvable at startup so a misconfigured image
      fails fast instead of on the first request.
    - ``job_ttl``: seconds a terminal job record stays pollable at
      `GET /v1/jobs/{job_id}` before it is swept (then 404).
    """

    expected_token: str
    iac_binary: str
    job_ttl: int = 3600

    def __post_init__(self) -> None:
        if not engine_available(self.iac_binary):
            raise ConfigError(
                f"IaC engine binary {self.iac_binary!r} not found on PATH. "
                f"Set IAC_BINARY to a binary on PATH or an absolute path."
            )

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            expected_token=os.environ.get("NEBULA_IAC_TOKEN", ""),
            iac_binary=os.environ.get("IAC_BINARY", "tofu"),
            job_ttl=int(os.environ.get("NEBULA_IAC_JOB_TTL") or "3600"),
        )


def engine_available(binary: str) -> bool:
    return shutil.which(binary) is not None


_GOOGLE_CREDENTIALS_ENV = "GOOGLE_CREDENTIALS"
_GOOGLE_APPLICATION_CREDENTIALS_ENV = "GOOGLE_APPLICATION_CREDENTIALS"


def materialize_google_credentials(home: Path | None = None) -> Path | None:
    """Turn ``GOOGLE_CREDENTIALS`` (a service-account key as JSON content)
    into a file, and point ``GOOGLE_APPLICATION_CREDENTIALS`` at it.

    Nebula accepts Google Cloud credentials in exactly one form:
    ``GOOGLE_CREDENTIALS`` holding the JSON key content, which is also
    what Terraform's/OpenTofu's ``google`` provider reads directly. The
    ``gcloud`` CLI and Google's client libraries — used ambiently by
    ``scope-resource-ids`` (see ``cloud_cli.py``) — only recognize
    Application Default Credentials, resolved from
    ``GOOGLE_APPLICATION_CREDENTIALS`` (a file path). This bridges the
    two: it writes the JSON to a private file at boot and sets that
    variable, so operators only ever configure ``GOOGLE_CREDENTIALS``
    and never manage a mounted key file themselves.

    A no-op returning ``None`` when ``GOOGLE_CREDENTIALS`` is unset.
    Raises ``ConfigError`` when it is set but not valid JSON, so a
    misconfigured credential fails at boot rather than on first use.
    ``home`` is overridable for tests.
    """
    raw = os.environ.get(_GOOGLE_CREDENTIALS_ENV, "")
    if not raw:
        return None

    try:
        json.loads(raw)
    except json.JSONDecodeError as e:
        raise ConfigError(f"{_GOOGLE_CREDENTIALS_ENV} is not valid JSON: {e}") from e

    creds_path = (home or Path.home()) / "google-credentials.json"
    # Create at 0600 from the first inode -- write_text()+chmod() would
    # briefly leave the file at the umask-default mode. Unlink any prior
    # boot's file first so a stale, more permissive inode is never reused.
    creds_path.unlink(missing_ok=True)
    fd = os.open(str(creds_path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(raw)
    os.environ[_GOOGLE_APPLICATION_CREDENTIALS_ENV] = str(creds_path)
    return creds_path

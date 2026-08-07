# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Runtime configuration for the IaC reference implementation."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass


class ConfigError(ValueError):
    """Raised when the resolved service configuration is unusable."""


@dataclass(frozen=True)
class Config:
    """Resolved from environment at startup.

    - ``expected_token``: bearer token clients must present. If unset,
      the service accepts any (or no) token (intended for local
      development).
    - ``terraform_binary``: name or absolute path of the terraform CLI to
      invoke. Lookup falls back to PATH so distros with ``terraform`` on
      PATH need no override. Asserted to be resolvable at startup so a
      misconfigured image fails fast instead of on the first request.
    - ``job_ttl``: seconds a terminal job record stays pollable at
      `GET /v1/jobs/{job_id}` before it is swept (then 404).
    """

    expected_token: str
    terraform_binary: str
    job_ttl: int = 3600

    def __post_init__(self) -> None:
        if not terraform_available(self.terraform_binary):
            raise ConfigError(
                f"terraform binary {self.terraform_binary!r} not found on PATH. "
                f"Install terraform or set TERRAFORM_BINARY to an absolute path."
            )

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            expected_token=os.environ.get("NEBULA_IAC_TOKEN", ""),
            terraform_binary=os.environ.get("TERRAFORM_BINARY", "terraform"),
            job_ttl=int(os.environ.get("NEBULA_IAC_JOB_TTL") or "3600"),
        )


def terraform_available(binary: str) -> bool:
    return shutil.which(binary) is not None

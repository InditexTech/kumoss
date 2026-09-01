# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Runtime configuration for the IaC reference implementation."""

from __future__ import annotations

import logging
import os
import shutil
from dataclasses import dataclass


class ConfigError(ValueError):
    """Raised when the resolved service configuration is unusable."""


# Friendly engine names → the actual CLI binary. OpenTofu's executable
# is literally ``tofu`` (that is the name every installer and the
# bundled image use), so accept the more recognizable ``opentofu`` as
# an alias for it. Values not listed here (``terraform``, an absolute
# path, a custom engine name) pass through unchanged.
_ENGINE_ALIASES = {"opentofu": "tofu"}


@dataclass(frozen=True)
class Config:
    """Resolved from environment at startup.

    - ``expected_token``: bearer token clients must present. If unset,
      the service accepts any (or no) token (intended for local
      development).
    - ``terraform_binary``: name or absolute path of the IaC engine CLI
      to invoke (OpenTofu by default; any Terraform-compatible engine
      works). Resolved from ``IAC_BINARY``, falling back to the
      deprecated ``TERRAFORM_BINARY``, then to ``opentofu`` (the
      default). The friendly name ``opentofu`` is mapped to the actual
      ``tofu`` executable via ``_ENGINE_ALIASES``. Lookup falls back to
      PATH so the bundled image needs no override. Asserted to be
      resolvable at startup so a misconfigured image fails fast instead
      of on the first request.
    - ``job_ttl``: seconds a terminal job record stays pollable at
      `GET /v1/jobs/{job_id}` before it is swept (then 404).
    """

    expected_token: str
    terraform_binary: str
    job_ttl: int = 3600

    def __post_init__(self) -> None:
        if not terraform_available(self.terraform_binary):
            raise ConfigError(
                f"IaC engine binary {self.terraform_binary!r} not found on PATH. "
                f"Install OpenTofu or set IAC_BINARY to an absolute path."
            )

    @classmethod
    def from_env(cls) -> "Config":
        binary = os.environ.get("IAC_BINARY")
        if not binary:
            legacy = os.environ.get("TERRAFORM_BINARY")
            if legacy:
                logging.getLogger("iac.config").warning(
                    "TERRAFORM_BINARY is deprecated; set IAC_BINARY instead."
                )
            binary = legacy or "opentofu"
        binary = _ENGINE_ALIASES.get(binary, binary)
        return cls(
            expected_token=os.environ.get("NEBULA_IAC_TOKEN", ""),
            terraform_binary=binary,
            job_ttl=int(os.environ.get("NEBULA_IAC_JOB_TTL") or "3600"),
        )


def terraform_available(binary: str) -> bool:
    return shutil.which(binary) is not None

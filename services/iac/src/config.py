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
    - ``allow_plan_without_creds``: when false (default), `terraform plan`
      is skipped if no cloud-credential env vars are present and the
      service returns success after `validate`. When true, `plan` is
      always attempted (may fail for credential reasons, surfaced in
      `feedback`).
    """

    expected_token: str
    terraform_binary: str
    allow_plan_without_creds: bool

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
            allow_plan_without_creds=os.environ.get(
                "NEBULA_IAC_ALLOW_PLAN_WITHOUT_CREDS", "false"
            ).lower()
            == "true",
        )


def have_cloud_credentials() -> bool:
    """Return True if any of the standard Terraform provider auth env vars are set.

    Conservative: any non-empty match is enough. Refine in your enterprise
    impl if you need stricter checks (e.g., assert tenant ID format).
    """
    candidates = (
        # Azure (azurerm provider)
        "ARM_CLIENT_ID",
        "ARM_CLIENT_SECRET",
        "ARM_TENANT_ID",
        "ARM_SUBSCRIPTION_ID",
        # GCP (google provider)
        "GOOGLE_APPLICATION_CREDENTIALS",
        "GOOGLE_CREDENTIALS",
        # AWS
        "AWS_ACCESS_KEY_ID",
        "AWS_PROFILE",
    )
    return any(os.environ.get(name) for name in candidates)


def terraform_available(binary: str) -> bool:
    return shutil.which(binary) is not None

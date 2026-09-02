# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Runtime configuration for the IaC reference implementation."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    """Resolved from environment at startup.

    All cloud credential fields default to empty and guard their
    respective login steps: missing values skip the provider with an
    info log rather than failing the service.
    """

    expected_token: str
    terraform_binary: str
    job_ttl: int = 3600

    azure_client_id: str = ""
    azure_client_secret: str = ""
    azure_tenant_id: str = ""
    google_application_credentials: str = ""
    google_credentials: str = ""
    aws_terraform_role_name: str = ""
    subprocess_timeout: int = 2700
    log_level: str = "INFO"
    cloud_login_refresh_min: int = 45

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            expected_token=os.environ.get("NEBULA_IAC_TOKEN", ""),
            terraform_binary=os.environ.get("TERRAFORM_BINARY", "terraform"),
            job_ttl=int(os.environ.get("NEBULA_IAC_JOB_TTL") or "3600"),
            azure_client_id=os.environ.get("ARM_CLIENT_ID", ""),
            azure_client_secret=os.environ.get("ARM_CLIENT_SECRET", ""),
            azure_tenant_id=os.environ.get("ARM_TENANT_ID", ""),
            google_application_credentials=os.environ.get(
                "GOOGLE_APPLICATION_CREDENTIALS", ""
            ),
            google_credentials=os.environ.get("GOOGLE_CREDENTIALS", ""),
            aws_terraform_role_name=os.environ.get("AWS_TERRAFORM_ROLE_NAME", ""),
            subprocess_timeout=int(
                os.environ.get("NEBULA_SUBPROCESS_TIMEOUT") or "2700"
            ),
            log_level=os.environ.get("LOG_LEVEL", "INFO"),
            cloud_login_refresh_min=int(
                os.environ.get("CLOUD_LOGIN_REFRESH_MIN") or "45"
            ),
        )


def terraform_available(binary: str) -> bool:
    return shutil.which(binary) is not None

# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Runtime configuration for the authz reference implementation."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    """Resolved from environment at startup.

    - ``expected_token``: bearer token clients must present. Empty
      disables auth (local-dev only).
    - ``role_store_path``: JSON file backing the user→roles map. Created
      on first write if missing.
    - ``root_admin_email``: when non-empty, the user with this email is
      granted the ``admin`` role on startup. The user record is created
      if it does not exist (id == email).
    - ``permissive_check``: when True, ``/v1/check`` returns
      ``authorized: true`` unconditionally. Default for the OSS
      reference impl. Enterprise impls override this with real cloud-
      access logic.
    """

    expected_token: str
    role_store_path: str
    root_admin_email: str
    permissive_check: bool

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            expected_token=os.environ.get("NEBULA_AUTHZ_TOKEN", ""),
            role_store_path=os.environ.get(
                "NEBULA_AUTHZ_ROLE_STORE", "/data/roles.json"
            ),
            root_admin_email=os.environ.get("NEBULA_AUTHZ_ROOT_ADMIN_EMAIL", ""),
            permissive_check=os.environ.get("NEBULA_AUTHZ_PERMISSIVE", "true").lower()
            == "true",
        )

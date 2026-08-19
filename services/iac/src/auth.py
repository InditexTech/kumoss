# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Bearer-token authentication for the IaC service."""

from __future__ import annotations

from fastapi import HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials

from .config import Config


def verify_bearer_token(
    config: Config, credentials: HTTPAuthorizationCredentials | None
) -> None:
    print(
        f"verify_bearer_token: config.expected_token={config.expected_token}, credentials={credentials}"
    )
    if not config.expected_token:
        return

    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header.",
        )

    if credentials.credentials != config.expected_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid bearer token.",
        )

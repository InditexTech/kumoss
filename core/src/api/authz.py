# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Policy Enforcement Point (PEP) — thin HTTP guard for AuthZEN decisions.

Most core write routes call ``authorize`` before mutating state.  It
delegates to ``AuthzServiceClient`` for the actual PDP evaluation and
maps the result to FastAPI exceptions.
"""

from fastapi import HTTPException

from src.clients.authz.models.action_name import ActionName
from src.domains.value_objects.token_claims import TokenClaims
from src.infrastructure.external.authz_service import AuthzServiceClient
from src.shared.constants import TerraformProvider
from src.shared.exceptions import ExceptionHandler


async def authorize(
    claims: TokenClaims,
    action: ActionName,
    *,
    scope_id: str,
    provider: TerraformProvider,
    repo_uri: str,
    iac_path: str | None = None,
) -> None:
    try:
        decision = await AuthzServiceClient().evaluate(
            claims,
            action,
            scope_id=scope_id,
            provider=provider,
            repo_uri=repo_uri,
            iac_path=iac_path,
        )
    except ExceptionHandler as e:
        raise HTTPException(status_code=e.error_code, detail=e.message) from e

    if not decision.allowed:
        raise HTTPException(
            status_code=403,
            detail=decision.reason_user or "Access denied",
        )

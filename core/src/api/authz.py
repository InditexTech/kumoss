# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Policy Enforcement Point (PEP) — thin HTTP guard for AuthZEN decisions.

Most core write routes call ``authorize`` before mutating state.  It
delegates to ``AuthzServiceClient`` for the actual PDP evaluation and
maps the result to FastAPI exceptions.
"""

from fastapi import HTTPException

from collections.abc import Sequence

from src.clients.authz.models.action_name import ActionName
from src.domains.value_objects.provider_scope import ProviderScope
from src.domains.value_objects.token_claims import TokenClaims
from src.infrastructure.external.authz_service import AuthzServiceClient
from src.shared.exceptions import ExceptionHandler


async def authorize(
    claims: TokenClaims,
    action: ActionName,
    *,
    scope_id: str,
    provider: str | None,
    repo_uri: str,
    root_module_path: str | None = None,
) -> None:
    try:
        decision = await AuthzServiceClient().evaluate(
            claims,
            action,
            scope_id=scope_id,
            provider=provider,
            repo_uri=repo_uri,
            root_module_path=root_module_path,
        )
    except ExceptionHandler as e:
        raise HTTPException(status_code=e.error_code, detail=e.message) from e

    if not decision.allowed:
        raise HTTPException(
            status_code=403,
            detail=decision.reason_user or "Access denied",
        )


async def authorize_providers(
    claims: TokenClaims,
    action: ActionName,
    *,
    providers: Sequence[ProviderScope],
    repo_uri: str,
    root_module_path: str | None = None,
) -> None:
    """Authorize ``action`` on every scope of a session's root module.

    One evaluation per provider that has a scope, all of which must allow.
    A module with no scoped provider (only ``random``, ``kubernetes``...)
    is evaluated once at the module level: empty resource id, no provider.
    """
    scoped = [p for p in providers if p.scope_id]
    if not scoped:
        await authorize(
            claims,
            action,
            scope_id="",
            provider=None,
            repo_uri=repo_uri,
            root_module_path=root_module_path,
        )
        return
    for pair in scoped:
        await authorize(
            claims,
            action,
            scope_id=pair.scope_id or "",
            provider=pair.provider,
            repo_uri=repo_uri,
            root_module_path=root_module_path,
        )

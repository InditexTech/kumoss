# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Authz microservice client used by core.

Wraps the generated `src.clients.authz` HTTP client behind a small,
async-friendly facade. Mirrors the pattern used by
`TerraformServiceValidator`: read endpoint+token from system_config,
construct a fresh `AuthenticatedClient` per call, degrade gracefully
when the service is disabled or unconfigured.

Surface:

- `AuthzServiceClient.check(cloud, project, environment, user_id)` →
  `CheckResult(authorized, portal_url, reason)`. Returns a permissive
  default when authz is disabled so existing callers keep working.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from src.clients.authz.api.check import check as check_op
from src.clients.authz.api.users import get_current_user as get_current_user_op
from src.clients.authz.client import AuthenticatedClient
from src.clients.authz.models.check_request import CheckRequest
from src.clients.authz.models.check_response import CheckResponse
from src.clients.authz.models.user import User
from src.clients.authz.types import UNSET, Unset
from src.shared.config import system_config
from src.shared.logger import logging


@dataclass(frozen=True)
class CheckResult:
    authorized: bool
    portal_url: str | None
    reason: str | None


def _from_unset(value: str | None | Unset) -> str | None:
    return None if isinstance(value, Unset) else value


class AuthzServiceClient:
    """Call the authz microservice via the generated HTTP client."""

    async def check(
        self,
        *,
        cloud: str,
        project: str,
        environment: str | None = None,
        user_id: str | None = None,
    ) -> CheckResult:
        cfg = system_config.services.authz
        if not cfg.enabled or not cfg.endpoint:
            logging.warning(
                "authz service is disabled or unconfigured; defaulting to "
                "authorized=True. Enable services.authz to enforce."
            )
            return CheckResult(
                authorized=True,
                portal_url=None,
                reason="authz service disabled in system config",
            )

        body = CheckRequest(
            cloud=cloud,
            project=project,
            environment=environment if environment else UNSET,
            user_id=user_id if user_id else UNSET,
        )
        client = AuthenticatedClient(
            base_url=cfg.endpoint,
            token=cfg.token,
            timeout=httpx.Timeout(15.0),
        )
        async with client as c:
            response = await check_op.asyncio(client=c, body=body)

        if not isinstance(response, CheckResponse):
            logging.error(
                f"authz service returned an unexpected response: {response!r}"
            )
            return CheckResult(
                authorized=False,
                portal_url=None,
                reason=f"authz call failed: {response!r}",
            )

        return CheckResult(
            authorized=response.authorized,
            portal_url=_from_unset(response.portal_url),
            reason=_from_unset(response.reason),
        )

    async def get_current_user(
        self,
        *,
        user_id: str | None,
        user_email: str | None = None,
    ) -> User | None:
        """Fetch the user record + roles for the caller from /v1/users/me.

        Returns ``None`` when authz is disabled/unconfigured or the call
        fails. Anonymous calls (``user_id`` is ``None``) reach the service
        too and may return an anonymous user record per the contract.
        """
        cfg = system_config.services.authz
        if not cfg.enabled or not cfg.endpoint:
            return None

        client = AuthenticatedClient(
            base_url=cfg.endpoint,
            token=cfg.token,
            timeout=httpx.Timeout(15.0),
        )
        async with client as c:
            response = await get_current_user_op.asyncio(
                client=c,
                x_user_id=user_id if user_id else UNSET,
                x_user_email=user_email if user_email else UNSET,
            )

        if not isinstance(response, User):
            logging.error(
                f"authz get_current_user returned an unexpected response: {response!r}"
            )
            return None
        return response

    async def is_admin(self, user_id: str | None) -> bool:
        """Convenience: True iff the caller holds the 'admin' role."""
        if not user_id:
            return False
        user = await self.get_current_user(user_id=user_id)
        if user is None:
            return False
        return "admin" in user.roles

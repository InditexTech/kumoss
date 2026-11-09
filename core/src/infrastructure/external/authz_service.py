# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Authz microservice client — AuthZEN 1.0 Access Evaluation.

Wraps the generated ``src.clients.authz`` HTTP client behind an
async-friendly adapter that accepts domain-level parameters, builds the
AuthZEN request, and returns a clean ``AuthzDecision``.  Follows the
``MappingServiceClient`` pattern: callers never touch wire-format types.
"""

from dataclasses import dataclass

import httpx

from src.clients.authz.api.evaluation import evaluate as evaluate_op
from src.clients.authz.client import AuthenticatedClient
from src.clients.authz.models.access_evaluation_request import (
    AccessEvaluationRequest,
)
from src.clients.authz.models.access_evaluation_response import (
    AccessEvaluationResponse,
)
from src.clients.authz.models.action import Action
from src.clients.authz.models.action_name import ActionName
from src.clients.authz.models.resource import Resource
from src.clients.authz.models.resource_properties import ResourceProperties
from src.clients.authz.models.resource_properties_provider import (
    ResourcePropertiesProvider,
)
from src.clients.authz.models.resource_type import ResourceType
from src.clients.authz.models.subject import Subject
from src.clients.authz.models.subject_properties import SubjectProperties
from src.clients.authz.models.subject_type import SubjectType
from src.clients.authz.types import UNSET, Unset
from src.domains.value_objects.token_claims import TokenClaims
from src.shared.config import system_config
from src.shared.constants import TerraformProvider
from src.shared.exceptions import ExceptionHandler
from src.shared.logger import logging


@dataclass(frozen=True)
class AuthzDecision:
    allowed: bool
    reason_user: str | None = None
    reason_admin: str | None = None


def _unwrap_reason(context, attr: str) -> str | None:
    if isinstance(context, Unset) or context is None:
        return None
    reason_obj = getattr(context, attr, None)
    if isinstance(reason_obj, Unset) or reason_obj is None:
        return None
    return reason_obj.additional_properties.get("en")


class AuthzServiceClient:
    """Call the authz PDP via the generated HTTP client."""

    async def evaluate(
        self,
        claims: TokenClaims,
        action: ActionName,
        *,
        scope_id: str,
        provider: TerraformProvider,
        repo_uri: str,
        iac_path: str | None = None,
    ) -> AuthzDecision:
        cfg = system_config.services.authz
        if not cfg.enabled:
            logging.warning(
                "authz service is disabled; defaulting to decision=True. "
                "Enable services.authz to enforce."
            )
            return AuthzDecision(allowed=True)
        if not cfg.endpoint:
            raise ExceptionHandler(
                "Authorization service is enabled but no endpoint is configured.",
                503,
            )

        props = dict(claims.properties)
        if not claims.email_verified:
            props.pop("email", None)
        subject_props = SubjectProperties.from_dict(props)

        resource_props = ResourceProperties(
            provider=ResourcePropertiesProvider(provider.value),
            repo_uri=repo_uri,
            iac_path=iac_path if iac_path else UNSET,
        )

        request = AccessEvaluationRequest(
            subject=Subject(
                type_=SubjectType.USER,
                id=claims.issuer,
                properties=subject_props,
            ),
            action=Action(name=action),
            resource=Resource(
                type_=ResourceType.SCOPE,
                id=scope_id,
                properties=resource_props,
            ),
        )

        client = AuthenticatedClient(
            base_url=cfg.endpoint,
            token=cfg.token,
            timeout=httpx.Timeout(cfg.timeout),
        )
        try:
            async with client as c:
                response = await evaluate_op.asyncio(client=c, body=request)
        except httpx.TimeoutException as e:
            raise ExceptionHandler(f"authz PDP timed out: {e}", 504) from e
        except httpx.RequestError as e:
            raise ExceptionHandler(f"authz PDP unreachable: {e}", 502) from e
        except (ValueError, TypeError, KeyError) as e:
            raise ExceptionHandler(
                f"authz PDP returned an unparseable response: {e!r}", 502
            ) from e

        if (
            not isinstance(response, AccessEvaluationResponse)
            or type(response.decision) is not bool
        ):
            raise ExceptionHandler(
                f"authz PDP returned an off-contract response: {response!r}",
                502,
            )

        reason_user = _unwrap_reason(response.context, "reason_user")
        reason_admin = _unwrap_reason(response.context, "reason_admin")

        if reason_admin:
            logging.warning("PDP deny reason (admin): %s", reason_admin)

        return AuthzDecision(
            allowed=response.decision,
            reason_user=reason_user,
            reason_admin=reason_admin,
        )

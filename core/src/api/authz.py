# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Policy Enforcement Point (PEP) helper for AuthZEN access evaluation.

Every core write route calls ``authorize`` before mutating state. It
builds the AuthZEN request from token claims + session/request context,
sends it to the PDP, and translates the response into FastAPI exceptions.
"""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import HTTPException

from src.clients.authz.models.access_evaluation_request import (
    AccessEvaluationRequest,
)
from src.clients.authz.models.action import Action
from src.clients.authz.models.action_name import ActionName
from src.clients.authz.models.request_context import RequestContext
from src.clients.authz.models.resource import Resource
from src.clients.authz.models.resource_properties import ResourceProperties
from src.clients.authz.models.resource_type import ResourceType
from src.clients.authz.models.subject import Subject
from src.clients.authz.models.subject_properties import SubjectProperties
from src.clients.authz.models.subject_type import SubjectType
from src.clients.authz.types import UNSET, Unset
from src.domains.value_objects.token_claims import TokenClaims
from src.shared.config import system_config
from src.shared.constants import TerraformProvider
from src.infrastructure.external.authz_service import AuthzServiceClient
from src.shared.exceptions import ExceptionHandler

logger = logging.getLogger(__name__)


async def authorize(
    claims: TokenClaims,
    action: str,
    *,
    user_id: int,
    scope_id: str,
    provider: TerraformProvider,
    repo_uri: str,
    iac_path: str | None = None,
    session_id: UUID | None = None,
    iteration: bool = False,
) -> None:
    cfg = system_config.services.authz
    if not cfg.enabled:
        return
    if not cfg.endpoint:
        raise HTTPException(
            status_code=503,
            detail="Authorization service is enabled but no endpoint is configured.",
        )

    props = dict(claims.properties)
    if not claims.email_verified:
        props.pop("email", None)
    subject_props = SubjectProperties.from_dict(props)

    resource_props = ResourceProperties(
        provider=provider,
        repo_uri=repo_uri,
        iac_path=iac_path if iac_path else UNSET,
    )

    context = RequestContext(
        session_id=str(session_id) if session_id else UNSET,
        iteration=iteration,
    )

    request = AccessEvaluationRequest(
        subject=Subject(
            type_=SubjectType.USER,
            id=str(user_id),
            properties=subject_props,
        ),
        action=Action(name=ActionName(action)),
        resource=Resource(
            type_=ResourceType.SCOPE,
            id=scope_id,
            properties=resource_props,
        ),
        context=context,
    )

    try:
        response = await AuthzServiceClient().evaluate(request)
    except ExceptionHandler as e:
        raise HTTPException(status_code=e.error_code, detail=e.message) from e

    if not response.decision:
        reason_user_msg = "Access denied"
        if not isinstance(response.context, Unset) and response.context is not None:
            reason_user = response.context.reason_user
            if not isinstance(reason_user, Unset) and reason_user is not None:
                en = reason_user.additional_properties.get("en")
                if en:
                    reason_user_msg = en
            reason_admin = response.context.reason_admin
            if not isinstance(reason_admin, Unset) and reason_admin is not None:
                admin_en = reason_admin.additional_properties.get("en")
                if admin_en:
                    logger.warning("PDP deny reason (admin): %s", admin_en)

        raise HTTPException(status_code=403, detail=reason_user_msg)

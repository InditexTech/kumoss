# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Authz microservice client — AuthZEN 1.0 Access Evaluation.

Wraps the generated ``src.clients.authz`` HTTP client behind a small,
async-friendly facade. Mirrors the pattern used by the IaC client:
read endpoint+token from system_config, construct a fresh
``AuthenticatedClient`` per call, degrade gracefully when the service
is disabled.
"""

from __future__ import annotations

import httpx

from src.clients.authz.api.evaluation import evaluate as evaluate_op
from src.clients.authz.client import AuthenticatedClient
from src.clients.authz.models.access_evaluation_request import (
    AccessEvaluationRequest,
)
from src.clients.authz.models.access_evaluation_response import (
    AccessEvaluationResponse,
)
from src.shared.config import system_config
from src.shared.exceptions import ExceptionHandler
from src.shared.logger import logging


class AuthzServiceClient:
    """Call the authz PDP via the generated HTTP client."""

    async def evaluate(
        self, request: AccessEvaluationRequest
    ) -> AccessEvaluationResponse:
        cfg = system_config.services.authz
        if not cfg.enabled or not cfg.endpoint:
            logging.warning(
                "authz service is disabled or unconfigured; defaulting to "
                "decision=True. Enable services.authz to enforce."
            )
            return AccessEvaluationResponse(decision=True)

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

        if not isinstance(response, AccessEvaluationResponse):
            raise ExceptionHandler(
                f"authz PDP returned an off-contract response: {response!r}",
                502,
            )

        return response

# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""ITerraformValidator implementation that delegates to the IaC service.

This is the OSS-default validator. It calls the IaC microservice
(contracts/openapi/iac.v1.yaml) over HTTP using the generated
client. The service operates on a workspace path that must be visible
to it; the docker-compose setup mounts a shared volume into both the
core and the IaC service so that paths line up.
"""

from __future__ import annotations

from pathlib import Path
from typing import override

import httpx

from src.clients.iac.api.validate import validate as validate_op
from src.clients.iac.client import AuthenticatedClient
from src.clients.iac.models.validate_request import ValidateRequest
from src.clients.iac.models.validate_response import ValidateResponse
from src.clients.iac.types import UNSET
from src.domains.dto import TerraformValidationDTO
from src.domains.interfaces.terraform_validator_interface import ITerraformValidator
from src.domains.services.session_service import SessionService
from src.domains.services.tracer_service import trace_terraform
from src.shared.config import system_config
from src.shared.constants import SessionStatus
from src.shared.logger import logging
from src.shared.exceptions import ExceptionHandler


class TerraformServiceValidator(ITerraformValidator):
    """Validate by calling the IaC microservice."""

    def __init__(
        self,
        workspace_path: Path,
        session_service: SessionService,
    ):
        self.__workspace_path = workspace_path
        self.__session_svc = session_service

    @trace_terraform
    @override
    async def validate(
        self,
        branch: str,
        targets: list[str],
        get_drift: bool = False,
    ) -> TerraformValidationDTO:
        await self.__session_svc.update_status(
            msg="Waiting for infrastructure as code to be validated.",
            status=SessionStatus.VALIDATING,
        )

        cfg = system_config.services.iac
        if not cfg.enabled or not cfg.endpoint:
            raise ExceptionHandler(
                message="IaC service is disabled or has no endpoint; cannot validate. "
                + "Enable services.iac in the system config.",
                error_code=500,
            )

        client = AuthenticatedClient(
            base_url=cfg.endpoint,
            token=cfg.token,
            timeout=httpx.Timeout(cfg.timeout),
        )
        body = ValidateRequest(
            workspace_path=str(self.__workspace_path),
            branch=branch if branch else UNSET,
            targets=targets,
            get_drift=get_drift,
        )
        try:
            async with client as c:
                response = await validate_op.asyncio(client=c, body=body)
        except httpx.TimeoutException as e:
            raise ExceptionHandler(f"IaC service timed out: {e}", 504) from e
        except httpx.RequestError as e:
            raise ExceptionHandler(f"IaC service unreachable: {e}", 502) from e

        if not isinstance(response, ValidateResponse):
            raise ExceptionHandler(
                f"IaC service returned an unexpected response: {response!r}", 502
            )
        if response.validation and response.feedback:
            logging.warning(response.feedback)
        return TerraformValidationDTO(
            validation=response.validation,
            feedback=response.feedback,
            terraform_plan=response.terraform_plan,
            terraform_targets=list(response.terraform_targets),
        )

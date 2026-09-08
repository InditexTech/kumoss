# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from collections.abc import Awaitable
from typing import Callable

from src.domains.dto import TerraformValidationDTO
from src.domains.entities import History, SessionContext
from src.domains.interfaces import ITerraform
from src.domains.services import (
    ArtifactStorageService,
    TerraformValidationService,
    TaskService,
)
from src.domains.value_objects import Conventions
from src.shared.constants import ContentType
from src.shared.logger import logging


class TerraformDriftService:
    def __init__(
        self,
        session_context: SessionContext,
        validation_service: TerraformValidationService,
        validator_provider: ITerraform,
        split_service: TaskService,
        artifact_service: ArtifactStorageService,
    ):
        self.__ctx = session_context
        self.__validation_svc = validation_service
        self.__validator_prv = validator_provider
        self.__split_svc = split_service
        self.__artifact_svc = artifact_service

    async def detect_and_resolve_drift(
        self,
        targets: list[str],
        conventions: Conventions,
        max_iterations: int,
        validator: Callable[[History], Awaitable[TerraformValidationDTO]],
    ) -> TerraformValidationDTO:
        validation = TerraformValidationDTO.empty()

        for i in range(max_iterations):
            logging.debug(f"Drift report no: {i + 1}/{max_iterations}")

            # Generate drift JSON report
            validation = await self.__validator_prv.validate(
                targets=targets,
                get_drift=True,
            )

            if validation.terraform_plan:
                _ = await self.__artifact_svc.store_terraform_plan(
                    session_id=self.__ctx.id,
                    round_id=self.__ctx.round_id,
                    targets=targets,
                    content=validation.terraform_plan,
                    content_type=ContentType.TEXT,
                    is_drift=False,
                )

            if validation.feedback:
                _ = await self.__artifact_svc.store_terraform_plan(
                    session_id=self.__ctx.id,
                    round_id=self.__ctx.round_id,
                    targets=targets,
                    content=validation.feedback,
                    content_type=ContentType.TEXT,
                    is_drift=True,
                )

            # break if drift validation is successful
            if validation.validation:
                break

            # Split Task into different operations
            operations: list[list[str]] = await self.__split_svc.split_task(
                task=validation.feedback,
            )

            for idx, group_ops in enumerate(operations):
                logging.debug(f"Operation {idx + 1}/{len(operations)}: {group_ops}")
                _ = await self.__validation_svc.generate_and_validate(
                    q=str(group_ops),
                    ctx=self.__ctx,
                    conventions=conventions,
                    include_forbidden_actions=False,
                    validator=validator,
                )
        if validation.validation:
            logging.warning("Drift pre-check completed, resources are synchronized")
        else:
            logging.warning(
                f"Drift resolution completed but issues remain: {validation.feedback}"
            )

        return validation

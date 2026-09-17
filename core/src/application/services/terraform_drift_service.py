# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from src.domains.dto import TerraformValidationDTO
from src.domains.entities import History, SessionContext
from src.domains.interfaces import ITerraform
from src.domains.services import (
    ArtifactStorageService,
    TerraformValidationService,
    TaskService,
)
from src.domains.value_objects import Conventions
from src.shared.constants import ContentType, OperationType
from src.shared.logger import logging


class TerraformDriftService:
    def __init__(
        self,
        session_context: SessionContext,
        validation_service: TerraformValidationService,
        terraform_service: ITerraform,
        split_service: TaskService,
        artifact_service: ArtifactStorageService,
    ):
        self.__ctx = session_context
        self.__validation_svc = validation_service
        self.__terraform_svc = terraform_service
        self.__split_svc = split_service
        self.__artifact_svc = artifact_service

    async def detect_and_resolve_drift(
        self,
        filter_session_changes: bool,
        targets: list[str],
        conventions: Conventions,
        max_iterations: int,
    ) -> TerraformValidationDTO:
        validation = TerraformValidationDTO.empty()

        async def validator(history: History) -> TerraformValidationDTO:
            return await self.__terraform_svc.validate(
                targets=targets,
                get_drift=False,
            )

        for i in range(max_iterations):
            logging.debug(f"Drift report no: {i + 1}/{max_iterations}")

            validation = await self.__terraform_svc.validate(
                targets=targets,
                get_drift=True,
            )

            await self.__upload_artifacts(validation, targets)

            if validation.validation:
                break

            operations: list[list[str]] = await self.__split_svc.split_task(
                task=validation.feedback,
            )
            if filter_session_changes:
                operations = await self.__split_svc.filter_reconciliation(
                    operations=operations,
                )
                if not operations:
                    logging.warning(
                        "Drift pre-check completed, remaining drift corresponds to session changes"
                    )
                    return validation

            for idx, group_ops in enumerate(operations):
                logging.debug(f"Operation {idx + 1}/{len(operations)}: {group_ops}")
                _ = await self.__validation_svc.generate_and_validate(
                    q=str(group_ops),
                    ctx=self.__ctx,
                    conventions=conventions,
                    include_forbidden_actions=False,
                    operation_type=OperationType.DRIFT,
                    validator=validator,
                )
        if validation.validation:
            logging.warning("Drift pre-check completed, resources are synchronized")
        else:
            logging.warning(
                f"Drift resolution completed but issues remain: {validation.feedback}"
            )

        return validation

    async def __upload_artifacts(
        self,
        validation: TerraformValidationDTO,
        targets: list[str],
    ) -> None:
        if validation.feedback:
            _ = await self.__artifact_svc.store_terraform_plan(
                session_id=self.__ctx.id,
                round_id=self.__ctx.round_id,
                targets=targets,
                content=validation.feedback,
                content_type=ContentType.TEXT,
                is_drift=True,
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

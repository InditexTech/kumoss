# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from src.domains.dto import TerraformValidationDTO
from src.domains.entities import SessionContext
from src.domains.interfaces import ITerraformValidator
from src.domains.services import (
    ArtifactStorageService,
    TerraformValidationService,
    TaskSplitService,
)
from src.domains.value_objects import Conventions
from src.shared.logger import logging


class TerraformDriftService:
    def __init__(
        self,
        session_context: SessionContext,
        validation_service: TerraformValidationService,
        validator_provider: ITerraformValidator,
        split_service: TaskSplitService,
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
    ) -> TerraformValidationDTO:
        validation = TerraformValidationDTO.empty()

        for i in range(max_iterations):
            logging.debug(f"Drift report no: {i + 1}/{max_iterations}")

            # Generate drift JSON report
            validation = await self.__validator_prv.validate(
                branch=self.__ctx.branch_name,
                targets=targets,
                get_drift=True,
            )

            if validation.terraform_plan:
                _ = await self.__artifact_svc.store_terraform_plan(
                    session_id=self.__ctx.id,
                    round_id=self.__ctx.round_id,
                    targets=targets,
                    content=validation.terraform_plan,
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
                    history=self.__ctx.history,
                    branch_name=self.__ctx.branch_name,
                    conventions=conventions,
                    include_forbidden_actions=False,
                )
        if validation:
            logging.warning("Drift pre-check completed, resources are synchronized")
        else:
            logging.warning(
                f"Drift resolution completed but issues remain: {validation.feedback}"
            )

        return validation

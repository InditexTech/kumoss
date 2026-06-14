# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from src.domains.dto import TerraformValidationDTO
from src.domains.entities.history import History
from src.domains.interfaces import ITerraformValidator
from src.domains.services import (
    TerraformValidationService,
    TaskSplitService,
)
from src.domains.services.database_service import DatabaseService
from src.shared.logger import logging


class TerraformDriftService:
    def __init__(
        self,
        validation_service: TerraformValidationService,
        validator_provider: ITerraformValidator,
        split_service: TaskSplitService,
    ):
        self.__validation_svc = validation_service
        self.__validator_prv = validator_provider
        self.__split_svc = split_service

    async def detect_and_resolve_drift(
        self,
        branch: str,
        targets: list[str],
        history: History,
        max_iterations: int,
    ) -> TerraformValidationDTO:
        validation = TerraformValidationDTO.empty()

        for i in range(max_iterations):
            logging.debug(f"Drift report no: {i + 1}/{max_iterations}")

            # Generate drift JSON report
            validation = await self.__validator_prv.validate(
                branch=branch,
                targets=targets,
                get_drift=True,
            )

            # Guardamos el terraform plan del drift
            if validation.terraform_plan:
                await DatabaseService.upload_artifact(
                    content=validation.terraform_plan,
                    artifact_type="terraform_plan",
                    phase="drift",
                    terraform_targets=validation.terraform_targets,
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
                    query=str(group_ops),
                    history=history,
                    include_forbidden_actions=False,
                )

        return validation

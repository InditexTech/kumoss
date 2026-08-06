# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from dataclasses import dataclass

from src.domains.entities import SessionContext
from src.domains.interfaces import IFileSystem
from src.domains.interfaces.terraform_validator_interface import ITerraformValidator
from src.domains.interfaces.git_interface import IGit
from src.domains.services import ArtifactStorageService
from src.domains.services.llm_service import LLMOrchestrationService
from src.domains.services.template_service import TemplateOrchestrationService
from src.domains.services.terraform_target_service import TerraformTargetService
from src.domains.services.tool_service import ToolOrchestrationService
from src.domains.dto import TerraformValidationDTO, ToolResultDTO
from src.domains.value_objects import Conventions
from src.shared.config import system_config
from src.shared.constants import ContentType, PromptsLibrary, ToolContext
from src.shared.logger import logging


@dataclass
class ValidationState:
    max_tries: int
    count: int


class TerraformValidationService:
    def __init__(
        self,
        validator: ITerraformValidator,
        git: IGit,
        files: IFileSystem,
        template_service: TemplateOrchestrationService,
        llm_service: LLMOrchestrationService,
        tool_orchestration_service: ToolOrchestrationService,
        target_service: TerraformTargetService,
        artifact_service: ArtifactStorageService,
    ):
        self.__validator = validator
        self.__git = git
        self.__files = files
        self.__template_svc = template_service
        self.__llm_svc = llm_service
        self.__tool_orchestration = tool_orchestration_service
        self.__target_svc = target_service
        self.__artifact_svc = artifact_service
        self.__count: int = 0

    async def __upload_changed_files(
        self, ctx: SessionContext, file_names: list[str]
    ) -> None:
        for name in file_names:
            content = self.__files.read_file(name)
            _ = await self.__artifact_svc.store_code_change(
                session_id=ctx.id,
                round_id=ctx.round_id,
                file_name=name,
                content=content,
                content_type=ContentType.TEXT,
            )

    async def generate_and_validate(
        self,
        q: str,
        ctx: SessionContext,
        conventions: Conventions,
        include_forbidden_actions: bool,
    ) -> TerraformValidationDTO:
        """
        Execute the terraform generation and validation cycle using tool calls

        :param query: User query
        :param history: task conversation history
        :return: last validation state ValidationDTO
        """
        first_q = q
        validation = TerraformValidationDTO.empty()
        local_history = ctx.history.deepcopy()
        while (
            not validation.validation
            and self.__count < system_config.orchestration.max_validation_iteration
        ):
            self.__count += 1
            logging.debug(
                f"Validation service {self.__count}/{system_config.orchestration.max_validation_iteration}"
            )

            task_complete: ToolResultDTO = await self.__llm_svc.generate(
                query=q,
                tools=self.__tool_orchestration.get_available_tools(
                    contexts=[
                        ToolContext.EXTERNAL_INFORMATION,
                        ToolContext.FILE_OPERATIONS,
                        ToolContext.WORKSPACE_INSPECTION,
                    ]
                ),
                sentinel_tool=self.__tool_orchestration.get_sentinel_tool(
                    context=ToolContext.GENERAL_TASK_COMPLETION,
                ),
                prompt=await self.__template_svc.render(
                    prompt=PromptsLibrary.IAC_GENERATOR,
                    resources=conventions.templates,
                    abbreviations=conventions.abbreviations,
                    include_forbidden_actions=include_forbidden_actions,
                ),
                history=local_history,
            )

            local_history.append_turn(q, task_complete.result.get("summary"))

            await self.__upload_changed_files(
                ctx, await self.__git.get_changed_files("AM")
            )
            await self.__git.commit_and_push(ctx.branch_name)

            validation = await self.__validator.validate(
                branch=ctx.branch_name,
                targets=await self.__target_svc.generate(q, local_history),
            )
            _ = await self.__artifact_svc.store_terraform_plan(
                session_id=ctx.id,
                round_id=ctx.round_id,
                targets=validation.terraform_targets,
                content=validation.terraform_plan,
                content_type=ContentType.TEXT,
            )

            q = validation.feedback

        ctx.history.append_turn(first_q, local_history.get_last_turn().assistant)
        return validation

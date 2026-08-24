# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from collections.abc import Awaitable
from dataclasses import dataclass
from typing import Callable

from src.domains.entities import History, SessionContext
from src.domains.interfaces import IFileSystem
from src.domains.interfaces.git_interface import IGit
from src.domains.services import ArtifactStorageService, SessionService
from src.domains.services.llm_service import LLMOrchestrationService
from src.domains.services.template_service import TemplateOrchestrationService
from src.domains.services.tool_service import ToolOrchestrationService
from src.domains.dto import TerraformValidationDTO, ToolResultDTO
from src.domains.value_objects import Conventions
from src.shared.config import system_config
from src.shared.constants import ContentType, PromptsLibrary, SessionStatus, ToolContext
from src.shared.logger import logging
from src.shared.exceptions import ExceptionHandler


@dataclass
class ValidationState:
    max_tries: int
    count: int


class TerraformValidationService:
    def __init__(
        self,
        git: IGit,
        files: IFileSystem,
        session_service: SessionService,
        template_service: TemplateOrchestrationService,
        llm_service: LLMOrchestrationService,
        tool_orchestration_service: ToolOrchestrationService,
        artifact_service: ArtifactStorageService,
    ):
        self.__git = git
        self.__files = files
        self.__session_svc = session_service
        self.__template_svc = template_service
        self.__llm_svc = llm_service
        self.__tool_orchestration = tool_orchestration_service
        self.__artifact_svc = artifact_service
        self.__count: int = 0

    async def __upload_changed_files(self, ctx: SessionContext) -> None:
        async def __upload(name: str, content: str, **metadata: str) -> None:
            _ = await self.__artifact_svc.store_code_change(
                session_id=ctx.id,
                round_id=ctx.round_id,
                file_name=name,
                content=content,
                content_type=ContentType.TEXT,
                metadata=metadata,
            )

        tracked_file_names: list[str] = await self.__git.get_changed_files(
            working_tree=True,
            diff_filter="AM",
        )
        for name in tracked_file_names:
            content = await self.__git.show_diff(
                working_tree=True,
                full_content=True,
                file_path=name,
            )
            await __upload(name, content, new_file="false")

        untracked_file_names: list[str] = await self.__git.get_untracked_files()
        for name in untracked_file_names:
            try:
                content = self.__files.read_file(name)
            except ExceptionHandler as e:
                logging.warning(f"Error reading file '{name}': {e.message}")
                continue
            await __upload(name, content, new_file="true")

    def __tool_contexts(self, contexts: list[ToolContext]) -> list[ToolContext]:
        if system_config.compliance.enabled:
            contexts.append(ToolContext.INLINE_COMPLIANCE)
        return contexts

    async def generate_and_validate(
        self,
        q: str,
        ctx: SessionContext,
        conventions: Conventions,
        include_forbidden_actions: bool,
        validator: Callable[[History], Awaitable[TerraformValidationDTO]],
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
            _ = await self.__session_svc.update_status(
                msg=q,
                prompt=await self.__template_svc.render(PromptsLibrary.STATUS_UPDATE),
                status=SessionStatus.GENERATING,
                history=local_history,
            )

            task_complete: ToolResultDTO = await self.__llm_svc.generate(
                query=q,
                tools=self.__tool_orchestration.get_available_tools(
                    contexts=self.__tool_contexts([
                        ToolContext.EXTERNAL_INFORMATION,
                        ToolContext.FILE_OPERATIONS,
                        ToolContext.WORKSPACE_INSPECTION,
                    ])
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

            await self.__upload_changed_files(ctx)
            await self.__git.commit_and_push(ctx.branch_name)

            _ = await self.__session_svc.update_status(
                msg="Waiting for infrastructure as code to be validated.",
                prompt=await self.__template_svc.render(PromptsLibrary.STATUS_UPDATE),
                status=SessionStatus.VALIDATING,
                history=local_history,
            )
            validation = await validator(local_history)
            if validation.terraform_plan:
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

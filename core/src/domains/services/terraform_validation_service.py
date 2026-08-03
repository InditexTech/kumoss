# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from dataclasses import dataclass

from src.domains.entities import SessionContext
from src.domains.interfaces.terraform_validator_interface import ITerraformValidator
from src.domains.interfaces.git_interface import IGit
from src.domains.services.llm_service import LLMOrchestrationService
from src.domains.services.session_service import SessionService
from src.domains.services.template_service import TemplateOrchestrationService
from src.domains.services.terraform_target_service import TerraformTargetService
from src.domains.services.tool_service import ToolOrchestrationService
from src.domains.dto import TerraformValidationDTO, ToolResultDTO
from src.shared.config import system_config
from src.shared.constants import PromptsLibrary, SessionStatus, ToolContext
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
        template_service: TemplateOrchestrationService,
        llm_service: LLMOrchestrationService,
        session_service: SessionService,
        tool_orchestration_service: ToolOrchestrationService,
        target_service: TerraformTargetService,
    ):
        self.__validator = validator
        self.__git = git
        self.__template_svc = template_service
        self.__llm_svc = llm_service
        self.__session_svc = session_service
        self.__tool_orchestration = tool_orchestration_service
        self.__target_svc = target_service

    async def generate_and_validate(
        self,
        query: str,
        ctx: SessionContext,
        include_forbidden_actions: bool,
    ) -> TerraformValidationDTO:
        """
        Execute the terraform generation and validation cycle using tool calls

        :param query: User query
        :param history: task conversation history
        :return: last validation state ValidationDTO
        """
        validation_state = ValidationState(
            max_tries=system_config.orchestration.max_validation_iteration,
            count=0,
        )
        validation_dto = TerraformValidationDTO.empty()
        local_history = ctx.history.deepcopy()
        while (
            not validation_dto.validation
            and validation_state.count < validation_state.max_tries
        ):
            validation_state.count += 1
            logging.debug(validation_state)

            templates, abbreviations = await self.__template_svc.compose_template(
                query=query,
                history=ctx.history,
            )
            chain_result: ToolResultDTO = await self.__llm_svc.generate(
                query=query,
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
                    resources=templates,
                    abbreviations=abbreviations,
                    include_forbidden_actions=include_forbidden_actions,
                ),
                history=local_history,
            )
            local_history.append_turn(query, str(chain_result.result))
            # summary: str | None = chain_result.result.get("summary")
            # self.__session_svc.append_summary(summary) if summary else None

            await self.__session_svc.update_status(
                msg=query,
                prompt=await self.__template_svc.render(PromptsLibrary.STATUS_UPDATE),
                status=SessionStatus.GENERATING,
                history=local_history,
            )

            await self.__git.commit_and_push(ctx.branch_name)

            validation_dto = await self.__validator.validate(
                branch=ctx.branch_name,
                targets=await self.__target_svc.generate(query, local_history),
            )
            query = validation_dto.feedback

        return validation_dto

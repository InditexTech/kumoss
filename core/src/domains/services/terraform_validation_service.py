# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from dataclasses import dataclass

from src.domains.entities import History
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
        self.__count: int = 0

    async def generate_and_validate(
        self,
        q: str,
        history: History,
        branch_name: str,
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
        local_history = history.deepcopy()
        while (
            not validation.validation
            and self.__count < system_config.orchestration.max_validation_iteration
        ):
            self.__count += 1
            logging.debug(
                f"Validation service {self.__count}/{system_config.orchestration.max_validation_iteration}"
            )

            templates, abbreviations = await self.__template_svc.compose_template(
                query=q,
                history=history,
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
                    resources=templates,
                    abbreviations=abbreviations,
                    include_forbidden_actions=include_forbidden_actions,
                ),
                history=local_history,
            )
            local_history.append_turn(q, task_complete.result.get("summary"))

            _ = await self.__session_svc.update_status(
                msg=q,
                prompt=await self.__template_svc.render(PromptsLibrary.STATUS_UPDATE),
                status=SessionStatus.GENERATING,
                history=local_history,
            )

            await self.__git.commit_and_push(branch_name)

            validation = await self.__validator.validate(
                branch=branch_name,
                targets=await self.__target_svc.generate(q, local_history),
            )
            q = validation.feedback

        history.append_turn(first_q, local_history.get_last_turn().assistant)
        return validation

# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from src.domains.dto import ToolResultDTO
from src.domains.entities.history import History
from src.domains.services.llm_service import LLMOrchestrationService
from src.domains.services.template_service import TemplateOrchestrationService
from src.domains.services.tool_service import ToolOrchestrationService
from src.shared.constants import ToolContext, PromptsLibrary


class FilterRequestService:
    def __init__(
        self,
        second_llm_service: LLMOrchestrationService,
        tool_service: ToolOrchestrationService,
        template_service: TemplateOrchestrationService,
    ):
        self.__llm_svc = second_llm_service
        self.__tool_svc = tool_service
        self.__template_svc = template_service

    async def filter(self, request: str, history: History) -> tuple[bool, str]:
        response: ToolResultDTO = await self.__llm_svc.generate(
            query=request,
            tools=self.__tool_svc.get_available_tools([ToolContext.DOMAIN_FILTERING]),
            prompt=await self.__template_svc.render(PromptsLibrary.DOMAIN_FILTER),
            history=history,
        )

        return response.result["status"], response.result["explanation"]

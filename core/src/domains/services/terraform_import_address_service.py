# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from src.domains.entities.history import History
from src.domains.services.llm_service import LLMOrchestrationService
from src.domains.services.template_service import TemplateOrchestrationService
from src.domains.services.tool_service import ToolOrchestrationService
from src.domains.dto import ToolDefinitionDTO, ToolResultDTO
from src.shared.constants import PromptsLibrary, ToolContext


class TerraformImportAddressService:
    """Resolves which resource blocks an import round generated.

    The generation agent writes the blocks; this service reads them back
    from the session branch diff and pairs each Terraform address with the
    cloud resource id it must be imported from.

    The pair goes straight to ``terraform import``, so the id has to be
    spelled the way the provider parses it — a cloud listing API and a
    Terraform provider do not always agree on the case of a resource type
    segment. Web search rides along with the workspace tools for that:
    the registry's import example is what settles the canonical spelling.
    """

    def __init__(
        self,
        tool_service: ToolOrchestrationService,
        llm_service: LLMOrchestrationService,
        template_service: TemplateOrchestrationService,
    ):
        self.__tool_svc = tool_service
        self.__llm_svc = llm_service
        self.__template_svc = template_service

    async def get_import_addresses(
        self, history: History, selected_ids: list[str]
    ) -> list[tuple[str, str]]:
        tools_definition: list[ToolDefinitionDTO] = self.__tool_svc.get_available_tools(
            contexts=[
                ToolContext.WORKSPACE_INSPECTION,
                ToolContext.EXTERNAL_INFORMATION,
            ]
        )
        response: ToolResultDTO = await self.__llm_svc.generate(
            query="Map the generated Terraform blocks to their cloud resource ids.",
            tools=tools_definition,
            sentinel_tool=self.__tool_svc.get_sentinel_tool(ToolContext.IAC_IMPORT),
            prompt=await self.__template_svc.render(
                PromptsLibrary.IMPORT_ADDRESSES, selected_ids=selected_ids
            ),
            history=history,
        )
        return [
            (entry["address"], entry["resource_id"])
            for entry in response.result["imports"]
        ]

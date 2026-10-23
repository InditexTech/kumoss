# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from src.domains.services.llm_service import LLMOrchestrationService
from src.domains.services.template_service import TemplateOrchestrationService
from src.domains.services.tool_service import ToolOrchestrationService
from src.domains.dto import (
    TerraformImportAttempt,
    TerraformImportMappingDTO,
    ToolDefinitionDTO,
    ToolResultDTO,
)
from src.shared.constants import PromptsLibrary, ToolContext


class TerraformImportAddressService:
    """Resolves which resource blocks an import round generated.

    The generation agent writes the blocks; this service reads them back
    from the session branch diff and pairs each Terraform address with the
    cloud resource id it must be imported from.

    The pair goes straight to ``terraform import``, so the id has to be
    written in the format the provider documents for that resource type —
    a cloud listing id is not always the import id (an AWS ARN where the
    provider wants a bucket name or a ``vpc-…`` id, a lower-cased Azure
    type segment). Web search rides along with the workspace tools for
    that: the registry's "Import" section, for the provider version in
    use, is what settles the format of each resource type.

    A block the agent cannot give an import id comes back in
    ``unresolved`` with its reason, so the round never mistakes a missing
    mapping for a complete one.
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
        self, selected_ids: list[str]
    ) -> TerraformImportMappingDTO:
        tools_definition: list[ToolDefinitionDTO] = self.__tool_svc.get_available_tools(
            contexts=[
                ToolContext.WORKSPACE_INSPECTION,
                ToolContext.EXTERNAL_INFORMATION,
            ]
        )
        response: ToolResultDTO = await self.__llm_svc.generate(
            query="Map the generated Terraform blocks to their import ids, in the format the provider documents for each resource type.",
            tools=tools_definition,
            sentinel_tool=self.__tool_svc.get_sentinel_tool(
                ToolContext.IMPORT_ADDRESSES
            ),
            prompt=await self.__template_svc.render(
                PromptsLibrary.IMPORT_ADDRESSES, selected_ids=selected_ids
            ),
        )
        return TerraformImportMappingDTO(
            imports={
                TerraformImportAttempt(
                    entry["address"],
                    entry["resource_id"],
                    listed_id=entry.get("listed_id", ""),
                )
                for entry in response.result["imports"]
            },
            unresolved={
                # No import id was built, so none was attempted: the agent's
                # `resource_id` here is the listed id it paired the block with.
                TerraformImportAttempt(
                    entry["address"],
                    "",
                    entry["reason"],
                    listed_id=entry["resource_id"],
                )
                for entry in response.result.get("unresolved", [])
            },
        )

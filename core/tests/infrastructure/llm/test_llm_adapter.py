# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

# pyright: basic, reportAssignmentType=false, reportAttributeAccessIssue=false
import unittest

from src.application.commands import AdvancedOptions, TerraformCRUDCommand
from src.application.factory import HandlerFactory
from src.domains.dto import (
    LLMResponseDTO,
    ToolDefinitionDTO,
)
from src.domains.entities.history import History
from src.infrastructure.llm._google_gemini import GoogleGemini
from src.shared.constants import PromptsLibrary, ToolContext
from tests.setups import setup_repository, clean_resources

from tests.settings import Settings


class TestLLMAdapter(unittest.IsolatedAsyncioTestCase):
    main_service: GoogleGemini = None

    @classmethod
    async def asyncSetUp(cls):
        await setup_repository(setup_tracer=True)
        cls.command = TerraformCRUDCommand(
            q="whocares",
            environment=Settings.DEFAULT_PROJECT_ENV,
            cloud=Settings.DEFAULT_PROJECT_CLOUD,
            repository_id=Settings.DEFAULT_PROJECT_UID,
            user_id=Settings.USER_ID,
            advanced_options=AdvancedOptions(),
        )
        handler = HandlerFactory(cls.command).get_terraform_crud_handler()
        validation_svc = handler._TerraformCRUDHandler__validation_svc
        cls.__template_svc = validation_svc._TerraformValidationService__template_svc
        cls.__tool_svc = validation_svc._TerraformValidationService__tool_orchestration
        cls.main_service = HandlerFactory.get_llm_adapter(
            provider=Settings.LLM_PROVIDER,
            temperature=0.1,
        )

    @classmethod
    async def asyncTearDown(cls):
        clean_resources()

    async def test_inference_plain_text(self):
        output = await self.main_service.inference(
            msg="hey, how you doing",
            system_prompt="answer the user's question",
            thinking=True,
        )
        print(output)
        self.assertIsInstance(output, LLMResponseDTO)

    async def test_inference_tool(self):
        sentinel_tool_definition: ToolDefinitionDTO = self.__tool_svc.get_sentinel_tool(
            context=ToolContext.TARGET_GENERATOR
        )
        tools: list[ToolDefinitionDTO] = self.__tool_svc.get_available_tools(
            contexts=[ToolContext.WORKSPACE_INSPECTION]
        )
        tools.append(sentinel_tool_definition)

        output = await self.main_service.inference(
            msg="create an storage account",
            system_prompt=(
                await self.__template_svc.render(PromptsLibrary.TARGET_GENERATOR)
            ).prompt,
            tools=tools,
        )
        print(output)
        self.assertIsInstance(output, LLMResponseDTO)

    async def test_inference_multiple_tools(self):
        query = "create an storage account"
        sentinel_tool_definition: ToolDefinitionDTO = self.__tool_svc.get_sentinel_tool(
            context=ToolContext.TARGET_GENERATOR
        )
        tools: list[ToolDefinitionDTO] = self.__tool_svc.get_available_tools(
            contexts=[ToolContext.WORKSPACE_INSPECTION]
        )
        tools.append(sentinel_tool_definition)
        history = History()
        output = await self.main_service.inference(
            msg=query,
            system_prompt=(
                await self.__template_svc.render(PromptsLibrary.TARGET_GENERATOR)
            ).prompt,
            tools=tools,
        )
        tools_result = await self.__tool_svc.execute_tool_calls(output.tool_calls)
        history.append_turn(user_msg=query, assistant_msg=output.tool_calls)
        print(tools_result)
        output = await self.main_service.inference(
            msg=tools_result,
            system_prompt=(
                await self.__template_svc.render(PromptsLibrary.TARGET_GENERATOR)
            ).prompt,
            tools=tools,
            history=history,
        )
        print(output)
        self.assertIsInstance(output, LLMResponseDTO)

    async def test_inference_complete_chain(self):
        query = "create an storage account"
        sentinel_tool_definition: ToolDefinitionDTO = self.__tool_svc.get_sentinel_tool(
            context=ToolContext.TARGET_GENERATOR
        )
        tools: list[ToolDefinitionDTO] = self.__tool_svc.get_available_tools(
            contexts=[ToolContext.WORKSPACE_INSPECTION]
        )
        tools.append(sentinel_tool_definition)
        history = History()
        output = None
        while not output or "generate_terraform_targets" not in [
            t.name for t in output.tool_calls
        ]:
            output = await self.main_service.inference(
                msg=query,
                system_prompt=(
                    await self.__template_svc.render(PromptsLibrary.TARGET_GENERATOR)
                ).prompt,
                tools=tools,
                history=history,
            )
            tools_result = await self.__tool_svc.execute_tool_calls(output.tool_calls)
            history.append_turn(user_msg=query, assistant_msg=output.tool_calls)
            print(tools_result)
            output = await self.main_service.inference(
                msg=tools_result,
                system_prompt=(
                    await self.__template_svc.render(PromptsLibrary.TARGET_GENERATOR)
                ).prompt,
                tools=tools,
                history=history,
            )
            history.append_turn(user_msg=tools_result, assistant_msg=output.tool_calls)
            print(output)
        self.assertIsInstance(output, LLMResponseDTO)


if __name__ == "__main__":
    unittest.main()

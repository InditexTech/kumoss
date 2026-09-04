# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

# pyright: basic, reportAssignmentType=false, reportAttributeAccessIssue=false
import unittest

from src.application.commands import TerraformCRUDCommand, AdvancedOptions
from src.application.factory import HandlerFactory
from src.infrastructure.exceptions import ToolInferenceParamsError
from src.infrastructure.tools import ToolRegistryWorkspace
from src.shared.constants import ToolContext
from tests.setups import setup_repository, clean_resources

from tests.settings import Settings


class TestToolRegistry(unittest.IsolatedAsyncioTestCase):
    main_service: ToolRegistryWorkspace = None

    @classmethod
    async def asyncSetUp(cls):
        await setup_repository()
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
        tool_svc = validation_svc._TerraformValidationService__tool_orchestration
        cls.main_service = tool_svc._ToolOrchestrationService__tool_registry

    @classmethod
    async def asyncTearDown(cls):
        clean_resources()

    async def test_handle_grep_search(self):
        test_input = {
            "explanation": "whatever explanation",
            "searches": [
                {"query": "vault", "include_pattern": "*.tf", "case_sensitive": True},
                {"query": "provider", "include_pattern": "*.md"},
            ],
        }
        output = self.main_service._ToolRegistryWorkspace__handle_grep_search(
            test_input
        )
        self.assertIsInstance(output, str)

    async def test_handle_pr_generator(self):
        test_input = {
            "title": "Add storage account for the billing app",
            "description": "## Summary\nAdds a storage account.",
        }
        output = self.main_service._ToolRegistryStatic__handle_pr_generator(test_input)
        self.assertEqual(output, test_input)

    async def test_handle_pr_generator_invalid_params(self):
        with self.assertRaises(ToolInferenceParamsError):
            self.main_service._ToolRegistryStatic__handle_pr_generator(
                {"title": 123, "description": "whatever"}
            )

    async def test_pr_generator_single_tool_context(self):
        tools = self.main_service.get_available_tools(ToolContext.PR_GENERATOR)
        self.assertEqual(len(tools), 1)
        self.assertEqual(tools[0].name, "generate_pull_request")
        self.assertEqual(set(tools[0].parameters["required"]), {"title", "description"})


if __name__ == "__main__":
    unittest.main()

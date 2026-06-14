# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

# pyright: basic, reportAssignmentType=false, reportAttributeAccessIssue=false
import unittest

from src.application.commands import TerraformCRUDCommand, AdvancedOptions
from src.application.factory import HandlerFactory
from src.infrastructure.tools.tool_registry import ToolRegistry
from tests.setups import setup_repository, clean_resources

from tests.settings import Settings


class TestToolRegistry(unittest.IsolatedAsyncioTestCase):
    main_service: ToolRegistry = None

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
        output = self.main_service._ToolRegistry__handle_grep_search(test_input)
        print(output)
        self.assertIsInstance(output, str)


if __name__ == "__main__":
    unittest.main()

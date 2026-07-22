# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

# pyright: basic, reportAssignmentType=false, reportAttributeAccessIssue=false
import unittest

from unittest.mock import patch, AsyncMock
from src.domains.interfaces import ITemplate
from src.infrastructure.templates.factory import TemplateFactory
from src.infrastructure.templates._fetcher import remote_fetcher

from src.shared.constants import TerraformProvider
# from tests.setups import setup_repository, clean_resources


class TestGeneratePayloadService(unittest.IsolatedAsyncioTestCase):
    # Fixture for mocking the fetch method to return predefined responses based on the prompt_name
    MOCK_RESPONSES = {
        "abbreviations": "mocked_abbreviations",
        "resources_list": "mocked_resources_list",
        "storage_account": "mocked_storage_account_content",
        # "app_service": "mocked_app_service_content",
    }

    main_service: ITemplate = None

    @classmethod
    async def asyncSetUp(cls):
        ### This is a workaround to set the telemetry collector URL to localhost for testing purposes.
        # from src.shared.config import system_config
        # cls.original_collector_url = system_config.telemetry.collector_url

        # # Cambiar a localhost para los tests
        # system_config.telemetry.collector_url = "http://localhost/monitoring/"

        # await setup_repository(setup_tracer=True) # This line is from the old test
        cls.main_service = TemplateFactory(
            TerraformProvider.AZURE, cwd="/test/project"
        ).get()

    @classmethod
    async def asyncTearDown(cls):
        ### Restore the original telemetry collector URL after tests
        # from src.shared.config import system_config
        # system_config.telemetry.collector_url = cls.original_collector_url

        # clean_resources() # This is from the old test
        cls.main_service = None

    # async def test_render_iac_generator(self):
    #     prompt: str = await self.main_service.render_iac_generator(
    #         resources=["storage_account"],
    #         abbreviations=["sta"],
    #         include_forbidden_actions=False,
    #     )
    #     self.assertIsInstance(prompt, str)
    #     self.assertTrue(prompt.find("Storage account") != -1)
    #     self.assertTrue(prompt.find("STRICTLY FORBIDDEN") == -1)
    #     prompt = await self.main_service.render_iac_generator(
    #         resources=["storage_account"],
    #         abbreviations=["sta"],
    #         include_forbidden_actions=True,
    #     )
    #     self.assertIsInstance(prompt, str)
    #     self.assertTrue(prompt.find("Storage account") != -1)
    #     self.assertTrue(prompt.find("STRICTLY FORBIDDEN") != -1)
    #     prompt = await self.main_service.render_iac_generator(
    #         resources=["wrong_template_name"],
    #         abbreviations=["sta"],
    #         include_forbidden_actions=True,
    #     )
    #     self.assertIsInstance(prompt, str)
    #     self.assertTrue(prompt.find("Storage account") == -1)
    #     self.assertTrue(prompt.find("STRICTLY FORBIDDEN") != -1)

    # async def test_render_domain_filter(self):
    #     prompt: str = self.main_service.render_domain_filter()
    #     self.assertIsInstance(prompt, str)

    @patch.object(remote_fetcher, "fetch", new_callable=AsyncMock)
    async def test_render_prompt_compositor(self, mock_fetch):
        # Function to return mock responses based on the prompt_name
        async def mock_fetch_impl(prompt_name, **kwargs):
            return self.MOCK_RESPONSES.get(
                prompt_name, f"default_{prompt_name}_mocked_response"
            )

        mock_fetch.side_effect = mock_fetch_impl

        prompt = await self.main_service.render_prompt_compositor(
            already_selected_templates=["storage_account"],
            already_selected_abbreviations=["sta-"],
        )
        self.assertIsInstance(prompt, str)
        self.assertTrue(prompt.find("mocked_abbreviations") != -1)
        self.assertTrue(prompt.find("mocked_storage_account") != -1)
        self.assertTrue(prompt.find("mocked_resources_list") != -1)
        self.assertTrue(prompt.find("mocked_storage_account_content") != -1)
        self.assertFalse(
            prompt.find("mocked_app_service_content") != -1
        )  # Should not be present since it was not selected


if __name__ == "__main__":
    unittest.main()

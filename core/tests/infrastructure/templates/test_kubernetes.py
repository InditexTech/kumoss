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


class TestKubernetesTemplateAdapter(unittest.IsolatedAsyncioTestCase):
    # Fixture for mocking the fetch method to return predefined responses based on the prompt_name
    MOCK_RESPONSES = {
        "abbreviations": "mocked_abbreviations",
        "resources_list": "mocked_resources_list",
        "deployment": "mocked_deployment_content",
        # "service": "mocked_service_content",
    }

    main_service: ITemplate = None

    @classmethod
    async def asyncSetUp(cls):
        # await setup_repository(setup_tracer=True)
        cls.main_service = TemplateFactory(
            TerraformProvider.KUBERNETES, cwd="/test/project"
        ).get()

    @classmethod
    async def asyncTearDown(cls):
        # clean_resources()
        cls.main_service = None

    # async def test_render_iac_generator(self):
    #     prompt: str = await self.main_service.render_iac_generator(
    #         resources=["deployment"],
    #         abbreviations=["deploy"],
    #         include_forbidden_actions=False,
    #     )
    #     self.assertIsInstance(prompt, str)
    #     self.assertTrue(prompt.find("Deployment") != -1)
    #     self.assertTrue(prompt.find("STRICTLY FORBIDDEN") == -1)
    #     prompt = await self.main_service.render_iac_generator(
    #         resources=["deployment"],
    #         abbreviations=["deploy"],
    #         include_forbidden_actions=True,
    #     )
    #     self.assertIsInstance(prompt, str)
    #     self.assertTrue(prompt.find("Deployment") != -1)
    #     self.assertTrue(prompt.find("STRICTLY FORBIDDEN") != -1)
    #     prompt = await self.main_service.render_iac_generator(
    #         resources=["wrong_template_name"],
    #         abbreviations=["deploy"],
    #         include_forbidden_actions=True,
    #     )
    #     self.assertIsInstance(prompt, str)
    #     self.assertTrue(prompt.find("Kubernetes Deployment") == -1)
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
            already_selected_templates=["deployment"],
            already_selected_abbreviations=["deploy-"],
        )
        self.assertIsInstance(prompt, str)
        self.assertTrue(prompt.find("mocked_abbreviations") != -1)
        self.assertTrue(prompt.find("mocked_deployment") != -1)
        self.assertTrue(prompt.find("mocked_resources_list") != -1)
        self.assertTrue(prompt.find("mocked_deployment_content") != -1)
        self.assertFalse(
            prompt.find("mocked_service_content") != -1
        )  # Should not be present since it was not selected


if __name__ == "__main__":
    unittest.main()

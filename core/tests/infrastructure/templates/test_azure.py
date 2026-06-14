# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

# pyright: basic, reportAssignmentType=false, reportAttributeAccessIssue=false
import unittest

from src.domains.interfaces import ITemplate
from src.infrastructure.templates.factory import TemplateFactory
from src.shared.constants import TemplateProvider

from tests.setups import setup_repository, clean_resources


class TestGeneratePayloadService(unittest.IsolatedAsyncioTestCase):
    main_service: ITemplate = None

    @classmethod
    async def asyncSetUp(cls):
        await setup_repository(setup_tracer=True)
        cls.main_service = TemplateFactory(
            TemplateProvider.AZURE, cwd="/test/project"
        ).get()

    @classmethod
    async def asyncTearDown(cls):
        clean_resources()
        cls.main_service = None

    async def test_render_iac_generator(self):
        prompt: str = await self.main_service.render_iac_generator(
            resources=["storage_account"],
            abbreviations=["sta"],
            include_forbidden_actions=False,
        )
        self.assertIsInstance(prompt, str)
        self.assertTrue(prompt.find("Storage account") != -1)
        self.assertTrue(prompt.find("STRICTLY FORBIDDEN") == -1)
        prompt = await self.main_service.render_iac_generator(
            resources=["storage_account"],
            abbreviations=["sta"],
            include_forbidden_actions=True,
        )
        self.assertIsInstance(prompt, str)
        self.assertTrue(prompt.find("Storage account") != -1)
        self.assertTrue(prompt.find("STRICTLY FORBIDDEN") != -1)
        prompt = await self.main_service.render_iac_generator(
            resources=["wrong_template_name"],
            abbreviations=["sta"],
            include_forbidden_actions=True,
        )
        self.assertIsInstance(prompt, str)
        self.assertTrue(prompt.find("Storage account") == -1)
        self.assertTrue(prompt.find("STRICTLY FORBIDDEN") != -1)

    async def test_render_domain_filter(self):
        prompt: str = self.main_service.render_domain_filter()
        self.assertIsInstance(prompt, str)


if __name__ == "__main__":
    unittest.main()

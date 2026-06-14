# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

# pyright: basic, reportAssignmentType=false, reportAttributeAccessIssue=false
import unittest


from src.infrastructure.external.gemini_web_search import GeminiWebSearch
from src.infrastructure.llm.factory import LLMFactory
from tests.settings import LLMProvider
from tests.setups import setup_repository, clean_resources


class TestGeminiWebSearch(unittest.IsolatedAsyncioTestCase):
    main_service: GeminiWebSearch = None

    @classmethod
    async def asyncSetUp(cls):
        await setup_repository(setup_tracer=True)
        cls.main_service = GeminiWebSearch(
            gemini=LLMFactory(provider=LLMProvider.GEMINI_FLASH, temperature=0.1).get()
        )

    @classmethod
    async def asyncTearDown(cls):
        clean_resources()

    async def test_web_search(self):
        output = await self.main_service.search(
            "what are the last versions of the cosmosdb azurerm terraform resource?"
        )
        print(output)
        self.assertIsInstance(output, str)


if __name__ == "__main__":
    unittest.main()

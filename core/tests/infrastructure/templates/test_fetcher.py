# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""How the prompt fetcher reports what Langfuse answers.

Provider prompts are optional, so a prompt (or label) Langfuse does not
have must surface as a 404 the template adapter can skip, while anything
else stays an error.
"""

import unittest
from unittest.mock import patch

import httpx

from src.infrastructure.exceptions import PromptFetchError
from src.infrastructure.templates._fetcher import _PromptFetcher
from src.infrastructure.templates.template_adapter import TemplateAdapter
from tests.infrastructure.templates.fake_langfuse import FakeLangfuse


class TestFetcher(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.langfuse = FakeLangfuse()
        self.fetcher = _PromptFetcher(self.langfuse.client())

    async def _fetch(self, scope: str = "azurerm") -> str:
        return await self.fetcher.fetch(
            "networking", scope, "guidelines", "development"
        )

    async def test_the_version_the_environment_label_is_on_is_read(self):
        self.langfuse.add("azurerm/guidelines/networking", "v1", ("development",))
        self.langfuse.add("azurerm/guidelines/networking", "v2", ("production",))

        self.assertEqual(await self._fetch(), "v1")

    async def test_the_prompt_is_read_from_its_scope_and_type_folders(self):
        requested: list[str] = []

        def record(request: httpx.Request) -> None:
            requested.append(request.url.raw_path.decode().split("?")[0])

        self.langfuse.fail = record
        self.langfuse.add("azurerm/guidelines/networking", "v1", ("development",))

        _ = await self._fetch()

        # One path segment: Langfuse wants a folder path URL-encoded.
        self.assertEqual(
            requested,
            ["/api/public/v2/prompts/azurerm%2Fguidelines%2Fnetworking"],
        )

    async def test_a_chat_prompt_of_one_message_is_read_as_its_text(self):
        # An operator may save a prompt as chat in the Langfuse UI.
        self.langfuse.add(
            "azurerm/guidelines/networking",
            [{"role": "system", "content": "no public IPs"}],
            ("development",),
            type="chat",
        )

        self.assertEqual(await self._fetch(), "no public IPs")

    async def test_a_missing_prompt_is_a_404(self):
        with self.assertRaises(PromptFetchError) as ctx:
            _ = await self._fetch("random")
        self.assertEqual(ctx.exception.error_code, 404)

    async def test_a_prompt_without_the_label_is_a_404(self):
        self.langfuse.add("azurerm/guidelines/networking", "v1", ("production",))

        with self.assertRaises(PromptFetchError) as ctx:
            _ = await self._fetch()
        self.assertEqual(ctx.exception.error_code, 404)

    async def test_a_refusal_keeps_its_status(self):
        self.langfuse.fail = lambda _: httpx.Response(401)

        with self.assertRaises(PromptFetchError) as ctx:
            _ = await self._fetch()
        self.assertEqual(ctx.exception.error_code, 401)

    async def test_an_unreachable_langfuse_is_not_mistaken_for_a_missing_prompt(self):
        def down(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused", request=request)

        self.langfuse.fail = down

        with self.assertRaises(PromptFetchError) as ctx:
            _ = await self._fetch()
        self.assertEqual(ctx.exception.error_code, 500)

    async def test_a_prompt_of_another_shape_is_an_error(self):
        self.langfuse.add(
            "azurerm/guidelines/networking",
            [{"role": "system", "content": "a"}, {"role": "user", "content": "b"}],
            ("development",),
            type="chat",
        )

        with self.assertRaises(PromptFetchError) as ctx:
            _ = await self._fetch()
        self.assertEqual(ctx.exception.error_code, 502)

    async def test_providers_without_prompts_are_skipped_end_to_end(self):
        self.langfuse.add(
            "azurerm/guidelines/networking", "no public IPs", ("development",)
        )

        adapter = TemplateAdapter(providers=("azurerm", "random"), cwd="/w")
        with patch(
            "src.infrastructure.templates.template_adapter.remote_fetcher",
            self.fetcher,
        ):
            text = await adapter._fetch_guidelines("networking")  # pyright: ignore[reportPrivateUsage]
        self.assertEqual(text, "## azurerm\nno public IPs")

    async def test_a_versioned_fetch_names_the_version_read(self):
        self.langfuse.add("general/policies/compliance", "package a", ("production",))
        self.langfuse.add("general/policies/compliance", "package b", ("development",))

        text, revision = await self.fetcher.fetch_versioned(
            "compliance", "general", "policies", "development"
        )

        self.assertEqual(
            (text, revision), ("package b", "general/policies/compliance@2")
        )

# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""How the prompt fetcher reports what the Phoenix client raises.

The Phoenix client signals a missing prompt with a ``ValueError``, not an
HTTP error; provider prompts are optional, so that must surface as a 404
the template adapter can skip, while anything else stays an error.
"""

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from src.infrastructure.exceptions import PhoenixPromptFetchError
from src.infrastructure.templates._fetcher import remote_fetcher
from src.infrastructure.templates.template_adapter import TemplateAdapter


def _prompt(text: str) -> SimpleNamespace:
    return SimpleNamespace(
        _template={"messages": [{"content": [{"text": text}]}]},
    )


class TestFetcher(unittest.IsolatedAsyncioTestCase):
    def _client_get(self, get: AsyncMock):
        client = remote_fetcher._PromptFetcher__client  # pyright: ignore[reportAttributeAccessIssue]
        return patch.object(client.prompts, "get", get)

    async def test_a_missing_prompt_is_a_404(self):
        get = AsyncMock(
            side_effect=ValueError(
                "Prompt not found: random-guidelines-forbidden_actions"
            )
        )
        with self._client_get(get):
            with self.assertRaises(PhoenixPromptFetchError) as ctx:
                _ = await remote_fetcher.fetch(
                    "forbidden_actions", "random", "guidelines", "development"
                )
        self.assertEqual(ctx.exception.error_code, 404)

    async def test_any_other_value_error_is_not_mistaken_for_a_missing_prompt(self):
        get = AsyncMock(side_effect=ValueError("unexpected response shape"))
        with self._client_get(get):
            with self.assertRaises(PhoenixPromptFetchError) as ctx:
                _ = await remote_fetcher.fetch(
                    "forbidden_actions", "azurerm", "guidelines", "development"
                )
        self.assertEqual(ctx.exception.error_code, 502)

    async def test_providers_without_prompts_are_skipped_end_to_end(self):
        async def get(prompt_identifier: str, tag: str):
            if prompt_identifier.startswith("azurerm-"):
                return _prompt("no public IPs")
            raise ValueError(f"Prompt not found: {prompt_identifier}")

        adapter = TemplateAdapter(providers=("azurerm", "random"), cwd="/w")
        with self._client_get(AsyncMock(side_effect=get)):
            text = await adapter._fetch_guidelines("forbidden_actions")  # pyright: ignore[reportPrivateUsage]
        self.assertEqual(text, "## azurerm\nno public IPs")

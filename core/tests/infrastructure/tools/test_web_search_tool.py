# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""The web_search tool hands the engine's hits straight to the agent.

The query goes to whichever engine ``config.yaml`` names
(``web_search.provider``) through the ``SearchServiceClient`` facade, and
the agent gets plain ``title: content (url)`` lines back. There is no
LLM-native fallback: an unset provider, a dead engine and an empty result
set each degrade into a "do NOT retry" result the agent can read, and
none of them reaches an inference.
"""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from src.domains.dto import ToolCallDTO
from src.infrastructure.external.search_service import (
    SearchEngineError,
    SearchResult,
)
from src.infrastructure.tools.tool_registry_static import ToolRegistryStatic


def _results(*tuples: tuple[str, str, str]) -> list[SearchResult]:
    return [
        SearchResult(title=title, url=url, content=content)
        for title, url, content in tuples
    ]


class TestWebSearchTool(unittest.IsolatedAsyncioTestCase):
    def _registry(self, provider: str, llm: MagicMock | None = None):
        """Patch web_search.provider while the registry is constructed."""
        config = MagicMock()
        config.web_search.provider = provider
        with patch(
            "src.infrastructure.tools.tool_registry_static.system_config",
            config,
        ):
            return ToolRegistryStatic(llm=llm)

    async def _run(self, registry: ToolRegistryStatic, query: str):
        return await registry.execute_tool(
            ToolCallDTO(id="call_1", name="web_search", parameters={"query": query})
        )

    def _tool_module_patch(self, provider: str):
        """system_config is re-read by the handler on every call."""
        config = MagicMock()
        config.web_search.provider = provider
        return patch(
            "src.infrastructure.tools.tool_registry_static.system_config",
            config,
        )

    async def _search(
        self,
        query: str = "q",
        llm: MagicMock | None = None,
        results: list[SearchResult] | None = None,
        side_effect: Exception | None = None,
    ):
        llm = llm if llm is not None else MagicMock(inference=AsyncMock())
        registry = self._registry("searxng", llm=llm)
        with (
            self._tool_module_patch("searxng"),
            patch(
                "src.infrastructure.tools.tool_registry_static.SearchServiceClient"
            ) as client_cls,
        ):
            client_cls.return_value.search = AsyncMock(
                return_value=results if results is not None else _results(),
                side_effect=side_effect,
            )
            return await self._run(registry, query), llm

    async def test_results_are_formatted_one_line_per_hit(self):
        result, llm = await self._search(
            query="terraform s3 bucket",
            results=_results(
                (
                    "Terraform Registry",
                    "https://registry.terraform.io",
                    "s3 bucket docs",
                )
            ),
        )

        self.assertTrue(result.success, result.error_message)
        self.assertEqual(
            result.result["result"],
            "- Terraform Registry: s3 bucket docs (https://registry.terraform.io)",
        )
        llm.inference.assert_not_awaited()

    async def test_multiple_results_are_joined_in_engine_order(self):
        result, _ = await self._search(
            results=_results(
                ("First", "https://one", "a"),
                ("Second", "https://two", "b"),
                ("Third", "https://three", "c"),
            )
        )

        self.assertEqual(
            result.result["result"],
            "- First: a (https://one)\n"
            "- Second: b (https://two)\n"
            "- Third: c (https://three)",
        )

    async def test_the_query_is_echoed_back_with_the_result(self):
        result, _ = await self._search(
            query="k8s gateway api", results=_results(("T", "https://a", "body"))
        )

        self.assertEqual(result.result["query"], "k8s gateway api")

    async def test_no_provider_configured_never_searches(self):
        llm = MagicMock(inference=AsyncMock())
        registry = self._registry("", llm=llm)

        with (
            self._tool_module_patch(""),
            patch(
                "src.infrastructure.tools.tool_registry_static.SearchServiceClient"
            ) as client_cls,
        ):
            result = await self._run(registry, "q")

        self.assertTrue(result.success, result.error_message)
        self.assertIn("Web search is unavailable", result.result["result"])
        self.assertIn("Do NOT retry web_search", result.result["result"])
        client_cls.return_value.search.assert_not_called()
        llm.inference.assert_not_awaited()

    async def test_engine_failure_is_reported_not_raised(self):
        result, llm = await self._search(
            side_effect=SearchEngineError(
                "the 'searxng' search engine call failed", 502
            )
        )

        self.assertTrue(result.success, result.error_message)
        self.assertIn("Web search is unavailable", result.result["result"])
        self.assertIn("Do NOT retry web_search", result.result["result"])
        llm.inference.assert_not_awaited()

    async def test_empty_engine_results_tell_the_agent_not_to_retry(self):
        result, llm = await self._search(query="obscure query", results=[])

        self.assertTrue(result.success, result.error_message)
        self.assertIn("returned no content", result.result["result"])
        self.assertIn("Do NOT retry web_search", result.result["result"])
        llm.inference.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()

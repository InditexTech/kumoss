# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""The web_search tool routes between two backends.

When ``config.yaml`` names a search engine (``web_search.provider``) the
query goes to that engine through the ``SearchServiceClient`` facade and
the agent gets plain ``title: snippet (url)`` lines. When it does not —
or the engine comes back empty or fails — the tool degrades: to the
LLM-native search of the configured model, to a friendly "unavailable,
do NOT retry" result on engine failure, and to a "no content" result on
an empty response.
"""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from src.domains.dto import ToolCallDTO
from src.infrastructure.external.search_service import (
    SearchEngineError,
    SearchResult,
)
from src.infrastructure.tools.tool_registry_static import ToolRegistryStatic


def _llm_with_web_search(text: str) -> MagicMock:
    llm = MagicMock()
    llm.inference = AsyncMock(return_value=MagicMock(text=text))
    return llm


def _results(*tuples: tuple[str, str, str]) -> list[SearchResult]:
    return [
        SearchResult(title=title, url=url, snippet=snippet)
        for title, url, snippet in tuples
    ]


class TestWebSearchTool(unittest.IsolatedAsyncioTestCase):
    def _registry(self, provider: str, llm=None) -> ToolRegistryStatic:
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

    async def test_configured_engine_short_circuits_the_llm(self):
        llm = _llm_with_web_search("from the llm")
        registry = self._registry("searxng", llm=llm)

        with (
            self._tool_module_patch("searxng"),
            patch(
                "src.infrastructure.tools.tool_registry_static.SearchServiceClient"
            ) as client_cls,
        ):
            client_cls.return_value.search = AsyncMock(
                return_value=_results(
                    (
                        "Terraform Registry",
                        "https://registry.terraform.io",
                        "s3 bucket docs",
                    )
                )
            )
            result = await self._run(registry, "terraform s3 bucket")

        self.assertTrue(result.success, result.error_message)
        self.assertEqual(
            result.result["result"],
            "- Terraform Registry: s3 bucket docs (https://registry.terraform.io)",
        )
        llm.inference.assert_not_awaited()

    async def test_no_engine_configured_falls_back_to_llm_search(self):
        llm = _llm_with_web_search("from the llm")
        registry = self._registry("", llm=llm)

        with (
            self._tool_module_patch(""),
            patch(
                "src.infrastructure.tools.tool_registry_static.SearchServiceClient"
            ) as client_cls,
        ):
            result = await self._run(registry, "k8s gateway api")

        self.assertTrue(result.success, result.error_message)
        self.assertEqual(result.result["result"], "from the llm")
        llm.inference.assert_awaited_once()
        client_cls.return_value.search.assert_not_called()

    async def test_engine_failure_is_reported_not_raised(self):
        registry = self._registry("searxng")

        with (
            self._tool_module_patch("searxng"),
            patch(
                "src.infrastructure.tools.tool_registry_static.SearchServiceClient"
            ) as client_cls,
        ):
            client_cls.return_value.search = AsyncMock(
                side_effect=SearchEngineError(
                    "the 'searxng' search engine call failed", 502
                )
            )
            result = await self._run(registry, "q")

        self.assertTrue(result.success, result.error_message)
        self.assertIn("Web search is unavailable", result.result["result"])
        self.assertIn("Do NOT retry web_search", result.result["result"])

    async def test_empty_engine_results_tell_the_agent_not_to_retry(self):
        registry = self._registry("searxng")

        with (
            self._tool_module_patch("searxng"),
            patch(
                "src.infrastructure.tools.tool_registry_static.SearchServiceClient"
            ) as client_cls,
        ):
            client_cls.return_value.search = AsyncMock(return_value=[])
            result = await self._run(registry, "obscure query")

        self.assertTrue(result.success, result.error_message)
        self.assertIn("returned no content", result.result["result"])
        self.assertIn("Do NOT retry web_search", result.result["result"])

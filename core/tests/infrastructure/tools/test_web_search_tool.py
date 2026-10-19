# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""The web_search tool hands the engine's hits straight to the agent.

The query goes to whichever engine ``config.yaml`` names
(``web_search.provider``) through the ``SearchServiceClient`` facade, and
the agent gets plain ``title: content (url)`` lines back. There is no
LLM-native fallback: an unset provider and a dead engine degrade into a
"do NOT retry" result the agent can read, and neither reaches an
inference.

A search that simply finds nothing is treated as a query problem
instead: the agent is asked to search again with a different query, and
only once ``max_query_retries`` consecutive dead ends have been spent
is it told to stop. Any search that returns something refills that
budget.

With ``web_search.summarize`` on, those lines carry the small model's
condensed summaries instead of the raw pages, capped at
``summarize_top`` and ordered by relevance; a summarizer that fails
drops back to the raw hits.
"""

import unittest
from contextlib import contextmanager
from types import SimpleNamespace
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
        config.web_search.summarize = False
        with patch(
            "src.infrastructure.tools.tool_registry_static.system_config",
            config,
        ):
            return ToolRegistryStatic(llm=llm)

    async def _run(self, registry: ToolRegistryStatic, query: str):
        return await registry.execute_tool(
            ToolCallDTO(id="call_1", name="web_search", parameters={"query": query})
        )

    @contextmanager
    def _tool_module_patch(
        self,
        provider: str,
        summarize: bool = False,
        summarize_top: int = 1,
        max_query_retries: int = 3,
    ):
        """system_config is re-read by the handler on every call.

        The summarizer reads its own module-level ``system_config`` when
        the handler builds it, so both modules are patched with the same
        settings — otherwise the real ``summarize_top`` would decide how
        many summaries the tool returns.
        """
        config = MagicMock()
        config.web_search.provider = provider
        config.web_search.summarize = summarize
        config.web_search.summarize_top = summarize_top
        config.web_search.summarize_max_chars = 1200
        config.web_search.max_query_retries = max_query_retries
        with (
            patch(
                "src.infrastructure.tools.tool_registry_static.system_config",
                config,
            ),
            patch(
                "src.infrastructure.external.search_summarizer.system_config",
                config,
            ),
        ):
            yield config

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

    async def test_empty_engine_results_ask_for_a_different_query(self):
        result, llm = await self._search(query="obscure query", results=[])

        self.assertTrue(result.success, result.error_message)
        self.assertIn("returned no content", result.result["result"])
        self.assertIn("attempt 1 of 3", result.result["result"])
        self.assertIn("different query", result.result["result"])
        # Telling it to stop on the first miss wastes the other tries.
        self.assertNotIn("Do NOT retry web_search", result.result["result"])
        llm.inference.assert_not_awaited()

    async def test_the_last_dead_end_tells_the_agent_to_stop(self):
        llm = MagicMock(inference=AsyncMock())
        registry = self._registry("searxng", llm=llm)
        with (
            self._tool_module_patch("searxng", max_query_retries=2),
            patch(
                "src.infrastructure.tools.tool_registry_static.SearchServiceClient"
            ) as client_cls,
        ):
            client_cls.return_value.search = AsyncMock(return_value=[])
            first = await self._run(registry, "terraform foo")
            last = await self._run(registry, "terraform bar")

        self.assertIn("attempt 1 of 2", first.result["result"])
        self.assertNotIn("Do NOT retry web_search", first.result["result"])
        self.assertIn("Do NOT retry web_search", last.result["result"])
        self.assertNotIn("different query", last.result["result"])

    async def test_a_search_that_works_refills_the_retry_budget(self):
        llm = MagicMock(inference=AsyncMock())
        registry = self._registry("searxng", llm=llm)
        with (
            self._tool_module_patch("searxng", max_query_retries=2),
            patch(
                "src.infrastructure.tools.tool_registry_static.SearchServiceClient"
            ) as client_cls,
        ):
            client_cls.return_value.search = AsyncMock(
                side_effect=[[], _results(("T", "https://a", "body")), []]
            )
            await self._run(registry, "dead end")
            await self._run(registry, "a good one")
            after = await self._run(registry, "dead end again")

        # The streak was broken, so this is attempt 1 again, not the last.
        self.assertIn("attempt 1 of 2", after.result["result"])
        self.assertNotIn("Do NOT retry web_search", after.result["result"])

    async def test_an_engine_failure_does_not_spend_the_retry_budget(self):
        llm = MagicMock(inference=AsyncMock())
        registry = self._registry("searxng", llm=llm)
        with (
            self._tool_module_patch("searxng", max_query_retries=2),
            patch(
                "src.infrastructure.tools.tool_registry_static.SearchServiceClient"
            ) as client_cls,
        ):
            client_cls.return_value.search = AsyncMock(
                side_effect=[SearchEngineError("engine down", 502), []]
            )
            await self._run(registry, "first")
            after = await self._run(registry, "second")

        # No rephrasing fixes a dead engine, so that attempt costs nothing.
        self.assertIn("attempt 1 of 2", after.result["result"])

    async def test_every_page_irrelevant_asks_for_a_different_query(self):
        llm = MagicMock(inference=AsyncMock())
        llm.inference.side_effect = [
            SimpleNamespace(text="IRRELEVANT"),
            SimpleNamespace(text="IRRELEVANT"),
        ]
        with (
            self._tool_module_patch("searxng", summarize=True),
            patch(
                "src.infrastructure.tools.tool_registry_static.SearchServiceClient"
            ) as client_cls,
        ):
            client_cls.return_value.search = AsyncMock(
                return_value=_results(
                    ("Blog", "https://one", "a"), ("Forum", "https://two", "b")
                )
            )
            result = await self._run(self._registry("searxng", llm=llm), "q")

        # The pages existed but answered nothing: same dead end, and the
        # agent never sees the word IRRELEVANT.
        self.assertTrue(result.success, result.error_message)
        self.assertIn("no relevant content", result.result["result"])
        self.assertIn("attempt 1 of 3", result.result["result"])
        self.assertNotIn("IRRELEVANT", result.result["result"])

    async def test_summarized_search_returns_the_best_page_summary(self):
        llm = MagicMock(inference=AsyncMock())
        llm.inference.side_effect = [
            SimpleNamespace(text="sum 1"),
            SimpleNamespace(text="sum 2"),
            SimpleNamespace(text="sum 3"),
            SimpleNamespace(text="SELECT: 1,2"),
        ]
        with (
            self._tool_module_patch("searxng", summarize=True),
            patch(
                "src.infrastructure.tools.tool_registry_static.SearchServiceClient"
            ) as client_cls,
        ):
            client_cls.return_value.search = AsyncMock(
                return_value=_results(
                    ("First", "https://one", "first full text"),
                    ("Second", "https://two", "second full text"),
                    ("Third", "https://three", "third full text"),
                )
            )
            result = await self._run(self._registry("searxng", llm=llm), "q")

        # The summary stands in for the page: the agent reads "sum 2",
        # not "second full text".
        self.assertTrue(result.success, result.error_message)
        self.assertEqual(result.result["result"], "- Second: sum 2 (https://two)")
        self.assertEqual(llm.inference.await_count, 4)  # 3 summaries + 1 selection

    async def test_summaries_are_returned_in_relevance_order(self):
        llm = MagicMock(inference=AsyncMock())
        llm.inference.side_effect = [
            SimpleNamespace(text="sum 1"),
            SimpleNamespace(text="sum 2"),
            SimpleNamespace(text="sum 3"),
            SimpleNamespace(text="SELECT: 2,0"),
        ]
        with (
            self._tool_module_patch("searxng", summarize=True, summarize_top=3),
            patch(
                "src.infrastructure.tools.tool_registry_static.SearchServiceClient"
            ) as client_cls,
        ):
            client_cls.return_value.search = AsyncMock(
                return_value=_results(
                    ("First", "https://one", "a"),
                    ("Second", "https://two", "b"),
                    ("Third", "https://three", "c"),
                )
            )
            result = await self._run(self._registry("searxng", llm=llm), "q")

        # Ranking order, not engine order — and the unranked page is out.
        self.assertTrue(result.success, result.error_message)
        self.assertEqual(
            result.result["result"],
            "- Third: sum 3 (https://three)\n- First: sum 1 (https://one)",
        )

    async def test_discarded_sources_are_logged_not_returned(self):
        llm = MagicMock(inference=AsyncMock())
        llm.inference.side_effect = [
            SimpleNamespace(text="sum 1"),
            SimpleNamespace(text="sum 2"),
            SimpleNamespace(text="SELECT: 1"),
        ]
        registry = self._registry("searxng", llm=llm)
        with (
            self._tool_module_patch("searxng", summarize=True),
            patch(
                "src.infrastructure.tools.tool_registry_static.SearchServiceClient"
            ) as client_cls,
            self.assertLogs("src.shared.logger._logger", level="DEBUG") as logs,
        ):
            client_cls.return_value.search = AsyncMock(
                return_value=_results(
                    ("First", "https://one", "a"),
                    ("Second", "https://two", "b"),
                )
            )
            result = await self._run(registry, "q")

        self.assertTrue(result.success, result.error_message)
        self.assertEqual(result.result["result"], "- Second: sum 2 (https://two)")
        self.assertTrue(
            any("discarded 1 source(s)" in message for message in logs.output)
        )
        self.assertIn("First (https://one)", "".join(logs.output))

    async def test_summarizer_failure_falls_back_to_raw_results(self):
        llm = MagicMock(inference=AsyncMock())
        with (
            self._tool_module_patch("searxng", summarize=True),
            patch(
                "src.infrastructure.tools.tool_registry_static.SearchServiceClient"
            ) as client_cls,
            patch(
                "src.infrastructure.tools.tool_registry_static.SearchResultsSummarizer"
            ) as summarizer_cls,
        ):
            client_cls.return_value.search = AsyncMock(
                return_value=_results(
                    ("First", "https://one", "a"), ("Second", "https://two", "b")
                )
            )
            summarizer_cls.return_value.best = AsyncMock(
                side_effect=RuntimeError("boom")
            )
            result = await self._run(self._registry("searxng", llm=llm), "q")

        self.assertTrue(result.success, result.error_message)
        self.assertEqual(
            result.result["result"],
            "- First: a (https://one)\n- Second: b (https://two)",
        )


if __name__ == "__main__":
    unittest.main()

# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""The web_search tool reduces the engine's hits before the agent reads them.

The query goes to whichever engine ``config.yaml`` names
(``web_search.provider``) through the ``SearchServiceClient`` facade. Every
page is rendered and summarized, then ranked, and the agent gets the top
``summarize_top`` summaries as ``title: summary (url)`` lines. There is no
LLM-native fallback: an unset provider and a dead engine degrade into a
"do NOT retry" result the agent can read, and neither reaches an
inference.

A search that simply finds nothing is treated as a query problem
instead: the agent is answered with the reason and a nudge to search
again with a different query. The retry budget is the agent loop's own
``orchestration.max_tool_agent_executions``.

A summarizer that fails drops back to the raw hits.
"""

import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from src.domains.dto import ToolCallDTO
from src.domains.value_objects import SearchResult
from src.infrastructure.exceptions import SearchEngineError
from src.infrastructure.external.search_summarizer_service import (
    SearchResultsSummarizer,
)
from src.infrastructure.templates.template_adapter import TemplateAdapter
from src.infrastructure.tools.tool_registry_static import ToolRegistryStatic
from src.shared.constants import TerraformProvider


def _results(*tuples: tuple[str, str, str]) -> list[SearchResult]:
    return [
        SearchResult(title=title, url=url, content=content)
        for title, url, content in tuples
    ]


class TestWebSearchTool(unittest.IsolatedAsyncioTestCase):
    def _registry(
        self,
        provider: str,
        llm: MagicMock | None = None,
        summarize_top: int = 1,
    ):
        """Build the registry and its summarizer under patched settings.

        The summarizer reads ``web_search`` once, when it is built, so
        ``summarize_top`` has to be set here rather than at call time.
        """
        with self._tool_module_patch(provider, summarize_top):
            summarizer = SearchResultsSummarizer(
                llm or MagicMock(inference=AsyncMock()),
                TemplateAdapter(template_provider=TerraformProvider.AWS, cwd="."),
            )
            return ToolRegistryStatic(summarizer=summarizer)

    async def _run(self, registry: ToolRegistryStatic, query: str):
        return await registry.execute_tool(
            ToolCallDTO(id="call_1", name="web_search", parameters={"query": query})
        )

    @contextmanager
    def _tool_module_patch(
        self,
        provider: str,
        summarize_top: int = 1,
    ):
        """system_config is re-read by the handler on every call.

        The summarizer reads its own module-level ``system_config`` when
        it is built, so both modules are patched with the same settings —
        otherwise the real ``summarize_top`` would decide how many
        summaries the tool returns.
        """
        config = MagicMock()
        config.web_search.provider = provider
        config.web_search.summarize_top = summarize_top
        config.web_search.summarize_max_chars = 1200
        with (
            patch(
                "src.infrastructure.tools.tool_registry_static.system_config",
                config,
            ),
            patch(
                "src.infrastructure.external.search_summarizer_service.system_config",
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
        results = results if results is not None else _results()
        if llm is None:
            llm = MagicMock(inference=AsyncMock())
            # Faithful default: each page's summary is its own content and
            # the ranking keeps every page, so the search succeeds.
            llm.inference.side_effect = [
                *(SimpleNamespace(text=r.content) for r in results),
                SimpleNamespace(
                    text="SELECT: " + ",".join(str(i) for i in range(len(results)))
                ),
            ]
        registry = self._registry("searxng", llm=llm, summarize_top=len(results) or 1)
        with (
            self._tool_module_patch("searxng", summarize_top=len(results) or 1),
            patch(
                "src.infrastructure.tools.tool_registry_static.SearchServiceClient"
            ) as client_cls,
        ):
            client_cls.return_value.search = AsyncMock(
                return_value=results,
                side_effect=side_effect,
            )
            return await self._run(registry, query), llm

    async def test_results_are_formatted_one_line_per_hit(self):
        llm = MagicMock(inference=AsyncMock())
        llm.inference.side_effect = [
            SimpleNamespace(text="s3 bucket docs"),
            SimpleNamespace(text="SELECT: 0"),
        ]
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
            result = await self._run(
                self._registry("searxng", llm=llm), "terraform s3 bucket"
            )

        self.assertTrue(result.success, result.error_message)
        self.assertEqual(
            result.result["result"],
            "- Terraform Registry: s3 bucket docs (https://registry.terraform.io)",
        )

    async def test_multiple_results_are_joined_in_engine_order(self):
        llm = MagicMock(inference=AsyncMock())
        llm.inference.side_effect = [
            SimpleNamespace(text="a"),
            SimpleNamespace(text="b"),
            SimpleNamespace(text="c"),
            SimpleNamespace(text="SELECT: 0,1,2"),
        ]
        with (
            self._tool_module_patch("searxng", summarize_top=3),
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
            result = await self._run(
                self._registry("searxng", llm=llm, summarize_top=3), "q"
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
        self.assertIn("different query", result.result["result"])
        llm.inference.assert_not_awaited()

    async def test_every_page_irrelevant_asks_for_a_different_query(self):
        llm = MagicMock(inference=AsyncMock())
        llm.inference.side_effect = [
            SimpleNamespace(text="IRRELEVANT"),
            SimpleNamespace(text="IRRELEVANT"),
        ]
        with (
            self._tool_module_patch("searxng"),
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
            self._tool_module_patch("searxng"),
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
            self._tool_module_patch("searxng", summarize_top=3),
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
            result = await self._run(
                self._registry("searxng", llm=llm, summarize_top=3), "q"
            )

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
            self._tool_module_patch("searxng"),
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
        summarizer = MagicMock(best=AsyncMock(side_effect=RuntimeError("boom")))
        with (
            self._tool_module_patch("searxng"),
            patch(
                "src.infrastructure.tools.tool_registry_static.SearchServiceClient"
            ) as client_cls,
        ):
            client_cls.return_value.search = AsyncMock(
                return_value=_results(
                    ("First", "https://one", "a"), ("Second", "https://two", "b")
                )
            )
            registry = ToolRegistryStatic(summarizer=summarizer)
            result = await self._run(registry, "q")

        self.assertTrue(result.success, result.error_message)
        self.assertEqual(
            result.result["result"],
            "- First: a (https://one)\n- Second: b (https://two)",
        )


if __name__ == "__main__":
    unittest.main()

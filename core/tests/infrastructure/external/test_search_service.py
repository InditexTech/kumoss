# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""The web-search facade.

``SearchServiceClient`` is the thin seam between the core and whichever
search backend ``config.yaml`` names (SearXNG, Tavily, Brave, ...). Every
call is delegated to the LiteLLM unified search API with the configured
provider, endpoint and limits; an unreachable or misbehaving engine is
never surfaced raw — it is translated into the typed ``SearchEngineError``
the ``web_search`` tool turns into a "do not retry" result.
"""

import unittest
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

from src.infrastructure.external.search_service import (
    SearchEngineError,
    SearchServiceClient,
)


@dataclass(frozen=True)
class _FakeResult:
    title: str
    url: str
    snippet: str


def _config(
    provider: str,
    endpoint: str = "http://searxng:8888",
    max_results: int = 10,
) -> MagicMock:
    config = MagicMock()
    config.web_search.provider = provider
    config.web_search.endpoint = endpoint
    config.web_search.timeout = 30.0
    config.web_search.max_results = max_results
    return config


class TestSearchServiceClient(unittest.IsolatedAsyncioTestCase):
    async def test_delegates_to_litellm_with_the_configured_provider(self):
        client = SearchServiceClient()
        fake = MagicMock()
        fake.results = [_FakeResult("Title", "https://x", "snippet")]

        with (
            patch(
                "src.infrastructure.external.search_service.system_config",
                _config("searxng"),
            ),
            patch(
                "src.infrastructure.external.search_service.litellm.asearch",
                AsyncMock(return_value=fake),
            ) as asearch,
        ):
            results = await client.search("terraform s3")

        self.assertEqual(asearch.call_args.kwargs["query"], "terraform s3")
        self.assertEqual(asearch.call_args.kwargs["search_provider"], "searxng")
        self.assertEqual(asearch.call_args.kwargs["api_base"], "http://searxng:8888")
        self.assertEqual(asearch.call_args.kwargs["max_results"], 10)
        self.assertEqual(asearch.call_args.kwargs["timeout"], 30.0)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].title, "Title")
        self.assertEqual(results[0].url, "https://x")
        self.assertEqual(results[0].snippet, "snippet")

    async def test_maps_the_response_dot_results_list(self):
        client = SearchServiceClient()
        fake = MagicMock()
        fake.results = [
            _FakeResult("T1", "https://a", "s1"),
            _FakeResult("T2", "https://b", "s2"),
        ]

        with (
            patch(
                "src.infrastructure.external.search_service.system_config",
                _config("searxng"),
            ),
            patch(
                "src.infrastructure.external.search_service.litellm.asearch",
                AsyncMock(return_value=fake),
            ),
        ):
            results = await client.search("q")

        self.assertEqual([r.url for r in results], ["https://a", "https://b"])

    async def test_empty_and_none_result_lists_become_empty(self):
        client = SearchServiceClient()
        for payload in ([], None):
            fake = MagicMock()
            fake.results = payload

            with (
                patch(
                    "src.infrastructure.external.search_service.system_config",
                    _config("searxng"),
                ),
                patch(
                    "src.infrastructure.external.search_service.litellm.asearch",
                    AsyncMock(return_value=fake),
                ),
            ):
                self.assertEqual(await client.search("q"), [])

    async def test_result_cap_is_enforced_locally(self):
        # LiteLLM's SearXNG adapter ignores `max_results` and returns the
        # engine's full first page, so the facade must slice itself.
        client = SearchServiceClient()
        fake = MagicMock()
        fake.results = [
            MagicMock(title=f"T{i}", url=f"https://{i}", snippet="s") for i in range(20)
        ]

        with (
            patch(
                "src.infrastructure.external.search_service.system_config",
                _config("searxng", max_results=5),
            ),
            patch(
                "src.infrastructure.external.search_service.litellm.asearch",
                AsyncMock(return_value=fake),
            ),
        ):
            results = await client.search("q")

        self.assertEqual(len(results), 5)
        self.assertEqual([r.title for r in results], ["T0", "T1", "T2", "T3", "T4"])

    async def test_no_provider_configured_raises_typed_error(self):
        client = SearchServiceClient()

        with patch(
            "src.infrastructure.external.search_service.system_config",
            _config(""),
        ):
            with self.assertRaises(SearchEngineError) as ctx:
                await client.search("q")

        self.assertIn("web_search.provider", ctx.exception.message)

    async def test_engine_failure_raises_a_typed_error(self):
        client = SearchServiceClient()

        with (
            patch(
                "src.infrastructure.external.search_service.system_config",
                _config("searxng"),
            ),
            patch(
                "src.infrastructure.external.search_service.litellm.asearch",
                AsyncMock(side_effect=ConnectionError("boom")),
            ),
        ):
            with self.assertRaises(SearchEngineError) as ctx:
                await client.search("q")

        self.assertIn("searxng", ctx.exception.message)

    async def test_empty_endpoint_passes_api_base_as_none(self):
        # A hosted provider needs no endpoint; the facade must not forward
        # an empty string as LiteLLM's `api_base`.
        client = SearchServiceClient()
        fake = MagicMock()
        fake.results = []

        with (
            patch(
                "src.infrastructure.external.search_service.system_config",
                _config("tavily", endpoint=""),
            ),
            patch(
                "src.infrastructure.external.search_service.litellm.asearch",
                AsyncMock(return_value=fake),
            ) as asearch,
        ):
            await client.search("q")

        self.assertIsNone(asearch.call_args.kwargs["api_base"])

    async def test_result_fields_missing_on_the_engine_object_default_to(self):
        # Results come from arbitrary providers; an object without
        # `title`/`url`/`snippet` (or with falsy values) must still map,
        # never crash.
        client = SearchServiceClient()
        fake = MagicMock()
        bare = object()
        fake.results = [bare, _FakeResult("Kept", "https://x", "")]

        with (
            patch(
                "src.infrastructure.external.search_service.system_config",
                _config("searxng"),
            ),
            patch(
                "src.infrastructure.external.search_service.litellm.asearch",
                AsyncMock(return_value=fake),
            ),
        ):
            results = await client.search("q")

        self.assertEqual(
            [(r.title, r.url, r.snippet) for r in results],
            [("", "", ""), ("Kept", "https://x", "")],
        )

    async def test_response_without_a_results_attribute_is_empty(self):
        client = SearchServiceClient()
        fake = object()  # no `results` attribute at all

        with (
            patch(
                "src.infrastructure.external.search_service.system_config",
                _config("searxng"),
            ),
            patch(
                "src.infrastructure.external.search_service.litellm.asearch",
                AsyncMock(return_value=fake),
            ),
        ):
            self.assertEqual(await client.search("q"), [])

    async def test_engine_failure_message_does_not_leak_the_error(self):
        # The typed message is generic: the raw backend exception text
        # (which can carry internal URLs or credentials) stays in the log.
        client = SearchServiceClient()

        with (
            patch(
                "src.infrastructure.external.search_service.system_config",
                _config("tavily"),
            ),
            patch(
                "src.infrastructure.external.search_service.litellm.asearch",
                AsyncMock(side_effect=RuntimeError("secret token abc leaked")),
            ),
            self.assertRaises(SearchEngineError) as ctx,
        ):
            await client.search("q")

        self.assertNotIn("abc", ctx.exception.message)
        self.assertIn("tavily", ctx.exception.message)

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

Each hit's page is then read and reduced to text. That read is best
effort: the cases below pin that a page which will not fetch or parse
costs its own hit the body and nothing more, leaving the engine snippet
in its place. ``httpx`` is stubbed throughout — no case may touch the
network.
"""

import asyncio
import unittest
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

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
    max_page_chars: int = 6000,
) -> MagicMock:
    config = MagicMock()
    config.web_search.provider = provider
    config.web_search.endpoint = endpoint
    config.web_search.timeout = 30.0
    config.web_search.max_results = max_results
    config.web_search.max_page_chars = max_page_chars
    return config


def _fake_httpx(get: AsyncMock) -> MagicMock:
    """Stand in for the ``httpx.AsyncClient`` context manager."""
    client = MagicMock()
    client.get = get
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=client)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=ctx)


def _page(body: str = "<html><body>ignored</body></html>") -> AsyncMock:
    """An ``AsyncClient.get`` that answers 200 with ``body``."""
    response = MagicMock()
    response.text = body
    response.raise_for_status = MagicMock()
    return AsyncMock(return_value=response)


def _unreachable() -> AsyncMock:
    return AsyncMock(side_effect=httpx.ConnectError("offline"))


class _OfflineCase(unittest.IsolatedAsyncioTestCase):
    """Base case: every page read fails, so content is the snippet.

    Keeps the engine-delegation cases focused on the search call without
    letting a page read escape to the network.
    """

    def setUp(self) -> None:
        patcher = patch(
            "src.infrastructure.external.search_service.httpx.AsyncClient",
            _fake_httpx(_unreachable()),
        )
        patcher.start()
        self.addCleanup(patcher.stop)


class TestSearchServiceClient(_OfflineCase):
    async def test_delegates_to_litellm_with_the_configured_provider(self):
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
            results = await SearchServiceClient().search("terraform s3")

        self.assertEqual(asearch.call_args.kwargs["query"], "terraform s3")
        self.assertEqual(asearch.call_args.kwargs["search_provider"], "searxng")
        self.assertEqual(asearch.call_args.kwargs["api_base"], "http://searxng:8888")
        self.assertEqual(asearch.call_args.kwargs["timeout"], 30.0)
        # `max_results` is deliberately not forwarded: the adapter ignores
        # it and returns the engine's full first page either way, so the
        # cap is applied here instead (see the slicing case below).
        self.assertNotIn("max_results", asearch.call_args.kwargs)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].title, "Title")
        self.assertEqual(results[0].url, "https://x")
        self.assertEqual(results[0].content, "snippet")

    async def test_maps_the_response_dot_results_list(self):
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
            results = await SearchServiceClient().search("q")

        self.assertEqual([r.url for r in results], ["https://a", "https://b"])

    async def test_empty_and_none_result_lists_become_empty(self):
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
                self.assertEqual(await SearchServiceClient().search("q"), [])

    async def test_result_cap_is_enforced_locally(self):
        # LiteLLM's SearXNG adapter ignores `max_results` and returns the
        # engine's full first page, so the facade must slice itself.
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
            results = await SearchServiceClient().search("q")

        self.assertEqual(len(results), 5)
        self.assertEqual([r.title for r in results], ["T0", "T1", "T2", "T3", "T4"])

    async def test_no_provider_configured_raises_typed_error(self):

        with patch(
            "src.infrastructure.external.search_service.system_config",
            _config(""),
        ):
            with self.assertRaises(SearchEngineError) as ctx:
                await SearchServiceClient().search("q")

        self.assertIn("web_search.provider", ctx.exception.message)

    async def test_engine_failure_raises_a_typed_error(self):

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
                await SearchServiceClient().search("q")

        self.assertIn("searxng", ctx.exception.message)

    async def test_empty_endpoint_passes_api_base_as_none(self):
        # A hosted provider needs no endpoint; the facade must not forward
        # an empty string as LiteLLM's `api_base`.
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
            await SearchServiceClient().search("q")

        self.assertIsNone(asearch.call_args.kwargs["api_base"])

    async def test_result_fields_missing_on_the_engine_object_default_to(self):
        # Results come from arbitrary providers; an object without
        # `title`/`url`/`snippet` (or with falsy values) must still map,
        # never crash.
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
            results = await SearchServiceClient().search("q")

        self.assertEqual(
            [(r.title, r.url, r.content) for r in results],
            [("", "", ""), ("Kept", "https://x", "")],
        )

    async def test_response_without_a_results_attribute_is_empty(self):
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
            self.assertEqual(await SearchServiceClient().search("q"), [])

    async def test_engine_failure_message_does_not_leak_the_error(self):
        # The typed message is generic: the raw backend exception text
        # (which can carry internal URLs or credentials) stays in the log.

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
            await SearchServiceClient().search("q")

        self.assertNotIn("abc", ctx.exception.message)
        self.assertIn("tavily", ctx.exception.message)


class TestPageReads(unittest.IsolatedAsyncioTestCase):
    """Reading each hit's page, and degrading when that fails."""

    async def _search(self, hits: list[object], get: AsyncMock, **cfg: object):
        response = MagicMock()
        response.results = hits

        with (
            patch(
                "src.infrastructure.external.search_service.system_config",
                _config("searxng", **cfg),  # type: ignore[arg-type]
            ),
            patch(
                "src.infrastructure.external.search_service.litellm.asearch",
                AsyncMock(return_value=response),
            ),
            patch(
                "src.infrastructure.external.search_service.httpx.AsyncClient",
                _fake_httpx(get),
            ),
        ):
            return await SearchServiceClient().search("q")

    async def test_extracted_page_text_replaces_the_snippet(self):
        with patch(
            "src.infrastructure.external.search_service.trafilatura.extract",
            return_value="# The whole page",
        ):
            results = await self._search(
                [_FakeResult("T", "https://a", "thin snippet")], _page()
            )

        self.assertEqual(results[0].content, "# The whole page")

    async def test_an_unreachable_page_falls_back_to_the_snippet(self):
        results = await self._search(
            [_FakeResult("T", "https://a", "thin snippet")], _unreachable()
        )

        self.assertEqual(results[0].content, "thin snippet")

    async def test_a_non_2xx_page_falls_back_to_the_snippet(self):
        get = _page()
        get.return_value.raise_for_status.side_effect = httpx.HTTPStatusError(
            "403", request=MagicMock(), response=MagicMock()
        )

        results = await self._search([_FakeResult("T", "https://a", "snip")], get)

        self.assertEqual(results[0].content, "snip")

    async def test_an_unparseable_page_falls_back_to_the_snippet(self):
        # trafilatura returns None for what it cannot reduce to text
        # (PDFs, JS-only pages).
        with patch(
            "src.infrastructure.external.search_service.trafilatura.extract",
            return_value=None,
        ):
            results = await self._search(
                [_FakeResult("T", "https://a", "snip")], _page()
            )

        self.assertEqual(results[0].content, "snip")

    async def test_a_hit_without_a_url_falls_back_to_the_snippet(self):
        results = await self._search([_FakeResult("T", "", "snip")], _page())

        self.assertEqual(results[0].content, "snip")

    async def test_page_text_is_truncated_to_max_page_chars(self):
        with patch(
            "src.infrastructure.external.search_service.trafilatura.extract",
            return_value="x" * 10_000,
        ):
            results = await self._search(
                [_FakeResult("T", "https://a", "snip")], _page(), max_page_chars=500
            )

        self.assertEqual(results[0].content, "x" * 500)

    async def test_one_bad_page_does_not_cost_the_other_hits(self):
        # The whole point of the per-hit fallback: a single 403 in a page
        # of ten results must not fail the search.
        hits = [_FakeResult(f"T{i}", f"https://{i}", f"snip{i}") for i in range(3)]
        responses = [MagicMock(text="ok"), MagicMock(text="ok"), MagicMock(text="ok")]
        responses[1].raise_for_status.side_effect = httpx.HTTPStatusError(
            "403", request=MagicMock(), response=MagicMock()
        )
        get = AsyncMock(side_effect=responses)

        with patch(
            "src.infrastructure.external.search_service.trafilatura.extract",
            return_value="body",
        ):
            results = await self._search(hits, get)

        self.assertEqual([r.content for r in results], ["body", "snip1", "body"])

    async def test_pages_are_read_concurrently(self):
        # Serialising the reads would multiply the per-request timeout by
        # `max_results`, so they must all be in flight at once.
        in_flight = 0
        peak = 0

        async def _slow(_url: str):
            nonlocal in_flight, peak
            in_flight += 1
            peak = max(peak, in_flight)
            await asyncio.sleep(0)
            in_flight -= 1
            return MagicMock(text="ok")

        hits = [_FakeResult(f"T{i}", f"https://{i}", "s") for i in range(5)]
        with patch(
            "src.infrastructure.external.search_service.trafilatura.extract",
            return_value="body",
        ):
            await self._search(hits, AsyncMock(side_effect=_slow))

        self.assertEqual(peak, 5)

# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""The web-search facade, ported from the core's ``test_search_service.py``.

``SearchServiceClient`` is the thin seam between the core and whichever
search backend ``config.yaml`` names (SearXNG, Tavily, Brave, ...). Every
call is delegated to the LiteLLM unified search API with the configured
provider, endpoint and limits; an unreachable or misbehaving engine is
never surfaced raw — it is translated into the typed ``SearchEngineError``
the HTTP layer turns into a problem response.

Each hit's page is then rendered in headless Chromium and reduced to
markdown. That read is best effort: the cases below pin that a page
which will not render costs its own hit the body and nothing more,
leaving the engine snippet in its place. The page reader is stubbed
throughout — no case may launch a browser or touch the network.

One deliberate difference from the core's file: its
``test_delegates_to_litellm_with_the_configured_provider`` asserted that
``max_results`` is *not* forwarded, but the core's code has forwarded it
since 44cd6baf ("Re-added max_results parameter in litellm.asearch"). The
code is the behaviour this service reproduces, so the case asserts the
forwarded value.
"""

import asyncio
import unittest
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

from src.search_service import SearchEngineError, SearchServiceClient


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
    config.provider = provider
    config.endpoint = endpoint
    config.timeout = 30.0
    config.max_results = max_results
    config.max_page_chars = max_page_chars
    return config


def _reader(
    markdown: str | None = None,
) -> MagicMock:
    """A ``_PageReader`` class stub no browser escapes from.

    With ``markdown``, every page read returns it; without, every read
    raises, so the engine snippet stays.
    """
    stub = MagicMock()
    ctx = stub.return_value
    ctx.__aenter__ = AsyncMock(return_value=ctx)
    ctx.__aexit__ = AsyncMock(return_value=False)
    if markdown is None:
        ctx.read = AsyncMock(side_effect=RuntimeError("no browser"))
    else:
        ctx.read = AsyncMock(return_value=markdown)
    return stub


class _NoCrawlCase(unittest.IsolatedAsyncioTestCase):
    """Base case: every page read fails, so content is the snippet.

    Keeps the engine-delegation cases focused on the search call without
    letting a page read launch Chromium or escape to the network.
    """

    def setUp(self) -> None:
        patcher = patch("src.search_service._PageReader", _reader())
        patcher.start()
        self.addCleanup(patcher.stop)


class TestSearchServiceClient(_NoCrawlCase):
    async def test_delegates_to_litellm_with_the_configured_provider(self):
        fake = MagicMock()
        fake.results = [_FakeResult("Title", "https://x", "snippet")]

        with patch(
            "src.search_service.litellm.asearch", AsyncMock(return_value=fake)
        ) as asearch:
            results = await SearchServiceClient(
                _config("searxng", max_results=7)
            ).search("terraform s3")

        asearch.assert_awaited_once_with(
            query="terraform s3",
            max_results=7,
            search_provider="searxng",
            api_base="http://searxng:8888",
            timeout=30.0,
        )
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

        with patch("src.search_service.litellm.asearch", AsyncMock(return_value=fake)):
            results = await SearchServiceClient(_config("searxng")).search("q")

        self.assertEqual([r.url for r in results], ["https://a", "https://b"])

    async def test_empty_and_none_result_lists_become_empty(self):
        for payload in ([], None):
            fake = MagicMock()
            fake.results = payload

            with patch(
                "src.search_service.litellm.asearch", AsyncMock(return_value=fake)
            ):
                self.assertEqual(
                    await SearchServiceClient(_config("searxng")).search("q"), []
                )

    async def test_no_hits_launch_no_browser(self):
        fake = MagicMock()
        fake.results = []
        reader = _reader("body")

        with (
            patch("src.search_service.litellm.asearch", AsyncMock(return_value=fake)),
            patch("src.search_service._PageReader", reader),
        ):
            await SearchServiceClient(_config("searxng")).search("q")

        self.assertEqual(reader.call_count, 0)

    async def test_result_cap_is_enforced_locally(self):
        # LiteLLM's SearXNG adapter ignores `max_results` and returns the
        # engine's full first page, so the facade must slice itself.
        fake = MagicMock()
        fake.results = [
            MagicMock(title=f"T{i}", url=f"https://{i}", snippet="s") for i in range(20)
        ]

        with patch("src.search_service.litellm.asearch", AsyncMock(return_value=fake)):
            results = await SearchServiceClient(
                _config("searxng", max_results=5)
            ).search("q")

        self.assertEqual(len(results), 5)
        self.assertEqual([r.title for r in results], ["T0", "T1", "T2", "T3", "T4"])

    async def test_no_provider_configured_raises_typed_error(self):
        with patch("src.search_service.litellm.asearch", AsyncMock()) as asearch:
            with self.assertRaises(SearchEngineError) as ctx:
                await SearchServiceClient(_config("")).search("q")

        self.assertEqual(
            ctx.exception.message,
            "no search engine is configured (web_search.provider is empty in "
            "config.yaml)",
        )
        self.assertEqual(ctx.exception.error_code, 400)
        asearch.assert_not_awaited()

    async def test_engine_failure_raises_a_typed_error(self):
        with patch(
            "src.search_service.litellm.asearch",
            AsyncMock(side_effect=ConnectionError("boom")),
        ):
            with self.assertLogs("src.logger._logger", level="ERROR") as logs:
                with self.assertRaises(SearchEngineError) as ctx:
                    await SearchServiceClient(_config("searxng")).search("q")

        self.assertEqual(
            ctx.exception.message, "the 'searxng' search engine call failed"
        )
        self.assertEqual(ctx.exception.error_code, 502)
        self.assertIn(
            "Web search via searxng failed: ConnectionError('boom')",
            "".join(logs.output),
        )

    async def test_empty_endpoint_passes_api_base_as_none(self):
        # A hosted provider needs no endpoint; the facade must not forward
        # an empty string as LiteLLM's `api_base`.
        fake = MagicMock()
        fake.results = []

        with patch(
            "src.search_service.litellm.asearch", AsyncMock(return_value=fake)
        ) as asearch:
            await SearchServiceClient(_config("tavily", endpoint="")).search("q")

        self.assertIsNone(asearch.call_args.kwargs["api_base"])

    async def test_result_fields_missing_on_the_engine_object_default_to(self):
        # Results come from arbitrary providers; an object without
        # `title`/`url`/`snippet` (or with falsy values) must still map,
        # never crash.
        fake = MagicMock()
        bare = object()
        fake.results = [bare, _FakeResult("Kept", "https://x", "")]

        with patch("src.search_service.litellm.asearch", AsyncMock(return_value=fake)):
            results = await SearchServiceClient(_config("searxng")).search("q")

        self.assertEqual(
            [(r.title, r.url, r.content) for r in results],
            [("", "", ""), ("Kept", "https://x", "")],
        )

    async def test_response_without_a_results_attribute_is_empty(self):
        fake = object()  # no `results` attribute at all

        with patch("src.search_service.litellm.asearch", AsyncMock(return_value=fake)):
            self.assertEqual(
                await SearchServiceClient(_config("searxng")).search("q"), []
            )

    async def test_engine_failure_message_does_not_leak_the_error(self):
        # The typed message is generic: the raw backend exception text
        # (which can carry internal URLs or credentials) stays in the log.
        with (
            patch(
                "src.search_service.litellm.asearch",
                AsyncMock(side_effect=RuntimeError("secret token abc leaked")),
            ),
            self.assertRaises(SearchEngineError) as ctx,
        ):
            await SearchServiceClient(_config("tavily")).search("q")

        self.assertNotIn("abc", ctx.exception.message)
        self.assertIn("tavily", ctx.exception.message)


class TestPageReads(unittest.IsolatedAsyncioTestCase):
    """Rendering each hit's page in Chromium, and degrading when that
    fails."""

    async def _search(
        self,
        hits: list[object],
        reader: MagicMock | None = None,
        **cfg: object,
    ):
        response = MagicMock()
        response.results = hits

        with (
            patch(
                "src.search_service.litellm.asearch",
                AsyncMock(return_value=response),
            ),
            patch("src.search_service._PageReader", reader or _reader()),
        ):
            return await SearchServiceClient(
                _config("searxng", **cfg)  # type: ignore[arg-type]
            ).search("q")

    async def test_rendered_markdown_replaces_the_snippet(self):
        results = await self._search(
            [_FakeResult("T", "https://a", "thin snippet")], _reader("# the page")
        )

        self.assertEqual(results[0].content, "# the page")

    async def test_the_hit_url_is_read_with_the_configured_timeout(self):
        reader = _reader("body")

        await self._search([_FakeResult("T", "https://a", "snip")], reader)

        read = reader.return_value.read
        self.assertEqual(read.call_args.args, ("https://a", 30.0))

    async def test_each_read_is_bounded_by_wait_for_with_the_timeout(self):
        reader = _reader("body")
        real_wait_for = asyncio.wait_for

        with patch(
            "src.search_service.asyncio.wait_for", side_effect=real_wait_for
        ) as wait_for:
            await self._search([_FakeResult("T", "https://a", "snip")], reader)

        self.assertEqual(wait_for.call_count, 1)
        self.assertEqual(wait_for.call_args.args[1], 30.0)

    async def test_a_hung_read_times_out_into_the_snippet(self):
        async def _hang(_url: str, _timeout: float):
            await asyncio.sleep(3600)

        reader = _reader()
        reader.return_value.read = AsyncMock(side_effect=_hang)
        cfg = _config("searxng")
        cfg.timeout = 0.05
        response = MagicMock()
        response.results = [_FakeResult("T", "https://a", "snip")]

        with (
            patch(
                "src.search_service.litellm.asearch", AsyncMock(return_value=response)
            ),
            patch("src.search_service._PageReader", reader),
        ):
            results = await SearchServiceClient(cfg).search("q")

        self.assertEqual(results[0].content, "snip")

    async def test_a_failed_read_falls_back_to_the_snippet(self):
        results = await self._search(
            [_FakeResult("T", "https://a", "thin snippet")], _reader()
        )

        self.assertEqual(results[0].content, "thin snippet")

    async def test_a_failed_read_is_logged_with_its_cause(self):
        # The warning is the only trace a dropped page leaves, so it has
        # to say *why*: a rejected certificate, a refused connection and
        # a timeout are one undiagnosable "could not render" otherwise.
        reader = _reader()
        reader.return_value.read = AsyncMock(
            side_effect=RuntimeError(
                "[SSL: CERTIFICATE_VERIFY_FAILED] self-signed certificate"
            )
        )

        with self.assertLogs("src.logger._logger", level="WARNING") as logs:
            await self._search([_FakeResult("T", "https://a", "snip")], reader)

        logged = "".join(logs.output)
        self.assertIn("CERTIFICATE_VERIFY_FAILED", logged)
        self.assertIn("RuntimeError", logged)
        self.assertIn("https://a", logged)
        self.assertIn(
            "Page read for 'https://a' failed, falling back to the engine "
            "snippet: RuntimeError('[SSL: CERTIFICATE_VERIFY_FAILED] "
            "self-signed certificate') (None)",
            logged,
        )

    async def test_a_hit_without_a_url_falls_back_to_the_snippet(self):
        # The reader never sees the empty url: the facade must not spend
        # a browser context on a hit the engine already sent without one.
        reader = _reader("body")

        results = await self._search([_FakeResult("T", "", "snip")], reader)

        self.assertEqual(results[0].content, "snip")
        self.assertEqual(reader.return_value.read.call_count, 0)

    async def test_page_text_is_truncated_to_max_page_chars(self):
        results = await self._search(
            [_FakeResult("T", "https://a", "snip")],
            _reader("x" * 10_000),
            max_page_chars=500,
        )

        self.assertEqual(results[0].content, "x" * 500)

    async def test_one_bad_page_does_not_cost_the_other_hits(self):
        # The whole point of the per-hit fallback: a single dead link in a
        # page of ten results must not fail the search.
        hits = [_FakeResult(f"T{i}", f"https://{i}", f"snip{i}") for i in range(3)]
        reader = _reader()
        reader.return_value.read = AsyncMock(
            side_effect=["body", RuntimeError("dead"), "body"]
        )

        results = await self._search(hits, reader)

        self.assertEqual([r.content for r in results], ["body", "snip1", "body"])

    async def test_pages_are_read_concurrently(self):
        # Serialising the reads would multiply the per-page timeout by
        # `max_results`, so they must all be in flight at once — and the
        # facade must still run them through one reader, not one reader
        # per page.
        in_flight = 0
        peak = 0

        async def _slow(_url: str, _timeout: float):
            nonlocal in_flight, peak
            in_flight += 1
            peak = max(peak, in_flight)
            await asyncio.sleep(0)
            in_flight -= 1
            return "body"

        reader = _reader()
        reader.return_value.read = AsyncMock(side_effect=_slow)
        hits = [_FakeResult(f"T{i}", f"https://{i}", "s") for i in range(5)]

        await self._search(hits, reader)

        self.assertEqual(peak, 5)
        self.assertEqual(reader.call_count, 1)


if __name__ == "__main__":
    unittest.main()

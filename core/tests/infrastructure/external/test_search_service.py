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

Each hit's page is then fetched and reduced to
markdown. That read is best effort: the cases below pin that a page
which will not fetch costs its own hit the body and nothing more,
leaving the engine snippet in its place. The page reader is stubbed
throughout — no case may touch the network.
"""

import asyncio
import unittest
from dataclasses import dataclass
from typing import Any, override
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from src.infrastructure.external import search_service
from src.infrastructure.external.search_service import (
    SearchEngineError,
    SearchServiceClient,
    _PageReader,
)
from src.infrastructure.exceptions import PageReadError


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


def _reader(
    markdown: str | None = None,
) -> MagicMock:
    """A ``_PageReader`` class stub no request escapes from.

    With ``markdown``, every page read returns it; without, every read
    raises, so the engine snippet stays.
    """
    stub = MagicMock()
    ctx = stub.return_value
    ctx.__aenter__ = AsyncMock(return_value=ctx)
    ctx.__aexit__ = AsyncMock(return_value=False)
    if markdown is None:
        ctx.read = AsyncMock(side_effect=RuntimeError("no network"))
    else:
        ctx.read = AsyncMock(return_value=markdown)
    return stub


class _NoCrawlCase(unittest.IsolatedAsyncioTestCase):
    """Base case: every page read fails, so content is the snippet.

    Keeps the engine-delegation cases focused on the search call without
    letting a page read escape to the network.
    """

    def setUp(self) -> None:
        patcher = patch(
            "src.infrastructure.external.search_service._PageReader",
            _reader(),
        )
        patcher.start()
        self.addCleanup(patcher.stop)


class TestSearchServiceClient(_NoCrawlCase):
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
    """Fetching each hit's page, and degrading when that fails."""

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
                "src.infrastructure.external.search_service.system_config",
                _config("searxng", **cfg),  # type: ignore[arg-type]
            ),
            patch(
                "src.infrastructure.external.search_service.litellm.asearch",
                AsyncMock(return_value=response),
            ),
            patch(
                "src.infrastructure.external.search_service._PageReader",
                reader or _reader(),
            ),
        ):
            return await SearchServiceClient().search("q")

    async def test_extracted_markdown_replaces_the_snippet(self):
        results = await self._search(
            [_FakeResult("T", "https://a", "thin snippet")], _reader("# the page")
        )

        self.assertEqual(results[0].content, "# the page")

    async def test_the_hit_url_is_read_with_the_configured_timeout(self):
        reader = _reader("body")

        await self._search([_FakeResult("T", "https://a", "snip")], reader)

        read = reader.return_value.read
        self.assertEqual(read.call_args.args, ("https://a", 30.0))

    async def test_a_failed_read_falls_back_to_the_snippet(self):
        results = await self._search(
            [_FakeResult("T", "https://a", "thin snippet")], _reader()
        )

        self.assertEqual(results[0].content, "thin snippet")

    async def test_a_failed_read_is_logged_with_its_cause(self):
        # The warning is the only trace a dropped page leaves, so it has
        # to say *why*: a rejected certificate, a refused connection and
        # a timeout are one undiagnosable "could not fetch" otherwise.
        reader = _reader()
        reader.return_value.read = AsyncMock(
            side_effect=RuntimeError(
                "[SSL: CERTIFICATE_VERIFY_FAILED] self-signed certificate"
            )
        )

        with self.assertLogs("src.shared.logger._logger", level="WARNING") as logs:
            await self._search([_FakeResult("T", "https://a", "snip")], reader)

        logged = "".join(logs.output)
        self.assertIn("CERTIFICATE_VERIFY_FAILED", logged)
        self.assertIn("RuntimeError", logged)
        self.assertIn("https://a", logged)

    async def test_a_hit_without_a_url_falls_back_to_the_snippet(self):
        # The reader never sees the empty url: the facade must not spend
        # a request on a hit the engine already sent without one.
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


_ARTICLE = (
    "<html><head><title>S3 backend</title></head><body><article>"
    + "<h1>S3 backend</h1>"
    + "<p>Stores the Terraform state as a given key in a given bucket on "
    + "Amazon S3. This backend also supports state locking, which can be "
    + "enabled by setting the use_lockfile argument to true.</p>" * 5
    + "</article></body></html>"
).encode()


class _Body(httpx.AsyncByteStream):
    """A response body that counts how many chunks were pulled from it."""

    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks: list[bytes] = chunks
        self.pulled: int = 0

    @override
    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in self.chunks:
            self.pulled += 1
            yield chunk


class TestPageReader(unittest.IsolatedAsyncioTestCase):
    """The real reader, over a mock transport: what it buffers, and what
    it refuses before buffering it."""

    async def _read(self, body: _Body, headers: dict[str, str]) -> str:
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, headers=headers, stream=body)

        real = httpx.AsyncClient

        def client(**kw: Any) -> httpx.AsyncClient:
            return real(transport=httpx.MockTransport(handler), **kw)

        with patch.object(search_service.httpx, "AsyncClient", client):
            async with _PageReader() as reader:
                return await reader.read("https://a", 30.0)

    async def test_an_html_page_is_reduced_to_markdown(self):
        body = _Body([_ARTICLE])

        text = await self._read(body, {"content-type": "text/html; charset=utf-8"})

        self.assertIn("state locking", text)

    async def test_a_page_without_a_content_type_is_still_read(self):
        text = await self._read(_Body([_ARTICLE]), {})

        self.assertIn("state locking", text)

    async def test_a_non_html_body_is_refused_before_it_is_read(self):
        body = _Body([b"%PDF-1.7"] * 3)

        with self.assertRaises(PageReadError) as ctx:
            _ = await self._read(body, {"content-type": "application/pdf"})

        self.assertEqual(ctx.exception.error_code, 415)
        self.assertEqual(body.pulled, 0)

    async def test_an_oversized_body_stops_downloading_at_the_cap(self):
        # The cap is what bounds memory: reading must stop at the chunk
        # that crosses it, not after the whole body has arrived.
        body = _Body([b"<p>xxxx</p>"] * 10)

        with (
            patch.object(_PageReader, "MAX_PAGE_BYTES", 20),
            self.assertRaises(PageReadError) as ctx,
        ):
            _ = await self._read(body, {"content-type": "text/html"})

        self.assertEqual(ctx.exception.error_code, 413)
        self.assertEqual(body.pulled, 2)

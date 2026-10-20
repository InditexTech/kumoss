# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Web-search facade used by the core's ``web_search`` tool.

Delegates to the LiteLLM unified search API (``litellm.asearch``) so the
search backend is swappable from ``config.yaml`` (SearXNG, Tavily, Brave,
Perplexity, ...), then reads each hit's page. Engine snippets are a
sentence or two, too thin for the provider-documentation lookups the
agents make, so each page is rendered in headless Chromium (Playwright)
and reduced to markdown with trafilatura: the render executes the page's
JavaScript, and Chromium carries the browser fingerprint bot protection
expects.

Degrades in layers, mirroring the pattern used by ``AuthzServiceClient``:
a page that will not render or extract falls back to the engine snippet,
and only a failure of the search call itself raises the typed
``SearchEngineError`` that the caller turns into a "do not retry" tool
result.
"""

from __future__ import annotations

import asyncio

from dataclasses import dataclass
from types import TracebackType
from typing import Any, Self

import litellm
import trafilatura
from playwright.async_api import async_playwright
from playwright.async_api import Error as PlaywrightError

from src.shared.config import system_config
from src.shared.logger import logging
from src.infrastructure.exceptions import SearchEngineError, PageReadError


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    content: str


def _text(hit: Any, field: str) -> str:
    """Read a string field off a provider result, tolerating its absence.

    The shape of a hit varies per LiteLLM search provider, so every field
    is optional and a missing or null one reads as an empty string.
    """
    return str(getattr(hit, field, "") or "")


class _PageReader:
    """Render search-hit pages in one shared headless Chromium.

    One browser serves a whole search's reads; each hit gets a throwaway
    context on top of it, which is far lighter than a Chromium per page.
    """

    def __init__(self) -> None:
        self.__playwright: Any = None
        self.__browser: Any = None

    async def __aenter__(self) -> Self:
        self.__playwright = await async_playwright().start()
        self.__browser = await self.__playwright.chromium.launch(headless=True)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self.__browser:
            await self.__browser.close()
        if self.__playwright:
            await self.__playwright.stop()

    async def read(self, url: str, timeout: float) -> str:
        """Render ``url`` and return its readable text as markdown.

        Raises ``PageReadError`` for every expected failure — a dead
        link, a non-2xx response, a document trafilatura cannot reduce to
        text (PDFs) — so the caller can tell those apart from a bug.
        """
        try:
            context = await self.__browser.new_context()
            try:
                page = await context.new_page()
                response = await page.goto(
                    url, timeout=timeout * 1000, wait_until="domcontentloaded"
                )
                try:
                    await page.wait_for_load_state("networkidle", timeout=5000)
                except PlaywrightError:
                    pass  # chatty pages never idle; the DOM is there already
                if response and response.status >= 400:
                    raise PageReadError(
                        message=f"'{url}' answered HTTP {response.status}",
                        error_code=502,
                    )
                html = await page.content()
            finally:
                await context.close()
        except PageReadError:
            raise
        except PlaywrightError as e:
            raise PageReadError(
                message=f"could not render '{url}'", error_code=502
            ) from e
        # trafilatura parses HTML with lxml: CPU-bound and blocking, so
        # keep it off the event loop while sibling reads are in flight.
        text = await asyncio.to_thread(
            trafilatura.extract, html, output_format="markdown"
        )
        if not text:
            raise PageReadError(
                message=f"no readable content at '{url}'", error_code=422
            )
        return text


class SearchServiceClient:
    """Call the configured LiteLLM search provider and read its hits."""

    def __init__(self) -> None:
        self.cfg = system_config.web_search

    async def search(self, query: str) -> list[SearchResult]:
        cfg = self.cfg
        if not cfg.provider:
            raise SearchEngineError(
                message=(
                    "no search engine is configured (web_search.provider is "
                    "empty in config.yaml)"
                ),
                error_code=400,
            )
        try:
            response = await litellm.asearch(
                query=query,
                max_results=cfg.max_results,
                search_provider=cfg.provider,
                api_base=cfg.endpoint or None,
                timeout=cfg.timeout,
            )
        except Exception as e:
            logging.error(f"Web search via {cfg.provider} failed: {e!r}")
            raise SearchEngineError(
                message=f"the '{cfg.provider}' search engine call failed",
                error_code=502,
            ) from e

        # Enforce the cap locally: LiteLLM's SearXNG adapter ignores
        # `max_results` and returns the engine's full first page.
        hits: list[Any] = (getattr(response, "results", None) or [])[: cfg.max_results]
        if not hits:
            return []

        # One page read per hit, all in flight at once, sharing a single
        # Chromium; each read is bounded by `wait_for` so a hung page
        # cannot stretch the batch.
        async def _read(url: str) -> str:
            if not url:
                raise PageReadError(message="search hit carried no url", error_code=422)
            text = await asyncio.wait_for(reader.read(url, cfg.timeout), cfg.timeout)
            return text[: cfg.max_page_chars]

        async with _PageReader() as reader:
            pages = await asyncio.gather(
                *(_read(_text(hit, "url")) for hit in hits),
                return_exceptions=True,
            )

        results: list[SearchResult] = []
        for hit, page in zip(hits, pages):
            if isinstance(page, BaseException):
                logging.warning(
                    f"Page read for '{_text(hit, 'url')}' failed, falling back "
                    + f"to the engine snippet: {page!r} ({page.__cause__!r})"
                )
            results.append(
                SearchResult(
                    title=_text(hit, "title"),
                    url=_text(hit, "url"),
                    content=page if isinstance(page, str) else _text(hit, "snippet"),
                )
            )
        return results

# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Web-search facade used by the core's ``web_search`` tool.

Delegates to the LiteLLM unified search API (``litellm.asearch``) so the
search backend is swappable from ``config.yaml`` (SearXNG, Tavily, Brave,
Perplexity, ...), then reads each hit's page and extracts its readable
text as markdown with trafilatura: engine snippets are a sentence or
two, too thin for the provider-documentation lookups the agents make.

Degrades in layers, mirroring the pattern used by ``AuthzServiceClient``:
a page that will not fetch or extract falls back to the engine snippet,
and only a failure of the search call itself raises the typed
``SearchEngineError`` that the caller turns into a "do not retry" tool
result.
"""

from __future__ import annotations

import asyncio

from types import TracebackType
from typing import Any, ClassVar, Self

import httpx
import litellm
import trafilatura

from src.domains.value_objects import SearchResult
from src.shared.config import system_config
from src.shared.logger import logging
from src.infrastructure.exceptions import SearchEngineError, PageReadError


def _text(hit: Any, field: str) -> str:
    """Read a string field off a provider result, tolerating its absence.

    The shape of a hit varies per LiteLLM search provider, so every field
    is optional and a missing or null one reads as an empty string.
    """
    return str(getattr(hit, field, "") or "")


class _PageReader:
    """Fetch search-hit pages over one shared HTTP client.

    One connection pool serves a whole search's reads, so hits on the
    same host reuse their connection.
    """

    # Some documentation sites and forums answer a library User-Agent with
    # a 403; a browser-shaped request header set gets the page.
    BROWSER_HEADERS: ClassVar[dict[str, str]] = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    def __init__(self) -> None:
        self.__client = httpx.AsyncClient(
            headers=self.BROWSER_HEADERS, follow_redirects=True
        )

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.__client.aclose()

    async def read(self, url: str, timeout: float) -> str:
        """Fetch ``url`` and return its readable text as markdown.

        Raises ``PageReadError`` for every expected failure — a dead
        link, a non-2xx response, a document trafilatura cannot reduce to
        text (PDFs, JavaScript-only pages) — so the caller can tell those
        apart from a bug.
        """
        try:
            response = await self.__client.get(url, timeout=timeout)
        except httpx.HTTPError as e:
            raise PageReadError(
                message=f"could not fetch '{url}'", error_code=502
            ) from e
        if response.status_code >= 400:
            raise PageReadError(
                message=f"'{url}' answered HTTP {response.status_code}",
                error_code=502,
            )
        html = response.content
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
        # HTTP client; each read is bounded by `wait_for` so a slow-dripping
        # page cannot stretch the batch.
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

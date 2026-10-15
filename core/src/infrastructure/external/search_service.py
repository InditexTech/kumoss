# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Web-search facade used by the core's ``web_search`` tool.

Delegates to the LiteLLM unified search API (``litellm.asearch``) so the
search backend is swappable from ``config.yaml`` (SearXNG, Tavily, Brave,
Perplexity, ...), then reads each hit's page and extracts its readable
text with trafilatura: engine snippets are a sentence or two, too thin
for the provider-documentation lookups the agents make.

Degrades in layers, mirroring the pattern used by ``AuthzServiceClient``:
a page that will not fetch or extract falls back to the engine snippet,
and only a failure of the search call itself raises the typed
``SearchEngineError`` that the caller turns into a "do not retry" tool
result.
"""

from __future__ import annotations

import asyncio

from dataclasses import dataclass
from typing import Any

import httpx
import litellm
import trafilatura

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

        # One page read per hit, all in flight at once: the reads are
        # independent, and serialising them would multiply `timeout` by
        # `max_results` on the tool's worst case.
        async with httpx.AsyncClient(
            timeout=cfg.timeout,
            follow_redirects=True,
        ) as client:
            pages = await asyncio.gather(
                *(self.__aread_page(client, _text(hit, "url")) for hit in hits),
                return_exceptions=True,
            )

        results: list[SearchResult] = []
        for hit, page in zip(hits, pages):
            if isinstance(page, BaseException):
                # An unreadable page costs that hit its body, not the
                # search: the snippet still carries something, and the
                # other hits are unaffected.
                logging.warning(
                    f"Page read for '{_text(hit, 'url')}' failed, falling back "
                    + f"to the engine snippet: {page!r}"
                )
            results.append(
                SearchResult(
                    title=_text(hit, "title"),
                    url=_text(hit, "url"),
                    content=page if isinstance(page, str) else _text(hit, "snippet"),
                )
            )
        return results

    async def __aread_page(self, client: httpx.AsyncClient, url: str) -> str:
        """Fetch ``url`` and return its readable text as markdown.

        Raises ``PageReadError`` for every expected failure — a dead link,
        a non-2xx response, a document trafilatura cannot parse (PDFs,
        JS-only pages) — so the caller can tell those apart from a bug.
        """
        cfg = self.cfg

        if not url:
            raise PageReadError(message="search hit carried no url", error_code=422)
        try:
            response = await client.get(url)
            _ = response.raise_for_status()
        except Exception as e:
            raise PageReadError(
                message=f"could not fetch '{url}'", error_code=502
            ) from e
        # trafilatura parses HTML with lxml: CPU-bound and blocking, so keep
        # it off the event loop while the sibling reads are still in flight.
        text = await asyncio.to_thread(
            trafilatura.extract, response.text, output_format="markdown"
        )
        if not text:
            raise PageReadError(
                message=f"no readable content at '{url}'", error_code=422
            )
        return text[: cfg.max_page_chars]

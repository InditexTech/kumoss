# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Web-search facade used by the core's ``web_search`` tool.

Delegates to the LiteLLM unified search API
(``litellm.asearch``) so the search backend is swappable from
``config.yaml`` (SearXNG, Tavily, Brave, Perplexity, ...). Mirrors the
pattern used by ``AuthzServiceClient``: read provider + endpoint from
``system_config``, degrade gracefully — here by raising the typed
``SearchEngineError`` the caller turns into a "do not retry" tool result.
"""

from __future__ import annotations

from dataclasses import dataclass

import litellm

from src.shared.config import system_config
from src.shared.logger import logging
from src.infrastructure.exceptions import SearchEngineError


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    snippet: str


class SearchServiceClient:
    """Call the configured LiteLLM search provider."""

    async def search(self, query: str) -> list[SearchResult]:
        cfg = system_config.web_search
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
                max_results=cfg.max_results,
                timeout=cfg.timeout,
            )
        except Exception as e:
            logging.error(f"Web search via {cfg.provider} failed: {e!r}")
            raise SearchEngineError(
                message=f"the '{cfg.provider}' search engine call failed",
                error_code=502,
            ) from e
        return [
            SearchResult(
                title=str(getattr(r, "title", "") or ""),
                url=str(getattr(r, "url", "") or ""),
                snippet=str(getattr(r, "snippet", "") or ""),
            )
            # Enforce the cap locally: LiteLLM's SearXNG adapter ignores
            # `max_results` and returns the engine's full first page.
            for r in (getattr(response, "results", None) or [])[: cfg.max_results]
        ]

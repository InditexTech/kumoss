# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Two-stage LLM reduction of the pages the ``web_search`` tool fetched.

Stage 1 condenses every ``SearchResult`` independently and concurrently
with the small model, one inference per page. A summary is an extract,
not a gist: it must carry everything on the page that bears on the
query, so nothing downstream has to go back to the raw scrape. Stage 2
compares those summaries against the original query in a single
cross-page inference and ranks the pages that validly answer it, best
first.

The caller returns the top-ranked *summaries* to the main agent, so it
reads a handful of dense, query-shaped extracts in relevance order.

Degradation is layered, mirroring ``search_service``: a page whose
summary inference fails keeps its (truncated) raw content as its
summary, an unusable ranking falls back to every relevant summary in
engine order, and any summarizer-level error is left for the tool
handler to swallow by falling back to the raw results.
"""

import asyncio

from src.domains.dto import LLMResponseDTO
from src.domains.interfaces import ILLMProvider, ITemplate
from src.domains.value_objects import PageSummary, SearchResult
from src.infrastructure.exceptions import (
    PageSelectionError,
    PageSummaryError,
)
from src.shared.config import system_config
from src.shared.logger import logging

_IRRELEVANT = "IRRELEVANT"


class SearchResultsSummarizer:
    """Condense search results and rank the summaries cross-page."""

    def __init__(self, llm: ILLMProvider, templates: ITemplate):
        self.__llm = llm
        self.__summarize_system = templates.render_search_summarizer(_IRRELEVANT)
        self.__select_system = templates.render_search_selector()
        self.cfg = system_config.web_search

    async def best(
        self, query: str, results: list[SearchResult]
    ) -> tuple[list[PageSummary], list[PageSummary]]:
        """Summaries, then a cross-page ranking; return the best ones.

        Returns ``(selected, discarded)``: ``selected`` holds at most
        ``summarize_top`` summaries in relevance order, ``discarded`` the
        rest, for logging only.

        An empty ``selected`` is a verdict, not a failure — nothing the
        engine returned answers the query, and the caller turns that into
        a prompt to search again. A ranking that cannot be used instead
        falls back to every relevant summary in engine order.
        """
        summaries = await self.summarize(query, results)
        irrelevant = [s for s in summaries if _is_irrelevant(s.summary)]
        relevant = [s for s in summaries if not _is_irrelevant(s.summary)]
        if not relevant:
            logging.info(
                f"Every page found for query '{query}' summarized as "
                + "irrelevant; nothing to rank."
            )
            return [], summaries

        try:
            ranked_ids = await self.__select(query, relevant, len(results))
        except PageSelectionError as e:
            logging.warning(
                f"Falling back to the engine order: {e.message} ({e.__cause__!r})"
            )
            return relevant, irrelevant
        if ranked_ids is None:
            logging.warning(
                "No usable page ranking for query "
                + f"'{query}'; returning every summary unranked."
            )
            return relevant, irrelevant
        if not ranked_ids:
            logging.info(f"No page found for query '{query}' answers it.")
            return [], summaries

        by_index = {s.index: s for s in relevant}
        ranked = [by_index[i] for i in ranked_ids if i in by_index]
        unranked = [s for s in relevant if s.index not in ranked_ids]
        top = ranked[: self.cfg.summarize_top]
        return top, ranked[self.cfg.summarize_top :] + unranked + irrelevant

    async def summarize(
        self, query: str, results: list[SearchResult]
    ) -> list[PageSummary]:
        """One small-LLM summary per page, all in flight at once.

        A page whose summary inference fails keeps a truncated copy of
        its content as its summary; the search itself is never lost to
        one bad page.
        """
        cap = self.cfg.summarize_max_chars

        async def _summarize_page(index: int, result: SearchResult) -> PageSummary:
            try:
                summary = await self.__infer(
                    self.__summarize_system, _page_prompt(query, result)
                )
            except Exception as e:
                raise PageSummaryError(
                    message=f"the summary inference for '{result.url}' failed",
                    error_code=502,
                ) from e
            return PageSummary(
                index=index, result=result, summary=summary[:cap] if summary else ""
            )

        gathered = await asyncio.gather(
            *(_summarize_page(i, r) for i, r in enumerate(results)),
            return_exceptions=True,
        )
        summaries: list[PageSummary] = []
        for i, outcome in enumerate(gathered):
            if isinstance(outcome, PageSummaryError):
                logging.warning(
                    "Keeping a raw excerpt after a failed page summary: "
                    + f"{outcome.message} ({outcome.__cause__!r})"
                )
                summaries.append(
                    PageSummary(
                        index=i, result=results[i], summary=results[i].content[:cap]
                    )
                )
            else:
                summaries.append(outcome)
        return summaries

    async def __select(
        self, query: str, summaries: list[PageSummary], total: int
    ) -> list[int] | None:
        """One cross-page inference ranking the ids, most relevant first.

        ``None`` is "the answer cannot be used", an empty list is "the
        answer is that no page is relevant"; raises ``PageSelectionError``
        when the inference itself fails.
        """
        listing = "\n\n".join(
            f"id={s.index}\ntitle: {s.result.title}\nurl: {s.result.url}\n"
            + f"summary: {s.summary}"
            for s in summaries
        )
        try:
            verdict = await self.__infer(
                self.__select_system, _select_prompt(query, listing)
            )
        except Exception as e:
            raise PageSelectionError(
                message=f"the cross-page selection for '{query}' failed",
                error_code=502,
            ) from e

        return _parse_selection(verdict, total)

    async def __infer(self, system_prompt: str, msg: str) -> str:
        response: LLMResponseDTO = await self.__llm.inference(
            msg=msg,
            system_prompt=system_prompt,
        )
        return response.text


def _is_irrelevant(summary: str) -> bool:
    """Whether the small model judged this page useless for the query."""
    return summary.strip().upper() == _IRRELEVANT


def _page_prompt(query: str, result: SearchResult) -> str:
    return (
        f"Query: {query}\n\n"
        + f"Page title: {result.title}\n"
        + f"Page url: {result.url}\n\n"
        + f"Page content:\n{result.content}"
    )


def _select_prompt(query: str, listing: str) -> str:
    return f"Query: {query}\n\nSummaries:\n\n{listing}"


def _parse_selection(verdict: str, total: int) -> list[int] | None:
    """Overlap-free `SELECT: ...` ids picked out of the verdict.

    Returns best-first unique zero-based ids bounded to valid page
    positions. An empty list is the model's own `SELECT: none`; ``None``
    is the absence of a verdict — no marker, or ids that are all
    unusable — which the caller degrades on rather than believes.
    """
    marker = "SELECT:"
    cut = verdict.find(marker)
    if cut < 0:
        return None
    answer = verdict[cut + len(marker) :].strip()
    if answer.lower().startswith("none"):
        return []
    parsed: list[int] = []
    for token in answer.split(","):
        token = token.strip().split()[0] if token.strip() else ""
        if token.isdigit() and 0 <= int(token) < total:
            parsed.append(int(token))
    return list(dict.fromkeys(parsed)) or None

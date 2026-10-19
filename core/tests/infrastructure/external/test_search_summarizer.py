# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""The search result summarizer's two-stage reduction.

Stage 1 condenses every page with one concurrent small-model
inference; stage 2 compares those summaries against the query in a
single inference and ranks the ids, most relevant first. What comes
back is the top summaries themselves, in that order — they are what the
tool hands the agent in place of the pages. Selection parsing is
tolerant of chatter, and every failure degrades towards every summary
in engine order instead of losing the search.
"""

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from src.infrastructure.external.search_service import SearchResult
from src.infrastructure.external.search_summarizer import (
    SearchResultsSummarizer,
    _parse_selection,
)


def _results() -> list[SearchResult]:
    return [
        SearchResult(title="T1", url="https://1", content="a"),
        SearchResult(title="T2", url="https://2", content="b"),
        SearchResult(title="T3", url="https://3", content="c"),
    ]


def _summarizer(llm: MagicMock, top: int = 1) -> SearchResultsSummarizer:
    """A summarizer under a patched config, ``summarize_top: 1`` by default."""
    with patch("src.infrastructure.external.search_summarizer.system_config") as config:
        config.web_search.summarize_top = top
        config.web_search.summarize_max_chars = 1200
        return SearchResultsSummarizer(llm)


class TestSelectionParsing(unittest.TestCase):
    """``None`` means "no usable verdict"; ``[]`` means "nothing is relevant"."""

    def test_ids_and_order_are_kept(self):
        self.assertEqual(_parse_selection("SELECT: 3,1", 5), [3, 1])

    def test_zero_is_a_valid_id_and_total_is_exclusive(self):
        self.assertEqual(_parse_selection("SELECT: 0", 5), [0])
        self.assertEqual(_parse_selection("SELECT: 4", 5), [4])
        self.assertIsNone(_parse_selection("SELECT: 5", 5))

    def test_chatter_around_the_marker_is_ignored(self):
        self.assertEqual(_parse_selection("Let me think...\nSELECT: 2\nDone.", 5), [2])

    def test_an_explicit_none_is_a_verdict_not_a_failure(self):
        self.assertEqual(_parse_selection("SELECT: none", 5), [])
        self.assertEqual(_parse_selection("SELECT: NONE", 5), [])

    def test_garbage_is_no_verdict_at_all(self):
        self.assertIsNone(_parse_selection("no selection marker here", 5))
        self.assertIsNone(_parse_selection("SELECT: 99, abc", 5))
        self.assertIsNone(_parse_selection("SELECT:", 5))

    def test_duplicates_collapse(self):
        self.assertEqual(_parse_selection("SELECT: 2,2,1", 5), [2, 1])

    def test_out_of_bounds_ids_are_dropped(self):
        self.assertIsNone(_parse_selection("SELECT: -1", 5))


class TestSearchResultsSummarizer(unittest.IsolatedAsyncioTestCase):
    async def test_one_inference_per_page_plus_one_selection(self):
        llm = MagicMock(
            inference=AsyncMock(
                side_effect=[
                    SimpleNamespace(text="s1"),
                    SimpleNamespace(text="s2"),
                    SimpleNamespace(text="s3"),
                    SimpleNamespace(text="SELECT: 1"),
                ]
            )
        )
        results = _results()
        selected, discarded = await _summarizer(llm).best("q", results)

        self.assertEqual(llm.inference.await_count, 4)
        # The winner's summary is what travels onward, its page kept
        # alongside it only for the title and url of the citation.
        self.assertEqual([s.summary for s in selected], ["s2"])
        self.assertEqual([s.result for s in selected], [results[1]])
        self.assertEqual([s.result for s in discarded], [results[0], results[2]])

    async def test_ranking_order_beats_engine_order(self):
        llm = MagicMock(
            inference=AsyncMock(
                side_effect=[
                    SimpleNamespace(text="s1"),
                    SimpleNamespace(text="s2"),
                    SimpleNamespace(text="s3"),
                    SimpleNamespace(text="SELECT: 2,0"),
                ]
            )
        )
        results = _results()
        selected, discarded = await _summarizer(llm, top=2).best("q", results)

        self.assertEqual([s.summary for s in selected], ["s3", "s1"])
        self.assertEqual([s.result for s in discarded], [results[1]])

    async def test_summaries_beyond_the_top_are_discarded_in_rank_order(self):
        llm = MagicMock(
            inference=AsyncMock(
                side_effect=[
                    SimpleNamespace(text="s1"),
                    SimpleNamespace(text="s2"),
                    SimpleNamespace(text="s3"),
                    SimpleNamespace(text="SELECT: 2,0,1"),
                ]
            )
        )
        results = _results()
        selected, discarded = await _summarizer(llm).best("q", results)

        self.assertEqual([s.summary for s in selected], ["s3"])
        self.assertEqual([s.summary for s in discarded], ["s1", "s2"])

    async def test_unparseable_selection_keeps_every_summary(self):
        llm = MagicMock(
            inference=AsyncMock(
                side_effect=[
                    SimpleNamespace(text="s1"),
                    SimpleNamespace(text="s2"),
                    SimpleNamespace(text="..."),
                ]
            )
        )
        results = _results()[:2]
        selected, discarded = await _summarizer(llm).best("q", results)

        # The reduction still happened: summaries, engine order, no cap.
        self.assertEqual([s.summary for s in selected], ["s1", "s2"])
        self.assertEqual(discarded, [])

    async def test_selection_inference_error_keeps_every_summary(self):
        llm = MagicMock(
            inference=AsyncMock(
                side_effect=[
                    SimpleNamespace(text="s1"),
                    SimpleNamespace(text="s2"),
                    RuntimeError("boom"),
                ]
            )
        )
        results = _results()[:2]
        selected, discarded = await _summarizer(llm).best("q", results)

        # The selection inference raising is a ``PageSelectionError``
        # swallowed inside ``best``: the search survives unranked.
        self.assertEqual([s.result for s in selected], results)
        self.assertEqual(discarded, [])

    async def test_none_explicitly_selected_selects_nothing(self):
        llm = MagicMock(
            inference=AsyncMock(
                side_effect=[
                    SimpleNamespace(text="s1"),
                    SimpleNamespace(text="s2"),
                    SimpleNamespace(text="SELECT: none"),
                ]
            )
        )
        results = _results()[:2]
        selected, discarded = await _summarizer(llm).best("q", results)

        # The ranker's verdict is believed: nothing here answers the
        # query, which the tool turns into a "rephrase" for the agent.
        self.assertEqual(selected, [])
        self.assertEqual([s.result for s in discarded], results)

    async def test_pages_summarized_as_irrelevant_select_nothing(self):
        llm = MagicMock(
            inference=AsyncMock(
                side_effect=[
                    SimpleNamespace(text="IRRELEVANT"),
                    SimpleNamespace(text="  irrelevant\n"),
                ]
            )
        )
        results = _results()[:2]
        selected, discarded = await _summarizer(llm).best("q", results)

        self.assertEqual(selected, [])
        self.assertEqual([s.result for s in discarded], results)
        # Nothing was left to rank, so the second inference is skipped.
        self.assertEqual(llm.inference.await_count, 2)

    async def test_irrelevant_pages_are_kept_out_of_the_ranking(self):
        llm = MagicMock(
            inference=AsyncMock(
                side_effect=[
                    SimpleNamespace(text="IRRELEVANT"),
                    SimpleNamespace(text="s2"),
                    SimpleNamespace(text="IRRELEVANT"),
                    SimpleNamespace(text="SELECT: 1"),
                ]
            )
        )
        results = _results()
        selected, discarded = await _summarizer(llm).best("q", results)

        listing = llm.inference.call_args_list[3].kwargs["msg"]
        self.assertIn("id=1", listing)
        self.assertNotIn("id=0", listing)
        self.assertNotIn("id=2", listing)
        self.assertEqual([s.result for s in selected], [results[1]])
        self.assertEqual([s.result for s in discarded], [results[0], results[2]])

    async def test_one_failed_page_summary_still_lets_the_rest_be_picked(self):
        llm = MagicMock(
            inference=AsyncMock(
                side_effect=[
                    RuntimeError("boom"),
                    SimpleNamespace(text="s2"),
                    SimpleNamespace(text="SELECT: 1"),
                ]
            )
        )
        results = _results()[:2]
        selected, _ = await _summarizer(llm).best("q", results)

        # The page whose summary inference died keeps a raw excerpt as
        # its summary; the other page is still picked and wins.
        self.assertEqual([s.result for s in selected], [results[1]])
        self.assertEqual([s.summary for s in selected], ["s2"])

    async def test_summaries_are_capped(self):
        llm = MagicMock(
            inference=AsyncMock(return_value=SimpleNamespace(text="x" * 3000))
        )
        summaries = await _summarizer(llm).summarize("q", [_results()[0]])

        self.assertEqual(len(summaries[0].summary), 1200)

    async def test_failed_summary_falls_back_to_a_truncated_excerpt(self):
        llm = MagicMock(inference=AsyncMock(side_effect=RuntimeError("boom")))
        long_page = SearchResult(title="T", url="u", content="y" * 3000)
        summaries = await _summarizer(llm).summarize("q", [long_page])

        self.assertEqual(len(summaries[0].summary), 1200)

    async def test_page_summaries_run_concurrently(self):
        state = {"active": 0, "peak": 0}

        async def inference(**kwargs):
            state["active"] += 1
            state["peak"] = max(state["peak"], state["active"])
            await asyncio.sleep(0.01)
            state["active"] -= 1
            return SimpleNamespace(text="s")

        llm = MagicMock()
        llm.inference = inference
        await _summarizer(llm).summarize("q", _results())

        self.assertEqual(state["peak"], 3)

    async def test_selection_prompt_carries_the_query_and_the_summaries(self):
        async def inference(msg, system_prompt=None, **kwargs):
            return SimpleNamespace(text="SELECT: 1")

        llm = MagicMock(inference=AsyncMock(side_effect=inference))
        await _summarizer(llm).best("terraform", [_results()[0]])

        self.assertIn("terraform", llm.inference.call_args_list[0].kwargs["msg"])
        self.assertIn("terraform", llm.inference.call_args_list[1].kwargs["msg"])
        self.assertIn("T1", llm.inference.call_args_list[1].kwargs["msg"])


if __name__ == "__main__":
    unittest.main()

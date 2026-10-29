# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""``_PageReader``: one headless Chromium per search, one context per page.

Playwright and trafilatura are replaced by fakes, so no browser starts
and nothing touches the network; the cases pin the exact calls made
(launch flags, goto / networkidle budgets, the off-loop markdown
extraction) and how each failure becomes a ``PageReadError``.
"""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from playwright.async_api import Error as PlaywrightError

from src.exceptions import PageReadError
from src.search_service import _PageReader


def _fake_playwright(
    status: int | None = 200,
    goto_error: Exception | None = None,
    idle_error: Exception | None = None,
    html: str = "<html><body><p>hi</p></body></html>",
):
    page = MagicMock()
    if goto_error is not None:
        page.goto = AsyncMock(side_effect=goto_error)
    else:
        page.goto = AsyncMock(
            return_value=None if status is None else MagicMock(status=status)
        )
    page.wait_for_load_state = AsyncMock(side_effect=idle_error)
    page.content = AsyncMock(return_value=html)

    context = MagicMock()
    context.new_page = AsyncMock(return_value=page)
    context.close = AsyncMock()

    browser = MagicMock()
    browser.new_context = AsyncMock(return_value=context)
    browser.close = AsyncMock()

    playwright = MagicMock()
    playwright.chromium.launch = AsyncMock(return_value=browser)
    playwright.stop = AsyncMock()

    starter = MagicMock()
    starter.start = AsyncMock(return_value=playwright)
    factory = MagicMock(return_value=starter)
    return factory, playwright, browser, context, page


class TestPageReader(unittest.IsolatedAsyncioTestCase):
    async def _read(self, fakes, extract=None, url="https://a", timeout=30.0):
        factory = fakes[0]
        extract = extract or MagicMock(return_value="# markdown")
        with (
            patch("src.search_service.async_playwright", factory),
            patch("src.search_service.trafilatura.extract", extract),
        ):
            async with _PageReader() as reader:
                return await reader.read(url, timeout)

    async def test_happy_path_renders_and_extracts_markdown(self):
        fakes = _fake_playwright()
        _, playwright, browser, context, page = fakes
        extract = MagicMock(return_value="# markdown")

        text = await self._read(fakes, extract)

        self.assertEqual(text, "# markdown")
        playwright.chromium.launch.assert_awaited_once_with(headless=True)
        page.goto.assert_awaited_once_with(
            "https://a", timeout=30000.0, wait_until="domcontentloaded"
        )
        page.wait_for_load_state.assert_awaited_once_with("networkidle", timeout=5000)
        extract.assert_called_once_with(
            "<html><body><p>hi</p></body></html>", output_format="markdown"
        )
        context.close.assert_awaited_once()
        browser.close.assert_awaited_once()
        playwright.stop.assert_awaited_once()

    async def test_extraction_runs_off_the_event_loop(self):
        fakes = _fake_playwright()
        with patch(
            "src.search_service.asyncio.to_thread", AsyncMock(return_value="md")
        ) as to_thread:
            text = await self._read(fakes)

        self.assertEqual(text, "md")
        args, kwargs = to_thread.call_args
        self.assertEqual(args[1], "<html><body><p>hi</p></body></html>")
        self.assertEqual(kwargs, {"output_format": "markdown"})

    async def test_a_page_that_never_idles_is_still_read(self):
        fakes = _fake_playwright(idle_error=PlaywrightError("Timeout 5000ms"))

        self.assertEqual(await self._read(fakes), "# markdown")

    async def test_http_errors_are_read_failures(self):
        for status in (400, 404, 500, 503):
            with self.subTest(status=status):
                fakes = _fake_playwright(status=status)
                with self.assertRaises(PageReadError) as ctx:
                    await self._read(fakes)
                self.assertEqual(
                    ctx.exception.message, f"'https://a' answered HTTP {status}"
                )
                self.assertEqual(ctx.exception.error_code, 502)
                fakes[3].close.assert_awaited_once()

    async def test_redirect_and_success_statuses_are_read(self):
        for status in (200, 204, 301, 399):
            with self.subTest(status=status):
                self.assertEqual(
                    await self._read(_fake_playwright(status=status)), "# markdown"
                )

    async def test_no_response_object_is_read(self):
        self.assertEqual(await self._read(_fake_playwright(status=None)), "# markdown")

    async def test_render_failures_become_page_read_errors_with_a_cause(self):
        cause = PlaywrightError("net::ERR_NAME_NOT_RESOLVED")
        fakes = _fake_playwright(goto_error=cause)

        with self.assertRaises(PageReadError) as ctx:
            await self._read(fakes)

        self.assertEqual(ctx.exception.message, "could not render 'https://a'")
        self.assertEqual(ctx.exception.error_code, 502)
        self.assertIs(ctx.exception.__cause__, cause)
        fakes[3].close.assert_awaited_once()

    async def test_unexpected_errors_are_not_masked(self):
        fakes = _fake_playwright(goto_error=RuntimeError("bug"))

        with self.assertRaises(RuntimeError):
            await self._read(fakes)

    async def test_unreadable_documents_are_page_read_errors(self):
        for empty in (None, ""):
            with self.subTest(extracted=empty):
                with self.assertRaises(PageReadError) as ctx:
                    await self._read(_fake_playwright(), MagicMock(return_value=empty))
                self.assertEqual(
                    ctx.exception.message, "no readable content at 'https://a'"
                )
                self.assertEqual(ctx.exception.error_code, 422)

    async def test_repr_matches_the_cores_log_format(self):
        # The fallback warning logs `{page!r}`; the core's ExceptionHandler
        # keeps the plain Exception repr while `str` adds the code.
        error = PageReadError(message="could not render 'x'", error_code=502)
        self.assertEqual(repr(error), "PageReadError(\"could not render 'x'\")")
        self.assertEqual(str(error), "Error 502: could not render 'x'")


if __name__ == "__main__":
    unittest.main()

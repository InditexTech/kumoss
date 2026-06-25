# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the GitHub git provider.

HTTP traffic is intercepted with httpx.MockTransport so no network is
required and we still exercise httpx's real request building and
response handling (including raise_for_status).
"""

import json
import unittest
from typing import Callable
from unittest.mock import patch

import httpx

from src.domains.dto import PullRequestDTO
from src.infrastructure.filesystem.git.providers.github import GitHub
from src.shared.exceptions import ExceptionHandler


def _build_provider(handler: Callable[[httpx.Request], httpx.Response]) -> GitHub:
    """Construct a GitHub provider whose httpx client uses a MockTransport."""
    with patch(
        "src.infrastructure.filesystem.git.providers.github.system_config"
    ) as cfg:
        cfg.git.pat_user = "u"
        cfg.git.pat_token = "t"
        provider = GitHub()
    # Replace the name-mangled private client. We mirror the production
    # auth/headers config so we can still assert on the outgoing request.
    provider._GitHub__client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        auth=httpx.BasicAuth(username="u", password="t"),
        timeout=20,
    )
    return provider


class TestGitHubCreatePR(unittest.IsolatedAsyncioTestCase):
    async def test_returns_dto_on_success(self):
        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["url"] = str(request.url)
            seen["method"] = request.method
            seen["body"] = json.loads(request.content.decode())
            return httpx.Response(
                201,
                json={"number": 42, "state": "open"},
            )

        provider = _build_provider(handler)
        result = await provider.create_pr(
            repository_url="https://github.com/octo/widgets",
            head="feature/x",
            base="main",
            title="My PR",
            description="Body text",
        )
        self.assertIsInstance(result, PullRequestDTO)
        self.assertEqual(result.id, 42)
        self.assertEqual(result.status, "open")
        self.assertEqual(result.url, "https://api.github.com/repos/octo/widgets/pulls")
        self.assertEqual(seen["method"], "POST")
        self.assertEqual(seen["url"], "https://api.github.com/repos/octo/widgets/pulls")
        self.assertEqual(
            seen["body"],
            {
                "title": "My PR",
                "head": "feature/x",
                "base": "main",
                "body": "Body text",
            },
        )

    async def test_works_when_url_has_no_scheme(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(201, json={"number": 1, "state": "open"})

        provider = _build_provider(handler)
        result = await provider.create_pr(
            repository_url="github.com/octo/widgets",
            head="h",
            base="main",
            title="t",
            description="d",
        )
        self.assertEqual(result.id, 1)

    async def test_raises_exception_handler_on_http_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                422,
                json={"message": "Validation Failed"},
            )

        provider = _build_provider(handler)
        with self.assertRaises(ExceptionHandler) as ctx:
            await provider.create_pr(
                repository_url="https://github.com/octo/widgets",
                head="feature/x",
                base="main",
                title="t",
                description="d",
            )
        self.assertEqual(ctx.exception.error_code, 422)
        self.assertIn("Validation Failed", ctx.exception.message)

    async def test_raises_504_on_timeout(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.TimeoutException("timed out", request=request)

        provider = _build_provider(handler)
        with self.assertRaises(ExceptionHandler) as ctx:
            await provider.create_pr(
                repository_url="https://github.com/octo/widgets",
                head="h",
                base="main",
                title="t",
                description="d",
            )
        self.assertEqual(ctx.exception.error_code, 504)
        self.assertEqual(ctx.exception.message, "PR creation timeout")

    async def test_raises_400_on_malformed_url(self):
        def handler(request: httpx.Request) -> httpx.Response:
            self.fail("HTTP must not be called for malformed URLs")

        provider = _build_provider(handler)
        with self.assertRaises(ExceptionHandler) as ctx:
            await provider.create_pr(
                repository_url="https://gitlab.com/foo/bar",
                head="h",
                base="main",
                title="t",
                description="d",
            )
        self.assertEqual(ctx.exception.error_code, 400)
        self.assertIn("Malformed repository URL", ctx.exception.message)


class TestGitHubCompletePR(unittest.IsolatedAsyncioTestCase):
    async def test_calls_approve_then_merge(self):
        calls: list[tuple[str, str]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append((request.method, str(request.url)))
            return httpx.Response(200, json={"ok": True})

        provider = _build_provider(handler)
        await provider.complete_pr(
            repository_url="https://github.com/octo/widgets",
            id=7,
        )
        self.assertEqual(
            calls,
            [
                ("POST", "https://api.github.com/repos/octo/widgets/pulls/7/reviews"),
                ("PUT", "https://api.github.com/repos/octo/widgets/pulls/7/merge"),
            ],
        )

    async def test_propagates_approve_failure_as_exception_handler(self):
        def handler(request: httpx.Request) -> httpx.Response:
            # Fail the first (approve) call; the merge call should never run.
            return httpx.Response(403, json={"message": "forbidden"})

        provider = _build_provider(handler)
        with self.assertRaises(ExceptionHandler) as ctx:
            await provider.complete_pr(
                repository_url="https://github.com/octo/widgets", id=7
            )
        self.assertEqual(ctx.exception.error_code, 403)

    async def test_propagates_merge_failure_as_exception_handler(self):
        seen_methods: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen_methods.append(request.method)
            if request.method == "POST":
                return httpx.Response(200, json={"ok": True})
            return httpx.Response(409, json={"message": "merge conflict"})

        provider = _build_provider(handler)
        with self.assertRaises(ExceptionHandler) as ctx:
            await provider.complete_pr(
                repository_url="https://github.com/octo/widgets", id=7
            )
        self.assertEqual(ctx.exception.error_code, 409)
        self.assertIn("merge conflict", ctx.exception.message)
        self.assertEqual(seen_methods, ["POST", "PUT"])

    async def test_raises_504_on_timeout(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.TimeoutException("timed out", request=request)

        provider = _build_provider(handler)
        with self.assertRaises(ExceptionHandler) as ctx:
            await provider.complete_pr(
                repository_url="https://github.com/octo/widgets", id=7
            )
        self.assertEqual(ctx.exception.error_code, 504)
        self.assertEqual(ctx.exception.message, "Complete PR timeout")

    async def test_raises_400_on_malformed_url(self):
        def handler(request: httpx.Request) -> httpx.Response:
            self.fail("HTTP must not be called for malformed URLs")

        provider = _build_provider(handler)
        with self.assertRaises(ExceptionHandler) as ctx:
            await provider.complete_pr(
                repository_url="https://gitlab.com/foo/bar", id=1
            )
        self.assertEqual(ctx.exception.error_code, 400)


if __name__ == "__main__":
    unittest.main()

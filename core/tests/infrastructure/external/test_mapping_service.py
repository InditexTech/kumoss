# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""The mapping client facade against contract 2.0.0.

Covers the disabled path answering with an identity passthrough, the
request carrying the identifier only, and the mapping of a response the
contract does not allow onto 502 rather than an unhandled 500. Also
pins that the core no longer exposes a browser-facing passthrough.
"""

import json
import unittest
from http import HTTPStatus
from unittest.mock import AsyncMock, patch

import httpx

from src.clients.mapping.models.problem import Problem
from src.clients.mapping.models.resolve_response import ResolveResponse
from src.clients.mapping.types import Response
from src.infrastructure.external import mapping_service
from src.infrastructure.external.mapping_service import (
    MappingServiceClient,
    ResolvedRef,
)
from src.main import app
from src.shared.config import system_config
from src.shared.config.system_config import ServiceConfig
from src.shared.exceptions import ExceptionHandler

IDENTIFIER = "https://github.com/me/my-iac.git"


class TestNoBrowserPassthrough(unittest.TestCase):
    # Asserted against the OpenAPI document rather than `app.routes`:
    # this FastAPI version keeps included routers as `_IncludedRouter`
    # wrappers with no `.path`.
    def test_resolve_route_is_gone(self):
        paths = app.openapi()["paths"]
        self.assertFalse([p for p in paths if p.startswith("/v1/mapping")])


class MappingClientTestCase(unittest.IsolatedAsyncioTestCase):
    """Shared config patching: mapping on or off for the duration."""

    def _configure(self, *, enabled: bool):
        patcher = patch.object(
            system_config.services,
            "mapping",
            ServiceConfig(
                enabled=enabled,
                endpoint="http://mapping:8081" if enabled else "",
                token="test-token",
            ),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def _patch_op(self, *, status: int = 200, **kwargs):
        """Replace the generated op's `asyncio_detailed` entry point.

        `return_value` is the parsed body; it is wrapped in a `Response`
        with `status`. `side_effect` is raised as is.
        """
        if "return_value" in kwargs:
            kwargs["return_value"] = Response(
                status_code=HTTPStatus(status),
                content=b"",
                headers={},
                parsed=kwargs["return_value"],
            )
        mock = AsyncMock(**kwargs)
        patcher = patch.object(mapping_service.resolve_op, "asyncio_detailed", mock)
        patcher.start()
        self.addCleanup(patcher.stop)
        return mock


class TestDisabledMappingIsIdentity(MappingClientTestCase):
    """Toggling `mapping.enabled` off must change nothing for a repo URL."""

    def setUp(self):
        self._configure(enabled=False)

    async def test_identifier_is_echoed_as_repo_url(self):
        resolved = await MappingServiceClient().resolve(IDENTIFIER)
        self.assertEqual(
            resolved, ResolvedRef(repo_url=IDENTIFIER, identifier=IDENTIFIER)
        )

    async def test_non_https_identifier_is_echoed_unchecked(self):
        resolved = await MappingServiceClient().resolve("my-project")
        self.assertEqual(resolved.repo_url, "my-project")

    async def test_service_is_never_contacted(self):
        op = self._patch_op(return_value=None)
        await MappingServiceClient().resolve(IDENTIFIER)
        op.assert_not_awaited()


class TestEnabledMapping(MappingClientTestCase):
    def setUp(self):
        self._configure(enabled=True)

    async def test_request_carries_the_identifier_only(self):
        op = self._patch_op(
            return_value=ResolveResponse(repo_url=IDENTIFIER, identifier="my-project")
        )
        await MappingServiceClient().resolve("my-project")
        body = op.await_args.kwargs["body"]
        # Contract 2.0.0 forbids anything else on the request.
        self.assertEqual(body.to_dict(), {"identifier": "my-project"})

    async def test_response_becomes_a_resolved_ref(self):
        self._patch_op(
            return_value=ResolveResponse(
                repo_url="https://git.example/iac.git", identifier="my-project"
            )
        )
        resolved = await MappingServiceClient().resolve("my-project")
        self.assertEqual(
            resolved,
            ResolvedRef(
                repo_url="https://git.example/iac.git", identifier="my-project"
            ),
        )


class TestEnabledMappingFailureModes(MappingClientTestCase):
    def setUp(self):
        self._configure(enabled=True)

    async def test_unparseable_body_is_502(self):
        # `response.json()` on a non-JSON 200 raises JSONDecodeError,
        # a ValueError; a body missing `repo_url` raises KeyError.
        for error in (
            json.JSONDecodeError("Expecting value", "<html>", 0),
            KeyError("repo_url"),
        ):
            with self.subTest(error=type(error).__name__):
                self._patch_op(side_effect=error)
                with self.assertRaises(ExceptionHandler) as ctx:
                    await MappingServiceClient().resolve(IDENTIFIER)
                self.assertEqual(ctx.exception.error_code, 502)

    async def test_non_https_repo_url_is_502(self):
        for repo_url in (
            "my-project",
            "git@github.com:me/my-iac.git",
            "ssh://git@github.com/me/my-iac.git",
            "file:///srv/git/my-iac.git",
            "http://github.com/me/my-iac.git",
        ):
            with self.subTest(repo_url=repo_url):
                self._patch_op(
                    return_value=ResolveResponse(
                        repo_url=repo_url, identifier="my-project"
                    )
                )
                with self.assertRaises(ExceptionHandler) as ctx:
                    await MappingServiceClient().resolve("my-project")
                self.assertEqual(ctx.exception.error_code, 502)
                self.assertNotIn(repo_url, ctx.exception.message)

    async def test_not_in_catalogue_is_404_with_the_mappers_reason(self):
        self._patch_op(
            status=404,
            return_value=Problem(
                title="Identifier could not be resolved",
                status=404,
                detail="set MAPPING_PREFIX_IDENTIFIER",
            ),
        )
        with self.assertRaises(ExceptionHandler) as ctx:
            await MappingServiceClient().resolve("foo")
        self.assertEqual(ctx.exception.error_code, 404)
        self.assertEqual(ctx.exception.message, "set MAPPING_PREFIX_IDENTIFIER")

    async def test_not_in_catalogue_without_detail_is_404_generic(self):
        self._patch_op(status=404, return_value=Problem(title="Not found", status=404))
        with self.assertRaises(ExceptionHandler) as ctx:
            await MappingServiceClient().resolve("foo")
        self.assertEqual(ctx.exception.error_code, 404)
        self.assertIn("could not resolve", ctx.exception.message)

    async def test_other_problem_status_is_502(self):
        self._patch_op(
            status=401, return_value=Problem(title="Unauthorized", status=401)
        )
        with self.assertRaises(ExceptionHandler) as ctx:
            await MappingServiceClient().resolve("foo")
        self.assertEqual(ctx.exception.error_code, 502)

    async def test_unexpected_response_type_is_502(self):
        self._patch_op(return_value=None)
        with self.assertRaises(ExceptionHandler) as ctx:
            await MappingServiceClient().resolve(IDENTIFIER)
        self.assertEqual(ctx.exception.error_code, 502)

    async def test_timeout_is_504(self):
        self._patch_op(side_effect=httpx.TimeoutException("too slow"))
        with self.assertRaises(ExceptionHandler) as ctx:
            await MappingServiceClient().resolve(IDENTIFIER)
        self.assertEqual(ctx.exception.error_code, 504)

    async def test_unreachable_is_502(self):
        self._patch_op(side_effect=httpx.ConnectError("refused"))
        with self.assertRaises(ExceptionHandler) as ctx:
            await MappingServiceClient().resolve(IDENTIFIER)
        self.assertEqual(ctx.exception.error_code, 502)


if __name__ == "__main__":
    unittest.main()

# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Mapping is exposed as a passthrough on the core api.

The browser used to call the mapping service directly. It now goes
through core under /v1/mapping/resolve, which forwards to the
configured mapping microservice (or falls back to identity passthrough
when the service is disabled in system config).

Also covers the client facade itself: the disabled path answering
byte-identically to what the reference service would return, the enum
conversion at both edges of the wire, and the mapping of a response
the contract does not allow onto 502 rather than an unhandled 500.
"""

import json
import unittest
from unittest.mock import AsyncMock, patch

import httpx

from src.api.v1 import mapping
from src.clients.mapping.models.resolve_response import ResolveResponse
from src.clients.mapping.models.terraform_provider import (
    TerraformProvider as MappingTerraformProvider,
)
from src.clients.mapping.types import UNSET
from src.infrastructure.external import mapping_service
from src.infrastructure.external.mapping_service import (
    MappingServiceClient,
    ResolvedRef,
)
from src.main import app
from src.shared.config import system_config
from src.shared.config.system_config import ServiceConfig
from src.shared.constants import TerraformProvider
from src.shared.exceptions import ExceptionHandler

IDENTIFIER = "https://github.com/me/my-iac.git"


class TestMappingPassthroughWired(unittest.TestCase):
    # Asserted against the OpenAPI document rather than `app.routes`:
    # this FastAPI version keeps included routers as `_IncludedRouter`
    # wrappers with no `.path`, so a flat scan over `app.routes` sees
    # only the built-in docs endpoints.
    @classmethod
    def setUpClass(cls):
        cls.schema = app.openapi()

    def test_resolve_route_is_registered_on_app(self):
        self.assertIn("/v1/mapping/resolve", self.schema["paths"])

    def test_response_schema_is_published(self):
        # The endpoint used to publish only a prose example while the
        # SPA's types were hand-written against it. A real schema is
        # what lets the two be checked instead of drifting.
        response = self.schema["paths"]["/v1/mapping/resolve"]["post"]["responses"]
        ref = response["200"]["content"]["application/json"]["schema"]["$ref"]
        self.assertEqual(ref.rsplit("/", 1)[-1], "MappingResolveResponse")
        properties = self.schema["components"]["schemas"]["MappingResolveResponse"][
            "properties"
        ]
        self.assertEqual(
            set(properties),
            {"repo_url", "identifier", "terraform_provider", "scope_id"},
        )

    def test_endpoint_uses_mapping_service_client(self):
        self.assertIs(
            mapping.MappingServiceClient,
            mapping_service.MappingServiceClient,
        )


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

    def _patch_op(self, **kwargs):
        """Replace the generated op's `asyncio` entry point."""
        mock = AsyncMock(**kwargs)
        patcher = patch.object(mapping_service.resolve_op, "asyncio", mock)
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
            resolved,
            ResolvedRef(
                repo_url=IDENTIFIER,
                identifier=IDENTIFIER,
                terraform_provider=None,
                scope_id=None,
            ),
        )

    async def test_requested_provider_survives(self):
        resolved = await MappingServiceClient().resolve(
            IDENTIFIER, terraform_provider=TerraformProvider.GCP
        )
        self.assertEqual(resolved.terraform_provider, TerraformProvider.GCP)
        self.assertIsNone(resolved.scope_id)

    async def test_non_https_identifier_is_echoed_unchecked(self):
        resolved = await MappingServiceClient().resolve("my-project")
        self.assertEqual(resolved.repo_url, "my-project")

    async def test_service_is_never_contacted(self):
        op = self._patch_op(return_value=None)
        await MappingServiceClient().resolve(IDENTIFIER)
        op.assert_not_awaited()


class TestEnabledMappingConvertsEnums(MappingClientTestCase):
    """`ResolvedRef` speaks core's enum; the wire speaks the client's."""

    def setUp(self):
        self._configure(enabled=True)

    async def test_outbound_provider_is_converted_to_the_client_enum(self):
        op = self._patch_op(
            return_value=ResolveResponse(repo_url=IDENTIFIER, identifier=IDENTIFIER)
        )
        await MappingServiceClient().resolve(
            "my-project", terraform_provider=TerraformProvider.AZURE
        )
        body = op.await_args.kwargs["body"]
        self.assertEqual(body.identifier, "my-project")
        self.assertIs(body.terraform_provider, MappingTerraformProvider.AZURE)
        # Serialises to the contract's vocabulary, not `azurerm`.
        self.assertEqual(body.to_dict()["terraform_provider"], "azure")

    async def test_no_provider_is_left_unset_on_the_wire(self):
        op = self._patch_op(
            return_value=ResolveResponse(repo_url=IDENTIFIER, identifier=IDENTIFIER)
        )
        await MappingServiceClient().resolve("my-project")
        body = op.await_args.kwargs["body"]
        self.assertIs(body.terraform_provider, UNSET)
        self.assertNotIn("terraform_provider", body.to_dict())

    async def test_inbound_provider_is_converted_to_the_core_enum(self):
        self._patch_op(
            return_value=ResolveResponse(
                repo_url="https://git.example/iac.git",
                identifier="my-project",
                terraform_provider=MappingTerraformProvider.OCI,
                scope_id="ocid1.compartment.oc1..aaaa",
            )
        )
        resolved = await MappingServiceClient().resolve("my-project")
        self.assertEqual(
            resolved,
            ResolvedRef(
                repo_url="https://git.example/iac.git",
                identifier="my-project",
                terraform_provider=TerraformProvider.OCI,
                scope_id="ocid1.compartment.oc1..aaaa",
            ),
        )
        self.assertIsInstance(resolved.terraform_provider, TerraformProvider)

    async def test_omitted_optional_fields_become_none(self):
        self._patch_op(
            return_value=ResolveResponse(repo_url=IDENTIFIER, identifier=IDENTIFIER)
        )
        resolved = await MappingServiceClient().resolve(IDENTIFIER)
        self.assertIsNone(resolved.terraform_provider)
        self.assertIsNone(resolved.scope_id)

    async def test_explicit_nulls_become_none(self):
        self._patch_op(
            return_value=ResolveResponse(
                repo_url=IDENTIFIER,
                identifier=IDENTIFIER,
                terraform_provider=None,
                scope_id=None,
            )
        )
        resolved = await MappingServiceClient().resolve(IDENTIFIER)
        self.assertIsNone(resolved.terraform_provider)
        self.assertIsNone(resolved.scope_id)


class TestEnabledMappingFailureModes(MappingClientTestCase):
    def setUp(self):
        self._configure(enabled=True)

    async def test_provider_outside_the_enum_is_502(self):
        # `anyOf: [$ref, null]` makes the generated parser swallow the
        # ValueError and hand back the raw string, so an implementation
        # answering `azurerm` reaches us as a `str` where the enum is
        # declared. Left alone it escapes as an unhandled 500.
        self._patch_op(
            return_value=ResolveResponse(
                repo_url=IDENTIFIER,
                identifier=IDENTIFIER,
                terraform_provider="azurerm",
            )
        )
        with self.assertRaises(ExceptionHandler) as ctx:
            await MappingServiceClient().resolve(IDENTIFIER)
        self.assertEqual(ctx.exception.error_code, 502)
        self.assertIn("azurerm", ctx.exception.message)

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

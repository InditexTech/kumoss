# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""The Terraform Registry client behind the ``terraform_docs`` tool.

``/v1/providers`` pins the provider version and lists its pages,
``/v2/provider-docs`` returns one page. Every version's page index is
cached in-process, an unknown provider, version or type is a
``TerraformDocsNotFoundError`` the agent can act on, and a registry
that cannot be reached is a ``TerraformRegistryError`` it cannot.
"""

import unittest
from collections.abc import Callable
from typing import Any
from unittest.mock import patch

import httpx

from src.infrastructure.exceptions import (
    TerraformDocsNotFoundError,
    TerraformRegistryError,
)
from src.infrastructure.external import terraform_registry_service as registry
from src.infrastructure.external.terraform_registry_service import (
    TerraformRegistryClient,
)

_PAGE = """---
subcategory: "S3 (Simple Storage)"
page_title: "AWS: aws_s3_bucket"
---

# Resource: aws_s3_bucket

## Argument Reference

* `bucket` - (Optional, Forces new resource) Name of the bucket.

## Import

Using `terraform import`, import S3 bucket using the `bucket`. For example:

```console
% terraform import aws_s3_bucket.bucket bucket-name
```
"""

_INDEX = [
    {"id": "1", "slug": "s3_bucket", "category": "data-sources", "language": "hcl"},
    {"id": "2", "slug": "s3_bucket", "category": "resources", "language": "python"},
    {"id": "3", "slug": "s3_bucket", "category": "resources", "language": "hcl"},
]


def _provider(version: str, versions: list[str] | None = None) -> dict[str, Any]:
    return {"version": version, "versions": versions or [version], "docs": _INDEX}


def _page(doc_id: str) -> dict[str, Any]:
    return {"data": {"id": doc_id, "attributes": {"content": _PAGE}}}


class TestTerraformRegistryClient(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        TerraformRegistryClient._doc_indexes.clear()
        self.paths: list[str] = []

    def _routes(
        self, routes: dict[str, Any]
    ) -> Callable[[httpx.Request], httpx.Response]:
        def handler(request: httpx.Request) -> httpx.Response:
            self.paths.append(request.url.path)
            answer = routes.get(request.url.path)
            if answer is None:
                return httpx.Response(404)
            if isinstance(answer, httpx.Response):
                return answer
            return httpx.Response(200, json=answer)

        return handler

    async def _fetch(
        self,
        handler: Callable[[httpx.Request], httpx.Response],
        *args: Any,
        **kwargs: Any,
    ):
        real = httpx.AsyncClient
        with patch.object(
            registry.httpx,
            "AsyncClient",
            lambda **kw: real(transport=httpx.MockTransport(handler), **kw),
        ):
            return await TerraformRegistryClient().fetch(*args, **kwargs)

    async def test_an_exact_version_reads_its_hcl_resource_page(self):
        handler = self._routes(
            {
                "/v1/providers/hashicorp/aws/5.82.0": _provider("5.82.0"),
                "/v2/provider-docs/3": _page("3"),
            }
        )
        doc = await self._fetch(handler, "hashicorp/aws", "aws_s3_bucket", "5.82.0")

        self.assertEqual(doc.source, "hashicorp/aws")
        self.assertEqual(doc.version, "5.82.0")
        self.assertTrue(doc.content.startswith("# Resource: aws_s3_bucket"))
        self.assertTrue(
            doc.url.endswith("/providers/hashicorp/aws/5.82.0/docs/resources/s3_bucket")
        )

    async def test_the_page_index_of_a_version_is_cached(self):
        handler = self._routes(
            {
                "/v1/providers/hashicorp/aws/5.82.0": _provider("5.82.0"),
                "/v2/provider-docs/3": _page("3"),
            }
        )
        await self._fetch(handler, "hashicorp/aws", "aws_s3_bucket", "5.82.0")
        await self._fetch(handler, "hashicorp/aws", "aws_s3_bucket", "5.82.0")

        self.assertEqual(self.paths.count("/v1/providers/hashicorp/aws/5.82.0"), 1)

    async def test_no_version_reads_the_latest(self):
        handler = self._routes(
            {
                "/v1/providers/hashicorp/aws": _provider("6.70.0"),
                "/v2/provider-docs/3": _page("3"),
            }
        )
        doc = await self._fetch(handler, "aws", "aws_s3_bucket")

        self.assertEqual(doc.version, "6.70.0")
        self.assertEqual(self.paths[0], "/v1/providers/hashicorp/aws")

    async def test_a_prerelease_version_is_read_as_published(self):
        handler = self._routes(
            {
                "/v1/providers/hashicorp/aws/1.0.0-rc1": _provider("1.0.0-rc1"),
                "/v2/provider-docs/3": _page("3"),
            }
        )
        doc = await self._fetch(handler, "hashicorp/aws", "aws_s3_bucket", "1.0.0-rc1")

        self.assertEqual(doc.version, "1.0.0-rc1")

    async def test_a_data_source_reads_the_data_sources_page(self):
        handler = self._routes(
            {
                "/v1/providers/hashicorp/aws/5.82.0": _provider("5.82.0"),
                "/v2/provider-docs/1": _page("1"),
            }
        )
        doc = await self._fetch(
            handler, "hashicorp/aws", "aws_s3_bucket", "5.82.0", data_source=True
        )

        self.assertIn("/docs/data-sources/", doc.url)
        self.assertIn("/v2/provider-docs/1", self.paths)

    async def test_a_prefix_other_than_the_provider_name_is_found(self):
        index = [{"id": "9", "slug": "compute_instance", "category": "resources"}]
        handler = self._routes(
            {
                "/v1/providers/hashicorp/google-beta/6.0.0": {
                    "version": "6.0.0",
                    "docs": index,
                },
                "/v2/provider-docs/9": _page("9"),
            }
        )
        doc = await self._fetch(
            handler, "hashicorp/google-beta", "google_compute_instance", "6.0.0"
        )

        self.assertTrue(doc.url.endswith("/resources/compute_instance"))

    async def test_an_undocumented_type_is_not_found(self):
        handler = self._routes(
            {"/v1/providers/hashicorp/aws/5.82.0": _provider("5.82.0")}
        )
        with self.assertRaises(TerraformDocsNotFoundError) as e:
            await self._fetch(handler, "hashicorp/aws", "aws_nope", "5.82.0")
        self.assertIn("aws_nope", e.exception.message)

    async def test_an_unknown_version_is_not_found(self):
        with self.assertRaises(TerraformDocsNotFoundError):
            await self._fetch(
                self._routes({}), "hashicorp/aws", "aws_s3_bucket", "9.9.9"
            )

    async def test_a_constraint_goes_to_the_registry_and_is_not_found(self):
        handler = self._routes({"/v1/providers/hashicorp/aws": _provider("6.1.0")})
        with self.assertRaises(TerraformDocsNotFoundError):
            await self._fetch(handler, "hashicorp/aws", "aws_s3_bucket", "~> 5.0")
        self.assertNotIn("/v1/providers/hashicorp/aws", self.paths)

    async def test_a_server_error_is_a_registry_error(self):
        handler = self._routes(
            {"/v1/providers/hashicorp/aws/5.82.0": httpx.Response(503)}
        )
        with self.assertRaises(TerraformRegistryError):
            await self._fetch(handler, "hashicorp/aws", "aws_s3_bucket", "5.82.0")

    async def test_an_unreachable_registry_is_a_registry_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused", request=request)

        with self.assertRaises(TerraformRegistryError):
            await self._fetch(handler, "hashicorp/aws", "aws_s3_bucket", "5.82.0")


class TestImportSection(unittest.TestCase):
    def test_the_section_runs_to_the_end_of_the_page(self):
        section = TerraformRegistryClient.import_section(_PAGE)

        self.assertTrue(section.startswith("## Import"))
        self.assertIn("terraform import aws_s3_bucket.bucket bucket-name", section)
        self.assertNotIn("Argument Reference", section)

    def test_the_section_stops_at_the_next_level_two_heading(self):
        page = "## Import\n\nid\n\n### Identity\n\nx\n\n## Timeouts\n\ny"

        self.assertEqual(
            TerraformRegistryClient.import_section(page),
            "## Import\n\nid\n\n### Identity\n\nx",
        )

    def test_a_page_without_import_has_none(self):
        self.assertIsNone(
            TerraformRegistryClient.import_section(
                "# Resource: x\n\n## Argument Reference\n"
            )
        )


class TestProviderSource(unittest.TestCase):
    def test_source_forms(self):
        self.assertEqual(
            TerraformRegistryClient.split_source("aws"), ("hashicorp", "aws")
        )
        self.assertEqual(
            TerraformRegistryClient.split_source("Oracle/OCI"), ("oracle", "oci")
        )
        self.assertEqual(
            TerraformRegistryClient.split_source(
                "registry.terraform.io/hashicorp/azurerm"
            ),
            ("hashicorp", "azurerm"),
        )

    def test_another_host_is_rejected(self):
        with self.assertRaises(TerraformDocsNotFoundError):
            TerraformRegistryClient.split_source("example.com/acme/thing")

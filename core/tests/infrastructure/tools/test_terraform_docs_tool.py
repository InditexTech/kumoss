# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""The terraform_docs tool reads one registry page for the agent.

Whatever the section, the agent gets the documentation condensed by the
search summarizer to its required ``focus``: section ``import`` sends
only the page's "Import" section to the summarizer, section ``full``
the whole page. A provider, version or type the registry does not know asks
the agent to correct its call; a registry that cannot be reached sends
it to ``web_search`` instead. Neither fails the tool call.
"""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from src.domains.dto import ToolCallDTO
from src.domains.value_objects import SearchResult, TerraformDoc
from src.infrastructure.exceptions import (
    PageSummaryError,
    TerraformDocsNotFoundError,
    TerraformRegistryError,
)
from src.infrastructure.external.terraform_registry_service import (
    TerraformRegistryClient,
)
from src.infrastructure.tools.tool_registry_static import ToolRegistryStatic
from src.shared.constants import ToolContext

_CONTENT = """# Resource: aws_s3_bucket

## Argument Reference

* `bucket` - (Optional, Forces new resource) Name of the bucket.

## Import

```console
% terraform import aws_s3_bucket.bucket bucket-name
```
"""

_DOC = TerraformDoc(
    source="hashicorp/aws",
    version="5.82.0",
    resource_type="aws_s3_bucket",
    url="https://registry.terraform.io/providers/hashicorp/aws/5.82.0/docs/resources/s3_bucket",
    content=_CONTENT,
)


class TestTerraformDocsTool(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.summarizer = MagicMock(condense=AsyncMock(return_value="condensed"))
        self.registry = ToolRegistryStatic(summarizer=self.summarizer)

    async def _run(self, fetch: AsyncMock | None = None, **parameters):
        fetch = fetch or AsyncMock(return_value=_DOC)
        with patch.object(TerraformRegistryClient, "fetch", fetch):
            result = await self.registry.execute_tool(
                ToolCallDTO(
                    id="call_1",
                    name="terraform_docs",
                    parameters={
                        "provider": "hashicorp/aws",
                        "resource_type": "aws_s3_bucket",
                        "focus": "the import ID format",
                        **parameters,
                    },
                )
            )
        return result, fetch

    def test_the_tool_is_external_information(self):
        names = [
            t.name
            for t in self.registry.get_available_tools(ToolContext.EXTERNAL_INFORMATION)
        ]
        self.assertEqual(names, ["web_search", "terraform_docs"])

    async def test_import_condenses_only_the_import_section(self):
        result, fetch = await self._run(section="import", version="5.82.0")

        self.assertTrue(result.success)
        self.assertEqual(result.result["result"], "condensed")
        self.assertEqual(result.result["version"], "5.82.0")
        self.assertEqual(result.result["url"], _DOC.url)
        fetch.assert_awaited_once_with(
            "hashicorp/aws", "aws_s3_bucket", "5.82.0", data_source=False
        )
        query, page = self.summarizer.condense.await_args.args
        self.assertEqual(query, "aws_s3_bucket: the import ID format")
        self.assertEqual(
            page.content,
            "## Import\n\n```console\n"
            + "% terraform import aws_s3_bucket.bucket bucket-name\n```",
        )

    async def test_a_page_without_import_says_so(self):
        doc = TerraformDoc(**{**_DOC.__dict__, "content": "# Resource: x\n"})
        result, _ = await self._run(fetch=AsyncMock(return_value=doc), section="import")

        self.assertIn("has no Import section", result.result["result"])
        self.summarizer.condense.assert_not_awaited()

    async def test_full_is_condensed_to_the_focus(self):
        result, fetch = await self._run(focus="which arguments force replacement")

        self.assertEqual(result.result["result"], "condensed")
        self.assertEqual(result.result["section"], "full")
        query, page = self.summarizer.condense.await_args.args
        self.assertEqual(query, "aws_s3_bucket: which arguments force replacement")
        self.assertIsInstance(page, SearchResult)
        self.assertEqual(page.content, _CONTENT)
        self.assertEqual(page.url, _DOC.url)
        fetch.assert_awaited_once_with(
            "hashicorp/aws", "aws_s3_bucket", None, data_source=False
        )

    async def test_a_blank_focus_is_rejected(self):
        result, fetch = await self._run(focus="  ")

        self.assertFalse(result.success)
        self.assertIn("`focus`", result.error_message)
        fetch.assert_not_awaited()

    async def test_a_data_source_is_fetched_as_one(self):
        _, fetch = await self._run(kind="data_source")

        self.assertTrue(fetch.await_args.kwargs["data_source"])

    async def test_a_failed_summarizer_returns_the_raw_page(self):
        self.summarizer.condense.side_effect = PageSummaryError(
            message="boom", error_code=502
        )
        result, _ = await self._run()

        self.assertTrue(result.success)
        self.assertEqual(result.result["result"], _CONTENT)

    async def test_a_page_with_nothing_on_the_focus_says_so(self):
        self.summarizer.condense.return_value = None
        result, _ = await self._run(focus="pricing")

        self.assertIn("has nothing on 'pricing'", result.result["result"])

    async def test_a_data_source_has_no_import_section(self):
        result, fetch = await self._run(section="import", kind="data_source")

        self.assertFalse(result.success)
        self.assertIn("Data sources cannot be imported", result.error_message)
        fetch.assert_not_awaited()

    async def test_an_unknown_section_is_rejected(self):
        result, _ = await self._run(section="examples")

        self.assertFalse(result.success)

    async def test_not_found_asks_for_a_corrected_call(self):
        result, _ = await self._run(
            fetch=AsyncMock(
                side_effect=TerraformDocsNotFoundError(
                    message="hashicorp/aws 5.82.0 documents no resource named 'aws_nope'.",
                    error_code=404,
                )
            )
        )

        self.assertTrue(result.success)
        self.assertIn("aws_nope", result.result["result"])
        self.assertIn("do not repeat this call", result.result["result"])

    async def test_an_unreachable_registry_sends_the_agent_to_web_search(self):
        result, _ = await self._run(
            fetch=AsyncMock(
                side_effect=TerraformRegistryError(
                    message="the Terraform Registry timed out", error_code=504
                )
            )
        )

        self.assertTrue(result.success)
        self.assertIn("Do NOT retry terraform_docs", result.result["result"])
        self.assertIn("web_search", result.result["result"])

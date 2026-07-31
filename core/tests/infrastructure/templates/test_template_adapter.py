# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

# pyright: basic, reportAssignmentType=false, reportAttributeAccessIssue=false
import unittest

from unittest.mock import patch, AsyncMock
from src.infrastructure.templates.template_adapter import TemplateAdapter
from src.infrastructure.templates._fetcher import remote_fetcher

from src.shared.constants import TerraformProvider


PROVIDER_TEST_CASES = {
    TerraformProvider.AWS: {
        "mock_responses": {
            "abbreviations": "mocked_abbreviations",
            "resources_list": "mocked_resources_list",
            "s3_bucket": "mocked_s3_bucket_content",
        },
        "selected_templates": ["s3_bucket"],
        "selected_abbreviations": ["s3-"],
        "expected_present": [
            "mocked_abbreviations",
            "mocked_s3_bucket",
            "mocked_resources_list",
            "mocked_s3_bucket_content",
        ],
        "expected_absent": ["mocked_lambda_content"],
    },
    TerraformProvider.AZURE: {
        "mock_responses": {
            "abbreviations": "mocked_abbreviations",
            "resources_list": "mocked_resources_list",
            "storage_account": "mocked_storage_account_content",
        },
        "selected_templates": ["storage_account"],
        "selected_abbreviations": ["sta-"],
        "expected_present": [
            "mocked_abbreviations",
            "mocked_storage_account",
            "mocked_resources_list",
            "mocked_storage_account_content",
        ],
        "expected_absent": ["mocked_app_service_content"],
    },
    TerraformProvider.GCP: {
        "mock_responses": {
            "abbreviations": "mocked_abbreviations",
            "resources_list": "mocked_resources_list",
            "storage_bucket": "mocked_storage_bucket_content",
        },
        "selected_templates": ["storage_bucket"],
        "selected_abbreviations": ["stb-"],
        "expected_present": [
            "mocked_abbreviations",
            "mocked_storage_bucket",
            "mocked_resources_list",
            "mocked_storage_bucket_content",
        ],
        "expected_absent": ["mocked_cloud_run_content"],
    },
    TerraformProvider.OCI: {
        "mock_responses": {
            "abbreviations": "mocked_abbreviations",
            "resources_list": "mocked_resources_list",
            "object_storage": "mocked_object_storage_content",
        },
        "selected_templates": ["object_storage"],
        "selected_abbreviations": ["bkt-"],
        "expected_present": [
            "mocked_abbreviations",
            "mocked_object_storage",
            "mocked_resources_list",
            "mocked_object_storage_content",
        ],
        "expected_absent": ["mocked_compute_instance_content"],
    },
    TerraformProvider.K8S: {
        "mock_responses": {
            "abbreviations": "mocked_abbreviations",
            "resources_list": "mocked_resources_list",
            "deployment": "mocked_deployment_content",
        },
        "selected_templates": ["deployment"],
        "selected_abbreviations": ["deploy-"],
        "expected_present": [
            "mocked_abbreviations",
            "mocked_deployment",
            "mocked_resources_list",
            "mocked_deployment_content",
        ],
        "expected_absent": ["mocked_service_content"],
    },
}


class TestTemplateAdapter(unittest.IsolatedAsyncioTestCase):
    @patch.object(remote_fetcher, "fetch", new_callable=AsyncMock)
    async def _run_prompt_compositor_test(
        self, provider: TerraformProvider, mock_fetch: AsyncMock
    ):
        case = PROVIDER_TEST_CASES[provider]
        mock_fetch.side_effect = lambda prompt_name, **_: case["mock_responses"].get(
            prompt_name, f"default_{prompt_name}_mocked_response"
        )

        adapter = TemplateAdapter(template_provider=provider, cwd="/test/project")
        prompt = await adapter.render_prompt_compositor(
            already_selected_templates=case["selected_templates"],
            already_selected_abbreviations=case["selected_abbreviations"],
        )

        self.assertIsInstance(prompt, str)
        for expected in case["expected_present"]:
            self.assertIn(expected, prompt)
        for absent in case["expected_absent"]:
            self.assertNotIn(absent, prompt)

    async def test_render_prompt_compositor_aws(self):
        await self._run_prompt_compositor_test(TerraformProvider.AWS)

    async def test_render_prompt_compositor_azure(self):
        await self._run_prompt_compositor_test(TerraformProvider.AZURE)

    async def test_render_prompt_compositor_gcp(self):
        await self._run_prompt_compositor_test(TerraformProvider.GCP)

    async def test_render_prompt_compositor_oci(self):
        await self._run_prompt_compositor_test(TerraformProvider.OCI)

    async def test_render_prompt_compositor_kubernetes(self):
        await self._run_prompt_compositor_test(TerraformProvider.K8S)


if __name__ == "__main__":
    unittest.main()

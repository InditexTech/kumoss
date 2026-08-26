# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

# pyright: basic, reportAssignmentType=false, reportAttributeAccessIssue=false
import unittest

from unittest.mock import patch, AsyncMock
from src.infrastructure.templates.template_adapter import TemplateAdapter
from src.infrastructure.templates._fetcher import remote_fetcher

from src.shared.constants import OperationType, ReportType, TerraformProvider


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

    @patch.object(remote_fetcher, "fetch", new_callable=AsyncMock)
    async def test_render_requests_filter_generate(self, mock_fetch: AsyncMock):
        mock_fetch.side_effect = lambda prompt_name, **_: (
            f"mocked_{prompt_name}_response"
        )

        adapter = TemplateAdapter(
            template_provider=TerraformProvider.AZURE, cwd="/test/project"
        )
        prompt = await adapter.render_requests_filter(
            operation_type=OperationType.GENERATE,
            resources=["storage_account"],
            abbreviations=["sta-"],
            include_forbidden_actions=True,
        )

        self.assertIsInstance(prompt, str)
        self.assertIn("mocked_requests_response", prompt)
        self.assertIn("mocked_storage_account_response", prompt)
        self.assertIn("mocked_terraform_response", prompt)
        self.assertIn("mocked_forbidden_actions_response", prompt)
        self.assertIn("Missing parameters NEVER block a creation request", prompt)
        self.assertIn("When in doubt about parameters, accept", prompt)
        self.assertIn(
            "drift detection and remediation are available through the drift operation",
            prompt,
        )
        self.assertNotIn("DRIFT REQUEST", prompt)
        self.assertNotIn("full-workspace drift run", prompt)
        self.assertIn("requests_filter", prompt)
        self.assertNotIn("lacks information required to act", prompt)
        self.assertNotIn("{{", prompt)

    @patch.object(remote_fetcher, "fetch", new_callable=AsyncMock)
    async def test_render_requests_filter_drift(self, mock_fetch: AsyncMock):
        mock_fetch.side_effect = lambda prompt_name, **_: (
            f"mocked_{prompt_name}_response"
        )

        adapter = TemplateAdapter(
            template_provider=TerraformProvider.AZURE, cwd="/test/project"
        )
        prompt = await adapter.render_requests_filter(
            operation_type=OperationType.DRIFT,
            resources=["storage_account"],
            abbreviations=["sta-"],
            include_forbidden_actions=True,
        )

        self.assertIsInstance(prompt, str)
        # Phoenix guidelines and sentinel mandate present
        self.assertIn("mocked_requests_response", prompt)
        self.assertIn("requests_filter", prompt)
        # Forbidden actions, naming conventions and template names present
        self.assertIn("mocked_forbidden_actions_response", prompt)
        self.assertIn("sta-", prompt)
        self.assertIn("storage_account", prompt)
        # No generation rulebook fetches rendered
        self.assertNotIn("mocked_terraform_response", prompt)
        self.assertNotIn("mocked_resource_creation_response", prompt)
        self.assertNotIn("mocked_networking_response", prompt)
        self.assertNotIn("mocked_permissions_response", prompt)
        # No resource template bodies (name-only)
        self.assertNotIn("mocked_storage_account_response", prompt)
        # Drift category A present, generate category A absent
        self.assertIn("DRIFT REQUEST", prompt)
        self.assertIn("resolve the drift", prompt)
        self.assertIn(
            "infrastructure changes are available through the generation operation",
            prompt,
        )
        self.assertNotIn("Missing parameters NEVER block a creation request", prompt)
        self.assertNotIn("{{", prompt)

    @patch.object(remote_fetcher, "fetch", new_callable=AsyncMock)
    async def test_render_requests_filter_drift_no_generation_fetches(
        self, mock_fetch: AsyncMock
    ):
        mock_fetch.side_effect = lambda prompt_name, **_: (
            f"mocked_{prompt_name}_response"
        )

        adapter = TemplateAdapter(
            template_provider=TerraformProvider.AZURE, cwd="/test/project"
        )
        await adapter.render_requests_filter(
            operation_type=OperationType.DRIFT,
            resources=["storage_account"],
            abbreviations=["sta-"],
            include_forbidden_actions=True,
        )

        fetched = {call.kwargs["prompt_name"] for call in mock_fetch.call_args_list}
        self.assertEqual(fetched, {"requests", "forbidden_actions"})

    PR_GENERATOR_MARKERS = {
        OperationType.GENERATE: "introduces new or modified Terraform infrastructure",
        OperationType.DRIFT: "remediates configuration drift",
        OperationType.IMPORT: "under Terraform management",
    }

    def _run_pr_generator_test(self, operation_type: OperationType):
        adapter = TemplateAdapter(
            template_provider=TerraformProvider.AZURE, cwd="/test/project"
        )
        prompt = adapter.render_pr_generator(operation_type=operation_type)

        self.assertIsInstance(prompt, str)
        self.assertIn("<operation_type>", prompt)
        self.assertIn(operation_type.value, prompt)
        self.assertIn("generate_pull_request", prompt)
        self.assertIn("## Summary", prompt)
        for op, marker in self.PR_GENERATOR_MARKERS.items():
            if op is operation_type:
                self.assertIn(marker, prompt)
            else:
                self.assertNotIn(marker, prompt)
        self.assertNotIn("{{", prompt)
        self.assertNotIn("OperationType", prompt)

    def test_render_pr_generator_generate(self):
        self._run_pr_generator_test(OperationType.GENERATE)

    def test_render_pr_generator_drift(self):
        self._run_pr_generator_test(OperationType.DRIFT)

    def test_render_pr_generator_import(self):
        self._run_pr_generator_test(OperationType.IMPORT)

    REPORT_GENERATOR_MARKERS = {
        "plan": ("FOR PLAN ANALYSIS REPORTS", "generate_terraform_plan_report"),
        "drift": ("FOR DRIFT REMEDIATION REPORTS", "generate_terraform_drift_report"),
        "apply": ("FOR APPLY REPORTS", "generate_terraform_apply_report"),
    }

    def _run_report_generator_test(self, report_type: ReportType, branch: str | None):
        adapter = TemplateAdapter(
            template_provider=TerraformProvider.AZURE, cwd="/test/project"
        )
        prompt = adapter.render_report_generator(report_type=report_type)

        self.assertIsInstance(prompt, str)
        self.assertIn("<report_type>", prompt)
        self.assertIn(report_type.value, prompt)
        for key, markers in self.REPORT_GENERATOR_MARKERS.items():
            for marker in markers:
                if key == branch:
                    self.assertIn(marker, prompt)
                else:
                    self.assertNotIn(marker, prompt)
        self.assertNotIn("{{", prompt)
        self.assertNotIn("ReportType", prompt)

    def test_render_report_generator_generate(self):
        self._run_report_generator_test(ReportType.GENERATE, branch="plan")

    def test_render_report_generator_import(self):
        # IMPORT has no dedicated report workflow: no branch is rendered
        self._run_report_generator_test(ReportType.IMPORT, branch=None)

    def test_render_report_generator_drift(self):
        self._run_report_generator_test(ReportType.DRIFT, branch="drift")

    def test_render_report_generator_apply(self):
        self._run_report_generator_test(ReportType.APPLY, branch="apply")

    def test_render_target_generator(self):
        adapter = TemplateAdapter(
            template_provider=TerraformProvider.AZURE, cwd="/test/project"
        )
        prompt = adapter.render_target_generator()

        self.assertIsInstance(prompt, str)
        self.assertIn("REQUIRED FIRST STEP", prompt)
        self.assertIn("diff_history", prompt)
        self.assertIn("sole source of truth", prompt)
        self.assertNotIn("Respect user scoping", prompt)
        self.assertNotIn("Do not infer changes to unrelated resources", prompt)


if __name__ == "__main__":
    unittest.main()

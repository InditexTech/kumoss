# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

# pyright: basic, reportAssignmentType=false, reportAttributeAccessIssue=false
import unittest

from unittest.mock import patch, AsyncMock
from src.infrastructure.templates.template_adapter import TemplateAdapter
from src.infrastructure.templates._fetcher import remote_fetcher

from src.shared.config import system_config
from src.shared.constants import (
    OperationType,
    ReportType,
    TargetGenerationMode,
    TerraformProvider,
)


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
        )

        self.assertIsInstance(prompt, str)
        self.assertIn("mocked_requests_response", prompt)
        self.assertIn("mocked_forbidden_actions_response", prompt)
        self.assertIn("/test/project", prompt)
        self.assertIn("Missing parameters NEVER block a creation request", prompt)
        self.assertIn("When in doubt about parameters, accept", prompt)
        self.assertNotIn("DRIFT REQUEST", prompt)
        self.assertIn("requests_filter", prompt)
        self.assertEqual(mock_fetch.await_count, 2)
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
        )

        self.assertIsInstance(prompt, str)
        self.assertIn("mocked_requests_response", prompt)
        self.assertIn("requests_filter", prompt)
        self.assertIn("mocked_forbidden_actions_response", prompt)
        self.assertIn("/test/project", prompt)
        self.assertIn("DRIFT REQUEST", prompt)
        self.assertIn("resolve the drift", prompt)
        self.assertIn(
            "infrastructure creation is available through the generation operation",
            prompt,
        )
        self.assertNotIn("Missing parameters NEVER block a creation request", prompt)
        self.assertEqual(mock_fetch.await_count, 2)
        self.assertNotIn("{{", prompt)

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
        "import": ("FOR IMPORT REPORTS", "generate_terraform_import_report"),
    }

    @patch.object(remote_fetcher, "fetch", new_callable=AsyncMock)
    async def _run_report_generator_test(
        self,
        report_type: ReportType,
        branch: str | None,
        mock_fetch: AsyncMock,
    ):
        mock_fetch.return_value = "- mocked impact rule:\n  - mocked nested rule.\n"

        adapter = TemplateAdapter(
            template_provider=TerraformProvider.AZURE, cwd="/test/project"
        )
        prompt = await adapter.render_report_generator(report_type=report_type)

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
        return prompt, mock_fetch

    async def test_render_report_generator_generate(self):
        prompt, mock_fetch = await self._run_report_generator_test(
            ReportType.GENERATE, "plan"
        )

        self.assertIn(
            "  4. Analyze Potential Impact:\n"
            "  - mocked impact rule:\n"
            "    - mocked nested rule.\n"
            "\n"
            "  5. Generate Human-Friendly Explanations:",
            prompt,
        )
        mock_fetch.assert_awaited_once_with(
            prompt_name="impact",
            scope="general",
            type="compliance",
            tag=system_config.environment,
        )
        # The plan report reasons about a plan it is given, not the branch.
        self.assertNotIn("diff_history", prompt)

    async def test_render_report_generator_import(self):
        # IMPORT has no dedicated report workflow: no branch is rendered
        _, mock_fetch = await self._run_report_generator_test(ReportType.IMPORT, None)
        mock_fetch.assert_not_awaited()

    async def test_render_report_generator_drift(self):
        prompt, mock_fetch = await self._run_report_generator_test(
            ReportType.DRIFT, "drift"
        )
        mock_fetch.assert_not_awaited()

        self.assertIn("REQUIRED FIRST STEP", prompt)
        self.assertIn("diff_history", prompt)
        self.assertIn("sole source of truth", prompt)
        self.assertIn("unreconciled_drift", prompt)
        self.assertIn("whitelisted_exceptions", prompt)
        self.assertIn("belongs in `whitelisted_exceptions` alone", prompt)

    async def test_render_report_generator_apply(self):
        prompt, mock_fetch = await self._run_report_generator_test(
            ReportType.APPLY, "apply"
        )
        mock_fetch.assert_not_awaited()

        self.assertNotIn("diff_history", prompt)

    async def test_render_target_generator_session(self):
        adapter = TemplateAdapter(
            template_provider=TerraformProvider.AZURE, cwd="/test/project"
        )
        prompt = await adapter.render_target_generator(
            mode=TargetGenerationMode.SESSION
        )

        self.assertIsInstance(prompt, str)
        self.assertIn("REQUIRED FIRST STEP", prompt)
        self.assertIn("diff_history", prompt)
        self.assertIn("sole source of truth", prompt)
        self.assertNotIn("Impact Analysis", prompt)
        self.assertNotIn("Drift Remediation", prompt)
        self.assertIn("depends_on", prompt)

    def test_target_generation_modes_are_session_and_drift_only(self):
        self.assertEqual(
            [m.value for m in TargetGenerationMode],
            ["session", "drift"],
        )

    def test_render_task_splitter_drift(self):
        adapter = TemplateAdapter(
            template_provider=TerraformProvider.AZURE, cwd="/test/project"
        )
        prompt = adapter.render_task_splitter(operation_type=OperationType.DRIFT)

        self.assertIn("JSON drift report", prompt)
        self.assertIn("dictionary_item_added", prompt)
        self.assertIn("The real infrastructure is the source of truth", prompt)
        self.assertIn("Describe the Change Only", prompt)
        self.assertNotIn("fewest possible side effects", prompt)
        self.assertNotIn("Troubleshooting Strategist", prompt)
        self.assertNotIn("Root Cause", prompt)
        self.assertIn("`report_decomposed_task_operations`", prompt)
        self.assertNotIn("{{", prompt)
        self.assertNotIn("{%", prompt)

    def test_render_task_splitter_terraform_errors(self):
        adapter = TemplateAdapter(
            template_provider=TerraformProvider.AZURE, cwd="/test/project"
        )
        for operation_type in (OperationType.GENERATE, OperationType.IMPORT):
            with self.subTest(operation_type=operation_type):
                prompt = adapter.render_task_splitter(operation_type=operation_type)

                self.assertIn("Troubleshooting Strategist", prompt)
                self.assertIn("Identify Root Causes", prompt)
                self.assertIn("fewest possible side effects", prompt)
                self.assertNotIn("drift report", prompt)
                self.assertNotIn("source of truth", prompt)
                self.assertNotIn("dictionary_item_added", prompt)
                self.assertIn("`report_decomposed_task_operations`", prompt)
                self.assertNotIn("{{", prompt)
                self.assertNotIn("{%", prompt)

    def test_render_filter_reconciliation(self):
        adapter = TemplateAdapter(
            template_provider=TerraformProvider.AZURE, cwd="/test/project"
        )
        prompt = adapter.render_filter_reconciliation()

        self.assertIsInstance(prompt, str)
        self.assertIn("REQUIRED FIRST STEP", prompt)
        self.assertIn("diff_history", prompt)
        self.assertIn("report_reconciliation_verdicts", prompt)
        self.assertNotIn("report_decomposed_task_operations", prompt)
        self.assertIn("/test/project", prompt)
        self.assertIn("reverts_session_change", prompt)
        self.assertNotIn("{{", prompt)

    @patch.object(remote_fetcher, "fetch", new_callable=AsyncMock)
    async def test_render_filter_drift_exceptions(self, mock_fetch: AsyncMock):
        mock_fetch.return_value = "mocked_drift_exceptions"
        adapter = TemplateAdapter(
            template_provider=TerraformProvider.AWS, cwd="/test/project"
        )

        prompt = await adapter.render_filter_drift_exceptions()

        mock_fetch.assert_awaited_once_with(
            prompt_name="drift_exceptions",
            scope="aws",
            type="guidelines",
            tag=system_config.environment,
        )
        self.assertIn("mocked_drift_exceptions", prompt)
        self.assertIn("<exception_rules>", prompt)
        self.assertIn("report_decomposed_task_operations", prompt)
        self.assertIn("Trim it", prompt)
        # Text-only agent: no workspace tools, no working directory.
        self.assertNotIn("diff_history", prompt)
        self.assertNotIn("/test/project", prompt)
        self.assertNotIn("{{", prompt)

    @patch.object(remote_fetcher, "fetch", new_callable=AsyncMock)
    async def test_render_import_exceptions_returns_the_scope_list(
        self, mock_fetch: AsyncMock
    ):
        mock_fetch.return_value = "- /subscriptions/s/resourceGroups/rg-a"
        adapter = TemplateAdapter(
            template_provider=TerraformProvider.AZURE, cwd="/test/project"
        )

        body = await adapter.render_import_exceptions()

        mock_fetch.assert_awaited_once_with(
            prompt_name="import_exceptions",
            scope="azure",
            type="guidelines",
            tag=system_config.environment,
        )
        # Returned verbatim: reading the IDs out of it is the caller's job.
        self.assertEqual(body, "- /subscriptions/s/resourceGroups/rg-a")

    @patch.object(remote_fetcher, "fetch", new_callable=AsyncMock)
    async def test_render_import_filter_leaves_exceptions_to_code(
        self, mock_fetch: AsyncMock
    ):
        adapter = TemplateAdapter(
            template_provider=TerraformProvider.AZURE, cwd="/test/project"
        )

        prompt = await adapter.render_import_filter(
            unmanaged_ids=["res-1"], resources=[], abbreviations=[]
        )

        self.assertIn("- res-1", prompt)
        self.assertNotIn("exception", prompt.lower())
        mock_fetch.assert_not_awaited()

    @patch.object(remote_fetcher, "fetch", new_callable=AsyncMock)
    async def test_render_target_generator_drift(self, mock_fetch: AsyncMock):
        mock_fetch.return_value = "mocked_drift_guidelines"
        adapter = TemplateAdapter(
            template_provider=TerraformProvider.AZURE, cwd="/test/project"
        )
        prompt = await adapter.render_target_generator(
            mode=TargetGenerationMode.DRIFT,
            resources=["storage_account"],
        )

        self.assertIsInstance(prompt, str)
        self.assertIn("Drift Remediation", prompt)
        self.assertIn("generate_terraform_targets", prompt)
        self.assertIn("storage_account", prompt)
        self.assertIn("mocked_drift_guidelines", prompt)
        self.assertIn("/test/project", prompt)
        self.assertNotIn("{{", prompt)
        mock_fetch.assert_awaited_once()
        self.assertEqual(
            mock_fetch.await_args.kwargs["prompt_name"], "targeting_policies"
        )
        self.assertEqual(mock_fetch.await_args.kwargs["scope"], "general")


if __name__ == "__main__":
    unittest.main()

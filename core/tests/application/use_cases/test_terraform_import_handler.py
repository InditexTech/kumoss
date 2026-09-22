# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for TerraformImportHandler.

All collaborators are mocked: these cover the 6-step pipeline
(discovery → selection → config generation → import execution →
convergence validation → gate), the early-exit paths (filter
rejection, empty discovery, empty selection), partial import
failures, and that the session is saved even on errors.
"""

import json
import unittest
from unittest.mock import AsyncMock, MagicMock

from src.application.exceptions import TerraformValidationFailedError
from src.application.use_cases.terraform_import_handler import TerraformImportHandler
from src.domains.dto import (
    TerraformDiscoveryDTO,
    TerraformImportAttempt,
    TerraformImportDTO,
    TerraformValidationDTO,
    ToolResultDTO,
)
from src.domains.value_objects import Conventions
from src.shared.config import system_config
from src.shared.constants import (
    OperationType,
    ReportType,
    SessionStatus,
    ToolContext,
)


def _discovery(resource_ids: list[str], feedback: str = "") -> TerraformDiscoveryDTO:
    """Build a discovery outcome: ids to import, or the reason there are none."""
    return TerraformDiscoveryDTO(resource_ids=resource_ids, feedback=feedback)


def _validation_dto(
    validation: bool, plan: str = "plan output", targets: list[str] | None = None
) -> TerraformValidationDTO:
    return TerraformValidationDTO(
        validation=validation,
        feedback="" if validation else "validation failed",
        terraform_plan=plan,
        terraform_targets=targets or [],
    )


def _import_outcome(
    imported: list[tuple[str, str]] | None = None,
    failed: list[tuple[str, str]] | None = None,
) -> TerraformImportDTO:
    """Build the import round outcome from (address, resource_id) pairs."""
    return TerraformImportDTO(
        imported=[
            TerraformImportAttempt(address=address, resource_id=resource_id)
            for address, resource_id in imported or []
        ],
        failed=[
            TerraformImportAttempt(
                address=address,
                resource_id=resource_id,
                error=f"import failed for {address}",
            )
            for address, resource_id in failed or []
        ],
    )


def _filter_result(selected: list[str], explanation: str = "matched") -> ToolResultDTO:
    return ToolResultDTO(
        name="report_decomposed_task_operations",
        tool_call_id="tc_1",
        success=True,
        result={"operations": selected, "explanation": explanation},
    )


class TestTerraformImportHandler(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.session_svc = AsyncMock()
        self.terraform_svc = AsyncMock()
        self.validation_svc = AsyncMock()
        self.template_svc = AsyncMock()
        self.requests_filter_svc = AsyncMock()
        self.import_svc = AsyncMock()
        self.import_address_svc = AsyncMock()
        self.import_address_svc.get_import_addresses.return_value = []
        self.target_svc = AsyncMock()
        self.drift_svc = AsyncMock()
        self.drift_svc.detect_and_resolve_drift.return_value = _validation_dto(True)
        self.report_svc = AsyncMock()
        self.llm_svc = AsyncMock()
        self.tool_svc = MagicMock()

        self.ctx = MagicMock()
        self.ctx.scope_id = "scope-123"
        self.ctx.terraform_prv = "azure"
        self.ctx.branch_name = "import/session-1"
        self.ctx.id = "session-1"
        self.ctx.operation = "IMPORT"
        self.ctx.history = MagicMock()

        self.template_svc.compose_template.return_value = Conventions(
            templates=["tpl_a"], abbreviations=["abbr_a"]
        )

        self.handler = TerraformImportHandler(
            session_ctx=self.ctx,
            session_service=self.session_svc,
            terraform_service=self.terraform_svc,
            validation_service=self.validation_svc,
            template_service=self.template_svc,
            requests_filter_service=self.requests_filter_svc,
            import_service=self.import_svc,
            import_address_service=self.import_address_svc,
            target_service=self.target_svc,
            drift_service=self.drift_svc,
            report_service=self.report_svc,
            llm_service=self.llm_svc,
            tool_service=self.tool_svc,
        )

    # --- Filter rejection ---

    async def test_filter_rejection_sets_uncompleted_and_saves(self):
        self.requests_filter_svc.filter.return_value = (False, "not an import request")

        task = await self.handler.handle("create a vnet", is_partial=True)
        await task()

        self.session_svc.next_round.assert_awaited_once_with("create a vnet")
        status_kwargs = self.session_svc.update_status.await_args.kwargs
        self.assertIs(status_kwargs["status"], SessionStatus.UNCOMPLETED)
        self.import_svc.get_unmanaged_resources.assert_not_awaited()
        self.session_svc.save.assert_awaited_once()

    # --- Step 1: Discovery ---

    async def test_empty_discovery_reports_why_nothing_can_be_imported(self):
        self.requests_filter_svc.filter.return_value = (True, "")
        self.import_svc.get_unmanaged_resources.return_value = _discovery(
            [], "Every resource in the scope scope-123 is already managed."
        )

        task = await self.handler.handle("import everything", is_partial=True)
        await task()

        # An empty scope is a completed round with an empty report, not a
        # dead end: the runner completes any handler that returns cleanly.
        # The report says which dead end discovery reached.
        report_kwargs = self.report_svc.generate_report.await_args.kwargs
        self.assertIs(report_kwargs["type"], ReportType.IMPORT)
        payload = json.loads(report_kwargs["content"])
        self.assertEqual(payload["selected_resource_ids"], [])
        self.assertIn("already managed", payload["summary"])
        self.llm_svc.generate.assert_not_awaited()
        self.session_svc.save.assert_awaited_once()

    async def test_failed_scope_query_reports_the_diagnostics(self):
        self.requests_filter_svc.filter.return_value = (True, "")
        self.import_svc.get_unmanaged_resources.return_value = _discovery(
            [], "The scope scope-123 could not be listed: Error: invalid token"
        )

        task = await self.handler.handle("import everything", is_partial=True)
        await task()

        # A failed cloud query is a succeeded IaC job, so the round closes
        # on the same path — carrying the provider's own diagnostics
        # instead of aborting the session.
        payload = json.loads(
            self.report_svc.generate_report.await_args.kwargs["content"]
        )
        self.assertIn("Error: invalid token", payload["summary"])
        self.validation_svc.generate_and_validate.assert_not_awaited()
        self.session_svc.save.assert_awaited_once()

    # --- Step 2: Selection ---

    async def test_empty_selection_reports_the_filter_explanation(self):
        self.requests_filter_svc.filter.return_value = (True, "")
        self.import_svc.get_unmanaged_resources.return_value = _discovery(
            ["res-1", "res-2"]
        )
        self.llm_svc.generate.return_value = _filter_result(
            [], "none of the resources match the query"
        )

        task = await self.handler.handle("import the database", is_partial=True)
        await task()

        payload = json.loads(
            self.report_svc.generate_report.await_args.kwargs["content"]
        )
        self.assertEqual(payload["summary"], "none of the resources match the query")
        self.assertEqual(payload["selected_resource_ids"], [])
        self.validation_svc.generate_and_validate.assert_not_awaited()
        self.session_svc.save.assert_awaited_once()

    async def test_selection_calls_llm_with_task_splitter_sentinel(self):
        self.requests_filter_svc.filter.return_value = (True, "")
        self.import_svc.get_unmanaged_resources.return_value = _discovery(["res-1"])
        self.llm_svc.generate.return_value = _filter_result(["res-1"])
        self.validation_svc.generate_and_validate.return_value = _validation_dto(True)
        self.import_address_svc.get_import_addresses.return_value = []
        self.import_svc.import_resources.return_value = _import_outcome()

        task = await self.handler.handle("import everything", is_partial=True)
        await task()

        # The task splitter sentinel is passed exactly once, inside `tools`,
        # and never duplicated through a separate `sentinel_tool` kwarg.
        llm_kwargs = self.llm_svc.generate.await_args.kwargs
        sentinel = self.tool_svc.get_sentinel_tool.return_value
        self.assertEqual(llm_kwargs["tools"], [sentinel])
        self.assertNotIn("sentinel_tool", llm_kwargs)
        self.tool_svc.get_sentinel_tool.assert_called_with(
            context=ToolContext.TASK_SPLITTER
        )

    # --- Full round (is_partial=False) ---

    async def test_full_round_imports_every_unmanaged_id_unfiltered(self):
        self.import_svc.get_unmanaged_resources.return_value = _discovery(
            ["res-1", "res-2"]
        )
        self.validation_svc.generate_and_validate.return_value = _validation_dto(True)
        self.import_address_svc.get_import_addresses.return_value = [
            ("azurerm_resource_group.main", "res-1")
        ]
        self.import_svc.import_resources.return_value = _import_outcome(
            imported=[("azurerm_resource_group.main", "res-1")]
        )

        task = await self.handler.handle("import everything", is_partial=False)
        await task()

        # A full round asks neither the request analyst nor the import_filter
        # agent: the whole scope diff is the selection.
        self.requests_filter_svc.filter.assert_not_awaited()
        self.llm_svc.generate.assert_not_awaited()
        # Every unmanaged id is carried to the generator inside the query.
        gen_q = self.validation_svc.generate_and_validate.await_args.kwargs["q"]
        self.assertTrue(gen_q.startswith("import everything"))
        self.assertIn("- res-1", gen_q)
        self.assertIn("- res-2", gen_q)

    async def test_full_round_with_empty_discovery_reports_nothing_to_import(self):
        self.import_svc.get_unmanaged_resources.return_value = _discovery(
            [], "The scope scope-123 holds no importable resource."
        )

        task = await self.handler.handle("import everything", is_partial=False)
        await task()

        payload = json.loads(
            self.report_svc.generate_report.await_args.kwargs["content"]
        )
        self.assertIn("no importable resource", payload["summary"])
        self.requests_filter_svc.filter.assert_not_awaited()
        self.validation_svc.generate_and_validate.assert_not_awaited()
        self.session_svc.save.assert_awaited_once()

    # --- Step 3: Config generation ---

    async def test_config_generation_carries_selected_ids_in_the_query(self):
        self.requests_filter_svc.filter.return_value = (True, "")
        self.import_svc.get_unmanaged_resources.return_value = _discovery(["res-1"])
        self.llm_svc.generate.return_value = _filter_result(["res-1"])
        self.validation_svc.generate_and_validate.return_value = _validation_dto(True)
        self.import_address_svc.get_import_addresses.return_value = [
            ("azurerm_resource_group.main", "res-1")
        ]
        self.import_svc.import_resources.return_value = _import_outcome(
            imported=[("azurerm_resource_group.main", "res-1")]
        )
        self.terraform_svc.validate.return_value = _validation_dto(True)

        task = await self.handler.handle("import res-1", is_partial=True)
        await task()

        # The selected ids reach the generator through the query, not through
        # the system prompt: the prompt says how to write Terraform, the query
        # says which resources to write it for.
        gen_kwargs = self.validation_svc.generate_and_validate.await_args.kwargs
        self.assertIs(gen_kwargs["operation_type"], OperationType.IMPORT)
        self.assertFalse(gen_kwargs["include_forbidden_actions"])
        self.assertNotIn("selected_ids", gen_kwargs)
        self.assertTrue(gen_kwargs["q"].startswith("import res-1"))
        self.assertIn("- res-1", gen_kwargs["q"])

    async def test_config_generation_failure_raises(self):
        self.requests_filter_svc.filter.return_value = (True, "")
        self.import_svc.get_unmanaged_resources.return_value = _discovery(["res-1"])
        self.llm_svc.generate.return_value = _filter_result(["res-1"])
        self.validation_svc.generate_and_validate.return_value = _validation_dto(False)
        self.report_svc.summarize_problem.return_value = (
            "generation failed: validation failed"
        )

        task = await self.handler.handle("import res-1", is_partial=True)
        with self.assertRaises(TerraformValidationFailedError) as raised:
            await task()

        self.report_svc.summarize_problem.assert_awaited_once()
        self.assertEqual(
            raised.exception.message, "generation failed: validation failed"
        )
        self.import_svc.import_resources.assert_not_awaited()
        self.session_svc.save.assert_awaited_once()

    # --- Step 4: Import execution ---

    async def test_import_execution_uses_the_mapped_addresses(self):
        self.requests_filter_svc.filter.return_value = (True, "")
        self.import_svc.get_unmanaged_resources.return_value = _discovery(
            ["res-1", "res-2"]
        )
        self.llm_svc.generate.return_value = _filter_result(["res-1", "res-2"])
        self.validation_svc.generate_and_validate.return_value = _validation_dto(True)
        self.import_address_svc.get_import_addresses.return_value = [
            ("azurerm_resource_group.main", "res-1"),
            ("azurerm_virtual_network.vnet", "res-2"),
        ]
        self.import_svc.import_resources.return_value = _import_outcome(
            imported=[
                ("azurerm_resource_group.main", "res-1"),
                ("azurerm_virtual_network.vnet", "res-2"),
            ]
        )
        self.terraform_svc.validate.return_value = _validation_dto(True)

        task = await self.handler.handle("import all", is_partial=True)
        await task()

        # The mapping needs the selection to rebuild the ids: a generated
        # block never carries its own cloud resource id.
        self.import_address_svc.get_import_addresses.assert_awaited_once_with(
            ["res-1", "res-2"]
        )
        self.import_svc.import_resources.assert_awaited_once_with(
            [
                ("azurerm_resource_group.main", "res-1"),
                ("azurerm_virtual_network.vnet", "res-2"),
            ]
        )

    async def test_partial_import_failure_does_not_abort(self):
        self.requests_filter_svc.filter.return_value = (True, "")
        self.import_svc.get_unmanaged_resources.return_value = _discovery(
            ["res-1", "res-2"]
        )
        self.llm_svc.generate.return_value = _filter_result(["res-1", "res-2"])
        self.validation_svc.generate_and_validate.return_value = _validation_dto(True)
        self.import_address_svc.get_import_addresses.return_value = [
            ("azurerm_resource_group.main", "res-1"),
            ("azurerm_virtual_network.vnet", "res-2"),
        ]
        self.import_svc.import_resources.return_value = _import_outcome(
            imported=[("azurerm_resource_group.main", "res-1")],
            failed=[("azurerm_virtual_network.vnet", "res-2")],
        )
        self.terraform_svc.validate.return_value = _validation_dto(True)

        task = await self.handler.handle("import all", is_partial=True)
        await task()

        self.report_svc.generate_report.assert_awaited_once()

    async def test_no_mapped_address_yields_empty_imports(self):
        self.requests_filter_svc.filter.return_value = (True, "")
        self.import_svc.get_unmanaged_resources.return_value = _discovery(["res-1"])
        self.llm_svc.generate.return_value = _filter_result(["res-1"])
        self.validation_svc.generate_and_validate.return_value = _validation_dto(True)
        self.import_address_svc.get_import_addresses.return_value = []
        self.import_svc.import_resources.return_value = _import_outcome()

        task = await self.handler.handle("import res-1", is_partial=True)
        await task()

        self.import_svc.import_resources.assert_awaited_once_with([])

    # --- Step 5: Convergence validation ---

    async def test_convergence_runs_on_successful_imports(self):
        self.requests_filter_svc.filter.return_value = (True, "")
        self.import_svc.get_unmanaged_resources.return_value = _discovery(["res-1"])
        self.llm_svc.generate.return_value = _filter_result(["res-1"])
        self.validation_svc.generate_and_validate.return_value = _validation_dto(True)
        self.import_address_svc.get_import_addresses.return_value = [
            ("azurerm_resource_group.main", "res-1")
        ]
        self.import_svc.import_resources.return_value = _import_outcome(
            imported=[("azurerm_resource_group.main", "res-1")]
        )

        task = await self.handler.handle("import res-1", is_partial=True)
        await task()

        self.drift_svc.detect_and_resolve_drift.assert_awaited_once()
        drift_kwargs = self.drift_svc.detect_and_resolve_drift.await_args.kwargs
        self.assertEqual(drift_kwargs["targets"], ["azurerm_resource_group.main"])
        self.assertEqual(
            drift_kwargs["conventions"],
            Conventions(templates=["tpl_a"], abbreviations=["abbr_a"]),
        )
        self.assertEqual(
            drift_kwargs["max_iterations"],
            system_config.orchestration.max_drift_reports,
        )

    async def test_convergence_delegates_planning_to_the_drift_service(self):
        self.requests_filter_svc.filter.return_value = (True, "")
        self.import_svc.get_unmanaged_resources.return_value = _discovery(["res-1"])
        self.llm_svc.generate.return_value = _filter_result(["res-1"])
        self.validation_svc.generate_and_validate.return_value = _validation_dto(True)
        self.import_address_svc.get_import_addresses.return_value = [
            ("azurerm_resource_group.main", "res-1")
        ]
        self.import_svc.import_resources.return_value = _import_outcome(
            imported=[("azurerm_resource_group.main", "res-1")]
        )
        self.terraform_svc.validate.return_value = _validation_dto(True)

        task = await self.handler.handle("import res-1", is_partial=True)
        await task()

        # The drift service plans the imported addresses itself, so the
        # handler neither plans nor narrows the round to session changes.
        drift_kwargs = self.drift_svc.detect_and_resolve_drift.await_args.kwargs
        self.assertIs(drift_kwargs["filter_session_changes"], False)
        self.terraform_svc.validate.assert_not_awaited()

    async def test_report_uses_convergence_plan_when_imports_succeed(self):
        self.requests_filter_svc.filter.return_value = (True, "")
        self.import_svc.get_unmanaged_resources.return_value = _discovery(["res-1"])
        self.llm_svc.generate.return_value = _filter_result(["res-1"])
        self.validation_svc.generate_and_validate.return_value = _validation_dto(
            True, plan="generation plan"
        )
        self.import_address_svc.get_import_addresses.return_value = [
            ("azurerm_resource_group.main", "res-1")
        ]
        self.import_svc.import_resources.return_value = _import_outcome(
            imported=[("azurerm_resource_group.main", "res-1")]
        )
        self.drift_svc.detect_and_resolve_drift.return_value = _validation_dto(
            True, plan="convergence plan"
        )

        task = await self.handler.handle("import res-1", is_partial=True)
        await task()

        report_kwargs = self.report_svc.generate_report.await_args.kwargs
        payload = json.loads(report_kwargs["content"])
        self.assertEqual(payload["plan_after_import"], "convergence plan")

    async def test_unresolved_convergence_does_not_abort(self):
        self.requests_filter_svc.filter.return_value = (True, "")
        self.import_svc.get_unmanaged_resources.return_value = _discovery(["res-1"])
        self.llm_svc.generate.return_value = _filter_result(["res-1"])
        self.validation_svc.generate_and_validate.return_value = _validation_dto(True)
        self.import_address_svc.get_import_addresses.return_value = [
            ("azurerm_resource_group.main", "res-1")
        ]
        self.import_svc.import_resources.return_value = _import_outcome(
            imported=[("azurerm_resource_group.main", "res-1")]
        )
        self.drift_svc.detect_and_resolve_drift.return_value = _validation_dto(False)

        task = await self.handler.handle("import res-1", is_partial=True)
        await task()

        self.report_svc.generate_report.assert_awaited_once()

    async def test_convergence_skipped_when_all_imports_fail(self):
        self.requests_filter_svc.filter.return_value = (True, "")
        self.import_svc.get_unmanaged_resources.return_value = _discovery(["res-1"])
        self.llm_svc.generate.return_value = _filter_result(["res-1"])
        self.validation_svc.generate_and_validate.return_value = _validation_dto(True)
        self.import_address_svc.get_import_addresses.return_value = [
            ("azurerm_resource_group.main", "res-1")
        ]
        self.import_svc.import_resources.return_value = _import_outcome(
            failed=[("azurerm_resource_group.main", "res-1")]
        )

        task = await self.handler.handle("import res-1", is_partial=True)
        await task()

        self.drift_svc.detect_and_resolve_drift.assert_not_awaited()

    # --- Step 6: Gate ---

    async def test_gate_generates_import_report(self):
        self.requests_filter_svc.filter.return_value = (True, "")
        self.import_svc.get_unmanaged_resources.return_value = _discovery(["res-1"])
        self.llm_svc.generate.return_value = _filter_result(["res-1"])
        self.validation_svc.generate_and_validate.return_value = _validation_dto(
            True, plan="the plan"
        )
        self.import_address_svc.get_import_addresses.return_value = []
        self.import_svc.import_resources.return_value = _import_outcome()

        task = await self.handler.handle("import res-1", is_partial=True)
        await task()

        report_kwargs = self.report_svc.generate_report.await_args.kwargs
        self.assertIs(report_kwargs["type"], ReportType.IMPORT)
        payload = json.loads(report_kwargs["content"])
        self.assertEqual(payload["plan_after_import"], "the plan")

    async def test_report_content_carries_the_per_resource_import_outcome(self):
        self.requests_filter_svc.filter.return_value = (True, "")
        self.import_svc.get_unmanaged_resources.return_value = _discovery(
            ["res-1", "res-2"]
        )
        self.llm_svc.generate.return_value = _filter_result(["res-1", "res-2"])
        self.validation_svc.generate_and_validate.return_value = _validation_dto(True)
        self.import_address_svc.get_import_addresses.return_value = [
            ("azurerm_resource_group.main", "res-1"),
            ("azurerm_storage_account.sta", "res-2"),
        ]
        self.import_svc.import_resources.return_value = _import_outcome(
            imported=[("azurerm_resource_group.main", "res-1")],
            failed=[("azurerm_storage_account.sta", "res-2")],
        )
        self.drift_svc.detect_and_resolve_drift.return_value = _validation_dto(
            True, plan="no changes"
        )

        task = await self.handler.handle("import res-1 and res-2", is_partial=True)
        await task()

        # A clean plan says nothing on its own, so the import report is fed
        # the outcome of every attempted import, successes and failures alike.
        payload = json.loads(
            self.report_svc.generate_report.await_args.kwargs["content"]
        )
        self.assertEqual(payload["selected_resource_ids"], ["res-1", "res-2"])
        self.assertEqual(
            payload["import_results"],
            {
                "imported": [
                    {
                        "address": "azurerm_resource_group.main",
                        "resource_id": "res-1",
                        "error": "",
                    },
                ],
                "failed": [
                    {
                        "address": "azurerm_storage_account.sta",
                        "resource_id": "res-2",
                        "error": "import failed for azurerm_storage_account.sta",
                    },
                ],
            },
        )

    # --- Session always saved ---

    async def test_session_saved_on_filter_rejection(self):
        self.requests_filter_svc.filter.return_value = (False, "rejected")

        task = await self.handler.handle("create something", is_partial=True)
        await task()

        self.session_svc.save.assert_awaited_once()

    async def test_session_saved_on_generation_failure(self):
        self.requests_filter_svc.filter.return_value = (True, "")
        self.import_svc.get_unmanaged_resources.return_value = _discovery(["res-1"])
        self.llm_svc.generate.return_value = _filter_result(["res-1"])
        self.validation_svc.generate_and_validate.return_value = _validation_dto(False)
        self.report_svc.summarize_problem.return_value = "failed"

        task = await self.handler.handle("import res-1", is_partial=True)
        with self.assertRaises(TerraformValidationFailedError):
            await task()

        self.session_svc.save.assert_awaited_once()

    # --- Pipeline ordering ---

    async def test_steps_execute_in_order(self):
        order: list[str] = []

        async def track_filter(*args, **kwargs):
            order.append("filter")
            return (True, "")

        async def track_discovery(*args, **kwargs):
            order.append("discovery")
            return _discovery(["res-1"])

        async def track_selection(*args, **kwargs):
            order.append("selection")
            return _filter_result(["res-1"])

        async def track_generation(*args, **kwargs):
            order.append("generation")
            return _validation_dto(True)

        async def track_import(*args, **kwargs):
            order.append("import")
            return _import_outcome(imported=[("azurerm_resource_group.main", "res-1")])

        async def track_convergence(*args, **kwargs):
            order.append("convergence")
            return _validation_dto(True)

        self.requests_filter_svc.filter.side_effect = track_filter
        self.import_svc.get_unmanaged_resources.side_effect = track_discovery
        self.llm_svc.generate.side_effect = track_selection
        self.validation_svc.generate_and_validate.side_effect = track_generation
        self.import_address_svc.get_import_addresses.return_value = [
            ("azurerm_resource_group.main", "res-1")
        ]
        self.import_svc.import_resources.side_effect = track_import
        self.drift_svc.detect_and_resolve_drift.side_effect = track_convergence

        task = await self.handler.handle("import all", is_partial=True)
        await task()

        self.assertEqual(
            order,
            ["filter", "discovery", "selection", "generation", "import", "convergence"],
        )


if __name__ == "__main__":
    unittest.main()

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

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from src.application.exceptions import SetLockError, TerraformValidationFailedError
from src.application.use_cases.terraform_import_handler import TerraformImportHandler
from src.domains.dto import ComplianceCheckReport, TerraformValidationDTO, ToolResultDTO
from src.domains.value_objects import Conventions
from src.shared.config import system_config
from src.shared.constants import (
    PromptsLibrary,
    ReportType,
    SessionStatus,
    ToolContext,
)


def _validation_dto(
    validation: bool, plan: str = "plan output", targets: list[str] | None = None
) -> TerraformValidationDTO:
    return TerraformValidationDTO(
        validation=validation,
        feedback="" if validation else "validation failed",
        terraform_plan=plan,
        terraform_targets=targets or [],
    )


def _import_dto(validation: bool, address: str) -> TerraformValidationDTO:
    return TerraformValidationDTO(
        validation=validation,
        feedback="" if validation else f"import failed for {address}",
        terraform_plan="",
        terraform_targets=[address],
    )


def _filter_result(selected: list[str], explanation: str = "matched") -> ToolResultDTO:
    return ToolResultDTO(
        name="iac_filter",
        tool_call_id="tc_1",
        success=True,
        result={"selected_resource_ids": selected, "explanation": explanation},
    )


def _generation_result(imports: list[dict]) -> ToolResultDTO:
    return ToolResultDTO(
        name="iac_import",
        tool_call_id="tc_2",
        success=True,
        result={"status": True, "summary": "done", "imports": imports},
    )


class TestTerraformImportHandler(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.session_svc = AsyncMock()
        self.terraform_svc = AsyncMock()
        self.validation_svc = AsyncMock()
        self.template_svc = AsyncMock()
        self.requests_filter_svc = AsyncMock()
        self.import_svc = AsyncMock()
        self.drift_svc = AsyncMock()
        self.drift_svc.detect_and_resolve_drift.return_value = _validation_dto(True)
        self.report_svc = AsyncMock()
        self.compliance_svc = AsyncMock()
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
            drift_service=self.drift_svc,
            report_service=self.report_svc,
            compliance_service=self.compliance_svc,
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

    async def test_empty_discovery_sets_uncompleted(self):
        self.requests_filter_svc.filter.return_value = (True, "")
        self.import_svc.get_unmanaged_resources.return_value = []

        task = await self.handler.handle("import everything", is_partial=True)
        await task()

        status_kwargs = self.session_svc.update_status.await_args.kwargs
        self.assertIs(status_kwargs["status"], SessionStatus.UNCOMPLETED)
        self.assertIn("No unmanaged resources", status_kwargs["msg"])
        self.llm_svc.generate.assert_not_awaited()
        self.session_svc.save.assert_awaited_once()

    # --- Step 2: Selection ---

    async def test_empty_selection_sets_uncompleted_with_explanation(self):
        self.requests_filter_svc.filter.return_value = (True, "")
        self.import_svc.get_unmanaged_resources.return_value = ["res-1", "res-2"]
        self.llm_svc.generate.return_value = _filter_result(
            [], "none of the resources match the query"
        )

        task = await self.handler.handle("import the database", is_partial=True)
        await task()

        status_kwargs = self.session_svc.update_status.await_args.kwargs
        self.assertIs(status_kwargs["status"], SessionStatus.UNCOMPLETED)
        self.assertEqual(status_kwargs["msg"], "none of the resources match the query")
        self.validation_svc.generate_and_validate.assert_not_awaited()
        self.session_svc.save.assert_awaited_once()

    async def test_selection_calls_llm_with_iac_filter_sentinel(self):
        self.requests_filter_svc.filter.return_value = (True, "")
        self.import_svc.get_unmanaged_resources.return_value = ["res-1"]
        self.llm_svc.generate.return_value = _filter_result(["res-1"])
        self.validation_svc.generate_and_validate.return_value = _validation_dto(True)
        self.validation_svc.last_generation_result = _generation_result([])
        self.import_svc.import_resources.return_value = []
        self.compliance_svc.check.return_value = ComplianceCheckReport.empty()

        task = await self.handler.handle("import everything", is_partial=True)
        with patch(
            "src.application.use_cases.terraform_import_handler.DatabaseService"
        ) as db_mock:
            db_mock.set_lock = AsyncMock(return_value=True)
            await task()

        # The iac_filter sentinel is passed exactly once, inside `tools`,
        # and never duplicated through a separate `sentinel_tool` kwarg.
        llm_kwargs = self.llm_svc.generate.await_args.kwargs
        sentinel = self.tool_svc.get_sentinel_tool.return_value
        self.assertEqual(llm_kwargs["tools"], [sentinel])
        self.assertNotIn("sentinel_tool", llm_kwargs)
        self.tool_svc.get_sentinel_tool.assert_called_with(
            context=ToolContext.IAC_FILTER
        )

    # --- Full round (is_partial=False) ---

    async def test_full_round_imports_every_unmanaged_id_unfiltered(self):
        self.import_svc.get_unmanaged_resources.return_value = ["res-1", "res-2"]
        self.validation_svc.generate_and_validate.return_value = _validation_dto(True)
        self.validation_svc.last_generation_result = _generation_result(
            [{"address": "azurerm_resource_group.main", "resource_id": "res-1"}]
        )
        self.import_svc.import_resources.return_value = [
            _import_dto(True, "azurerm_resource_group.main")
        ]
        self.compliance_svc.check.return_value = ComplianceCheckReport.empty()

        task = await self.handler.handle("import everything", is_partial=False)
        with patch(
            "src.application.use_cases.terraform_import_handler.DatabaseService"
        ) as db_mock:
            db_mock.set_lock = AsyncMock(return_value=True)
            await task()

        # A full round asks neither the request analyst nor the iac_filter
        # agent: the whole scope diff is the selection.
        self.requests_filter_svc.filter.assert_not_awaited()
        self.llm_svc.generate.assert_not_awaited()
        gen_kwargs = self.validation_svc.generate_and_validate.await_args.kwargs
        self.assertEqual(
            gen_kwargs["prompt_kwargs"], {"selected_ids": ["res-1", "res-2"]}
        )

    async def test_full_round_with_empty_discovery_sets_uncompleted(self):
        self.import_svc.get_unmanaged_resources.return_value = []

        task = await self.handler.handle("import everything", is_partial=False)
        await task()

        status_kwargs = self.session_svc.update_status.await_args.kwargs
        self.assertIs(status_kwargs["status"], SessionStatus.UNCOMPLETED)
        self.assertIn("No unmanaged resources", status_kwargs["msg"])
        self.requests_filter_svc.filter.assert_not_awaited()
        self.validation_svc.generate_and_validate.assert_not_awaited()
        self.session_svc.save.assert_awaited_once()

    # --- Step 3: Config generation ---

    async def test_config_generation_uses_iac_import_prompt_and_sentinel(self):
        self.requests_filter_svc.filter.return_value = (True, "")
        self.import_svc.get_unmanaged_resources.return_value = ["res-1"]
        self.llm_svc.generate.return_value = _filter_result(["res-1"])
        self.validation_svc.generate_and_validate.return_value = _validation_dto(True)
        self.validation_svc.last_generation_result = _generation_result(
            [{"address": "azurerm_resource_group.main", "resource_id": "res-1"}]
        )
        self.import_svc.import_resources.return_value = [
            _import_dto(True, "azurerm_resource_group.main")
        ]
        self.terraform_svc.validate.return_value = _validation_dto(True)
        self.compliance_svc.check.return_value = ComplianceCheckReport.empty()

        task = await self.handler.handle("import res-1", is_partial=True)
        with patch(
            "src.application.use_cases.terraform_import_handler.DatabaseService"
        ) as db_mock:
            db_mock.set_lock = AsyncMock(return_value=True)
            await task()

        gen_kwargs = self.validation_svc.generate_and_validate.await_args.kwargs
        self.assertIs(gen_kwargs["prompt_key"], PromptsLibrary.IAC_IMPORT)
        self.assertIs(gen_kwargs["sentinel_context"], ToolContext.IAC_IMPORT)
        self.assertEqual(gen_kwargs["prompt_kwargs"], {"selected_ids": ["res-1"]})
        self.assertFalse(gen_kwargs["include_forbidden_actions"])

    async def test_config_generation_failure_raises(self):
        self.requests_filter_svc.filter.return_value = (True, "")
        self.import_svc.get_unmanaged_resources.return_value = ["res-1"]
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

    async def test_import_execution_extracts_mapping_from_generation_result(self):
        self.requests_filter_svc.filter.return_value = (True, "")
        self.import_svc.get_unmanaged_resources.return_value = ["res-1", "res-2"]
        self.llm_svc.generate.return_value = _filter_result(["res-1", "res-2"])
        self.validation_svc.generate_and_validate.return_value = _validation_dto(True)
        self.validation_svc.last_generation_result = _generation_result(
            [
                {"address": "azurerm_resource_group.main", "resource_id": "res-1"},
                {"address": "azurerm_virtual_network.vnet", "resource_id": "res-2"},
            ]
        )
        self.import_svc.import_resources.return_value = [
            _import_dto(True, "azurerm_resource_group.main"),
            _import_dto(True, "azurerm_virtual_network.vnet"),
        ]
        self.terraform_svc.validate.return_value = _validation_dto(True)
        self.compliance_svc.check.return_value = ComplianceCheckReport.empty()

        task = await self.handler.handle("import all", is_partial=True)
        with patch(
            "src.application.use_cases.terraform_import_handler.DatabaseService"
        ) as db_mock:
            db_mock.set_lock = AsyncMock(return_value=True)
            await task()

        self.import_svc.import_resources.assert_awaited_once_with(
            [
                ("azurerm_resource_group.main", "res-1"),
                ("azurerm_virtual_network.vnet", "res-2"),
            ]
        )

    async def test_partial_import_failure_does_not_abort(self):
        self.requests_filter_svc.filter.return_value = (True, "")
        self.import_svc.get_unmanaged_resources.return_value = ["res-1", "res-2"]
        self.llm_svc.generate.return_value = _filter_result(["res-1", "res-2"])
        self.validation_svc.generate_and_validate.return_value = _validation_dto(True)
        self.validation_svc.last_generation_result = _generation_result(
            [
                {"address": "azurerm_resource_group.main", "resource_id": "res-1"},
                {"address": "azurerm_virtual_network.vnet", "resource_id": "res-2"},
            ]
        )
        self.import_svc.import_resources.return_value = [
            _import_dto(True, "azurerm_resource_group.main"),
            _import_dto(False, "azurerm_virtual_network.vnet"),
        ]
        self.terraform_svc.validate.return_value = _validation_dto(True)
        self.compliance_svc.check.return_value = ComplianceCheckReport.empty()

        task = await self.handler.handle("import all", is_partial=True)
        with patch(
            "src.application.use_cases.terraform_import_handler.DatabaseService"
        ) as db_mock:
            db_mock.set_lock = AsyncMock(return_value=True)
            await task()

        self.report_svc.generate_report.assert_awaited_once()

    async def test_no_generation_result_yields_empty_imports(self):
        self.requests_filter_svc.filter.return_value = (True, "")
        self.import_svc.get_unmanaged_resources.return_value = ["res-1"]
        self.llm_svc.generate.return_value = _filter_result(["res-1"])
        self.validation_svc.generate_and_validate.return_value = _validation_dto(True)
        self.validation_svc.last_generation_result = None
        self.import_svc.import_resources.return_value = []
        self.compliance_svc.check.return_value = ComplianceCheckReport.empty()

        task = await self.handler.handle("import res-1", is_partial=True)
        with patch(
            "src.application.use_cases.terraform_import_handler.DatabaseService"
        ) as db_mock:
            db_mock.set_lock = AsyncMock(return_value=True)
            await task()

        self.import_svc.import_resources.assert_awaited_once_with([])

    # --- Step 5: Convergence validation ---

    async def test_convergence_runs_on_successful_imports(self):
        self.requests_filter_svc.filter.return_value = (True, "")
        self.import_svc.get_unmanaged_resources.return_value = ["res-1"]
        self.llm_svc.generate.return_value = _filter_result(["res-1"])
        self.validation_svc.generate_and_validate.return_value = _validation_dto(True)
        self.validation_svc.last_generation_result = _generation_result(
            [{"address": "azurerm_resource_group.main", "resource_id": "res-1"}]
        )
        self.import_svc.import_resources.return_value = [
            _import_dto(True, "azurerm_resource_group.main")
        ]
        self.compliance_svc.check.return_value = ComplianceCheckReport.empty()

        task = await self.handler.handle("import res-1", is_partial=True)
        with patch(
            "src.application.use_cases.terraform_import_handler.DatabaseService"
        ) as db_mock:
            db_mock.set_lock = AsyncMock(return_value=True)
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
        self.import_svc.get_unmanaged_resources.return_value = ["res-1"]
        self.llm_svc.generate.return_value = _filter_result(["res-1"])
        self.validation_svc.generate_and_validate.return_value = _validation_dto(True)
        self.validation_svc.last_generation_result = _generation_result(
            [{"address": "azurerm_resource_group.main", "resource_id": "res-1"}]
        )
        self.import_svc.import_resources.return_value = [
            _import_dto(True, "azurerm_resource_group.main")
        ]
        self.terraform_svc.validate.return_value = _validation_dto(True)
        self.compliance_svc.check.return_value = ComplianceCheckReport.empty()

        task = await self.handler.handle("import res-1", is_partial=True)
        with patch(
            "src.application.use_cases.terraform_import_handler.DatabaseService"
        ) as db_mock:
            db_mock.set_lock = AsyncMock(return_value=True)
            await task()

        # The drift service plans the imported addresses itself, so the
        # handler neither plans nor narrows the round to session changes.
        drift_kwargs = self.drift_svc.detect_and_resolve_drift.await_args.kwargs
        self.assertIs(drift_kwargs["filter_session_changes"], False)
        self.terraform_svc.validate.assert_not_awaited()

    async def test_report_uses_convergence_plan_when_imports_succeed(self):
        self.requests_filter_svc.filter.return_value = (True, "")
        self.import_svc.get_unmanaged_resources.return_value = ["res-1"]
        self.llm_svc.generate.return_value = _filter_result(["res-1"])
        self.validation_svc.generate_and_validate.return_value = _validation_dto(
            True, plan="generation plan"
        )
        self.validation_svc.last_generation_result = _generation_result(
            [{"address": "azurerm_resource_group.main", "resource_id": "res-1"}]
        )
        self.import_svc.import_resources.return_value = [
            _import_dto(True, "azurerm_resource_group.main")
        ]
        self.drift_svc.detect_and_resolve_drift.return_value = _validation_dto(
            True, plan="convergence plan"
        )
        self.compliance_svc.check.return_value = ComplianceCheckReport.empty()

        task = await self.handler.handle("import res-1", is_partial=True)
        with patch(
            "src.application.use_cases.terraform_import_handler.DatabaseService"
        ) as db_mock:
            db_mock.set_lock = AsyncMock(return_value=True)
            await task()

        report_kwargs = self.report_svc.generate_report.await_args.kwargs
        self.assertEqual(report_kwargs["content"], "convergence plan")

    async def test_unresolved_convergence_does_not_abort(self):
        self.requests_filter_svc.filter.return_value = (True, "")
        self.import_svc.get_unmanaged_resources.return_value = ["res-1"]
        self.llm_svc.generate.return_value = _filter_result(["res-1"])
        self.validation_svc.generate_and_validate.return_value = _validation_dto(True)
        self.validation_svc.last_generation_result = _generation_result(
            [{"address": "azurerm_resource_group.main", "resource_id": "res-1"}]
        )
        self.import_svc.import_resources.return_value = [
            _import_dto(True, "azurerm_resource_group.main")
        ]
        self.drift_svc.detect_and_resolve_drift.return_value = _validation_dto(False)
        self.compliance_svc.check.return_value = ComplianceCheckReport.empty()

        task = await self.handler.handle("import res-1", is_partial=True)
        with patch(
            "src.application.use_cases.terraform_import_handler.DatabaseService"
        ) as db_mock:
            db_mock.set_lock = AsyncMock(return_value=True)
            await task()

        self.report_svc.generate_report.assert_awaited_once()

    async def test_convergence_skipped_when_all_imports_fail(self):
        self.requests_filter_svc.filter.return_value = (True, "")
        self.import_svc.get_unmanaged_resources.return_value = ["res-1"]
        self.llm_svc.generate.return_value = _filter_result(["res-1"])
        self.validation_svc.generate_and_validate.return_value = _validation_dto(True)
        self.validation_svc.last_generation_result = _generation_result(
            [{"address": "azurerm_resource_group.main", "resource_id": "res-1"}]
        )
        self.import_svc.import_resources.return_value = [
            _import_dto(False, "azurerm_resource_group.main")
        ]
        self.compliance_svc.check.return_value = ComplianceCheckReport.empty()

        task = await self.handler.handle("import res-1", is_partial=True)
        with patch(
            "src.application.use_cases.terraform_import_handler.DatabaseService"
        ) as db_mock:
            db_mock.set_lock = AsyncMock(return_value=True)
            await task()

        self.drift_svc.detect_and_resolve_drift.assert_not_awaited()

    # --- Step 6: Gate ---

    async def test_gate_generates_import_report(self):
        self.requests_filter_svc.filter.return_value = (True, "")
        self.import_svc.get_unmanaged_resources.return_value = ["res-1"]
        self.llm_svc.generate.return_value = _filter_result(["res-1"])
        self.validation_svc.generate_and_validate.return_value = _validation_dto(
            True, plan="the plan"
        )
        self.validation_svc.last_generation_result = _generation_result([])
        self.import_svc.import_resources.return_value = []
        self.compliance_svc.check.return_value = ComplianceCheckReport.empty()

        task = await self.handler.handle("import res-1", is_partial=True)
        with patch(
            "src.application.use_cases.terraform_import_handler.DatabaseService"
        ) as db_mock:
            db_mock.set_lock = AsyncMock(return_value=True)
            await task()

        report_kwargs = self.report_svc.generate_report.await_args.kwargs
        self.assertIs(report_kwargs["type"], ReportType.IMPORT)
        self.assertEqual(report_kwargs["content"], "the plan")

    @patch(
        "src.application.use_cases.terraform_import_handler.NotificationServiceClient"
    )
    @patch("src.application.use_cases.terraform_import_handler.DatabaseService")
    async def test_compliance_failure_locks_and_notifies(self, db_mock, notif_mock):
        self.requests_filter_svc.filter.return_value = (True, "")
        self.import_svc.get_unmanaged_resources.return_value = ["res-1"]
        self.llm_svc.generate.return_value = _filter_result(["res-1"])
        self.validation_svc.generate_and_validate.return_value = _validation_dto(True)
        self.validation_svc.last_generation_result = _generation_result([])
        self.import_svc.import_resources.return_value = []
        self.compliance_svc.check.return_value = ComplianceCheckReport(
            passed=False,
            violations=[],
            summary="policy violation",
            checked_rules=["rule-1"],
        )
        db_mock.set_lock = AsyncMock(return_value=True)
        notif_mock.notify_compliance_failure = AsyncMock()

        task = await self.handler.handle("import res-1", is_partial=True)
        await task()

        db_mock.set_lock.assert_awaited_once_with("session-1", True)
        notif_mock.notify_compliance_failure.assert_awaited_once()

    @patch("src.application.use_cases.terraform_import_handler.DatabaseService")
    async def test_compliance_lock_failure_raises_set_lock_error(self, db_mock):
        self.requests_filter_svc.filter.return_value = (True, "")
        self.import_svc.get_unmanaged_resources.return_value = ["res-1"]
        self.llm_svc.generate.return_value = _filter_result(["res-1"])
        self.validation_svc.generate_and_validate.return_value = _validation_dto(True)
        self.validation_svc.last_generation_result = _generation_result([])
        self.import_svc.import_resources.return_value = []
        self.compliance_svc.check.return_value = ComplianceCheckReport(
            passed=False,
            violations=[],
            summary="violation",
            checked_rules=[],
        )
        db_mock.set_lock = AsyncMock(return_value=False)

        task = await self.handler.handle("import res-1", is_partial=True)
        with self.assertRaises(SetLockError):
            await task()

        self.session_svc.save.assert_awaited_once()

    @patch("src.application.use_cases.terraform_import_handler.DatabaseService")
    async def test_compliance_pass_unlocks(self, db_mock):
        self.requests_filter_svc.filter.return_value = (True, "")
        self.import_svc.get_unmanaged_resources.return_value = ["res-1"]
        self.llm_svc.generate.return_value = _filter_result(["res-1"])
        self.validation_svc.generate_and_validate.return_value = _validation_dto(True)
        self.validation_svc.last_generation_result = _generation_result([])
        self.import_svc.import_resources.return_value = []
        self.compliance_svc.check.return_value = ComplianceCheckReport.empty()
        db_mock.set_lock = AsyncMock(return_value=True)

        task = await self.handler.handle("import res-1", is_partial=True)
        await task()

        db_mock.set_lock.assert_awaited_once_with("session-1", False)

    # --- Session always saved ---

    async def test_session_saved_on_filter_rejection(self):
        self.requests_filter_svc.filter.return_value = (False, "rejected")

        task = await self.handler.handle("create something", is_partial=True)
        await task()

        self.session_svc.save.assert_awaited_once()

    async def test_session_saved_on_generation_failure(self):
        self.requests_filter_svc.filter.return_value = (True, "")
        self.import_svc.get_unmanaged_resources.return_value = ["res-1"]
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
            return ["res-1"]

        async def track_selection(*args, **kwargs):
            order.append("selection")
            return _filter_result(["res-1"])

        async def track_generation(*args, **kwargs):
            order.append("generation")
            return _validation_dto(True)

        async def track_import(*args, **kwargs):
            order.append("import")
            return [_import_dto(True, "azurerm_resource_group.main")]

        async def track_convergence(*args, **kwargs):
            order.append("convergence")
            return _validation_dto(True)

        self.requests_filter_svc.filter.side_effect = track_filter
        self.import_svc.get_unmanaged_resources.side_effect = track_discovery
        self.llm_svc.generate.side_effect = track_selection
        self.validation_svc.generate_and_validate.side_effect = track_generation
        self.validation_svc.last_generation_result = _generation_result(
            [{"address": "azurerm_resource_group.main", "resource_id": "res-1"}]
        )
        self.import_svc.import_resources.side_effect = track_import
        self.drift_svc.detect_and_resolve_drift.side_effect = track_convergence
        self.compliance_svc.check.return_value = ComplianceCheckReport.empty()

        task = await self.handler.handle("import all", is_partial=True)
        with patch(
            "src.application.use_cases.terraform_import_handler.DatabaseService"
        ) as db_mock:
            db_mock.set_lock = AsyncMock(return_value=True)
            await task()

        self.assertEqual(
            order,
            ["filter", "discovery", "selection", "generation", "import", "convergence"],
        )


if __name__ == "__main__":
    unittest.main()

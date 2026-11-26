# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Probing a root module before a session, and preparing its inputs at session start."""

import unittest
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import override
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from src.application.iac_requests import ManifestAnswers, ManifestVariableAnswer
from src.application.services.manifest_session_service import (
    ManifestProbeService,
    SessionInputsService,
)
from src.domains.entities import SessionContext
from src.domains.exceptions import ManifestInputError
from src.domains.interfaces.git_interface import IGit
from src.domains.interfaces.workspace_interface import IWorkspace
from src.domains.services.database_service import DatabaseService
from src.domains.services.manifest_service import ManifestService
from src.domains.value_objects import (
    ProviderScope,
    TerraformInputs,
    VariableSpec,
)
from src.shared.constants import ManifestStatus, OperationType
from tests.domains.services.test_manifest_service import (
    AZURERM,
    DB_PASSWORD,
    OCI,
    OWNERS,
    RANDOM,
    REGION,
    FakeInspector,
    FakeManifests,
    FakeSecrets,
    requirements,
)

COMPARTMENT = VariableSpec("compartment_ocid", "string", required=True)


def session(
    providers: tuple[ProviderScope, ...] = (), project_identifier: str | None = None
) -> SessionContext:
    ctx = SessionContext(
        id=uuid4(),
        user_id="1",
        round_id=1,
        repo_uri="https://github.com/org/repo",
        providers=providers,
        branch_name="Kumoss/2026",
        root_module_path="infra",
        operation_type=OperationType.GENERATE,
        history=[],
        chat_history=[],
        project_identifier=project_identifier,
    )
    ctx.set_call_dir(Path("/workspaces/s/c/infra"))
    return ctx


ANSWERS = ManifestAnswers(
    variables=[
        ManifestVariableAnswer(name="region", value={"location": "westeurope"}),
        ManifestVariableAnswer(name="db_password", value="s3cr3t"),
    ]
)


class TestSessionInputsService(unittest.IsolatedAsyncioTestCase):
    @override
    def setUp(self):
        self.inspector = FakeInspector(requirements())
        self.manifests = FakeManifests()
        self.secrets = FakeSecrets()
        self.git = AsyncMock(spec=IGit)
        self.service = SessionInputsService(
            ManifestService(self.inspector, self.manifests, self.secrets), self.git
        )
        patcher = patch.object(
            DatabaseService, "set_session_providers", new_callable=AsyncMock
        )
        self.set_session_providers = patcher.start()
        self.addCleanup(patcher.stop)

    async def test_first_call_saves_answers_commits_and_loads_inputs(self):
        ctx = session()
        await self.service.prepare(ctx, first_call=True, answers=ANSWERS)

        self.assertIsNotNone(self.manifests.stored)
        self.assertEqual(self.secrets.values, {"db_password": "s3cr3t"})
        self.git.commit_and_push.assert_awaited_once_with("Kumoss/2026")
        self.assertEqual(
            ctx.terraform_inputs,
            TerraformInputs(
                values={"region": {"location": "westeurope"}, "db_password": "s3cr3t"}
            ),
        )

    async def test_first_call_records_the_sessions_project_identifier(self):
        ctx = session(project_identifier="repo")
        await self.service.prepare(ctx, first_call=True, answers=ANSWERS)
        self.assertEqual(self.manifests.stored.project_identifier, "repo")

    async def test_first_call_without_needed_answers_fails_before_committing(self):
        with self.assertRaises(ManifestInputError) as ctx:
            await self.service.prepare(session(), first_call=True)
        self.assertEqual(ctx.exception.error_code, 422)
        self.assertIn("region", ctx.exception.message)
        self.assertIn("db_password", ctx.exception.message)
        self.git.commit_and_push.assert_not_awaited()
        self.assertIsNone(self.manifests.stored)

    async def test_first_call_with_nothing_to_ask_sets_the_manifest_up_alone(self):
        self.inspector.requirements = requirements(variables=(OWNERS,))
        ctx = session()
        await self.service.prepare(ctx, first_call=True)
        self.assertIsNotNone(self.manifests.stored)
        self.assertEqual(ctx.terraform_inputs, TerraformInputs())
        self.set_session_providers.assert_awaited_once_with(
            ctx.id, (ProviderScope("random"),)
        )
        self.assertEqual(ctx.providers, (ProviderScope("random"),))

    async def test_platform_variables_are_not_asked_only_the_scope(self):
        self.inspector.requirements = requirements(
            variables=(COMPARTMENT,), providers=(OCI,)
        )
        with self.assertRaises(ManifestInputError) as ctx:
            await self.service.prepare(session(), first_call=True)
        self.assertIn("scopes for oci", ctx.exception.message)
        self.assertNotIn("compartment_ocid", ctx.exception.message)

        ctx_ = session()
        await self.service.prepare(
            ctx_,
            first_call=True,
            answers=ManifestAnswers(scopes={"oci": "ocid1.compartment.oc1..aaa"}),
        )
        self.assertEqual(
            ctx_.providers, (ProviderScope("oci", "ocid1.compartment.oc1..aaa"),)
        )

    async def test_first_call_records_the_providers_and_scopes_of_the_manifest(self):
        self.inspector.requirements = requirements(
            variables=(REGION,), providers=(AZURERM, RANDOM)
        )
        ctx = session()
        authorize = AsyncMock()
        await self.service.prepare(
            ctx,
            first_call=True,
            answers=ManifestAnswers(
                variables=[ManifestVariableAnswer(name="region", value={})],
                scopes={"azurerm": "sub-123"},
            ),
            authorize=authorize,
        )
        expected = (ProviderScope("azurerm", "sub-123"), ProviderScope("random"))
        authorize.assert_awaited_once_with(expected)
        self.set_session_providers.assert_awaited_once_with(ctx.id, expected)
        self.assertEqual(ctx.providers, expected)
        self.assertEqual(ctx.scopes, (ProviderScope("azurerm", "sub-123"),))
        self.assertEqual(
            self.manifests.stored.scopes, (ProviderScope("azurerm", "sub-123"),)
        )

    async def test_first_call_without_answers_authorizes_through_sync(self):
        self.inspector.requirements = requirements(variables=(OWNERS,))
        authorize = AsyncMock()
        await self.service.prepare(session(), first_call=True, authorize=authorize)
        authorize.assert_awaited_once_with((ProviderScope("random"),))

    async def test_denied_first_call_saves_records_and_commits_nothing(self):
        self.inspector.requirements = requirements(
            variables=(REGION,), providers=(AZURERM,)
        )
        authorize = AsyncMock(side_effect=PermissionError("denied"))
        ctx = session()
        with self.assertRaises(PermissionError):
            await self.service.prepare(
                ctx,
                first_call=True,
                answers=ManifestAnswers(
                    variables=[ManifestVariableAnswer(name="region", value={})],
                    scopes={"azurerm": "sub-123"},
                ),
                authorize=authorize,
            )
        self.assertIsNone(self.manifests.stored)
        self.set_session_providers.assert_not_awaited()
        self.git.commit_and_push.assert_not_awaited()
        self.assertEqual(ctx.providers, ())

    async def test_missing_scope_is_reported_before_anything_is_recorded(self):
        self.inspector.requirements = requirements(variables=(), providers=(AZURERM,))
        authorize = AsyncMock()
        with self.assertRaises(ManifestInputError) as ctx:
            await self.service.prepare(session(), first_call=True, authorize=authorize)
        self.assertEqual(ctx.exception.error_code, 422)
        self.assertIn("scopes for azurerm", ctx.exception.message)
        authorize.assert_not_awaited()
        self.set_session_providers.assert_not_awaited()

    async def test_iteration_calls_only_load_even_when_the_code_drifted(self):
        await self.service.prepare(session(), first_call=True, answers=ANSWERS)
        saves = self.manifests.saves
        self.inspector.requirements = requirements(
            variables=(
                REGION,
                DB_PASSWORD,
                VariableSpec("new", "string", required=True),
            )
        )
        recorded = (ProviderScope("random"),)
        ctx = session(recorded)
        await self.service.prepare(ctx, first_call=False)
        self.assertEqual(self.manifests.saves, saves)
        self.git.commit_and_push.assert_awaited_once()
        # Iteration calls keep the providers recorded at setup.
        self.set_session_providers.assert_awaited_once()
        self.assertEqual(ctx.providers, recorded)
        self.assertIn("region", ctx.terraform_inputs.values)

    async def test_iteration_on_a_session_without_manifest_gets_no_inputs(self):
        ctx = session()
        await self.service.prepare(ctx, first_call=False)
        self.assertEqual(ctx.terraform_inputs, TerraformInputs())


class TestManifestProbeService(unittest.IsolatedAsyncioTestCase):
    async def test_probe_reads_the_default_branch_and_never_writes(self):
        clones: list[str] = []

        @asynccontextmanager
        async def clone(repo_uri: str) -> AsyncIterator[Path]:
            clones.append(repo_uri)
            yield Path("/tmp/clone")

        workspace = MagicMock(spec=IWorkspace)
        workspace.validate_uri = AsyncMock()
        workspace.default_branch_clone = clone
        workspace.root_module_dir.return_value = Path("/tmp/clone/infra")
        manifests = FakeManifests()
        service = ManifestProbeService(
            workspace,
            ManifestService(FakeInspector(requirements()), manifests, FakeSecrets()),
        )

        resolution = await service.probe("https://github.com/org/repo", "infra")

        self.assertEqual(clones, ["https://github.com/org/repo"])
        workspace.root_module_dir.assert_called_once_with(Path("/tmp/clone"), "infra")
        self.assertIs(resolution.status, ManifestStatus.NOT_FOUND)
        self.assertTrue(resolution.needs_input)
        self.assertEqual(manifests.saves, 0)

    async def test_probe_does_not_ask_for_platform_variables(self):
        @asynccontextmanager
        async def clone(repo_uri: str) -> AsyncIterator[Path]:
            yield Path("/tmp/clone")

        workspace = MagicMock(spec=IWorkspace)
        workspace.validate_uri = AsyncMock()
        workspace.default_branch_clone = clone
        workspace.root_module_dir.return_value = Path("/tmp/clone")
        service = ManifestProbeService(
            workspace,
            ManifestService(
                FakeInspector(requirements(variables=(COMPARTMENT,), providers=(OCI,))),
                FakeManifests(),
                FakeSecrets(),
            ),
        )
        resolution = await service.probe("https://x/y", None)
        self.assertEqual(resolution.missing_variables, ())
        self.assertEqual(resolution.missing_scopes, ("oci",))

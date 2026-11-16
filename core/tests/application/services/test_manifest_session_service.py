# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Probing a root module before a session, and preparing its inputs at session start."""

import unittest
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import override
from unittest.mock import AsyncMock, MagicMock
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
from src.domains.services.manifest_service import ManifestService
from src.domains.value_objects import (
    TerraformInputs,
    VariableSpec,
)
from src.shared.constants import ManifestStatus, OperationType, TerraformProvider
from tests.domains.services.test_manifest_service import (
    DB_PASSWORD,
    REGION,
    FakeInspector,
    FakeManifests,
    FakeSecrets,
    requirements,
)

COMPARTMENT = VariableSpec("compartment_ocid", "string", required=True)


def session(provider: TerraformProvider = TerraformProvider.AZURE) -> SessionContext:
    ctx = SessionContext(
        id=uuid4(),
        user_id="1",
        round_id=1,
        repo_uri="https://github.com/org/repo",
        scope_id="scope-1",
        terraform_prv=provider,
        branch_name="Kumoss/2026",
        root_module_path="infra",
        operation_type=OperationType.GENERATE,
        history=[],
        chat_history=[],
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

    async def test_first_call_without_needed_answers_fails_before_committing(self):
        with self.assertRaises(ManifestInputError) as ctx:
            await self.service.prepare(session(), first_call=True)
        self.assertEqual(ctx.exception.error_code, 422)
        self.assertIn("region", ctx.exception.message)
        self.assertIn("db_password", ctx.exception.message)
        self.git.commit_and_push.assert_not_awaited()
        self.assertIsNone(self.manifests.stored)

    async def test_first_call_with_nothing_to_ask_sets_the_manifest_up_alone(self):
        self.inspector.requirements = requirements(variables=(COMPARTMENT,))
        ctx = session(TerraformProvider.OCI)
        await self.service.prepare(ctx, first_call=True)
        self.assertIsNotNone(self.manifests.stored)
        self.assertEqual(ctx.terraform_inputs, TerraformInputs())

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
        ctx = session()
        await self.service.prepare(ctx, first_call=False)
        self.assertEqual(self.manifests.saves, saves)
        self.git.commit_and_push.assert_awaited_once()
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

        resolution = await service.probe(
            "https://github.com/org/repo", "infra", TerraformProvider.AZURE
        )

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
                FakeInspector(requirements(variables=(COMPARTMENT,))),
                FakeManifests(),
                FakeSecrets(),
            ),
        )
        resolution = await service.probe("https://x/y", None, TerraformProvider.OCI)
        self.assertFalse(resolution.needs_input)

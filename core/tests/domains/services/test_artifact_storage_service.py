# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""ArtifactStorageService tests: upload + DB row as one truthful unit.

The happy paths run against the real docker-compose Postgres, Redis and
RustFS; the failure paths use fake ports, because what matters there is
the compensating behavior (delete-on-DB-failure, no row on store
failure), not the backend.
"""

import unittest
from types import SimpleNamespace
from typing import override
from uuid import uuid4

from src.domains.exceptions import ObjectStorageError, ObjectStorageUnavailable
from src.shared.exceptions import ExceptionHandler
from src.domains.interfaces import IObjectStorage
from src.domains.services import ArtifactStorageService
from src.domains.services.database_service import DatabaseService
from src.infrastructure.database.database import db
from src.infrastructure.database.models import (
    Artifact,
    Base,
    CodeChange,
    Report,
    TerraformPlan,
    User as DbUser,
)
from src.infrastructure.redis import redis_client
from src.infrastructure.storage._s3 import S3ObjectStorage
from src.shared.constants import (
    ContentType,
    OperationType,
    ReportType,
    TerraformProvider,
)

_ENDPOINT = "http://object-storage:9000"


class _RecordingStorage(IObjectStorage):
    """Fake port that records calls; ``put``/``delete`` always succeed."""

    def __init__(self):
        self.puts: list[str] = []
        self.metas: list[dict[str, str]] = []
        self.deletes: list[str] = []

    @property
    @override
    def metadata_header_prefix(self) -> str:
        return "x-fake-meta-"

    @override
    async def ensure_bucket(self) -> None:
        pass

    @override
    async def put(
        self, key: str, data: bytes, content_type: str, metadata: dict[str, str]
    ) -> None:
        self.puts.append(key)
        self.metas.append(metadata)

    @override
    async def get(self, key: str) -> bytes:
        return b""

    @override
    async def exists(self, key: str) -> bool:
        return key in self.puts

    @override
    async def delete(self, key: str) -> None:
        self.deletes.append(key)

    @override
    def presigned_get_url(self, key: str, expires_in: int | None = None) -> str:
        return f"https://fake/{key}"


class _DownStorage(_RecordingStorage):
    """Fake port whose ``put`` fails like an unreachable store."""

    @override
    async def put(
        self, key: str, data: bytes, content_type: str, metadata: dict[str, str]
    ) -> None:
        raise ObjectStorageUnavailable(message="object store is down", error_code=503)


class _RoundBase(unittest.IsolatedAsyncioTestCase):
    """One fresh session + open round per test, against real backends."""

    async def asyncSetUp(self):
        await db.initialize()
        await redis_client.initialize()
        async with db.session_manager.engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        # Unique email per run so stale Redis mappings never leak in.
        self.username = f"user-{uuid4().hex[:8]}@example.com"
        user = await db.create(
            DbUser,
            issuer="urn:test",
            subject=f"sub-{uuid4().hex[:8]}",
            email=self.username,
        )
        self.sid = uuid4()
        _ = await DatabaseService.create_session(
            session_id=self.sid,
            user_pk=user.id,
            operation=OperationType.GENERATE,
            repo_uri="https://example.com/foo.git",
            terraform_prv=TerraformProvider.AZURE,
            scope_id="sub-123",
            branch_name="Nebula/x",
            query="create a resource group",
            iac_path="infra",
        )
        self.round_id = await DatabaseService.create_round(self.sid, "add a vnet")

        self.bucket = f"test-{uuid4().hex[:12]}"
        self.storage = S3ObjectStorage(
            bucket=self.bucket,
            region="us-east-1",
            endpoint_url=_ENDPOINT,
            public_endpoint_url=_ENDPOINT,
            access_key="rustfsadmin",
            secret_key="rustfsadmin",
            presign_expiry_seconds=172_800,
        )
        await self.storage.ensure_bucket()
        self.service = ArtifactStorageService(self.storage)

    async def asyncTearDown(self):
        await redis_client.close()
        await db.close()


class TestStoreArtifacts(_RoundBase):
    async def test_store_report_uploads_and_records_row(self):
        report_id = await self.service.store_report(
            self.sid,
            self.round_id,
            ReportType.GENERATE,
            '{"summary": "ok"}',
            content_type=ContentType.JSON,
        )

        report: Report | None = await db.get_by(Report, id=report_id)
        self.assertIsNotNone(report)
        assert report is not None
        self.assertEqual(report.round_id, self.round_id)
        self.assertEqual(report.type, ReportType.GENERATE)

        artifact: Artifact | None = await db.get_by(Artifact, id=report.artifact_id)
        self.assertIsNotNone(artifact)
        assert artifact is not None
        prefix = f"sessions/{self.sid}/rounds/{self.round_id}/reports/generate-"
        self.assertTrue(artifact.uri.startswith(prefix), artifact.uri)
        self.assertEqual(artifact.content_type, "application/json")
        self.assertEqual(artifact.file_size_bytes, len(b'{"summary": "ok"}'))

        # The uploaded bytes must round-trip from the store.
        self.assertEqual(await self.storage.get(artifact.uri), b'{"summary": "ok"}')

    async def test_store_terraform_plan_records_targets(self):
        plan_id = await self.service.store_terraform_plan(
            self.sid,
            self.round_id,
            ["azurerm_resource_group.rg"],
            "plan output",
            content_type=ContentType.TEXT,
        )

        plan: TerraformPlan | None = await db.get_by(TerraformPlan, id=plan_id)
        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertEqual(plan.targets, ["azurerm_resource_group.rg"])

        artifact: Artifact | None = await db.get_by(Artifact, id=plan.artifact_id)
        assert artifact is not None
        self.assertIn(f"/rounds/{self.round_id}/plans/", artifact.uri)
        self.assertEqual(artifact.content_type, "text/plain")
        self.assertEqual(await self.storage.get(artifact.uri), b"plan output")

    async def test_store_code_change_keeps_nested_name_in_db_only(self):
        change_id = await self.service.store_code_change(
            self.sid,
            self.round_id,
            "infra/main.tf",
            'resource "x" "y" {}',
            content_type=ContentType.TEXT,
        )

        change: CodeChange | None = await db.get_by(CodeChange, id=change_id)
        self.assertIsNotNone(change)
        assert change is not None
        # Original (nested) path in the DB; sanitized inside the key.
        self.assertEqual(change.file_name, "infra/main.tf")

        artifact: Artifact | None = await db.get_by(Artifact, id=change.artifact_id)
        assert artifact is not None
        self.assertNotIn("infra/main.tf", artifact.uri)
        self.assertTrue(artifact.uri.endswith("-infra_main.tf"), artifact.uri)

    async def test_two_reports_in_one_round_get_distinct_keys(self):
        first = await self.service.store_report(
            self.sid,
            self.round_id,
            ReportType.GENERATE,
            "one",
            content_type=ContentType.JSON,
        )
        second = await self.service.store_report(
            self.sid,
            self.round_id,
            ReportType.GENERATE,
            "two",
            content_type=ContentType.JSON,
        )

        first_report = await db.get_by(Report, id=first)
        second_report = await db.get_by(Report, id=second)
        assert first_report is not None and second_report is not None
        first_artifact = await db.get_by(Artifact, id=first_report.artifact_id)
        second_artifact = await db.get_by(Artifact, id=second_report.artifact_id)
        assert first_artifact is not None and second_artifact is not None
        self.assertNotEqual(first_artifact.uri, second_artifact.uri)

    async def test_detail_read_model_presigns_stored_keys(self):
        """End-to-end through the __artifact_url seam."""
        _ = await self.service.store_report(
            self.sid,
            self.round_id,
            ReportType.GENERATE,
            '{"summary": "ok"}',
            content_type=ContentType.JSON,
        )

        detail = await DatabaseService.get_session_detail(self.sid)
        # Round 1 is opened by create_session; ours is round 2.
        self.assertEqual(len(detail.rounds), 2)
        [report_ref] = detail.rounds[1].reports
        # Signed by the config-selected singleton: assert shape, not host.
        self.assertIn("X-Amz-Signature=", report_ref.url)
        self.assertIn(f"/rounds/{self.round_id}/reports/generate-", report_ref.url)
        # The read model surfaces the stored report type and round query.
        self.assertEqual(report_ref.type, ReportType.GENERATE)
        self.assertEqual(detail.rounds[1].query, "add a vnet")


class TestStoreFailureModes(_RoundBase):
    async def test_db_failure_triggers_compensating_delete(self):
        fake = _RecordingStorage()
        service = ArtifactStorageService(fake)

        # The DB layer already translates SQL errors into the base
        # ExceptionHandler, which the service re-raises as-is.
        missing_round = self.round_id + 999_999
        with self.assertRaises(ExceptionHandler):
            _ = await service.store_report(
                self.sid,
                missing_round,
                ReportType.GENERATE,
                "content",
                content_type=ContentType.JSON,
            )

        # The uploaded key must have been deleted again.
        self.assertEqual(len(fake.puts), 1)
        self.assertEqual(fake.deletes, fake.puts)
        # No report row may survive. (add_report is not atomic: the
        # artifact row commits before the FK failure, so an orphaned —
        # unreachable — artifacts row may remain; only the typed row
        # makes an artifact visible to the read model.)
        reports: list[Report] = await db.list_by(Report)
        self.assertEqual(reports, [])

    async def test_oversized_content_type_rejected_before_upload(self):
        fake = _RecordingStorage()
        service = ArtifactStorageService(fake)

        with self.assertRaises(ObjectStorageError) as caught:
            _ = await service.store_report(
                self.sid,
                self.round_id,
                ReportType.GENERATE,
                "content",
                # A bare object standing in for ContentType: no real member
                # is long enough to trip the guard, so this fakes one via
                # the same `.value` the real enum exposes.
                content_type=SimpleNamespace(value="application/" + ("x" * 60)),
            )
        self.assertEqual(caught.exception.error_code, 400)
        self.assertEqual(fake.puts, [])

    async def test_store_failure_writes_no_row(self):
        service = ArtifactStorageService(_DownStorage())

        with self.assertRaises(ObjectStorageUnavailable):
            _ = await service.store_report(
                self.sid,
                self.round_id,
                ReportType.GENERATE,
                "content",
                content_type=ContentType.JSON,
            )

        artifacts: list[Artifact] = await db.list_by(Artifact)
        self.assertEqual(artifacts, [])


class TestPlanTypeMetadata(_RoundBase):
    """The caller's metadata is what labels a plan object.

    The read model returns a round's plans unlabelled and in order, so
    the object metadata is the only place a consumer can ask what a
    given plan artifact actually is — the key carries no flavour.
    """

    async def asyncSetUp(self):
        await super().asyncSetUp()
        # Swap the real S3 port for the recorder: the assertion is about
        # what the service hands to ``put``, not what MinIO stores.
        self.recorder = _RecordingStorage()
        self.service = ArtifactStorageService(self.recorder)

    async def __store(self, metadata: dict[str, str] = None) -> None:
        _ = await self.service.store_terraform_plan(
            self.sid,
            self.round_id,
            ["azurerm_resource_group.rg"],
            "plan output",
            content_type=ContentType.TEXT,
            metadata=metadata,
        )

    async def test_caller_metadata_reaches_the_object_verbatim(self):
        await self.__store(metadata={"type": "drift", "origin": "validation"})
        self.assertEqual(
            self.recorder.metas[-1], {"type": "drift", "origin": "validation"}
        )

    async def test_an_unlabelled_plan_carries_no_metadata(self):
        await self.__store()
        self.assertEqual(self.recorder.metas[-1], {})

    async def test_the_key_carries_no_flavour(self):
        # Two plans of different kinds land under the same prefix, so no
        # consumer can classify one by parsing its key.
        await self.__store(metadata={"type": "drift"})
        await self.__store(metadata={"type": "plan"})

        prefix = f"sessions/{self.sid}/rounds/{self.round_id}/plans/"
        for key in self.recorder.puts[-2:]:
            self.assertTrue(key.startswith(prefix), key)
            self.assertNotIn("drift", key)
            self.assertNotIn("plan-", key)
        self.assertNotEqual(self.recorder.puts[-2], self.recorder.puts[-1])


if __name__ == "__main__":
    _ = unittest.main()

# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import re
from collections.abc import Awaitable, Callable
from typing import final
from uuid import UUID, uuid4

from src.domains.exceptions import ObjectStorageError
from src.domains.interfaces import IObjectStorage
from src.domains.services.database_service import DatabaseService
from src.shared.constants import ContentType, ReportType
from src.shared.exceptions import ExceptionHandler
from src.shared.logger import logging

# Object keys keep a sanitized copy of user-provided file names; the
# untouched original lives in database.
_UNSAFE_NAME_CHARS = re.compile(r"[^A-Za-z0-9._-]+")
_MAX_NAME_LEN = 100


def _safe_name(file_name: str) -> str:
    return _UNSAFE_NAME_CHARS.sub("_", file_name)[:_MAX_NAME_LEN] or "file"


def _token() -> str:
    # A round stores several plans and reports — a drift pass writes its
    # diff and its plan, and every validation iteration adds another —
    # and the read model returns them all. A random token keeps each
    # write at a fresh key so an old DB row can never alias new bytes.
    return uuid4().hex[:8]


@final
class ArtifactStorageService:
    """Uploads round artifacts to object storage and records the DB rows.

    The stored ``artifacts.uri`` is the object KEY;
    ``DatabaseService.__artifact_url`` presigns it at read time. Upload happens
    before the row insert; a failed insert triggers a best-effort
    compensating delete so no row ever points at a missing object, while
    an orphaned object is harmless garbage.

    Every failure path raises an ``ExceptionHandler`` subclass: the
    storage port already guarantees that for store operations, and DB
    errors are re-raised as-is when they are ``ExceptionHandler``s or
    wrapped in ``ObjectStorageError`` otherwise.
    """

    def __init__(self, storage: IObjectStorage):
        self.__storage = storage

    async def store_report(
        self,
        session_id: UUID,
        round_id: int,
        report_type: ReportType,
        content: str | bytes,
        content_type: ContentType,
        metadata: dict[str, str] = None,
    ) -> int:
        """Persist a round report; returns the reports row pk.

        Args:
            session_id: Owning session uuid (key namespacing only).
            round_id: Round pk the report belongs to.
            report_type: Report flavour (GENERATE/DRIFT/IMPORT/APPLY).
            content: Report body; str is stored utf-8 encoded.
            content_type: MIME type served on reads (max 64 chars).
            metadata: Metadata attached to the object.
        """
        data = self.__encode(content)
        key = (
            f"sessions/{session_id}/rounds/{round_id}"
            + f"/reports/{report_type.value}-{_token()}.json"
        )
        return await self.__store(
            key=key,
            data=data,
            content_type=content_type.value,
            metadata=metadata if metadata else {},
            context=f"session {session_id} round {round_id}",
            db_write=lambda: DatabaseService.add_report(
                round_id=round_id,
                report_type=report_type,
                uri=key,
                content_type=content_type.value,
                file_size_bytes=len(data),
            ),
        )

    async def store_compliance_check(
        self,
        session_id: UUID,
        round_id: int,
        passed: bool,
        content: str | bytes,
        content_type: ContentType,
        metadata: dict[str, str] = None,
    ) -> int:
        """Persist a round compliance check; returns the compliance_checks row pk.

        Args:
            session_id: Owning session uuid (key namespacing only).
            round_id: Round pk the check belongs to.
            passed: Verdict of the check, surfaced by the read model.
            content: Check report body; str is stored utf-8 encoded.
            content_type: MIME type served on reads (max 64 chars).
            metadata: Metadata attached to the object.
        """
        data = self.__encode(content)
        key = (
            f"sessions/{session_id}/rounds/{round_id}"
            + f"/compliance/check-{_token()}.json"
        )
        return await self.__store(
            key=key,
            data=data,
            content_type=content_type.value,
            metadata=metadata if metadata else {},
            context=f"session {session_id} round {round_id}",
            db_write=lambda: DatabaseService.add_compliance_check(
                round_id=round_id,
                passed=passed,
                uri=key,
                content_type=content_type.value,
                file_size_bytes=len(data),
            ),
        )

    async def store_terraform_plan(
        self,
        session_id: UUID,
        round_id: int,
        targets: list[str],
        content: str | bytes,
        content_type: ContentType,
        metadata: dict[str, str] = None,
    ) -> int:
        """Persist a round terraform plan; returns the terraform_plans row pk.

        Args:
            session_id: Owning session uuid (key namespacing only).
            round_id: Round pk the plan belongs to.
            targets: Terraform targets the plan covers.
            content: Plan body; str is stored utf-8 encoded.
            content_type: MIME type served on reads (max 64 chars).
            metadata: Metadata attached to the object. The
                ``terraform_plans`` row holds no flavour, so callers that
                store more than one kind of plan (a drift diff and a
                validation plan) label it here and a consumer reads it
                off the object.
        """
        data = self.__encode(content)
        key = f"sessions/{session_id}/rounds/{round_id}" + f"/plans/{_token()}.txt"
        return await self.__store(
            key=key,
            data=data,
            content_type=content_type.value,
            metadata=metadata if metadata else {},
            context=f"session {session_id} round {round_id}",
            db_write=lambda: DatabaseService.add_terraform_plan(
                round_id=round_id,
                targets=targets,
                uri=key,
                content_type=content_type.value,
                file_size_bytes=len(data),
            ),
        )

    async def store_code_change(
        self,
        session_id: UUID,
        round_id: int,
        file_name: str,
        content: str | bytes,
        content_type: ContentType,
        metadata: dict[str, str] = None,
    ) -> int:
        """Persist a round code change; returns the code_changes row pk.

        Args:
            session_id: Owning session uuid (key namespacing only).
            round_id: Round pk the change belongs to.
            file_name: Original (possibly nested) file path; stored
                verbatim in the DB, sanitized inside the object key.
            content: File body; str is stored utf-8 encoded.
            content_type: MIME type served on reads (max 64 chars).
            metadata: Metadata attached to the object.
        """
        data = self.__encode(content)
        key = (
            f"sessions/{session_id}/rounds/{round_id}"
            + f"/changes/{_token()}-{_safe_name(file_name)}"
        )
        if not metadata:
            metadata = {}
        return await self.__store(
            key=key,
            data=data,
            content_type=content_type.value,
            metadata=metadata if metadata else {},
            context=f"session {session_id} round {round_id}",
            db_write=lambda: DatabaseService.add_code_change(
                round_id=round_id,
                file_name=file_name,
                uri=key,
                content_type=content_type.value,
                file_size_bytes=len(data),
            ),
        )

    @staticmethod
    def __encode(content: str | bytes) -> bytes:
        return content.encode("utf-8") if isinstance(content, str) else content

    async def __store(
        self,
        key: str,
        data: bytes,
        content_type: str,
        metadata: dict[str, str],
        context: str,
        db_write: Callable[[], Awaitable[int]],
    ) -> int:
        """Upload-then-record; compensating delete keeps rows truthful."""
        if len(content_type) > 64:
            raise ObjectStorageError(
                message=(
                    "content_type too long for artifacts.content_type (max 64): "
                    + repr(content_type)
                ),
                error_code=400,
            )
        await self.__storage.put(key, data, content_type, metadata)
        try:
            return await db_write()
        except Exception as e:
            await self.__compensate(key)
            if isinstance(e, ExceptionHandler):
                raise
            raise ObjectStorageError(
                message=f"Recording artifact '{key}' failed ({context}): {e}",
                error_code=500,
            ) from e

    async def __compensate(self, key: str) -> None:
        try:
            await self.__storage.delete(key)
        except Exception as e:
            # Best-effort: an orphaned object is recoverable garbage,
            # unlike a DB row pointing at a missing object.
            logging.warning(f"Compensating delete of '{key}' failed: {e}")

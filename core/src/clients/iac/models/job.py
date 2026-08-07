# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Self, TypeVar, cast
from uuid import UUID

from attrs import define as _attrs_define

from ..models.job_kind import JobKind
from ..models.job_status import JobStatus

if TYPE_CHECKING:
    from ..models.apply_result import ApplyResult
    from ..models.import_result import ImportResult
    from ..models.problem import Problem
    from ..models.validate_result import ValidateResult


T = TypeVar("T", bound="Job")


@_attrs_define
class Job:
    """A submitted terraform job. All keys are always present;
    `started_at`, `finished_at`, `result`, and `error` are null
    until they become meaningful.

        Attributes:
            job_id (UUID):
            kind (JobKind): Which terraform pipeline the job runs.
            status (JobStatus): `queued`: accepted, waiting for its workspace's FIFO queue.
                `running`: terraform pipeline executing.
                `succeeded`: pipeline ran to completion — inspect `result` for
                the terraform-level outcome (which may carry false flags).
                `failed`: service-level fault — inspect `error`.
            created_at (datetime.datetime): When the job was accepted (UTC).
            started_at (datetime.datetime | None): When the job left the queue and began running, or null while
                still `queued`.
            finished_at (datetime.datetime | None): When the job reached a terminal state, or null.
            result (ApplyResult | ImportResult | None | ValidateResult): Non-null iff `status` is `succeeded`. The variant
                matches
                `kind` (`validate` → ValidateResult, `apply` → ApplyResult,
                `import` → ImportResult); the variants are also structurally
                distinguishable by their required fields, in the order
                listed.
            error (None | Problem): Non-null iff `status` is `failed`. The embedded `status`
                member is the HTTP status code an equivalent synchronous
                API would have returned (e.g. 500 credential retrieval
                failure, 422 unresolvable credentials, 504 subprocess
                timeout, 503 shut down before completion).
    """

    job_id: UUID
    kind: JobKind
    status: JobStatus
    created_at: datetime.datetime
    started_at: datetime.datetime | None
    finished_at: datetime.datetime | None
    result: ApplyResult | ImportResult | None | ValidateResult
    error: None | Problem

    def to_dict(self) -> dict[str, Any]:
        from ..models.apply_result import ApplyResult
        from ..models.import_result import ImportResult
        from ..models.problem import Problem
        from ..models.validate_result import ValidateResult

        job_id = str(self.job_id)

        kind = self.kind.value

        status = self.status.value

        created_at = self.created_at.isoformat()

        started_at: None | str
        if isinstance(self.started_at, datetime.datetime):
            started_at = self.started_at.isoformat()
        else:
            started_at = self.started_at

        finished_at: None | str
        if isinstance(self.finished_at, datetime.datetime):
            finished_at = self.finished_at.isoformat()
        else:
            finished_at = self.finished_at

        result: dict[str, Any] | None
        if (
            isinstance(self.result, ValidateResult)
            or isinstance(self.result, ApplyResult)
            or isinstance(self.result, ImportResult)
        ):
            result = self.result.to_dict()
        else:
            result = self.result

        error: dict[str, Any] | None
        if isinstance(self.error, Problem):
            error = self.error.to_dict()
        else:
            error = self.error

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "job_id": job_id,
                "kind": kind,
                "status": status,
                "created_at": created_at,
                "started_at": started_at,
                "finished_at": finished_at,
                "result": result,
                "error": error,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.apply_result import ApplyResult
        from ..models.import_result import ImportResult
        from ..models.problem import Problem
        from ..models.validate_result import ValidateResult

        d = dict(src_dict)
        job_id = UUID(d.pop("job_id"))

        kind = JobKind(d.pop("kind"))

        status = JobStatus(d.pop("status"))

        created_at = datetime.datetime.fromisoformat(d.pop("created_at"))

        def _parse_started_at(data: object) -> datetime.datetime | None:
            if data is None:
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                started_at_type_0 = datetime.datetime.fromisoformat(data)

                return started_at_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None, data)

        started_at = _parse_started_at(d.pop("started_at"))

        def _parse_finished_at(data: object) -> datetime.datetime | None:
            if data is None:
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                finished_at_type_0 = datetime.datetime.fromisoformat(data)

                return finished_at_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None, data)

        finished_at = _parse_finished_at(d.pop("finished_at"))

        def _parse_result(
            data: object,
        ) -> ApplyResult | ImportResult | None | ValidateResult:
            if data is None:
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                result_type_0 = ValidateResult.from_dict(data)

                return result_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                result_type_1 = ApplyResult.from_dict(data)

                return result_type_1
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                result_type_2 = ImportResult.from_dict(data)

                return result_type_2
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(ApplyResult | ImportResult | None | ValidateResult, data)

        result = _parse_result(d.pop("result"))

        def _parse_error(data: object) -> None | Problem:
            if data is None:
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                error_type_0 = Problem.from_dict(data)

                return error_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | Problem, data)

        error = _parse_error(d.pop("error"))

        job = cls(
            job_id=job_id,
            kind=kind,
            status=status,
            created_at=created_at,
            started_at=started_at,
            finished_at=finished_at,
            result=result,
            error=error,
        )

        return job

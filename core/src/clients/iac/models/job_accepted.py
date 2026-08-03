# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Self, TypeVar
from uuid import UUID

from attrs import define as _attrs_define

from ..models.job_status import JobStatus

T = TypeVar("T", bound="JobAccepted")


@_attrs_define
class JobAccepted:
    """Returned by the submitting endpoints when a job is enqueued.

    Attributes:
        job_id (UUID): Identifier to poll at `GET /v1/jobs/{job_id}`.
        status (JobStatus): `queued`: accepted, waiting for its workspace's FIFO queue.
            `running`: terraform pipeline executing.
            `succeeded`: pipeline ran to completion — inspect `result` for
            the terraform-level outcome (which may carry false flags).
            `failed`: service-level fault — inspect `error`.
    """

    job_id: UUID
    status: JobStatus

    def to_dict(self) -> dict[str, Any]:
        job_id = str(self.job_id)

        status = self.status.value

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "job_id": job_id,
                "status": status,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        job_id = UUID(d.pop("job_id"))

        status = JobStatus(d.pop("status"))

        job_accepted = cls(
            job_id=job_id,
            status=status,
        )

        return job_accepted

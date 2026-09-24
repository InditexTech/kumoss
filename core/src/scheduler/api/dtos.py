# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Request and response models for the operations and schedules API."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from src.scheduler.constants import OperationKind, OperationStatus

class OperationResponse(BaseModel):
    uuid: UUID
    session_uuid: UUID | None = None
    schedule_uuid: UUID | None = None
    kind: OperationKind
    status: OperationStatus
    params: dict
    scheduled_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    attempt: int
    max_attempts: int
    error: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class PaginatedOperations(BaseModel):
    items: list[OperationResponse]
    total: int
    page: int
    page_size: int

class CreateScheduleRequest(BaseModel):
    user_id: str = Field(min_length=1)
    name: str = Field(min_length=1, max_length=254)
    kind: OperationKind
    cron: str = Field(min_length=1, max_length=128)
    params: dict = Field(default_factory=dict)
    enabled: bool = True


class UpdateScheduleRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=254)
    cron: str | None = Field(default=None, min_length=1, max_length=128)
    params: dict | None = None
    enabled: bool | None = None


class ScheduleResponse(BaseModel):
    uuid: UUID
    user_id: str | None = None
    name: str
    kind: OperationKind
    cron: str
    enabled: bool
    params: dict
    next_run_at: datetime | None = None
    last_run_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class PaginatedSchedules(BaseModel):
    items: list[ScheduleResponse]
    total: int
    page: int
    page_size: int

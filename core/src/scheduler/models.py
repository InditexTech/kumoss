# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from datetime import datetime
from typing import final, override

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.infrastructure.database.models import Base
from src.scheduler.constants import OperationKind, OperationStatus


@final
class Operation(Base):

    __tablename__ = "operations"
    __table_args__ = (
        Index("ix_operations_claim", "status", "scheduled_at"),
    )

    uuid: Mapped[str] = mapped_column(
        UUID(as_uuid=True), unique=True, index=True, nullable=False
    )

    session_id: Mapped[int] = mapped_column(
        ForeignKey("sessions.id"), index=True, nullable=False
    )

    schedule_id: Mapped[int | None] = mapped_column(
        ForeignKey("operation_schedules.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )

    kind: Mapped[OperationKind] = mapped_column(nullable=False)
    params: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[OperationStatus] = mapped_column(
        default=OperationStatus.PENDING, nullable=False
    )

    scheduled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    attempt: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=10800, nullable=False)

    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    claimed_by: Mapped[str | None] = mapped_column(String(254), nullable=True)

    cancel_requested: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )

    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    dedup_key: Mapped[str | None] = mapped_column(String(512), nullable=True)


    schedule: Mapped["OperationSchedule | None"] = relationship(
        "OperationSchedule",
        back_populates="operations",
        foreign_keys=[schedule_id],
    )

    @override
    def __repr__(self) -> str:
        return (
            f"<Operation(uuid='{self.uuid}', kind={self.kind.value}, "
            f"status={self.status.value})>"
        )


@final
class OperationSchedule(Base):

    __tablename__ = "operation_schedules"

    uuid: Mapped[str] = mapped_column(
        UUID(as_uuid=True), unique=True, index=True, nullable=False
    )

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), index=True, nullable=False
    )

    name: Mapped[str] = mapped_column(String(254), nullable=False)
    kind: Mapped[OperationKind] = mapped_column(nullable=False)
    params: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    cron: Mapped[str] = mapped_column(String(128), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    next_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True, nullable=True
    )
    last_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    last_operation_id: Mapped[int | None] = mapped_column(
        ForeignKey("operations.id", ondelete="SET NULL"), nullable=True
    )

    operations: Mapped[list["Operation"]] = relationship(
        "Operation",
        back_populates="schedule",
        foreign_keys="Operation.schedule_id",
    )

    @override
    def __repr__(self) -> str:
        return (
            f"<OperationSchedule(uuid='{self.uuid}', name='{self.name}', "
            f"cron='{self.cron}', enabled={self.enabled})>"
        )

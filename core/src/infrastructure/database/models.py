# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Database models for Kumoss application."""

from datetime import datetime, timezone
from typing import Any, final, override

from sqlalchemy import (
    Boolean,
    Enum as SAEnum,
    ForeignKey,
    Index,
    String,
    Text,
    DateTime,
    Integer,
    JSON,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from src.shared.constants import (
    GitProviderName,
    OperationRole,
    OperationStatus,
    OperationType,
    PanelRole,
    ReportType,
    SessionStatus,
    TerraformProvider as TP,
)


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


@final
class User(Base):
    """Internal users resolved from OIDC identities.

    Identity key is (issuer, subject); email is display/bootstrap data and
    may collide across issuers. A NULL panel_role means no admin-panel
    access.
    """

    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("issuer", "subject"),)

    issuer: Mapped[str] = mapped_column(String(512))
    subject: Mapped[str] = mapped_column(String(254))
    email: Mapped[str | None] = mapped_column(String(254), index=True)
    display_name: Mapped[str | None] = mapped_column(String(254))
    operation_role: Mapped[OperationRole] = mapped_column(
        default=OperationRole.DEVELOPER
    )
    panel_role: Mapped[PanelRole | None] = mapped_column(nullable=True)
    # relations
    sessions: Mapped[list["Session"]] = relationship("Session", cascade="all, delete")

    @override
    def __repr__(self) -> str:
        return f"<User(id={self.id}, issuer='{self.issuer}', subject='{self.subject}')>"


@final
class Session(Base):
    """"""

    __tablename__ = "sessions"

    uuid: Mapped[UUID[str]] = mapped_column(UUID(as_uuid=True), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    operation: Mapped[OperationType] = mapped_column()
    in_flight: Mapped[bool] = mapped_column(default=False)
    is_blocked: Mapped[bool] = mapped_column(default=False)
    # relations
    workspaces: Mapped[list["Workspace"]] = relationship(
        "Workspace", cascade="all, delete"
    )
    terraform_providers: Mapped[list["TerraformProvider"]] = relationship(
        "TerraformProvider", cascade="all, delete"
    )
    histories: Mapped[list["History"]] = relationship("History", cascade="all, delete")
    statuses: Mapped[list["Status"]] = relationship("Status", cascade="all, delete")
    rounds: Mapped[list["Round"]] = relationship(
        "Round", cascade="all, delete", order_by="Round.number"
    )

    @override
    def __repr__(self) -> str:
        return f"""<Session(session_id='{self.uuid}',
                      in_flight='{self.in_flight}, is_blocked='{self.is_blocked}')>"""


@final
class Workspace(Base):
    """"""

    __tablename__ = "workspaces"

    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"), index=True)
    uri: Mapped[str] = mapped_column(Text)
    branch: Mapped[str] = mapped_column(String(254))
    root_path: Mapped[str] = mapped_column(Text)

    @override
    def __repr__(self) -> str:
        return f"<Workspace(session_id='{self.session_id}', uri={self.uri}')>"


@final
class TerraformProvider(Base):
    """"""

    __tablename__ = "terraform_providers"

    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"), index=True)
    provider: Mapped[TP] = mapped_column()
    scope_id: Mapped[str] = mapped_column(String(1016))

    @override
    def __repr__(self) -> str:
        return f"<TerraformProvider(session_id='{self.session_id}', name={self.provider}')>"


@final
class PullRequest(Base):
    """"""

    __tablename__ = "pull_requests"

    round_id: Mapped[int] = mapped_column(ForeignKey("rounds.id"), index=True)
    provider: Mapped[GitProviderName] = mapped_column()
    number: Mapped[int] = mapped_column()
    url: Mapped[str] = mapped_column(String(254))

    @override
    def __repr__(self) -> str:
        return f"<PullRequest(round_id='{self.round_id}', url={self.url}')>"


@final
class History(Base):
    """"""

    __tablename__ = "histories"

    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"), index=True)
    first_query: Mapped[str] = mapped_column(Text)
    payload: Mapped[list[dict[str, str]]] = mapped_column(JSON, default=list)

    @override
    def __repr__(self) -> str:
        return f"<History(session_id='{self.session_id}', first_query={self.first_query}')>"


@final
class Status(Base):
    """"""

    __tablename__ = "statuses"

    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"), index=True)
    round_id: Mapped[int] = mapped_column(ForeignKey("rounds.id"), index=True)
    status: Mapped[SessionStatus] = mapped_column(default=SessionStatus.STARTED)
    message: Mapped[str] = mapped_column(Text)

    @override
    def __repr__(self) -> str:
        return f"<Status(session_id='{self.session_id}', status={self.status.name}')>"


@final
class Round(Base):
    """One generation iteration within a session; per-round artifacts hang off it."""

    __tablename__ = "rounds"
    __table_args__ = (UniqueConstraint("session_id", "number"),)

    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    query: Mapped[str] = mapped_column(Text)
    # relations
    statuses: Mapped[list["Status"]] = relationship("Status")
    pull_requests: Mapped[list["PullRequest"]] = relationship(
        "PullRequest", cascade="all, delete"
    )
    terraform_plans: Mapped[list["TerraformPlan"]] = relationship(
        "TerraformPlan", cascade="all, delete"
    )
    reports: Mapped[list["Report"]] = relationship("Report", cascade="all, delete")
    compliance_checks: Mapped[list["ComplianceCheck"]] = relationship(
        "ComplianceCheck", cascade="all, delete"
    )
    code_changes: Mapped[list["CodeChange"]] = relationship(
        "CodeChange", cascade="all, delete"
    )

    @override
    def __repr__(self) -> str:
        return f"<Round(session_id='{self.session_id}', number={self.number})>"


@final
class Artifact(Base):
    """"""

    __tablename__ = "artifacts"

    uri: Mapped[str] = mapped_column(Text)
    content_type: Mapped[str] = mapped_column(String(64))
    file_size_bytes: Mapped[int] = mapped_column(Integer)
    # relations
    terraform_plans: Mapped[list["TerraformPlan"]] = relationship(
        "TerraformPlan", back_populates="artifact", cascade="all, delete"
    )
    reports: Mapped[list["Report"]] = relationship(
        "Report", back_populates="artifact", cascade="all, delete"
    )
    compliance_checks: Mapped[list["ComplianceCheck"]] = relationship(
        "ComplianceCheck", back_populates="artifact", cascade="all, delete"
    )
    code_changes: Mapped[list["CodeChange"]] = relationship(
        "CodeChange", back_populates="artifact", cascade="all, delete"
    )

    @override
    def __repr__(self) -> str:
        return f"<Artifact(uri='{self.uri}', content_type='{self.content_type}')>"


@final
class TerraformPlan(Base):
    """"""

    __tablename__ = "terraform_plans"

    round_id: Mapped[int] = mapped_column(ForeignKey("rounds.id"), index=True)
    artifact_id: Mapped[int] = mapped_column(ForeignKey("artifacts.id"), index=True)
    targets: Mapped[list[str]] = mapped_column(ARRAY(String))
    # relations
    artifact: Mapped["Artifact"] = relationship(
        "Artifact", back_populates="terraform_plans"
    )

    @override
    def __repr__(self) -> str:
        return f"<TerraformPlan(round_id='{self.round_id}', targets='{self.targets}')>"


@final
class Report(Base):
    """"""

    __tablename__ = "reports"

    round_id: Mapped[int] = mapped_column(ForeignKey("rounds.id"), index=True)
    artifact_id: Mapped[int] = mapped_column(ForeignKey("artifacts.id"), index=True)
    type: Mapped[ReportType] = mapped_column()
    # relations
    artifact: Mapped["Artifact"] = relationship("Artifact", back_populates="reports")

    @override
    def __repr__(self) -> str:
        return f"<Report(round_id='{self.round_id}', type='{self.type}')>"


@final
class ComplianceCheck(Base):
    """"""

    __tablename__ = "compliance_checks"

    round_id: Mapped[int] = mapped_column(ForeignKey("rounds.id"), index=True)
    artifact_id: Mapped[int] = mapped_column(ForeignKey("artifacts.id"), index=True)
    passed: Mapped[bool] = mapped_column()
    # relations
    artifact: Mapped["Artifact"] = relationship(
        "Artifact", back_populates="compliance_checks"
    )

    @override
    def __repr__(self) -> str:
        return f"<ComplianceCheck(round_id='{self.round_id}', passed='{self.passed}')>"


@final
class CodeChange(Base):
    """"""

    __tablename__ = "code_changes"

    round_id: Mapped[int] = mapped_column(ForeignKey("rounds.id"), index=True)
    artifact_id: Mapped[int] = mapped_column(ForeignKey("artifacts.id"), index=True)
    file_name: Mapped[str] = mapped_column(String(254))
    # relations
    artifact: Mapped["Artifact"] = relationship(
        "Artifact", back_populates="code_changes"
    )

    @override
    def __repr__(self) -> str:
        return f"<CodeChange(round_id='{self.round_id}', file_name='{self.file_name}')>"


# Stored as VARCHAR rather than reusing the native ``operationtype`` enum of
# ``sessions.operation``: ``create_all`` never alters an existing type, so a
# native column could not hold APPLY on databases created before it existed.
_OPERATION_KIND = SAEnum(OperationType, native_enum=False, length=16)


@final
class Operation(Base):
    """One queued terraform operation on a session."""

    __tablename__ = "operations"
    __table_args__ = (
        Index("ix_operations_claim", "status", "scheduled_at"),
        # At most one active operation per session: the enqueue-time guard
        # that rejects concurrent calls on the same session.
        Index(
            "uq_operations_active_session",
            "session_id",
            unique=True,
            postgresql_where=text(  # nosemgrep: python.sqlalchemy.security.audit.avoid-sqlalchemy-text.avoid-sqlalchemy-text
                f"status IN ('{OperationStatus.PENDING.name}', "
                + f"'{OperationStatus.RUNNING.name}')"
            ),
        ),
    )

    uuid: Mapped[UUID[str]] = mapped_column(UUID(as_uuid=True), unique=True, index=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"), index=True)
    schedule_id: Mapped[int | None] = mapped_column(
        ForeignKey("operation_schedules.id", ondelete="SET NULL"), index=True
    )
    kind: Mapped[OperationType] = mapped_column(_OPERATION_KIND)
    params: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[OperationStatus] = mapped_column(default=OperationStatus.PENDING)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    timeout_seconds: Mapped[int] = mapped_column(Integer)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    claimed_by: Mapped[str | None] = mapped_column(String(254))
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
    # relations
    session: Mapped["Session"] = relationship("Session", lazy="joined")
    schedule: Mapped["OperationSchedule | None"] = relationship(
        "OperationSchedule", lazy="joined"
    )

    @override
    def __repr__(self) -> str:
        return f"<Operation(uuid='{self.uuid}', kind={self.kind.name}, status={self.status.name})>"


@final
class OperationSchedule(Base):
    """A cron schedule that fires a fresh-session operation for its owner."""

    __tablename__ = "operation_schedules"

    uuid: Mapped[UUID[str]] = mapped_column(UUID(as_uuid=True), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(254))
    kind: Mapped[OperationType] = mapped_column(_OPERATION_KIND)
    params: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    cron: Mapped[str] = mapped_column(String(128))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    next_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    @override
    def __repr__(self) -> str:
        return f"<OperationSchedule(uuid='{self.uuid}', name='{self.name}', cron='{self.cron}')>"

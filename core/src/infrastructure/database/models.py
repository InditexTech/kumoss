# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Database models for Nebula application."""

from datetime import datetime, timezone
from typing import final, override

from sqlalchemy import (
    ForeignKey,
    String,
    Text,
    DateTime,
    Integer,
    JSON,
)
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from src.shared.constants import (
    ArtifactType,
    GitProviderName,
    OperationType,
    SessionStatus,
    TemplateProvider,
)


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=datetime.now(timezone.utc),
        onupdate=datetime.now(timezone.utc),
    )


@final
class User(Base):
    """Users table for storing user related information."""

    __tablename__ = "users"

    username: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    # relations
    sessions: Mapped[list["Session"]] = relationship("Session", cascade="all, delete")

    @override
    def __repr__(self) -> str:
        return f"<Users(id={self.id}, username='{self.username}')>"


@final
class Session(Base):
    """"""

    __tablename__ = "sessions"
    uuid: Mapped[str] = mapped_column(UUID(as_uuid=True), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    status: Mapped[SessionStatus] = mapped_column(
        String(20), default=SessionStatus.STARTED
    )
    in_flight: Mapped[bool] = mapped_column(default=False)
    is_blocked: Mapped[bool] = mapped_column(default=False)
    # relations
    workspaces: Mapped[list["Workspace"]] = relationship(
        "Workspace", cascade="all, delete"
    )
    pull_requests: Mapped[list["PullRequest"]] = relationship(
        "PullRequest", cascade="all, delete"
    )
    cloud_providers: Mapped[list["CloudProvider"]] = relationship(
        "CloudProvider", cascade="all, delete"
    )
    histories: Mapped[list["History"]] = relationship("History", cascade="all, delete")
    operations: Mapped[list["Operation"]] = relationship(
        "Operation", cascade="all, delete"
    )

    @override
    def __repr__(self) -> str:
        return f"""<UserSession(session_id='{self.uuid}', status='{self.status}',
                      in_flight='{self.in_flight}, is_blocked='{self.is_blocked}')>"""


@final
class Workspace(Base):
    """"""

    __tablename__ = "workspaces"

    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"))
    uri: Mapped[str] = mapped_column(Text)
    branch: Mapped[str] = mapped_column(String(254))
    root_path: Mapped[str] = mapped_column(Text)

    @override
    def __repr__(self) -> str:
        return f"<Workspace(session_id='{self.session_id}', uri={self.uri}')>"


@final
class CloudProvider(Base):
    """"""

    __tablename__ = "cloud_providers"

    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"))
    name: Mapped[TemplateProvider] = mapped_column()

    @override
    def __repr__(self) -> str:
        return f"<CloudProvider(session_id='{self.session_id}', name={self.name}')>"


@final
class PullRequest(Base):
    """"""

    __tablename__ = "pull_requests"

    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"))
    provider: Mapped[GitProviderName] = mapped_column(String(20))
    url: Mapped[str] = mapped_column(String(254))

    @override
    def __repr__(self) -> str:
        return f"<PullRequest(session_id='{self.session_id}', url={self.url}')>"


@final
class History(Base):
    """"""

    __tablename__ = "histories"

    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"))
    first_query: Mapped[str] = mapped_column(Text)
    payload: Mapped[JSON] = mapped_column(default={})

    @override
    def __repr__(self) -> str:
        return f"<History(session_id='{self.session_id}', first_query={self.first_query}')>"


@final
class Operation(Base):
    """Tracks individual operations within a session."""

    __tablename__ = "operations"

    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"))
    operation: Mapped[OperationType] = mapped_column()
    type: Mapped[ArtifactType] = mapped_column()
    terraform_targets: Mapped[list[str]] = mapped_column(ARRAY(String))
    # relations
    artifacts: Mapped[list["Artifact"]] = relationship(
        "Artifact", cascade="all, delete"
    )

    @override
    def __repr__(self) -> str:
        return (
            f"<Operation(session_id='{self.session_id}', operation={self.operation})>"
        )


@final
class Artifact(Base):
    """"""

    __tablename__ = "artifacts"

    operation_id: Mapped[int] = mapped_column(ForeignKey("operations.id"))
    uri: Mapped[str] = mapped_column(Text)
    content_type: Mapped[str] = mapped_column(String(20))
    file_size_bytes: Mapped[int] = mapped_column(Integer)

    @override
    def __repr__(self) -> str:
        return f"<Artifact(operation_id='{self.operation_id}', uri='{self.uri}')>"


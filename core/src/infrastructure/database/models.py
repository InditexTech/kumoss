# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Database models for Nebula application."""

from datetime import datetime, timezone
from typing import Any, final, override

from sqlalchemy import (
    CheckConstraint,
    String,
    Text,
    DateTime,
    Integer,
    Boolean,
    Float,
    JSON,
)
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


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
class GreenaiUsers(Base):
    """GreenAI users table for storing user information."""

    __tablename__ = "greenai_users"

    username: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    teams_group_id: Mapped[str | None] = mapped_column(Text, nullable=True)

    @override
    def __repr__(self) -> str:
        return f"<GreenaiUsers(id={self.id}, username='{self.username}')>"


@final
class UserSession(Base):
    """One iterating session against a repo URI. Owns its history and last payload."""

    __tablename__ = "user_sessions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'completed', 'abandoned')",
            name="user_sessions_status_check",
        ),
    )

    session_id: Mapped[str] = mapped_column(
        PostgresUUID(as_uuid=False), nullable=False, unique=True, index=True
    )
    user_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    repo_uri: Mapped[str] = mapped_column(Text, nullable=False)
    cloud_provider: Mapped[str] = mapped_column(String(50), nullable=False)
    environment: Mapped[str] = mapped_column(String(50), nullable=False)
    branch_name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    in_flight: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    history: Mapped[list[dict[str, str]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    last_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    operation_type: Mapped[str] = mapped_column(
        String(50), nullable=False, default="generate"
    )
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    pull_request_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    apply_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    iac_path: Mapped[str | None] = mapped_column(Text, nullable=True)

    @override
    def __repr__(self) -> str:
        return f"<UserSession(session_id='{self.session_id}', status='{self.status}')>"


@final
class SessionOperation(Base):
    """Tracks individual operations within a session."""

    __tablename__ = "session_operations"

    session_id: Mapped[str] = mapped_column(
        PostgresUUID(as_uuid=False), nullable=False, index=True
    )
    operation_number: Mapped[int] = mapped_column(Integer, nullable=False)
    operation_type: Mapped[str] = mapped_column(String(100), nullable=False)
    operation_phase: Mapped[str | None] = mapped_column(String(100), nullable=True)
    operation_subtype: Mapped[str | None] = mapped_column(String(100), nullable=True)
    pipeline_run_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    terraform_targets: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    success: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    artifact_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    blob_container: Mapped[str | None] = mapped_column(String(255), nullable=True)
    blob_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    blob_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(100), nullable=True)

    @override
    def __repr__(self) -> str:
        return f"<SessionOperation(session_id='{self.session_id}', op=#{self.operation_number}, type='{self.operation_type}')>"

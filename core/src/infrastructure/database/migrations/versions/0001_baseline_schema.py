# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Baseline: the schema as create_all built it before Alembic.

Databases created before Alembic are stamped at this revision instead of
running it (see ``migrator``).

Revision ID: 0001
Revises:
Create Date: 2026-11-19 12:59:39.831548
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "artifacts",
        sa.Column("uri", sa.Text(), nullable=False),
        sa.Column("content_type", sa.String(length=64), nullable=False),
        sa.Column("file_size_bytes", sa.Integer(), nullable=False),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "users",
        sa.Column("issuer", sa.String(length=512), nullable=False),
        sa.Column("subject", sa.String(length=254), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=True),
        sa.Column("display_name", sa.String(length=254), nullable=True),
        sa.Column(
            "operation_role",
            sa.Enum("DEVELOPER", "DEVOPS", name="operationrole"),
            nullable=False,
        ),
        sa.Column(
            "panel_role",
            sa.Enum("VIEWER", "EDITOR", "ADMIN", name="panelrole"),
            nullable=True,
        ),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("issuer", "subject"),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=False)
    op.create_table(
        "sessions",
        sa.Column("uuid", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column(
            "operation",
            sa.Enum("GENERATE", "DRIFT", "IMPORT", "APPLY", name="operationtype"),
            nullable=False,
        ),
        sa.Column("in_flight", sa.Boolean(), nullable=False),
        sa.Column("is_blocked", sa.Boolean(), nullable=False),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_sessions_user_id"), "sessions", ["user_id"], unique=False)
    op.create_index(op.f("ix_sessions_uuid"), "sessions", ["uuid"], unique=True)
    op.create_table(
        "histories",
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("first_query", sa.Text(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("chat_payload", sa.JSON(), nullable=False),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["sessions.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_histories_session_id"), "histories", ["session_id"], unique=False
    )
    op.create_table(
        "rounds",
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["sessions.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", "number"),
    )
    op.create_index(
        op.f("ix_rounds_session_id"), "rounds", ["session_id"], unique=False
    )
    op.create_table(
        "terraform_providers",
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("scope_id", sa.String(length=1016), nullable=True),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["sessions.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_terraform_providers_session_id"),
        "terraform_providers",
        ["session_id"],
        unique=False,
    )
    op.create_table(
        "workspaces",
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("uri", sa.Text(), nullable=False),
        sa.Column("branch", sa.String(length=254), nullable=False),
        sa.Column("root_path", sa.Text(), nullable=False),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["sessions.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_workspaces_session_id"), "workspaces", ["session_id"], unique=False
    )
    op.create_table(
        "code_changes",
        sa.Column("round_id", sa.Integer(), nullable=False),
        sa.Column("artifact_id", sa.Integer(), nullable=False),
        sa.Column("file_name", sa.String(length=254), nullable=False),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["artifact_id"],
            ["artifacts.id"],
        ),
        sa.ForeignKeyConstraint(
            ["round_id"],
            ["rounds.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_code_changes_artifact_id"),
        "code_changes",
        ["artifact_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_code_changes_round_id"), "code_changes", ["round_id"], unique=False
    )
    op.create_table(
        "compliance_checks",
        sa.Column("round_id", sa.Integer(), nullable=False),
        sa.Column("artifact_id", sa.Integer(), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["artifact_id"],
            ["artifacts.id"],
        ),
        sa.ForeignKeyConstraint(
            ["round_id"],
            ["rounds.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_compliance_checks_artifact_id"),
        "compliance_checks",
        ["artifact_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_compliance_checks_round_id"),
        "compliance_checks",
        ["round_id"],
        unique=False,
    )
    op.create_table(
        "pull_requests",
        sa.Column("round_id", sa.Integer(), nullable=False),
        sa.Column(
            "provider",
            sa.Enum("GITHUB", "AZURE_DEVOPS", "GITLAB", name="gitprovidername"),
            nullable=False,
        ),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("url", sa.String(length=254), nullable=False),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["round_id"],
            ["rounds.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_pull_requests_round_id"), "pull_requests", ["round_id"], unique=False
    )
    op.create_table(
        "reports",
        sa.Column("round_id", sa.Integer(), nullable=False),
        sa.Column("artifact_id", sa.Integer(), nullable=False),
        sa.Column(
            "type",
            sa.Enum("GENERATE", "DRIFT", "IMPORT", "APPLY", name="reporttype"),
            nullable=False,
        ),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["artifact_id"],
            ["artifacts.id"],
        ),
        sa.ForeignKeyConstraint(
            ["round_id"],
            ["rounds.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_reports_artifact_id"), "reports", ["artifact_id"], unique=False
    )
    op.create_index(op.f("ix_reports_round_id"), "reports", ["round_id"], unique=False)
    op.create_table(
        "statuses",
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("round_id", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "STARTED",
                "FILTERING",
                "GENERATING",
                "VALIDATING",
                "RECONCILING",
                "REPORT",
                "APPLY",
                "COMPLETED",
                "UNCOMPLETED",
                "FAILED",
                name="sessionstatus",
            ),
            nullable=False,
        ),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["round_id"],
            ["rounds.id"],
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["sessions.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_statuses_round_id"), "statuses", ["round_id"], unique=False
    )
    op.create_index(
        op.f("ix_statuses_session_id"), "statuses", ["session_id"], unique=False
    )
    op.create_table(
        "terraform_plans",
        sa.Column("round_id", sa.Integer(), nullable=False),
        sa.Column("artifact_id", sa.Integer(), nullable=False),
        sa.Column("targets", postgresql.ARRAY(sa.String()), nullable=False),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["artifact_id"],
            ["artifacts.id"],
        ),
        sa.ForeignKeyConstraint(
            ["round_id"],
            ["rounds.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_terraform_plans_artifact_id"),
        "terraform_plans",
        ["artifact_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_terraform_plans_round_id"),
        "terraform_plans",
        ["round_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_terraform_plans_round_id"), table_name="terraform_plans")
    op.drop_index(op.f("ix_terraform_plans_artifact_id"), table_name="terraform_plans")
    op.drop_table("terraform_plans")
    op.drop_index(op.f("ix_statuses_session_id"), table_name="statuses")
    op.drop_index(op.f("ix_statuses_round_id"), table_name="statuses")
    op.drop_table("statuses")
    op.drop_index(op.f("ix_reports_round_id"), table_name="reports")
    op.drop_index(op.f("ix_reports_artifact_id"), table_name="reports")
    op.drop_table("reports")
    op.drop_index(op.f("ix_pull_requests_round_id"), table_name="pull_requests")
    op.drop_table("pull_requests")
    op.drop_index(op.f("ix_compliance_checks_round_id"), table_name="compliance_checks")
    op.drop_index(
        op.f("ix_compliance_checks_artifact_id"), table_name="compliance_checks"
    )
    op.drop_table("compliance_checks")
    op.drop_index(op.f("ix_code_changes_round_id"), table_name="code_changes")
    op.drop_index(op.f("ix_code_changes_artifact_id"), table_name="code_changes")
    op.drop_table("code_changes")
    op.drop_index(op.f("ix_workspaces_session_id"), table_name="workspaces")
    op.drop_table("workspaces")
    op.drop_index(
        op.f("ix_terraform_providers_session_id"), table_name="terraform_providers"
    )
    op.drop_table("terraform_providers")
    op.drop_index(op.f("ix_rounds_session_id"), table_name="rounds")
    op.drop_table("rounds")
    op.drop_index(op.f("ix_histories_session_id"), table_name="histories")
    op.drop_table("histories")
    op.drop_index(op.f("ix_sessions_uuid"), table_name="sessions")
    op.drop_index(op.f("ix_sessions_user_id"), table_name="sessions")
    op.drop_table("sessions")
    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_table("users")
    op.drop_table("artifacts")
    # Dropping a table leaves its native enum types behind.
    for enum in (
        "sessionstatus",
        "reporttype",
        "gitprovidername",
        "operationtype",
        "panelrole",
        "operationrole",
    ):
        op.execute(f"DROP TYPE IF EXISTS {enum}")

# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Store the project identifier a session's repository was named by, for
the IaC service. Sessions created before it have none.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-25 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "workspaces",
        sa.Column("project_identifier", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("workspaces", "project_identifier")

# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from dataclasses import dataclass
from datetime import datetime

from src.shared.constants import OperationRole, PanelRole


@dataclass(frozen=True)
class User:
    """Internal user resolved from an OIDC identity.

    Identity key is (issuer, subject); email is display/bootstrap data and
    may collide across issuers. A None panel_role means no admin-panel
    access.
    """

    id: int
    issuer: str
    subject: str
    email: str | None
    display_name: str | None
    operation_role: OperationRole
    panel_role: PanelRole | None
    created_at: datetime

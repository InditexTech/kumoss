# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from dataclasses import dataclass
from uuid import UUID


@dataclass
class SessionContext:
    """One in-flight call's worth of session state.

    Produced by SessionOrchestrationService.resolve(); consumed by the
    endpoint runners, HandlerFactory, and the three use-case handlers.
    """

    session_id: UUID
    user_id: str
    repo_uri: str
    cloud: str
    environment: str
    branch_name: str
    history: list[dict]
    is_first_call: bool
    iac_path: str | None = None

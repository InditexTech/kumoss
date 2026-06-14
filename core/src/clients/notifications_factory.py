# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Factory for the notifications service client.

Exposes a single ``get_notifications_client()`` helper that returns a
configured ``AuthenticatedClient`` if the notifications service is enabled in
the system configuration, or ``None`` otherwise. Call sites in the core should
treat ``None`` as "notifications turned off; skip the call" rather than an
error.
"""

from __future__ import annotations

from src.clients.notifications.client import AuthenticatedClient
from src.shared.config import system_config


def get_notifications_client() -> AuthenticatedClient | None:
    cfg = system_config.services.notifications
    if not cfg.enabled or not cfg.endpoint:
        return None
    import httpx

    return AuthenticatedClient(
        base_url=cfg.endpoint,
        token=cfg.token,
        timeout=httpx.Timeout(10.0),
    )

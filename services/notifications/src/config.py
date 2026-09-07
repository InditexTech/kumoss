# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Runtime configuration for the notifications reference implementation."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    """Resolved from environment at startup.

    - ``slack_webhook_url``: full incoming-webhook URL. Required for actual
      delivery; if unset, the service still accepts requests and returns
      ``503 Service Unavailable`` from /v1/notify (handy for smoke tests
      against a service that hasn't been wired to a backend yet).
    - ``expected_token``: bearer token clients must present. If unset, the
      service accepts any (or no) token (intended for local development).
    - ``log_level``: Python logging level name for the service's own
      logger (``LOG_LEVEL``, default ``INFO``). ``DEBUG`` additionally
      logs the rendered Slack payload.
    """

    slack_webhook_url: str
    expected_token: str
    log_level: str = "INFO"

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            slack_webhook_url=os.environ.get("SLACK_WEBHOOK_URL", ""),
            expected_token=os.environ.get("NEBULA_NOTIFICATIONS_TOKEN", ""),
            log_level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        )

# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Runtime configuration for the notifications reference implementation."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass


class ConfigError(ValueError):
    """Raised when the resolved service configuration is unusable."""


@dataclass(frozen=True)
class Config:
    """Resolved from environment at startup.

    - ``slack_webhook_url``: full incoming-webhook URL. Required: the
      service refuses to start without it so a deployment that cannot
      deliver anything fails at boot rather than on the first request.
    - ``expected_token``: bearer token clients must present. If unset, the
      service accepts any (or no) token (intended for local development).
    - ``log_level``: Python logging level name applied to the root logger
      (``LOG_LEVEL``, default ``INFO``).
    """

    slack_webhook_url: str
    expected_token: str
    log_level: str = "INFO"

    def __post_init__(self) -> None:
        if not self.slack_webhook_url:
            raise ConfigError("SLACK_WEBHOOK_URL must be set.")
        level = logging.getLevelNamesMapping().get(self.log_level)
        if level is None:
            raise ConfigError(f"LOG_LEVEL {self.log_level!r} is not a logging level.")
        logging.basicConfig(level=level)
        logging.getLogger().setLevel(level)
        third_party_level = max(level, logging.WARNING)
        logging.getLogger("httpx").setLevel(third_party_level)
        logging.getLogger("httpcore").setLevel(third_party_level)

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            slack_webhook_url=os.environ.get("SLACK_WEBHOOK_URL", ""),
            expected_token=os.environ.get("NEBULA_NOTIFICATIONS_TOKEN", ""),
            log_level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        )

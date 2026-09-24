# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Scheduler configuration, loaded from the ``scheduler:`` block in config.yaml."""

from __future__ import annotations

from pydantic import BaseModel


class SchedulerConfig(BaseModel, frozen=True):
    enabled: bool = False
    concurrency: int = 4
    claim_interval: float = 2.0
    heartbeat_interval: float = 30.0
    lease_seconds: float = 120.0
    reaper_interval: float = 60.0
    schedule_poll_interval: float = 30.0
    default_max_attempts: int = 2
    retry_backoff_seconds: float = 60.0
    retry_backoff_cap: float = 3600.0
    default_timeout_seconds: int = 10800
    shutdown_grace_seconds: float = 60.0

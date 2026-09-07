# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Request-scoped logging context for the IaC service.

Uses ``contextvars`` so every log line emitted during a request
automatically carries ``request_id``, ``workspace``, and ``job_id``
fields, letting operators filter interleaved logs from concurrent
requests.
"""

from __future__ import annotations

import contextvars
import logging
import sys
import uuid

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default="-"
)
workspace_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "workspace", default="-"
)
job_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("job_id", default="-")


def set_job_id(job_id: str) -> None:
    job_id_var.set(job_id)


def set_request_id(rid: str | None = None) -> str:
    """Set (or generate) a request ID for the current async context."""
    rid = rid or uuid.uuid4().hex[:12]
    request_id_var.set(rid)
    return rid


def set_workspace(path: str) -> None:
    workspace_var.set(path)


class ContextFilter(logging.Filter):
    """Inject ``request_id``, ``workspace``, and ``job_id`` into every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()  # type: ignore[attr-defined]
        record.workspace = workspace_var.get()  # type: ignore[attr-defined]
        record.job_id = job_id_var.get()  # type: ignore[attr-defined]
        return True


_LOG_FORMAT = (
    "%(asctime)s %(levelname)-7s [%(request_id)s] [%(workspace)s] [%(job_id)s] "
    "%(name)s — %(message)s"
)


def configure_logging(level: str = "INFO") -> None:
    """Set up structured logging with context fields on stdout."""
    root = logging.getLogger()
    root.setLevel(level.upper())

    if root.handlers:
        root.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt="%Y-%m-%dT%H:%M:%S"))
    handler.addFilter(ContextFilter())
    root.addHandler(handler)

# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Contains all the data models used in inputs/outputs"""

from .health import Health
from .health_status import HealthStatus
from .link import Link
from .notification_accepted import NotificationAccepted
from .notification_request import NotificationRequest
from .notification_request_context import NotificationRequestContext
from .notification_request_severity import NotificationRequestSeverity
from .notify_response_400 import NotifyResponse400
from .problem import Problem

__all__ = (
    "Health",
    "HealthStatus",
    "Link",
    "NotificationAccepted",
    "NotificationRequest",
    "NotificationRequestContext",
    "NotificationRequestSeverity",
    "NotifyResponse400",
    "Problem",
)

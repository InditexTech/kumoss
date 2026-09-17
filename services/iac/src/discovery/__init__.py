# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Per-cloud scope discovery for the import endpoints."""

from __future__ import annotations

from ._base import DiscoveryError
from .factory import ScopeDiscovery

__all__ = [
    "DiscoveryError",
    "ScopeDiscovery",
]

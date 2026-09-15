# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Exceptions raised by the IaC reference implementation."""

from __future__ import annotations


class ConfigError(ValueError):
    """Raised when the resolved service configuration is unusable."""

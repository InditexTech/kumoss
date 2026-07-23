# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from dataclasses import dataclass


@dataclass(frozen=True)
class WorkspaceFacts:
    """Value object: write-once workspace fields captured at session creation."""

    uri: str
    branch: str
    root_path: str

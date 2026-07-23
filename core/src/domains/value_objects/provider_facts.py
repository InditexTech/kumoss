# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from dataclasses import dataclass

from src.shared.constants import TerraformProvider


@dataclass(frozen=True)
class ProviderFacts:
    """Value object: write-once terraform-provider fields captured at creation."""

    provider: TerraformProvider
    scope_id: str

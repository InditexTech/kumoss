# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from dataclasses import dataclass


@dataclass(frozen=True)
class TerraformDoc:
    """Value object: one resource or data source page of a provider version's registry docs."""

    source: str  # `<namespace>/<name>`, e.g. `hashicorp/aws`
    version: str  # the exact provider version the page belongs to
    resource_type: str
    url: str
    content: str  # the page markdown, frontmatter removed

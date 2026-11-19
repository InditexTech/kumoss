# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from dataclasses import dataclass

from src.shared.constants import SCOPED_PROVIDERS


@dataclass(frozen=True)
class ProviderScope:
    """Value object: a Terraform provider a session runs with, and where.

    ``provider`` is the provider type name (``azurerm``, ``google``,
    ``random``...). ``scope_id`` is the subscription, project, account or
    compartment it targets, set only for providers the platform scopes
    (``SCOPED_PROVIDERS``); None for the others, which run on whatever the
    IaC service's own credentials and the module's configuration select.
    """

    provider: str
    scope_id: str | None = None

    @property
    def scoped(self) -> bool:
        return self.provider in SCOPED_PROVIDERS

# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from abc import ABC, abstractmethod
from collections.abc import Mapping

from src.domains.value_objects.manifest import JsonValue, RootModuleRef


class IManifestSecretStore(ABC):
    """Keeps the values of a root module's sensitive variables out of its repository.

    Keyed by the module's identity (repository and path), so every clone
    and every branch of the repository share the same values.
    """

    @abstractmethod
    async def load(self, module: RootModuleRef) -> dict[str, JsonValue]:
        """The module's secret values by variable name; empty when none are stored."""

    @abstractmethod
    async def save(
        self, module: RootModuleRef, values: Mapping[str, JsonValue]
    ) -> None:
        """Replace the module's secret values; an empty mapping removes them."""

# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from abc import ABC, abstractmethod
from pathlib import Path

from src.domains.value_objects.terraform_requirements import TerraformRequirements


class IConfigInspector(ABC):
    """Discovers what a Terraform root module needs from its code alone."""

    @abstractmethod
    async def inspect(self, directory: Path) -> TerraformRequirements:
        """Statically read the root module checked out at ``directory``.

        Nothing is initialized, downloaded or executed against a cloud.

        Raises:
            InvalidRootModulePath: When ``directory`` is not a Terraform module.
            ConfigInspectionError: When the configuration cannot be parsed.
        """

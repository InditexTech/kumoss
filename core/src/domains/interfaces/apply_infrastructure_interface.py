# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from abc import ABC, abstractmethod


class IApplyInfrastructure(ABC):
    @abstractmethod
    async def apply(self, terraform_targets: list[str]) -> None:
        """Applies the current changes, if any. The operation is performed on the default Git branch.

        :param terraform_targets: A list of Terraform resource targets to filter when applying.
        """
        pass

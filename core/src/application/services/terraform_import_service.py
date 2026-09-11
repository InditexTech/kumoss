# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from src.domains.dto import TerraformValidationDTO
from src.domains.interfaces import ITerraform
from src.shared.constants import TerraformProvider
from src.shared.logger import logging


class TerraformImportService:
    def __init__(
        self,
        import_provider: ITerraform,
    ):
        self.__import_prv = import_provider

    async def get_unmanaged_resources(
        self,
        scope_id: str,
        terraform_provider: TerraformProvider,
    ) -> list[str]:
        managed_res = await self.__import_prv.state_resource_ids()

        logging.info(f"Managed resources for scope {scope_id}: {managed_res}")

        scope_res = await self.__import_prv.scope_resource_ids(
            scope_id=scope_id,
            terraform_provider=terraform_provider,
        )
        logging.info(f"Scope resources for scope {scope_id}: {scope_res}")

        unmanaged_res = sorted(set(scope_res) - set(managed_res))
        logging.info(f"Unmanaged resources for scope {scope_id}: {unmanaged_res}")
        return unmanaged_res

    async def import_resources(
        self,
        imports: list[tuple[str, str]],
    ) -> list[TerraformValidationDTO]:
        results: list[TerraformValidationDTO] = []
        for address, resource_id in imports:
            result = await self.__import_prv.import_resource(
                address=address,
                resource_id=resource_id,
            )
            results.append(result)
            if not result.validation:
                logging.warning(
                    f"Import failed for {address} ({resource_id}): {result.feedback}"
                )
        return results

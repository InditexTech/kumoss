# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from src.domains.dto import (
    TerraformDiscoveryDTO,
    TerraformImportAttempt,
    TerraformImportDTO,
)
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
    ) -> TerraformDiscoveryDTO:
        """Diff the cloud scope against the Terraform state.

        Returns the unmanaged resource IDs and, when there are none, why:
        the three ways a round can find nothing to import — the cloud
        query failed, the scope holds nothing importable, or every
        resource in it is already managed — stay separate outcomes for
        the caller to report, not one empty list.
        """
        state = await self.__import_prv.state_resource_ids()
        managed_res = state.resource_ids

        logging.debug(f"Managed resources for scope {scope_id}: {managed_res}")

        scope = await self.__import_prv.scope_resource_ids(
            scope_id=scope_id,
            terraform_provider=terraform_provider,
        )
        logging.debug(f"Scope resources for scope {scope_id}: {scope.resource_ids}")

        if scope.feedback:
            logging.warning(f"Listing scope {scope_id} failed: {scope.feedback}")
            return TerraformDiscoveryDTO(
                resource_ids=[],
                feedback=f"The scope {scope_id} could not be listed: {scope.feedback}",
            )
        if not scope.resource_ids:
            return TerraformDiscoveryDTO(
                resource_ids=[],
                feedback=f"The scope {scope_id} holds no importable resource.",
            )

        unmanaged_res = sorted(set(scope.resource_ids) - set(managed_res))
        logging.debug(f"Unmanaged resources for scope {scope_id}: {unmanaged_res}")
        return TerraformDiscoveryDTO(
            resource_ids=unmanaged_res,
            feedback=""
            if unmanaged_res
            else f"Every resource in the scope {scope_id} is already managed.",
        )

    async def import_resources(
        self,
        imports: list[tuple[str, str]],
    ) -> TerraformImportDTO:
        outcome = TerraformImportDTO(imported=[], failed=[])
        for address, resource_id in imports:
            result = await self.__import_prv.import_resource(
                address=address,
                resource_id=resource_id,
            )
            attempt = TerraformImportAttempt(
                address=address,
                resource_id=resource_id,
                error=result.feedback,
            )
            if result.ok:
                outcome.imported.append(attempt)
            else:
                outcome.failed.append(attempt)
                logging.warning(
                    f"Import failed for {address} ({resource_id}): {result.feedback}"
                )
        return outcome

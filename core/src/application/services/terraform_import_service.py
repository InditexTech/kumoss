# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import re
from collections.abc import Callable

from src.domains.dto import (
    TerraformDiscoveryDTO,
    TerraformImportAttempt,
    TerraformImportDTO,
)
from src.domains.interfaces import ITerraform
from src.domains.services.template_service import TemplateOrchestrationService
from src.shared.constants import PromptsLibrary, TerraformProvider
from src.shared.logger import logging


class TerraformImportService:
    _BULLET: re.Pattern[str] = re.compile(r"^\s*[-*]\s+(.+?)\s*$")

    def __init__(
        self,
        import_provider: ITerraform,
        template_service: TemplateOrchestrationService,
    ):
        self.__import_prv = import_provider
        self.__template_svc = template_service

    async def get_unmanaged_resources(
        self,
        scope_id: str,
        terraform_provider: TerraformProvider,
    ) -> TerraformDiscoveryDTO:
        """Diff the cloud scope against the Terraform state.

        Returns the unmanaged resource IDs.

        The exception list is applied here, on every round.

        Azure ARM IDs compare case-insensitively. Every other provider compares
        exactly.
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

        key = self.__comparison_key(terraform_provider)
        seen = {key(rid) for rid in managed_res}
        unmanaged_res: list[str] = []
        for rid in scope.resource_ids:
            if key(rid) not in seen:
                seen.add(key(rid))
                unmanaged_res.append(rid)
        unmanaged_res.sort()
        logging.debug(f"Unmanaged resources for scope {scope_id}: {unmanaged_res}")
        if not unmanaged_res:
            return TerraformDiscoveryDTO(
                resource_ids=[],
                feedback=f"Every resource in the scope {scope_id} is already managed.",
            )

        exceptions = await self.__template_svc.render(PromptsLibrary.IMPORT_EXCEPTIONS)
        withheld = {key(rid) for rid in self.__exception_ids(exceptions.prompt)}
        importable = [rid for rid in unmanaged_res if key(rid) not in withheld]
        excluded = [rid for rid in unmanaged_res if key(rid) in withheld]
        if excluded:
            logging.debug(
                f"Import exceptions withheld for scope {scope_id}: {excluded}"
            )
        return TerraformDiscoveryDTO(
            resource_ids=importable,
            feedback=""
            if importable
            else f"Every unmanaged resource in the scope {scope_id} is on the "
            + "import exception list.",
            excluded=excluded,
        )

    @classmethod
    def __exception_ids(cls, body: str) -> list[str]:
        """Read the resource IDs an import exception list names.

        The list is enforced in code rather than by an agent, so its body
        is parsed: every markdown bullet is one resource ID, optionally in
        backticks, and every other line is prose.
        """
        ids: list[str] = []
        for line in body.splitlines():
            match = cls._BULLET.match(line)
            if match:
                rid = match.group(1).strip().strip("`").strip()
                if rid:
                    ids.append(rid)
        return ids

    @staticmethod
    def __comparison_key(
        terraform_provider: TerraformProvider,
    ) -> Callable[[str], str]:
        if terraform_provider is TerraformProvider.AZURE:
            return str.casefold
        return lambda rid: rid

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

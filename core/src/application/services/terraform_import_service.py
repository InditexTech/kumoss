# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import re
from collections.abc import Callable, Sequence

from src.domains.dto import (
    TerraformDiscoveryDTO,
    TerraformImportAttempt,
    TerraformImportDTO,
)
from src.domains.interfaces import ITerraform
from src.domains.services.template_service import TemplateOrchestrationService
from src.domains.value_objects import ProviderScope
from src.shared.constants import DISCOVERABLE_PROVIDERS, PromptsLibrary
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
        self, scopes: Sequence[ProviderScope]
    ) -> TerraformDiscoveryDTO:
        """Diff the root module's cloud scopes against the Terraform state.

        Every scope of a provider the IaC service can list
        (``DISCOVERABLE_PROVIDERS``) is listed; the unmanaged resource IDs
        of all of them are returned together. A scope that cannot be
        listed is reported in the feedback without hiding the others.

        The exception list is applied here, on every round.

        Azure ARM IDs compare case-insensitively. Every other provider compares
        exactly.
        """
        listable = [
            sc for sc in scopes if sc.scope_id and sc.provider in DISCOVERABLE_PROVIDERS
        ]
        if not listable:
            return TerraformDiscoveryDTO(
                resource_ids=[],
                feedback="The root module uses no provider whose scope can be listed "
                + f"({', '.join(sorted(DISCOVERABLE_PROVIDERS))}).",
            )

        state = await self.__import_prv.state_resource_ids()
        managed_res = state.resource_ids
        logging.debug(f"Managed resources: {managed_res}")

        unmanaged: dict[str, Callable[[str], str]] = {}
        problems: list[str] = []
        listed_any = False
        for sc in listable:
            label = f"{sc.provider} scope {sc.scope_id}"
            listed = await self.__import_prv.scope_resource_ids(sc)
            logging.debug(f"Resources in {label}: {listed.resource_ids}")
            if listed.feedback:
                logging.warning(f"Listing {label} failed: {listed.feedback}")
                problems.append(f"The {label} could not be listed: {listed.feedback}")
                continue
            listed_any = listed_any or bool(listed.resource_ids)
            key = self.__comparison_key(sc.provider)
            seen = {key(rid) for rid in managed_res}
            for rid in listed.resource_ids:
                if key(rid) not in seen and rid not in unmanaged:
                    seen.add(key(rid))
                    unmanaged[rid] = key
        unmanaged_res = sorted(unmanaged)
        logging.debug(f"Unmanaged resources: {unmanaged_res}")
        scopes_text = ", ".join(f"{sc.provider} {sc.scope_id}" for sc in listable)
        if not unmanaged_res:
            if len(problems) < len(listable):
                problems.append(
                    f"Every resource in the scopes ({scopes_text}) is already managed."
                    if listed_any
                    else f"The scopes ({scopes_text}) hold no importable resource."
                )
            return TerraformDiscoveryDTO(resource_ids=[], feedback=" ".join(problems))

        exceptions = await self.__template_svc.render(PromptsLibrary.IMPORT_EXCEPTIONS)
        exception_ids = self.__exception_ids(exceptions.prompt)
        withheld = {
            rid
            for rid, key in unmanaged.items()
            if key(rid) in {key(e) for e in exception_ids}
        }
        importable = [rid for rid in unmanaged_res if rid not in withheld]
        excluded = [rid for rid in unmanaged_res if rid in withheld]
        if excluded:
            logging.debug(f"Import exceptions withheld: {excluded}")
        if not importable:
            problems.append(
                f"Every unmanaged resource in the scopes ({scopes_text}) is on the "
                + "import exception list."
            )
        return TerraformDiscoveryDTO(
            resource_ids=importable,
            feedback=" ".join(problems),
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
    def __comparison_key(provider: str) -> Callable[[str], str]:
        if provider == "azurerm":
            return str.casefold
        return lambda rid: rid

    async def import_resources(
        self,
        imports: list[TerraformImportAttempt],
    ) -> TerraformImportDTO:
        outcome = TerraformImportDTO.empty()
        for r in imports:
            result = await self.__import_prv.import_resource(
                address=r.address,
                resource_id=r.resource_id,
            )
            attempt = TerraformImportAttempt(
                address=r.address,
                resource_id=r.resource_id,
                listed_id=r.listed_id,
                error=result.feedback,
            )
            if result.ok:
                outcome.imported.add(attempt)
            else:
                outcome.failed.add(attempt)
                logging.warning(
                    f"Import failed for {r.address} ({r.resource_id}): {result.feedback}"
                )
        return outcome

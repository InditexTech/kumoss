# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Azure subscription contents through Resource Graph."""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, ClassVar

import httpx
from azure.core.credentials import TokenCredential
from azure.identity import (
    CertificateCredential,
    ClientAssertionCredential,
    ClientSecretCredential,
    ManagedIdentityCredential,
    WorkloadIdentityCredential,
)

from .base import CloudApi, DiscoveryError, as_list, as_mapping, as_text

logger = logging.getLogger("iac.discovery.azure")


class AzureCredentials:
    """The azure-identity credential the ARM_* variables select."""

    _SCOPE: ClassVar[str] = "https://management.azure.com/.default"
    _TRUTHY: ClassVar[frozenset[str]] = frozenset({"true", "1", "yes", "on"})

    def __init__(self, environ: Mapping[str, str]) -> None:
        self._environ: Mapping[str, str] = environ

    async def token(self) -> str:
        return await asyncio.to_thread(self._token)

    def _token(self) -> str:
        try:
            credential = self.resolve()
        except DiscoveryError:
            raise
        except Exception as exc:
            raise DiscoveryError(f"Azure credentials are misconfigured: {exc}") from exc
        try:
            access = credential.get_token(self._SCOPE)
        except Exception as exc:
            raise DiscoveryError(f"Azure token request failed: {exc}") from exc
        return access.token

    def resolve(self) -> TokenCredential:
        tenant_id = self._environ.get("ARM_TENANT_ID", "")
        client_id = self._environ.get("ARM_CLIENT_ID", "")
        if self._truthy("ARM_USE_MSI"):
            return ManagedIdentityCredential(client_id=client_id or None)
        if self._truthy("ARM_USE_AKS_WORKLOAD_IDENTITY"):
            return WorkloadIdentityCredential(
                tenant_id=tenant_id,
                client_id=client_id,
                token_file_path=self._environ.get("AZURE_FEDERATED_TOKEN_FILE", ""),
            )
        assertion = self._assertion()
        if assertion is not None:
            return ClientAssertionCredential(
                tenant_id=tenant_id, client_id=client_id, func=assertion
            )
        certificate = self._environ.get("ARM_CLIENT_CERTIFICATE_PATH")
        if certificate:
            return CertificateCredential(
                tenant_id=tenant_id,
                client_id=client_id,
                certificate_path=certificate,
                password=self._environ.get("ARM_CLIENT_CERTIFICATE_PASSWORD"),
            )
        secret = self._environ.get("ARM_CLIENT_SECRET")
        if secret:
            return ClientSecretCredential(
                tenant_id=tenant_id, client_id=client_id, client_secret=secret
            )
        raise DiscoveryError(
            "no Azure credentials configured for scope discovery; "
            + "set ARM_* per PROVIDERS.md"
        )

    def _assertion(self) -> Callable[[], str] | None:
        if not self._truthy("ARM_USE_OIDC"):
            return None
        token = self._environ.get("ARM_OIDC_TOKEN")
        if token:
            return lambda: token
        path = self._environ.get("ARM_OIDC_TOKEN_FILE_PATH")
        if path:
            return lambda: Path(path).read_text(encoding="utf-8").strip()
        return None

    def _truthy(self, name: str) -> bool:
        return self._environ.get(name, "").strip().lower() in self._TRUTHY


class AzureScopeLister:
    """Resource Graph rows belonging to the requested subscription."""

    _SCOPE: ClassVar[re.Pattern[str]] = re.compile(
        r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
        re.IGNORECASE,
    )
    _ENDPOINT: ClassVar[str] = (
        "https://management.azure.com/providers/Microsoft.ResourceGraph"
        "/resources?api-version=2022-10-01"
    )
    _SOURCE: ClassVar[str] = "Resource Graph"
    _TRUNCATED: ClassVar[frozenset[str]] = frozenset({"true", "1", "yes", "on"})
    _PAGE_SIZE: ClassVar[int] = 1000
    _PAGE_CAP: ClassVar[int] = 100
    _GROUP_TYPE: ClassVar[str] = "microsoft.resources/subscriptions/resourcegroups"
    _ROLE_TYPE: ClassVar[str] = "microsoft.authorization/roleassignments"
    _ALERT_TYPE: ClassVar[str] = "microsoft.alertsmanagement/smartdetectoralertrules"

    def __init__(self, environ: Mapping[str, str], client: httpx.AsyncClient) -> None:
        self._credentials: AzureCredentials = AzureCredentials(environ)
        self._client: httpx.AsyncClient = client

    async def list_resource_ids(self, scope_id: str) -> list[str]:
        if self._SCOPE.fullmatch(scope_id) is None:
            raise DiscoveryError(f"'{scope_id}' is not an Azure subscription id")
        api = CloudApi(self._client, self._SOURCE, await self._credentials.token())
        query = self.query(scope_id)
        ids: list[str] = []
        found = 0
        skip_token: str | None = None
        for page in range(1, self._PAGE_CAP + 1):
            options: dict[str, Any] = {"$top": self._PAGE_SIZE}
            if skip_token is not None:
                options["$skipToken"] = skip_token
            document = await api.post(
                self._ENDPOINT,
                {
                    "query": query,
                    "subscriptions": [scope_id],
                    "options": options,
                },
            )
            rows = as_list(document.get("data"))
            found += len(rows)
            ids.extend(self._rows(rows))
            skip_token = self._skip_token(document)
            if skip_token is None:
                if self._truncated(document):
                    raise DiscoveryError(
                        f"Resource Graph truncated the result set for {scope_id}"
                    )
                logger.info(
                    "azure discovery scope=%s pages=%d found=%d kept=%d",
                    scope_id,
                    page,
                    found,
                    len(ids),
                )
                return ids
        raise DiscoveryError(
            f"Resource Graph returned more than {self._PAGE_CAP} pages for {scope_id}"
        )

    def query(self, scope_id: str) -> str:
        scope = self._escape(scope_id)
        return "\n".join(
            [
                "resources",
                f"| where subscriptionId =~ '{scope}'",
                f"| where type != '{self._ALERT_TYPE}'",
                "| where tostring(tags) !contains '\"hidden-link'",
                *self._unmanaged(""),
                "| project id",
                "| union (",
                "    resourcecontainers",
                f"    | where type =~ '{self._GROUP_TYPE}'",
                f"    | where subscriptionId =~ '{scope}'",
                "    | where isempty(managedBy) and name !startswith 'MC_'"
                + " and name !~ 'NetworkWatcherRG'",
                "    | project id",
                ")",
                "| union (",
                "    authorizationresources",
                f"    | where type =~ '{self._ROLE_TYPE}'",
                f"    | where subscriptionId =~ '{scope}'",
                *self._unmanaged("    "),
                "    | project id",
                ")",
                "| order by id asc",
            ]
        )

    def _unmanaged(self, indent: str) -> list[str]:
        return [
            f"{indent}| extend managedGroup = tolower(resourceGroup)",
            f"{indent}| join kind=leftouter (",
            f"{indent}    resourcecontainers",
            f"{indent}    | where type =~ '{self._GROUP_TYPE}'",
            f"{indent}    | where isnotempty(managedBy) or name startswith 'MC_'"
            + " or name =~ 'NetworkWatcherRG'",
            f"{indent}    | project subscriptionId, managedGroup = tolower(name),"
            + " managedMark = 1",
            f"{indent}) on subscriptionId, managedGroup",
            f"{indent}| where isnull(managedMark)",
        ]

    def _escape(self, scope_id: str) -> str:
        return scope_id.replace("\\", "\\\\").replace("'", "\\'")

    def _rows(self, rows: list[Any]) -> list[str]:
        kept: list[str] = []
        for row in rows:
            identifier = as_text(as_mapping(row).get("id"))
            if identifier:
                kept.append(identifier)
        return kept

    def _skip_token(self, document: dict[str, Any]) -> str | None:
        return as_text(document.get("$skipToken")) or None

    def _truncated(self, document: dict[str, Any]) -> bool:
        value: Any = document.get("resultTruncated")
        if isinstance(value, bool):
            return value
        return as_text(value).strip().lower() in self._TRUNCATED

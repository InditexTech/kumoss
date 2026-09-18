# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""GCP project contents through Cloud Asset Inventory."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any, ClassVar
from urllib.parse import quote

import google.auth
import httpx
from google.auth import impersonated_credentials
from google.auth.credentials import Credentials
from google.auth.exceptions import GoogleAuthError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials as StaticCredentials

from ..exceptions import DiscoveryError
from ._base import CloudApi, as_list, as_mapping, as_text

logger = logging.getLogger("iac.discovery.gcp")


class GoogleCredentials:
    """The google-auth credential the GOOGLE_* variables select."""

    _SCOPES: ClassVar[tuple[str, ...]] = (
        "https://www.googleapis.com/auth/cloud-platform",
    )

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
            raise DiscoveryError(
                f"Google credentials are misconfigured: {exc}"
            ) from exc
        if not credential.valid:
            try:
                credential.refresh(Request())  # pyright: ignore[reportUnknownMemberType]
            except Exception as exc:
                raise DiscoveryError(f"Google token request failed: {exc}") from exc
        token: Any = credential.token
        if not isinstance(token, str) or not token:
            raise DiscoveryError("Google credentials produced no access token")
        return token

    def resolve(self) -> Credentials:
        base = self._base()
        target = self._environ.get("GOOGLE_IMPERSONATE_SERVICE_ACCOUNT")
        if not target:
            return base
        return impersonated_credentials.Credentials(
            source_credentials=base,
            target_principal=target,
            target_scopes=list(self._SCOPES),
        )

    def _base(self) -> Credentials:
        token = self._environ.get("GOOGLE_OAUTH_ACCESS_TOKEN")
        if token:
            return StaticCredentials(token=token)
        raw = self._environ.get("GOOGLE_CREDENTIALS")
        if raw:
            return self._from_value(raw)
        try:
            credential, _ = google.auth.default(scopes=list(self._SCOPES))  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        except GoogleAuthError as exc:
            raise DiscoveryError(
                "no Google credentials configured for scope discovery; "
                + "set GOOGLE_* per PROVIDERS.md"
            ) from exc
        return credential  # pyright: ignore[reportUnknownVariableType]

    def _from_value(self, raw: str) -> Credentials:
        if self._is_file(raw):
            credential, _ = google.auth.load_credentials_from_file(  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
                raw, scopes=list(self._SCOPES)
            )
            return credential  # pyright: ignore[reportUnknownVariableType]
        try:
            info: Any = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise DiscoveryError(
                "GOOGLE_CREDENTIALS is neither a readable file nor JSON content"
            ) from exc
        if not isinstance(info, dict):
            raise DiscoveryError("GOOGLE_CREDENTIALS is not a JSON object")
        credential, _ = google.auth.load_credentials_from_dict(  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
            info, scopes=list(self._SCOPES)
        )
        return credential  # pyright: ignore[reportUnknownVariableType]

    def _is_file(self, raw: str) -> bool:
        try:
            return Path(raw).is_file()
        except OSError:
            return False


class GcpScopeLister:
    """Cloud Asset Inventory assets plus project IAM bindings."""

    _SCOPE: ClassVar[re.Pattern[str]] = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")
    _CRM: ClassVar[str] = "https://cloudresourcemanager.googleapis.com/v1/projects/"
    _CAI: ClassVar[str] = "https://cloudasset.googleapis.com/v1/projects/"
    _ASSET_SOURCE: ClassVar[str] = "Cloud Asset Inventory"
    _PROJECT_SOURCE: ClassVar[str] = "Resource Manager"
    _READ_MASK: ClassVar[str] = "name,assetType,labels"
    _PAGE_SIZE: ClassVar[int] = 500
    _PAGE_CAP: ClassVar[int] = 200
    _PROJECT_TYPES: ClassVar[frozenset[str]] = frozenset(
        {
            "cloudresourcemanager.googleapis.com/Project",
            "compute.googleapis.com/Project",
        }
    )
    _BUCKET_TYPE: ClassVar[str] = "storage.googleapis.com/Bucket"
    _LABEL_PREFIX: ClassVar[str] = "goog-"
    _NAME_PREFIX: ClassVar[str] = "gke-"
    _STAGING_PREFIXES: ClassVar[tuple[str, ...]] = (
        "dataproc-staging-",
        "dataproc-temp-",
        "gcf-sources-",
        "gcf-v2-",
        "run-sources-",
    )
    _STAGING_SUFFIX: ClassVar[str] = "_cloudbuild"

    def __init__(self, environ: Mapping[str, str], client: httpx.AsyncClient) -> None:
        self._credentials: GoogleCredentials = GoogleCredentials(environ)
        self._client: httpx.AsyncClient = client

    async def list_resource_ids(self, scope_id: str) -> list[str]:
        if self._SCOPE.fullmatch(scope_id) is None:
            raise DiscoveryError(f"'{scope_id}' is not a GCP project id")
        token = await self._credentials.token()
        assets = CloudApi(self._client, self._ASSET_SOURCE, token)
        projects = CloudApi(self._client, self._PROJECT_SOURCE, token)
        number = await self._project_number(projects, scope_id)
        ids, pages, found = await self._assets(assets, scope_id, number)
        policy = await projects.post(
            f"{self._CRM}{quote(scope_id, safe='')}:getIamPolicy",
            {"options": {"requestedPolicyVersion": 3}},
        )
        bindings = self._iam_ids(policy, scope_id)
        ids.extend(bindings)
        logger.info(
            "gcp discovery scope=%s pages=%d found=%d iam=%d kept=%d",
            scope_id,
            pages,
            found,
            len(bindings),
            len(ids),
        )
        return ids

    async def _project_number(self, api: CloudApi, scope_id: str) -> str:
        document = await api.get(f"{self._CRM}{quote(scope_id, safe='')}")
        return as_text(document.get("projectNumber"))

    async def _assets(
        self, api: CloudApi, scope_id: str, number: str
    ) -> tuple[list[str], int, int]:
        url = f"{self._CAI}{quote(scope_id, safe='')}:searchAllResources"
        ids: list[str] = []
        found = 0
        page_token: str | None = None
        for page in range(1, self._PAGE_CAP + 1):
            params = {"pageSize": str(self._PAGE_SIZE), "readMask": self._READ_MASK}
            if page_token is not None:
                params["pageToken"] = page_token
            document = await api.get(url, params)
            assets = as_list(document.get("results"))
            found += len(assets)
            ids.extend(self._kept(assets, scope_id, number))
            page_token = as_text(document.get("nextPageToken")) or None
            if page_token is None:
                return ids, page, found
        raise DiscoveryError(
            f"Cloud Asset Inventory returned more than {self._PAGE_CAP} pages"
            + f" for {scope_id}"
        )

    def _kept(self, assets: list[Any], scope_id: str, number: str) -> list[str]:
        kept: list[str] = []
        for asset in assets:
            entry = as_mapping(asset)
            name = as_text(entry.get("name"))
            if not name:
                continue
            if self._excluded(
                as_text(entry.get("assetType")), name, as_mapping(entry.get("labels"))
            ):
                continue
            kept.append(self._normalize(name, scope_id, number))
        return kept

    def _excluded(self, asset_type: str, name: str, labels: dict[str, Any]) -> bool:
        if asset_type in self._PROJECT_TYPES:
            return True
        if any(key.startswith(self._LABEL_PREFIX) for key in labels):
            return True
        leaf = name.rsplit("/", 1)[-1]
        if leaf.startswith(self._NAME_PREFIX):
            return True
        return asset_type == self._BUCKET_TYPE and (
            leaf.startswith(self._STAGING_PREFIXES)
            or leaf.endswith(self._STAGING_SUFFIX)
        )

    def _normalize(self, name: str, scope_id: str, number: str) -> str:
        trimmed = name
        if trimmed.startswith("//"):
            trimmed = trimmed[2:].partition("/")[2]
        if not number:
            return trimmed
        trimmed = trimmed.replace(f"projects/{number}/", f"projects/{scope_id}/")
        if trimmed.endswith(f"projects/{number}"):
            trimmed = f"{trimmed.removesuffix(number)}{scope_id}"
        return trimmed

    def _iam_ids(self, policy: dict[str, Any], scope_id: str) -> list[str]:
        ids: list[str] = []
        for binding in as_list(policy.get("bindings")):
            entry = as_mapping(binding)
            role = as_text(entry.get("role"))
            if not role:
                continue
            for raw in as_list(entry.get("members")):
                member = as_text(raw)
                if member and self._kept_member(member, scope_id):
                    ids.append(f"{scope_id} {role} {member}")
        return ids

    def _kept_member(self, member: str, scope_id: str) -> bool:
        if member.startswith("deleted:"):
            return False
        if not member.startswith("serviceAccount:"):
            return True
        address = member.removeprefix("serviceAccount:")
        if not address.endswith(".gserviceaccount.com"):
            return True
        return address.endswith(f"@{scope_id}.iam.gserviceaccount.com")

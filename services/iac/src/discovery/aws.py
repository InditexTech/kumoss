# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""AWS account contents through Resource Explorer."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Mapping
from typing import Any, ClassVar

import boto3  # pyright: ignore[reportMissingTypeStubs]
from botocore.config import Config as BotoConfig  # pyright: ignore[reportMissingTypeStubs]
from botocore.exceptions import (  # pyright: ignore[reportMissingTypeStubs]
    BotoCoreError,
    ClientError,
)

from .base import DiscoveryError, as_list, as_mapping, as_text

logger = logging.getLogger("iac.discovery.aws")


class AwsScopeLister:
    """Resource Explorer rows for the account the credentials belong to."""

    _PAGE_SIZE: ClassVar[int] = 500
    _PAGE_CAP: ClassVar[int] = 200
    _CONNECT_TIMEOUT: ClassVar[int] = 10
    _READ_TIMEOUT: ClassVar[int] = 60
    _EXCLUDED_TYPES: ClassVar[frozenset[str]] = frozenset({"ec2:network-interface"})
    _MANAGED_TAG_PREFIXES: ClassVar[tuple[str, ...]] = (
        "aws:",
        "eks:",
        "kubernetes.io/",
        "k8s.io/",
        "alpha.eksctl.io/",
        "elbv2.k8s.aws/",
        "ingress.k8s.aws/",
        "service.k8s.aws/",
    )
    _MANAGED_ROLE_PATHS: ClassVar[tuple[str, ...]] = (
        ":role/aws-service-role/",
        ":role/aws-reserved/sso.amazonaws.com/",
    )

    def __init__(
        self,
        environ: Mapping[str, str],
        session_factory: Callable[[], Any] | None = None,
    ) -> None:
        self._environ: Mapping[str, str] = environ
        self._session_factory: Callable[[], Any] = (
            boto3.Session if session_factory is None else session_factory
        )

    async def list_resource_ids(self, scope_id: str) -> list[str]:
        return await asyncio.to_thread(self._list, scope_id)

    def _list(self, scope_id: str) -> list[str]:
        region = self._environ.get("AWS_REGION") or self._environ.get(
            "AWS_DEFAULT_REGION"
        )
        if not region:
            raise DiscoveryError("AWS_REGION is not set")
        try:
            session: Any = self._session_factory()
        except DiscoveryError:
            raise
        except Exception as exc:
            raise DiscoveryError(f"AWS session setup failed: {exc}") from exc
        self._check_account(session, region, scope_id)
        explorer, view_arn = self._view(session, region, scope_id)
        return self._resources(explorer, view_arn, scope_id)

    def _client(self, session: Any, service: str, region: str) -> Any:
        try:
            return session.client(
                service,
                region_name=region,
                config=BotoConfig(
                    connect_timeout=self._CONNECT_TIMEOUT,
                    read_timeout=self._READ_TIMEOUT,
                ),
            )
        except DiscoveryError:
            raise
        except Exception as exc:
            raise DiscoveryError(
                f"AWS client setup failed for {service}: {exc}"
            ) from exc

    def _check_account(self, session: Any, region: str, scope_id: str) -> None:
        sts = self._client(session, "sts", region)
        identity = self._call(sts.get_caller_identity, "STS GetCallerIdentity")
        account: Any = identity.get("Account")
        if account != scope_id:
            raise DiscoveryError(
                f"AWS credentials belong to account {account}, not {scope_id}"
            )

    def _view(self, session: Any, region: str, scope_id: str) -> tuple[Any, str]:
        local = self._client(session, "resource-explorer-2", region)
        indexes = self._call(
            lambda: local.list_indexes(Type="AGGREGATOR"),
            "Resource Explorer ListIndexes",
        )
        entries = as_list(indexes.get("Indexes"))
        if not entries:
            raise DiscoveryError(self._not_enabled(scope_id))
        explorer = self._client(
            session,
            "resource-explorer-2",
            as_text(as_mapping(entries[0]).get("Region")) or region,
        )
        view = self._call(explorer.get_default_view, "Resource Explorer GetDefaultView")
        view_arn = as_text(view.get("ViewArn"))
        if not view_arn:
            raise DiscoveryError(self._not_enabled(scope_id))
        return explorer, view_arn

    def _resources(self, explorer: Any, view_arn: str, scope_id: str) -> list[str]:
        ids: list[str] = []
        found = 0
        next_token: str | None = None
        for page in range(1, self._PAGE_CAP + 1):
            request: dict[str, Any] = {
                "ViewArn": view_arn,
                "MaxResults": self._PAGE_SIZE,
            }
            if next_token is not None:
                request["NextToken"] = next_token
            response = self._call(
                lambda: explorer.list_resources(**request),
                "Resource Explorer ListResources",
            )
            resources = as_list(response.get("Resources"))
            found += len(resources)
            ids.extend(self._kept(resources, scope_id))
            next_token = as_text(response.get("NextToken")) or None
            if next_token is None:
                logger.info(
                    "aws discovery scope=%s pages=%d found=%d kept=%d",
                    scope_id,
                    page,
                    found,
                    len(ids),
                )
                return ids
        raise DiscoveryError(
            f"Resource Explorer returned more than {self._PAGE_CAP} pages"
            + f" for {scope_id}"
        )

    def _not_enabled(self, scope_id: str) -> str:
        return (
            f"AWS Resource Explorer is not enabled for account {scope_id}: "
            "create an aggregator index and a default view; see README"
        )

    def _call(self, operation: Callable[[], Any], source: str) -> dict[str, Any]:
        try:
            response: Any = operation()
        except ClientError as exc:
            raise DiscoveryError(f"{source} failed: {self._reason(exc)}") from exc
        except BotoCoreError as exc:
            raise DiscoveryError(f"{source} failed: {exc}") from exc
        return as_mapping(response)

    def _reason(self, exc: ClientError) -> str:
        error = as_mapping(as_mapping(exc.response).get("Error"))
        code = as_text(error.get("Code"))
        message = as_text(error.get("Message"))
        return f"{code}: {message}" if code else str(exc)

    def _kept(self, resources: list[Any], scope_id: str) -> list[str]:
        kept: list[str] = []
        for resource in resources:
            entry = as_mapping(resource)
            arn = as_text(entry.get("Arn"))
            if not arn:
                continue
            if as_text(entry.get("OwningAccountId")) != scope_id:
                continue
            if as_text(entry.get("ResourceType")) in self._EXCLUDED_TYPES:
                continue
            if any(path in arn for path in self._MANAGED_ROLE_PATHS):
                continue
            if self._managed_tags(entry):
                continue
            kept.append(arn)
        return kept

    def _managed_tags(self, resource: dict[str, Any]) -> bool:
        for raw in as_list(resource.get("Properties")):
            prop = as_mapping(raw)
            if as_text(prop.get("Name")) != "tags":
                continue
            for item in as_list(prop.get("Data")):
                key = as_text(as_mapping(item).get("Key"))
                if key.startswith(self._MANAGED_TAG_PREFIXES):
                    return True
        return False

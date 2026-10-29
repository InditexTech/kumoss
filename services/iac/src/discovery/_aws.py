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

from ..exceptions import DiscoveryError
from ._base import as_list, as_mapping, as_text

logger = logging.getLogger("iac.discovery.aws")


class AwsScopeLister:
    """Resource Explorer rows for the account the credentials belong to."""

    _PAGE_SIZE: ClassVar[int] = 500
    _PAGE_CAP: ClassVar[int] = 200
    _CONNECT_TIMEOUT: ClassVar[int] = 10
    _READ_TIMEOUT: ClassVar[int] = 60
    _EXCLUDED_TYPES: ClassVar[frozenset[str]] = frozenset(
        {
            "ec2:network-interface",
            "ec2:security-group-rule",
            "resource-explorer-2:index",
            "resource-explorer-2:view",
        }
    )
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
        ":resource-explorer-2:",
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

    async def verify_account(self, scope_id: str) -> None:
        """Raise DiscoveryError unless the ambient credentials belong to
        account ``scope_id``.

        No environment variable selects an AWS account, so the engine
        runs in whatever account the credentials resolve to; this is the
        check that keeps it from running in a different one.
        """
        _ = await asyncio.to_thread(self._verified_session, scope_id)

    def _list(self, scope_id: str) -> list[str]:
        session, region = self._verified_session(scope_id)
        explorer, view_arn = self._view(session, region, scope_id)
        return self._resources(session, explorer, view_arn, scope_id)

    def _verified_session(self, scope_id: str) -> tuple[Any, str]:
        if not scope_id.isascii() or not scope_id.isdigit() or len(scope_id) != 12:
            raise DiscoveryError(f"'{scope_id}' is not an AWS account id")
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
        return session, region

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

    def _resources(
        self, session: Any, explorer: Any, view_arn: str, scope_id: str
    ) -> list[str]:
        ids: list[str] = []
        found = 0
        next_token: str | None = None
        ec2_defaults_cache: dict[str, set[str]] = {}
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
            ids.extend(self._kept(session, resources, scope_id, ec2_defaults_cache))
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

    def _kept(
        self,
        session: Any,
        resources: list[Any],
        scope_id: str,
        ec2_defaults_cache: dict[str, set[str]],
    ) -> list[str]:
        kept: list[str] = []
        for resource in resources:
            entry = as_mapping(resource)
            arn = as_text(entry.get("Arn"))
            if not arn:
                continue
            if as_text(entry.get("OwningAccountId")) != scope_id:
                continue
            res_type = as_text(entry.get("ResourceType"))
            if res_type in self._EXCLUDED_TYPES:
                continue
            if any(path in arn for path in self._MANAGED_ROLE_PATHS):
                continue
            if self._is_default_memorydb_acl(arn):
                continue
            if self._managed_tags(entry):
                continue
            if self._is_default_managed(entry):
                continue
            if self._is_default_ec2(session, entry, arn, res_type, ec2_defaults_cache):
                continue
            kept.append(arn)
        return kept

    def _is_default_memorydb_acl(self, arn: str) -> bool:
        parts = arn.split(":", 5)
        return (
            len(parts) >= 6 and parts[2] == "memorydb" and parts[5] == "acl/open-access"
        )

    def _is_default_ec2(
        self,
        session: Any,
        entry: dict[str, Any],
        arn: str,
        res_type: str,
        cache: dict[str, set[str]],
    ) -> bool:
        if res_type not in ("ec2:security-group", "ec2:route-table"):
            return False
        region = as_text(entry.get("Region"))
        if not region:
            parts = arn.split(":")
            if len(parts) >= 4 and parts[3]:
                region = parts[3]
        if not region:
            return False
        if region not in cache:
            cache[region] = self._resolve_ec2_defaults(session, region)
        resource_id = arn.rsplit("/", 1)[-1]
        return resource_id in cache[region]

    def _resolve_ec2_defaults(self, session: Any, region: str) -> set[str]:
        ec2 = self._client(session, "ec2", region)
        defaults: set[str] = set()

        sg_resp = self._call(
            lambda: ec2.describe_security_groups(
                Filters=[{"Name": "group-name", "Values": ["default"]}]
            ),
            f"EC2 DescribeSecurityGroups ({region})",
        )
        for sg in as_list(sg_resp.get("SecurityGroups")):
            sg_map = as_mapping(sg)
            group_name = as_text(sg_map.get("GroupName"))
            if group_name and group_name.lower() != "default":
                continue
            sg_id = as_text(sg_map.get("GroupId"))
            if sg_id:
                defaults.add(sg_id)

        rt_resp = self._call(
            lambda: ec2.describe_route_tables(
                Filters=[{"Name": "association.main", "Values": ["true"]}]
            ),
            f"EC2 DescribeRouteTables ({region})",
        )
        for rt in as_list(rt_resp.get("RouteTables")):
            rt_map = as_mapping(rt)
            associations = as_list(rt_map.get("Associations"))
            is_main = any(as_mapping(a).get("Main") is True for a in associations)
            if is_main or not associations:
                rt_id = as_text(rt_map.get("RouteTableId"))
                if rt_id:
                    defaults.add(rt_id)

        return defaults

    def _is_default_managed(self, resource: dict[str, Any]) -> bool:
        res_type = as_text(resource.get("ResourceType"))
        for raw in as_list(resource.get("Properties")):
            prop = as_mapping(raw)
            name = as_text(prop.get("Name"))
            data = prop.get("Data")
            if res_type == "ec2:security-group":
                if (
                    name.lower() in ("group-name", "groupname")
                    and as_text(data).lower() == "default"
                ):
                    return True
                if (
                    name.lower() in ("isdefault", "default")
                    and str(data).lower() == "true"
                ):
                    return True
            elif res_type == "ec2:route-table":
                if (
                    name.lower() in ("main", "association.main", "isdefault")
                    and str(data).lower() == "true"
                ):
                    return True
        return False

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

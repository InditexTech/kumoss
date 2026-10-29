# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""AWS account guard, Resource Explorer paging and managed-resource filtering."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from botocore.exceptions import (  # pyright: ignore[reportMissingTypeStubs]
    ClientError,
    EndpointConnectionError,
    ProfileNotFound,
)

from src.discovery._aws import AwsScopeLister
from src.exceptions import DiscoveryError

ACCOUNT: str = "123456789012"
REGION: dict[str, str] = {"AWS_REGION": "eu-west-1"}
AGGREGATOR: dict[str, Any] = {"Indexes": [{"Region": "eu-west-1"}]}
VIEW: dict[str, Any] = {"ViewArn": "arn:aws:resource-explorer-2:eu-west-1:1:view/all"}


class FakeSts:
    """The identity call, answering with a fixed account."""

    def __init__(self, account: str, error: Exception | None = None) -> None:
        self._account: str = account
        self._error: Exception | None = error

    def get_caller_identity(self) -> dict[str, Any]:
        if self._error is not None:
            raise self._error
        return {"Account": self._account}


class FakeExplorer:
    """Resource Explorer answering from canned pages."""

    def __init__(
        self,
        indexes: dict[str, Any],
        view: dict[str, Any],
        pages: list[dict[str, Any]],
    ) -> None:
        self._indexes: dict[str, Any] = indexes
        self._view: dict[str, Any] = view
        self._pages: list[dict[str, Any]] = pages
        self.requests: list[dict[str, Any]] = []

    def list_indexes(self, **_kwargs: Any) -> dict[str, Any]:
        return self._indexes

    def get_default_view(self) -> dict[str, Any]:
        return self._view

    def list_resources(self, **kwargs: Any) -> dict[str, Any]:
        self.requests.append(kwargs)
        index = int(str(kwargs.get("NextToken", "0")))
        return self._pages[min(index, len(self._pages) - 1)]


class FakeEc2:
    """EC2 client answering DescribeSecurityGroups and DescribeRouteTables."""

    def __init__(
        self,
        security_groups: list[dict[str, Any]] | None = None,
        route_tables: list[dict[str, Any]] | None = None,
    ) -> None:
        self.security_groups: list[dict[str, Any]] = (
            [{"GroupId": "sg-00000000000000001", "GroupName": "default"}]
            if security_groups is None
            else security_groups
        )
        self.route_tables: list[dict[str, Any]] = (
            [
                {
                    "RouteTableId": "rtb-00000000000000001",
                    "Associations": [{"Main": True}],
                }
            ]
            if route_tables is None
            else route_tables
        )
        self.requests: list[tuple[str, dict[str, Any]]] = []

    def describe_security_groups(self, **kwargs: Any) -> dict[str, Any]:
        self.requests.append(("describe_security_groups", kwargs))
        filters = kwargs.get("Filters", [])
        groups = self.security_groups
        for f in filters:
            if f.get("Name") == "group-name":
                vals = f.get("Values", [])
                groups = [sg for sg in groups if sg.get("GroupName") in vals]
        return {"SecurityGroups": groups}

    def describe_route_tables(self, **kwargs: Any) -> dict[str, Any]:
        self.requests.append(("describe_route_tables", kwargs))
        filters = kwargs.get("Filters", [])
        tables = self.route_tables
        for f in filters:
            if f.get("Name") == "association.main":
                vals = [str(v).lower() for v in f.get("Values", [])]
                tables = [
                    rt
                    for rt in tables
                    if any(
                        str(a.get("Main")).lower() in vals
                        for a in rt.get("Associations", [])
                    )
                ]
        return {"RouteTables": tables}


class FakeSession:
    """A boto3 session handing out the three fakes."""

    def __init__(
        self,
        sts: FakeSts,
        explorer: FakeExplorer,
        ec2: FakeEc2 | None = None,
    ) -> None:
        self._sts: FakeSts = sts
        self.explorer: FakeExplorer = explorer
        self.ec2: FakeEc2 = FakeEc2() if ec2 is None else ec2
        self.regions: list[str] = []

    def client(self, service: str, region_name: str, **_kwargs: Any) -> Any:
        self.regions.append(region_name)
        if service == "sts":
            return self._sts
        if service == "ec2":
            return self.ec2
        return self.explorer


def session_for(
    pages: list[dict[str, Any]],
    account: str = ACCOUNT,
    indexes: dict[str, Any] | None = None,
    view: dict[str, Any] | None = None,
    sts_error: Exception | None = None,
    ec2: FakeEc2 | None = None,
) -> FakeSession:
    return FakeSession(
        FakeSts(account, sts_error),
        FakeExplorer(
            AGGREGATOR if indexes is None else indexes,
            VIEW if view is None else view,
            pages,
        ),
        ec2,
    )


def list_ids(
    session: FakeSession,
    environ: dict[str, str] | None = None,
    scope_id: str = ACCOUNT,
) -> list[str]:
    lister = AwsScopeLister(REGION if environ is None else environ, lambda: session)
    return asyncio.run(lister.list_resource_ids(scope_id))


def resource(arn: str, **extra: Any) -> dict[str, Any]:
    return {"Arn": arn, "OwningAccountId": ACCOUNT, **extra}


def tagged(arn: str, key: str) -> dict[str, Any]:
    return resource(
        arn, Properties=[{"Name": "tags", "Data": [{"Key": key, "Value": "x"}]}]
    )


def test_a_missing_region_fails_before_any_call() -> None:
    with pytest.raises(DiscoveryError, match="AWS_REGION is not set"):
        _ = list_ids(session_for([{"Resources": []}]), {})


def test_aws_default_region_is_accepted() -> None:
    session = session_for([{"Resources": [resource("arn:aws:s3:::bucket")]}])
    assert list_ids(session, {"AWS_DEFAULT_REGION": "us-east-1"}) == [
        "arn:aws:s3:::bucket"
    ]


def test_a_broken_session_factory_is_a_discovery_error() -> None:
    def broken_factory() -> Any:
        raise ProfileNotFound(profile="does-not-exist")

    lister = AwsScopeLister(REGION, broken_factory)
    with pytest.raises(DiscoveryError, match="AWS session setup failed"):
        _ = asyncio.run(lister.list_resource_ids(ACCOUNT))


def test_credentials_for_another_account_are_refused() -> None:
    with pytest.raises(DiscoveryError, match="belong to account 999, not 123456789012"):
        _ = list_ids(session_for([{"Resources": []}], account="999"))


def test_verify_account_accepts_the_credentials_own_account() -> None:
    session = session_for([])
    lister = AwsScopeLister(REGION, lambda: session)
    asyncio.run(lister.verify_account(ACCOUNT))
    assert session.regions == ["eu-west-1"]  # STS only, no Resource Explorer


def test_verify_account_refuses_another_account() -> None:
    lister = AwsScopeLister(REGION, lambda: session_for([], account="999"))
    with pytest.raises(DiscoveryError, match="belong to account 999, not 123456789012"):
        asyncio.run(lister.verify_account(ACCOUNT))


def test_an_sts_client_error_names_the_code_and_message() -> None:
    error = ClientError(
        {"Error": {"Code": "AccessDenied", "Message": "not allowed"}},
        "GetCallerIdentity",
    )
    with pytest.raises(
        DiscoveryError,
        match="STS GetCallerIdentity failed: AccessDenied: not allowed",
    ):
        _ = list_ids(session_for([{"Resources": []}], sts_error=error))


def test_a_transport_failure_is_a_discovery_error() -> None:
    error = EndpointConnectionError(endpoint_url="https://sts.eu-west-1.amazonaws.com")
    with pytest.raises(DiscoveryError, match="STS GetCallerIdentity failed:"):
        _ = list_ids(session_for([{"Resources": []}], sts_error=error))


def test_no_aggregator_index_says_resource_explorer_is_off() -> None:
    with pytest.raises(DiscoveryError, match="Resource Explorer is not enabled"):
        _ = list_ids(session_for([{"Resources": []}], indexes={"Indexes": []}))


def test_no_default_view_says_resource_explorer_is_off() -> None:
    with pytest.raises(DiscoveryError, match="create an aggregator index"):
        _ = list_ids(session_for([{"Resources": []}], view={}))


def test_the_explorer_client_moves_to_the_aggregator_region() -> None:
    session = session_for(
        [{"Resources": []}], indexes={"Indexes": [{"Region": "us-east-1"}]}
    )
    _ = list_ids(session)
    assert session.regions == ["eu-west-1", "eu-west-1", "us-east-1"]


def test_paging_follows_the_next_token() -> None:
    pages = [
        {"Resources": [resource("arn:aws:s3:::one")], "NextToken": "1"},
        {"Resources": [resource("arn:aws:s3:::two")]},
    ]
    session = session_for(pages)
    assert list_ids(session) == ["arn:aws:s3:::one", "arn:aws:s3:::two"]
    assert session.explorer.requests[0] == {
        "ViewArn": VIEW["ViewArn"],
        "MaxResults": 500,
    }
    assert session.explorer.requests[1]["NextToken"] == "1"


def test_the_page_cap_fails_the_listing() -> None:
    session = session_for([{"Resources": [], "NextToken": "0"}])
    with pytest.raises(DiscoveryError, match="more than 200 pages"):
        _ = list_ids(session)


@pytest.mark.parametrize(
    "entry",
    [
        pytest.param({"OwningAccountId": ACCOUNT}, id="no-arn"),
        pytest.param(
            {"Arn": "arn:aws:s3:::other", "OwningAccountId": "999"},
            id="another-account",
        ),
        pytest.param(
            resource(
                "arn:aws:ec2:eu-west-1:1:network-interface/eni-1",
                ResourceType="ec2:network-interface",
            ),
            id="service-eni",
        ),
        pytest.param(
            resource("arn:aws:iam::1:role/aws-service-role/eks.amazonaws.com/x"),
            id="service-linked-role",
        ),
        pytest.param(
            resource("arn:aws:iam::1:role/aws-reserved/sso.amazonaws.com/y"),
            id="sso-role",
        ),
        pytest.param(
            tagged(
                "arn:aws:ec2:eu-west-1:1:instance/i-1", "aws:cloudformation:stack-id"
            ),
            id="cloudformation-tagged",
        ),
        pytest.param(
            tagged("arn:aws:ec2:eu-west-1:1:instance/i-2", "eks:cluster-name"),
            id="eks-tagged",
        ),
        pytest.param(
            tagged(
                "arn:aws:ec2:eu-west-1:1:security-group/sg-1",
                "kubernetes.io/cluster/c",
            ),
            id="kubernetes-tagged",
        ),
        pytest.param(
            resource(
                "arn:aws:ec2:eu-west-1:123456789012:security-group-rule/sgr-00000000000000001",
                ResourceType="ec2:security-group-rule",
            ),
            id="security-group-rule",
        ),
        pytest.param(
            resource(
                "arn:aws:ec2:eu-west-1:123456789012:security-group/sg-00000000000000001",
                ResourceType="ec2:security-group",
            ),
            id="default-security-group",
        ),
        pytest.param(
            resource(
                "arn:aws:ec2:eu-west-2:123456789012:route-table/rtb-00000000000000001",
                ResourceType="ec2:route-table",
            ),
            id="default-route-table",
        ),
        pytest.param(
            resource(
                "arn:aws:memorydb:ap-southeast-2:123456789012:acl/open-access",
                ResourceType="memorydb:acl",
            ),
            id="memorydb-open-access-acl",
        ),
        pytest.param(
            resource(
                "arn:aws:resource-explorer-2:us-east-2:123456789012:index/00000000-0000-4000-8000",
                ResourceType="resource-explorer-2:index",
            ),
            id="resource-explorer-index",
        ),
        pytest.param(
            resource(
                "arn:aws:resource-explorer-2:us-east-2:123456789012:view/default",
                ResourceType="resource-explorer-2:view",
            ),
            id="resource-explorer-view",
        ),
    ],
)
def test_managed_resources_are_dropped(entry: dict[str, Any]) -> None:
    assert list_ids(session_for([{"Resources": [entry]}])) == []


def test_user_tags_do_not_exclude_a_resource() -> None:
    entry = tagged("arn:aws:ec2:eu-west-1:1:instance/i-3", "Environment")
    assert list_ids(session_for([{"Resources": [entry]}])) == [
        "arn:aws:ec2:eu-west-1:1:instance/i-3"
    ]


def test_user_custom_security_group_and_route_table_survive() -> None:
    sg = resource(
        "arn:aws:ec2:eu-west-1:123456789012:security-group/sg-custom",
        ResourceType="ec2:security-group",
    )
    rtb = resource(
        "arn:aws:ec2:eu-west-1:123456789012:route-table/rtb-custom",
        ResourceType="ec2:route-table",
    )
    assert list_ids(session_for([{"Resources": [sg, rtb]}])) == [
        "arn:aws:ec2:eu-west-1:123456789012:security-group/sg-custom",
        "arn:aws:ec2:eu-west-1:123456789012:route-table/rtb-custom",
    ]


def test_user_custom_memorydb_acl_survives() -> None:
    acl = resource(
        "arn:aws:memorydb:ap-southeast-2:123456789012:acl/open-access-app",
        ResourceType="memorydb:acl",
    )
    assert list_ids(session_for([{"Resources": [acl]}])) == [
        "arn:aws:memorydb:ap-southeast-2:123456789012:acl/open-access-app"
    ]


def test_ec2_regional_describe_filters_defaults_realistically() -> None:
    sg_default = resource(
        "arn:aws:ec2:eu-west-1:123456789012:security-group/sg-default",
        ResourceType="ec2:security-group",
    )
    sg_custom = resource(
        "arn:aws:ec2:eu-west-1:123456789012:security-group/sg-app",
        ResourceType="ec2:security-group",
    )
    rtb_main = resource(
        "arn:aws:ec2:eu-west-1:123456789012:route-table/rtb-main",
        ResourceType="ec2:route-table",
    )
    rtb_custom = resource(
        "arn:aws:ec2:eu-west-1:123456789012:route-table/rtb-app",
        ResourceType="ec2:route-table",
    )
    fake_ec2 = FakeEc2(
        security_groups=[
            {"GroupId": "sg-default", "GroupName": "default"},
            {"GroupId": "sg-app", "GroupName": "app-sg"},
        ],
        route_tables=[
            {"RouteTableId": "rtb-main", "Associations": [{"Main": True}]},
            {"RouteTableId": "rtb-app", "Associations": [{"Main": False}]},
        ],
    )
    session = session_for(
        [{"Resources": [sg_default, sg_custom, rtb_main, rtb_custom]}],
        ec2=fake_ec2,
    )
    assert list_ids(session) == [
        "arn:aws:ec2:eu-west-1:123456789012:security-group/sg-app",
        "arn:aws:ec2:eu-west-1:123456789012:route-table/rtb-app",
    ]

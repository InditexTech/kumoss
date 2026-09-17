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
from src.discovery._base import DiscoveryError

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


class FakeSession:
    """A boto3 session handing out the two fakes."""

    def __init__(self, sts: FakeSts, explorer: FakeExplorer) -> None:
        self._sts: FakeSts = sts
        self.explorer: FakeExplorer = explorer
        self.regions: list[str] = []

    def client(self, service: str, region_name: str, **_kwargs: Any) -> Any:
        self.regions.append(region_name)
        return self._sts if service == "sts" else self.explorer


def session_for(
    pages: list[dict[str, Any]],
    account: str = ACCOUNT,
    indexes: dict[str, Any] | None = None,
    view: dict[str, Any] | None = None,
    sts_error: Exception | None = None,
) -> FakeSession:
    return FakeSession(
        FakeSts(account, sts_error),
        FakeExplorer(
            AGGREGATOR if indexes is None else indexes,
            VIEW if view is None else view,
            pages,
        ),
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
    ],
)
def test_managed_resources_are_dropped(entry: dict[str, Any]) -> None:
    assert list_ids(session_for([{"Resources": [entry]}])) == []


def test_user_tags_do_not_exclude_a_resource() -> None:
    entry = tagged("arn:aws:ec2:eu-west-1:1:instance/i-3", "Environment")
    assert list_ids(session_for([{"Resources": [entry]}])) == [
        "arn:aws:ec2:eu-west-1:1:instance/i-3"
    ]

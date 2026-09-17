# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Azure credential selection and the Resource Graph query."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from src.discovery import _azure as azure_module
from src.discovery._azure import AzureCredentials, AzurosCloudapi
from src.discovery._base import DiscoveryError

Handler = Callable[[httpx.Request], httpx.Response]

SECRET: dict[str, str] = {
    "ARM_TENANT_ID": "tenant-1",
    "ARM_CLIENT_ID": "client-1",
    "ARM_CLIENT_SECRET": "secret-1",
}

SUBSCRIPTION: str = "3f2504e0-4f89-11d3-9a0c-0305e82c3301"

CREDENTIAL_NAMES: list[str] = [
    "ManagedIdentityCredential",
    "WorkloadIdentityCredential",
    "ClientAssertionCredential",
    "CertificateCredential",
    "ClientSecretCredential",
]


def patch_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> list[tuple[str, dict[str, Any]]]:
    calls: list[tuple[str, dict[str, Any]]] = []

    def factory(name: str) -> Callable[..., str]:
        def build(**kwargs: Any) -> str:
            calls.append((name, kwargs))
            return name

        return build

    for name in CREDENTIAL_NAMES:
        monkeypatch.setattr(azure_module, name, factory(name))
    return calls


def patch_token(monkeypatch: pytest.MonkeyPatch) -> None:
    async def token(_self: AzureCredentials) -> str:
        return "token-1"

    monkeypatch.setattr(AzureCredentials, "token", token)


def list_ids(handler: Handler, environ: dict[str, str], scope_id: str) -> list[str]:
    async def call() -> list[str]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await AzurosCloudapi(environ, client).list_resource_ids(scope_id)

    return asyncio.run(call())


@pytest.mark.parametrize(
    ("environ", "expected"),
    [
        pytest.param({"ARM_USE_MSI": "true"}, "ManagedIdentityCredential", id="msi"),
        pytest.param(
            {"ARM_USE_AKS_WORKLOAD_IDENTITY": "1", **SECRET},
            "WorkloadIdentityCredential",
            id="workload-identity",
        ),
        pytest.param(
            {"ARM_USE_OIDC": "yes", "ARM_OIDC_TOKEN": "assertion", **SECRET},
            "ClientAssertionCredential",
            id="oidc-token",
        ),
        pytest.param(
            {"ARM_CLIENT_CERTIFICATE_PATH": "/certs/spn.pfx", **SECRET},
            "CertificateCredential",
            id="certificate",
        ),
        pytest.param(dict(SECRET), "ClientSecretCredential", id="client-secret"),
        pytest.param(
            {"ARM_USE_OIDC": "on", **SECRET},
            "ClientSecretCredential",
            id="oidc-without-a-token-falls-through",
        ),
    ],
)
def test_the_environment_selects_the_credential(
    environ: dict[str, str], expected: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = patch_credentials(monkeypatch)
    assert AzureCredentials(environ).resolve() == expected
    assert [name for name, _ in calls] == [expected]


def test_the_oidc_assertion_reads_the_token_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    calls = patch_credentials(monkeypatch)
    token_file = tmp_path / "token"
    _ = token_file.write_text("file-assertion\n", encoding="utf-8")
    environ = {
        "ARM_USE_OIDC": "true",
        "ARM_OIDC_TOKEN_FILE_PATH": str(token_file),
        **SECRET,
    }

    _ = AzureCredentials(environ).resolve()

    assertion: Callable[[], str] = calls[0][1]["func"]
    assert assertion() == "file-assertion"


def test_no_credentials_is_a_discovery_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _ = patch_credentials(monkeypatch)
    with pytest.raises(DiscoveryError, match="no Azure credentials configured"):
        _ = AzureCredentials({}).resolve()


def test_a_token_failure_is_a_discovery_error(monkeypatch: pytest.MonkeyPatch) -> None:
    class Failing:
        def get_token(self, _scope: str) -> object:
            raise RuntimeError("AADSTS700016")

    def resolve(_self: AzureCredentials) -> object:
        return Failing()

    monkeypatch.setattr(AzureCredentials, "resolve", resolve)
    with pytest.raises(
        DiscoveryError, match="Azure token request failed: AADSTS700016"
    ):
        _ = asyncio.run(AzureCredentials({}).token())


def test_a_partial_environment_becomes_a_discovery_error() -> None:
    credentials = AzureCredentials({"ARM_CLIENT_SECRET": "s"})
    with pytest.raises(DiscoveryError, match="misconfigured"):
        _ = asyncio.run(credentials.token())


@pytest.mark.parametrize(
    "clause",
    [
        "microsoft.alertsmanagement/smartdetectoralertrules",
        "!contains '\"hidden-link",
        "name startswith 'MC_'",
        "NetworkWatcherRG",
        "isnotempty(managedBy)",
        "join kind=leftouter (",
        ") on subscriptionId, managedGroup",
        "where isnull(managedMark)",
        "authorizationresources",
        "microsoft.resources/subscriptions/resourcegroups",
        "order by id asc",
    ],
)
def test_the_query_carries_every_exclusion(clause: str) -> None:
    query = AzurosCloudapi({}, httpx.AsyncClient()).query(SUBSCRIPTION)
    assert clause in query


@pytest.mark.parametrize(
    "rejected",
    ["let ", "kind=leftanti", "kind=leftsemi", "kind=anti"],
)
def test_the_query_avoids_what_resource_graph_cannot_parse(rejected: str) -> None:
    query = AzurosCloudapi({}, httpx.AsyncClient()).query(SUBSCRIPTION)
    assert rejected not in query


def test_the_query_inlines_the_managed_group_lookup() -> None:
    query = AzurosCloudapi({}, httpx.AsyncClient()).query(SUBSCRIPTION)
    assert query.count("join kind=leftouter (") == 2
    assert query.count("    | join kind=leftouter (") == 1
    assert query.count("isnull(managedMark)") == 2
    assert query.count("managedGroup = tolower(name)") == 2


def test_the_query_confines_every_arm_to_the_subscription() -> None:
    query = AzurosCloudapi({}, httpx.AsyncClient()).query(SUBSCRIPTION)
    assert query.count(f"where subscriptionId =~ '{SUBSCRIPTION}'") == 3
    assert f"contains '{SUBSCRIPTION}'" not in query


def test_the_query_escapes_the_scope() -> None:
    query = AzurosCloudapi({}, httpx.AsyncClient()).query("o'brien\\x")
    assert "=~ 'o\\'brien\\\\x'" in query


def test_paging_follows_the_skip_token(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_token(monkeypatch)
    bodies: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body: dict[str, Any] = json.loads(request.content)
        bodies.append(body)
        if "$skipToken" not in body["options"]:
            return httpx.Response(
                200, json={"data": [{"id": "/a"}], "$skipToken": "page-2"}
            )
        return httpx.Response(200, json={"data": [{"id": "/b"}]})

    assert list_ids(handler, {}, SUBSCRIPTION) == ["/a", "/b"]
    assert bodies[0]["options"]["$top"] == 1000
    assert bodies[1]["options"]["$skipToken"] == "page-2"


def test_the_page_cap_fails_the_listing(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_token(monkeypatch)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"id": "/a"}], "$skipToken": "more"})

    with pytest.raises(DiscoveryError, match="more than 100 pages"):
        _ = list_ids(handler, {}, SUBSCRIPTION)


def test_an_api_error_carries_status_and_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_token(monkeypatch)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error": {"message": "Forbidden by policy"}})

    with pytest.raises(
        DiscoveryError, match="403 from Resource Graph: Forbidden by policy"
    ):
        _ = list_ids(handler, {}, SUBSCRIPTION)


def test_the_request_names_the_subscription_it_queries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_token(monkeypatch)
    bodies: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"data": [{"id": "/a"}]})

    assert list_ids(handler, {}, SUBSCRIPTION) == ["/a"]
    assert bodies[0]["subscriptions"] == [SUBSCRIPTION]


@pytest.mark.parametrize(
    "scope_id",
    [
        pytest.param("/", id="matches-every-resource-id"),
        pytest.param("e", id="matches-nearly-every-resource-id"),
        pytest.param("sub-1", id="not-a-guid"),
        pytest.param(f"{SUBSCRIPTION}x", id="guid-with-a-tail"),
    ],
)
def test_a_scope_that_is_not_a_subscription_id_reaches_no_api(
    scope_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    patch_token(monkeypatch)
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"data": []})

    with pytest.raises(DiscoveryError, match="is not an Azure subscription id"):
        _ = list_ids(handler, {}, scope_id)

    assert seen == []


@pytest.mark.parametrize(
    "truncated",
    [pytest.param("true", id="string"), pytest.param(True, id="boolean")],
)
def test_a_truncated_result_set_fails_the_listing(
    truncated: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    patch_token(monkeypatch)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"data": [{"id": "/a"}], "resultTruncated": truncated}
        )

    with pytest.raises(DiscoveryError, match="truncated the result set"):
        _ = list_ids(handler, {}, SUBSCRIPTION)


def test_an_untruncated_result_set_is_returned(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_token(monkeypatch)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"data": [{"id": "/a"}], "resultTruncated": "false"}
        )

    assert list_ids(handler, {}, SUBSCRIPTION) == ["/a"]

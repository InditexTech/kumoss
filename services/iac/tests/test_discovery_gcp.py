# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""GCP credential selection, asset filtering and IAM expansion."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from google.auth import impersonated_credentials

from src.discovery._base import DiscoveryError
from src.discovery._gcp import GcpScopeLister, GoogleCredentials

Handler = Callable[[httpx.Request], httpx.Response]

NUMBER: str = "123456789"
EMPTY_POLICY: dict[str, Any] = {"bindings": []}


def patch_token(monkeypatch: pytest.MonkeyPatch) -> None:
    async def token(_self: GoogleCredentials) -> str:
        return "token-1"

    monkeypatch.setattr(GoogleCredentials, "token", token)


def handler_for(
    pages: list[dict[str, Any]],
    policy: dict[str, Any] | None = None,
    number: str = NUMBER,
) -> Handler:
    def handle(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith(":getIamPolicy"):
            return httpx.Response(200, json=policy or EMPTY_POLICY)
        if ":searchAllResources" in url:
            index = int(request.url.params.get("pageToken", "0"))
            return httpx.Response(200, json=pages[index])
        return httpx.Response(200, json={"projectNumber": number})

    return handle


def list_ids(handler: Handler, scope_id: str = "proj-1") -> list[str]:
    async def call() -> list[str]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await GcpScopeLister({}, client).list_resource_ids(scope_id)

    return asyncio.run(call())


def assets(*entries: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"results": list(entries)}]


def recording_handler(seen: list[httpx.Request]) -> Handler:
    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={})

    return handle


def test_a_static_access_token_is_used_as_is() -> None:
    credentials = GoogleCredentials({"GOOGLE_OAUTH_ACCESS_TOKEN": "ya29.static"})
    assert asyncio.run(credentials.token()) == "ya29.static"


def test_inline_json_credentials_that_are_not_json_fail() -> None:
    credentials = GoogleCredentials({"GOOGLE_CREDENTIALS": "not json at all"})
    with pytest.raises(DiscoveryError, match="neither a readable file nor JSON"):
        _ = credentials.resolve()


def test_a_credentials_file_is_loaded_from_disk(tmp_path: Any) -> None:
    path = tmp_path / "sa.json"
    _ = path.write_text(json.dumps({"type": "authorized_user"}), encoding="utf-8")
    credentials = GoogleCredentials({"GOOGLE_CREDENTIALS": str(path)})
    with pytest.raises(Exception, match="authorized_user|refresh_token|fields"):
        _ = credentials.resolve()


def test_no_credentials_is_a_discovery_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    monkeypatch.setenv("GCE_METADATA_HOST", "127.0.0.1:1")
    with pytest.raises(DiscoveryError, match="no Google credentials configured"):
        _ = GoogleCredentials({}).resolve()


def test_a_malformed_credentials_file_is_a_discovery_error(tmp_path: Any) -> None:
    path = tmp_path / "sa.json"
    _ = path.write_text(json.dumps({"type": "authorized_user"}), encoding="utf-8")
    credentials = GoogleCredentials({"GOOGLE_CREDENTIALS": str(path)})
    with pytest.raises(DiscoveryError, match="Google credentials are misconfigured"):
        _ = asyncio.run(credentials.token())


def test_asset_names_lose_the_service_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_token(monkeypatch)
    page = assets(
        {
            "name": "//compute.googleapis.com/projects/proj-1/zones/z/instances/web",
            "assetType": "compute.googleapis.com/Instance",
        }
    )
    assert list_ids(handler_for(page)) == ["projects/proj-1/zones/z/instances/web"]


def test_project_numbers_become_the_project_id(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_token(monkeypatch)
    page = assets(
        {
            "name": f"//run.googleapis.com/projects/{NUMBER}/locations/eu/services/api",
            "assetType": "run.googleapis.com/Service",
        },
        {
            "name": f"//serviceusage.googleapis.com/projects/{NUMBER}",
            "assetType": "serviceusage.googleapis.com/Service",
        },
    )
    assert list_ids(handler_for(page)) == [
        "projects/proj-1/locations/eu/services/api",
        "projects/proj-1",
    ]


@pytest.mark.parametrize(
    "asset",
    [
        pytest.param(
            {
                "name": "//cloudresourcemanager.googleapis.com/projects/proj-1",
                "assetType": "cloudresourcemanager.googleapis.com/Project",
            },
            id="the-project-itself",
        ),
        pytest.param(
            {
                "name": "//compute.googleapis.com/projects/proj-1/zones/z/disks/pvc-1",
                "assetType": "compute.googleapis.com/Disk",
                "labels": {"goog-gke-volume": "true"},
            },
            id="goog-labelled",
        ),
        pytest.param(
            {
                "name": "//compute.googleapis.com/projects/proj-1/global/networks/x",
                "assetType": "compute.googleapis.com/Network",
                "labels": {"goog-terraform-provisioned": "true"},
            },
            id="already-terraform-managed",
        ),
        pytest.param(
            {
                "name": "//compute.googleapis.com/projects/proj-1/zones/z/instances/gke-cluster-pool-abc",
                "assetType": "compute.googleapis.com/Instance",
            },
            id="gke-named",
        ),
        pytest.param(
            {
                "name": "//storage.googleapis.com/dataproc-staging-eu-1-abc",
                "assetType": "storage.googleapis.com/Bucket",
            },
            id="dataproc-staging-bucket",
        ),
        pytest.param(
            {
                "name": "//storage.googleapis.com/proj-1_cloudbuild",
                "assetType": "storage.googleapis.com/Bucket",
            },
            id="cloudbuild-bucket",
        ),
    ],
)
def test_managed_assets_are_dropped(
    asset: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    patch_token(monkeypatch)
    assert list_ids(handler_for(assets(asset))) == []


def test_a_user_bucket_survives(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_token(monkeypatch)
    page = assets(
        {
            "name": "//storage.googleapis.com/my-app-data",
            "assetType": "storage.googleapis.com/Bucket",
        }
    )
    assert list_ids(handler_for(page)) == ["my-app-data"]


def test_paging_follows_the_next_page_token(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_token(monkeypatch)
    pages = [
        {
            "results": [
                {"name": "//storage.googleapis.com/one", "assetType": "x/Bucket"}
            ],
            "nextPageToken": "1",
        },
        {
            "results": [
                {"name": "//storage.googleapis.com/two", "assetType": "x/Bucket"}
            ]
        },
    ]
    assert list_ids(handler_for(pages)) == ["one", "two"]


def test_the_page_cap_fails_the_listing(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_token(monkeypatch)

    def handle(request: httpx.Request) -> httpx.Response:
        if ":searchAllResources" in str(request.url):
            return httpx.Response(200, json={"results": [], "nextPageToken": "more"})
        return httpx.Response(200, json={"projectNumber": NUMBER})

    with pytest.raises(DiscoveryError, match="more than 200 pages"):
        _ = list_ids(handle)


def test_iam_bindings_become_one_id_per_role_and_member(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_token(monkeypatch)
    policy: dict[str, Any] = {
        "bindings": [
            {
                "role": "roles/viewer",
                "members": [
                    "user:ada@example.com",
                    "serviceAccount:app@proj-1.iam.gserviceaccount.com",
                    "serviceAccount:service-1@compute-system.iam.gserviceaccount.com",
                    "deleted:user:gone@example.com",
                ],
            },
            {"role": "roles/editor", "members": ["group:team@example.com"]},
        ]
    }
    assert list_ids(handler_for(assets(), policy)) == [
        "proj-1 roles/viewer user:ada@example.com",
        "proj-1 roles/viewer serviceAccount:app@proj-1.iam.gserviceaccount.com",
        "proj-1 roles/editor group:team@example.com",
    ]


def test_an_api_error_carries_status_and_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_token(monkeypatch)

    def handle(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error": {"message": "Asset API disabled"}})

    with pytest.raises(
        DiscoveryError, match="403 from Resource Manager: Asset API disabled"
    ):
        _ = list_ids(handle)


@pytest.mark.parametrize(
    "scope_id",
    [
        pytest.param("../organizations/123456", id="another-scope-by-traversal"),
        pytest.param("proj\n1", id="non-printable"),
        pytest.param("p", id="too-short"),
    ],
)
def test_a_scope_that_is_not_a_project_id_reaches_no_api(
    scope_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    patch_token(monkeypatch)
    seen: list[httpx.Request] = []

    with pytest.raises(DiscoveryError, match="is not a GCP project id"):
        _ = list_ids(recording_handler(seen), scope_id)

    assert seen == []


def test_impersonation_wraps_the_base_credential_for_the_target() -> None:
    credentials = GoogleCredentials(
        {
            "GOOGLE_OAUTH_ACCESS_TOKEN": "ya29.static",
            "GOOGLE_IMPERSONATE_SERVICE_ACCOUNT": "runner@proj-1.iam.gserviceaccount.com",
        }
    )

    resolved = credentials.resolve()

    assert isinstance(resolved, impersonated_credentials.Credentials)
    assert resolved.service_account_email == "runner@proj-1.iam.gserviceaccount.com"

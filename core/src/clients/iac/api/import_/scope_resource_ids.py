# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from http import HTTPStatus
from typing import Any

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.job_accepted import JobAccepted
from ...models.problem import Problem
from ...models.scope_resource_ids_request import ScopeResourceIdsRequest
from ...models.scope_resource_ids_response_400 import ScopeResourceIdsResponse400
from ...types import Response


def _get_kwargs(
    *,
    body: ScopeResourceIdsRequest,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/v1/import/scope-resource-ids",
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> JobAccepted | Problem | ScopeResourceIdsResponse400 | None:
    if response.status_code == 202:
        response_202 = JobAccepted.from_dict(response.json())

        return response_202

    if response.status_code == 400:
        response_400 = ScopeResourceIdsResponse400.from_dict(response.json())

        return response_400

    if response.status_code == 401:
        response_401 = Problem.from_dict(response.json())

        return response_401

    if response.status_code == 403:
        response_403 = Problem.from_dict(response.json())

        return response_403

    if response.status_code == 404:
        response_404 = Problem.from_dict(response.json())

        return response_404

    if response.status_code == 422:
        response_422 = Problem.from_dict(response.json())

        return response_422

    if response.status_code == 503:
        response_503 = Problem.from_dict(response.json())

        return response_503

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Response[JobAccepted | Problem | ScopeResourceIdsResponse400]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient,
    body: ScopeResourceIdsRequest,
) -> Response[JobAccepted | Problem | ScopeResourceIdsResponse400]:
    """Enqueue a job listing the resource IDs present in a cloud scope.

     Enqueues a job that queries the cloud provider named in
    `terraform_provider` for the resources that exist in the scope
    `scope_id`, then returns `202 Accepted` immediately. Poll
    `GET /v1/jobs/{job_id}` for the OperationResult: on exit code
    0, `stdout` is a JSON array of provider-native resource ID
    strings —

    * `azure`: resource and resource-container IDs whose id
      contains `scope_id` (Azure Resource Graph);
    * `gcp`: asset names of the project's resources plus the IAM
      role names bound in the project (Cloud Asset Inventory);
    * `aws`: resource ARNs across the account's enabled regions
      (Resource Groups Tagging API).

    Failures of the underlying cloud query are normal outcomes:
    the job ends `succeeded` with a non-zero `exit_code` and
    diagnostics in `stderr`.

    Unlike the other endpoints, `scope_id` is required here — it
    names the scope being listed rather than acting as a
    credential fallback — and `terraform_provider` selects which
    provider is queried. The workspace is used to resolve provider
    credentials; the OSS reference impl shells out to the
    corresponding cloud CLI (`az`, `gcloud`, `aws`) with the
    service's ambient credentials.

    Args:
        body (ScopeResourceIdsRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[JobAccepted | Problem | ScopeResourceIdsResponse400]
    """

    kwargs = _get_kwargs(
        body=body,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    *,
    client: AuthenticatedClient,
    body: ScopeResourceIdsRequest,
) -> JobAccepted | Problem | ScopeResourceIdsResponse400 | None:
    """Enqueue a job listing the resource IDs present in a cloud scope.

     Enqueues a job that queries the cloud provider named in
    `terraform_provider` for the resources that exist in the scope
    `scope_id`, then returns `202 Accepted` immediately. Poll
    `GET /v1/jobs/{job_id}` for the OperationResult: on exit code
    0, `stdout` is a JSON array of provider-native resource ID
    strings —

    * `azure`: resource and resource-container IDs whose id
      contains `scope_id` (Azure Resource Graph);
    * `gcp`: asset names of the project's resources plus the IAM
      role names bound in the project (Cloud Asset Inventory);
    * `aws`: resource ARNs across the account's enabled regions
      (Resource Groups Tagging API).

    Failures of the underlying cloud query are normal outcomes:
    the job ends `succeeded` with a non-zero `exit_code` and
    diagnostics in `stderr`.

    Unlike the other endpoints, `scope_id` is required here — it
    names the scope being listed rather than acting as a
    credential fallback — and `terraform_provider` selects which
    provider is queried. The workspace is used to resolve provider
    credentials; the OSS reference impl shells out to the
    corresponding cloud CLI (`az`, `gcloud`, `aws`) with the
    service's ambient credentials.

    Args:
        body (ScopeResourceIdsRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        JobAccepted | Problem | ScopeResourceIdsResponse400
    """

    return sync_detailed(
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
    body: ScopeResourceIdsRequest,
) -> Response[JobAccepted | Problem | ScopeResourceIdsResponse400]:
    """Enqueue a job listing the resource IDs present in a cloud scope.

     Enqueues a job that queries the cloud provider named in
    `terraform_provider` for the resources that exist in the scope
    `scope_id`, then returns `202 Accepted` immediately. Poll
    `GET /v1/jobs/{job_id}` for the OperationResult: on exit code
    0, `stdout` is a JSON array of provider-native resource ID
    strings —

    * `azure`: resource and resource-container IDs whose id
      contains `scope_id` (Azure Resource Graph);
    * `gcp`: asset names of the project's resources plus the IAM
      role names bound in the project (Cloud Asset Inventory);
    * `aws`: resource ARNs across the account's enabled regions
      (Resource Groups Tagging API).

    Failures of the underlying cloud query are normal outcomes:
    the job ends `succeeded` with a non-zero `exit_code` and
    diagnostics in `stderr`.

    Unlike the other endpoints, `scope_id` is required here — it
    names the scope being listed rather than acting as a
    credential fallback — and `terraform_provider` selects which
    provider is queried. The workspace is used to resolve provider
    credentials; the OSS reference impl shells out to the
    corresponding cloud CLI (`az`, `gcloud`, `aws`) with the
    service's ambient credentials.

    Args:
        body (ScopeResourceIdsRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[JobAccepted | Problem | ScopeResourceIdsResponse400]
    """

    kwargs = _get_kwargs(
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient,
    body: ScopeResourceIdsRequest,
) -> JobAccepted | Problem | ScopeResourceIdsResponse400 | None:
    """Enqueue a job listing the resource IDs present in a cloud scope.

     Enqueues a job that queries the cloud provider named in
    `terraform_provider` for the resources that exist in the scope
    `scope_id`, then returns `202 Accepted` immediately. Poll
    `GET /v1/jobs/{job_id}` for the OperationResult: on exit code
    0, `stdout` is a JSON array of provider-native resource ID
    strings —

    * `azure`: resource and resource-container IDs whose id
      contains `scope_id` (Azure Resource Graph);
    * `gcp`: asset names of the project's resources plus the IAM
      role names bound in the project (Cloud Asset Inventory);
    * `aws`: resource ARNs across the account's enabled regions
      (Resource Groups Tagging API).

    Failures of the underlying cloud query are normal outcomes:
    the job ends `succeeded` with a non-zero `exit_code` and
    diagnostics in `stderr`.

    Unlike the other endpoints, `scope_id` is required here — it
    names the scope being listed rather than acting as a
    credential fallback — and `terraform_provider` selects which
    provider is queried. The workspace is used to resolve provider
    credentials; the OSS reference impl shells out to the
    corresponding cloud CLI (`az`, `gcloud`, `aws`) with the
    service's ambient credentials.

    Args:
        body (ScopeResourceIdsRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        JobAccepted | Problem | ScopeResourceIdsResponse400
    """

    return (
        await asyncio_detailed(
            client=client,
            body=body,
        )
    ).parsed

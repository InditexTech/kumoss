# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from http import HTTPStatus
from typing import Any

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.apply_request import ApplyRequest
from ...models.apply_response_400 import ApplyResponse400
from ...models.job_accepted import JobAccepted
from ...models.problem import Problem
from ...types import Response


def _get_kwargs(
    *,
    body: ApplyRequest,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/v1/apply",
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> ApplyResponse400 | JobAccepted | Problem | None:
    if response.status_code == 202:
        response_202 = JobAccepted.from_dict(response.json())

        return response_202

    if response.status_code == 400:
        response_400 = ApplyResponse400.from_dict(response.json())

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
) -> Response[ApplyResponse400 | JobAccepted | Problem]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient,
    body: ApplyRequest,
) -> Response[ApplyResponse400 | JobAccepted | Problem]:
    """Enqueue an apply job for a workspace.

     Enqueues a job that runs `terraform plan` (with optional
    `-target=` filters) and, if the plan succeeds,
    `terraform apply` of that plan against the workspace at
    `workspace_path`, then returns `202 Accepted` immediately.
    Poll `GET /v1/jobs/{job_id}` for the ApplyResult, which
    carries terraform's output and a boolean success flag.
    Terraform-level failures (init, plan, or apply) end the job as
    `succeeded` with `success: false` and diagnostics in
    `feedback`.

    Args:
        body (ApplyRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ApplyResponse400 | JobAccepted | Problem]
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
    body: ApplyRequest,
) -> ApplyResponse400 | JobAccepted | Problem | None:
    """Enqueue an apply job for a workspace.

     Enqueues a job that runs `terraform plan` (with optional
    `-target=` filters) and, if the plan succeeds,
    `terraform apply` of that plan against the workspace at
    `workspace_path`, then returns `202 Accepted` immediately.
    Poll `GET /v1/jobs/{job_id}` for the ApplyResult, which
    carries terraform's output and a boolean success flag.
    Terraform-level failures (init, plan, or apply) end the job as
    `succeeded` with `success: false` and diagnostics in
    `feedback`.

    Args:
        body (ApplyRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ApplyResponse400 | JobAccepted | Problem
    """

    return sync_detailed(
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
    body: ApplyRequest,
) -> Response[ApplyResponse400 | JobAccepted | Problem]:
    """Enqueue an apply job for a workspace.

     Enqueues a job that runs `terraform plan` (with optional
    `-target=` filters) and, if the plan succeeds,
    `terraform apply` of that plan against the workspace at
    `workspace_path`, then returns `202 Accepted` immediately.
    Poll `GET /v1/jobs/{job_id}` for the ApplyResult, which
    carries terraform's output and a boolean success flag.
    Terraform-level failures (init, plan, or apply) end the job as
    `succeeded` with `success: false` and diagnostics in
    `feedback`.

    Args:
        body (ApplyRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ApplyResponse400 | JobAccepted | Problem]
    """

    kwargs = _get_kwargs(
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient,
    body: ApplyRequest,
) -> ApplyResponse400 | JobAccepted | Problem | None:
    """Enqueue an apply job for a workspace.

     Enqueues a job that runs `terraform plan` (with optional
    `-target=` filters) and, if the plan succeeds,
    `terraform apply` of that plan against the workspace at
    `workspace_path`, then returns `202 Accepted` immediately.
    Poll `GET /v1/jobs/{job_id}` for the ApplyResult, which
    carries terraform's output and a boolean success flag.
    Terraform-level failures (init, plan, or apply) end the job as
    `succeeded` with `success: false` and diagnostics in
    `feedback`.

    Args:
        body (ApplyRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ApplyResponse400 | JobAccepted | Problem
    """

    return (
        await asyncio_detailed(
            client=client,
            body=body,
        )
    ).parsed

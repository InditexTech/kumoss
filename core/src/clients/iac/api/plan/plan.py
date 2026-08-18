# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from http import HTTPStatus
from typing import Any

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.job_accepted import JobAccepted
from ...models.plan_request import PlanRequest
from ...models.plan_response_400 import PlanResponse400
from ...models.problem import Problem
from ...types import Response


def _get_kwargs(
    *,
    body: PlanRequest,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/v1/plan",
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> JobAccepted | PlanResponse400 | Problem | None:
    if response.status_code == 202:
        response_202 = JobAccepted.from_dict(response.json())

        return response_202

    if response.status_code == 400:
        response_400 = PlanResponse400.from_dict(response.json())

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
) -> Response[JobAccepted | PlanResponse400 | Problem]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient,
    body: PlanRequest,
) -> Response[JobAccepted | PlanResponse400 | Problem]:
    """Enqueue a `terraform plan` job for a workspace.

     Enqueues a job that runs `terraform plan -out <plan_file>`
    (with optional `-target=` filters) against the workspace at
    `workspace_path`, then returns `202 Accepted` immediately. Poll
    `GET /v1/jobs/{job_id}` for the OperationResult carrying the
    command's exit code and raw output; the human-readable plan
    text is `stdout`. The written plan file can then be rendered
    with a `show` job or applied with an `apply` job using the
    same `plan_file`.

    Implementations that require cloud credentials (the reference
    impl uses the standard Terraform provider env vars: ARM_*,
    GOOGLE_*, AWS_*) resolve them while the job runs; terraform's
    own authentication errors surface in the result's `stderr`.

    Args:
        body (PlanRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[JobAccepted | PlanResponse400 | Problem]
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
    body: PlanRequest,
) -> JobAccepted | PlanResponse400 | Problem | None:
    """Enqueue a `terraform plan` job for a workspace.

     Enqueues a job that runs `terraform plan -out <plan_file>`
    (with optional `-target=` filters) against the workspace at
    `workspace_path`, then returns `202 Accepted` immediately. Poll
    `GET /v1/jobs/{job_id}` for the OperationResult carrying the
    command's exit code and raw output; the human-readable plan
    text is `stdout`. The written plan file can then be rendered
    with a `show` job or applied with an `apply` job using the
    same `plan_file`.

    Implementations that require cloud credentials (the reference
    impl uses the standard Terraform provider env vars: ARM_*,
    GOOGLE_*, AWS_*) resolve them while the job runs; terraform's
    own authentication errors surface in the result's `stderr`.

    Args:
        body (PlanRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        JobAccepted | PlanResponse400 | Problem
    """

    return sync_detailed(
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
    body: PlanRequest,
) -> Response[JobAccepted | PlanResponse400 | Problem]:
    """Enqueue a `terraform plan` job for a workspace.

     Enqueues a job that runs `terraform plan -out <plan_file>`
    (with optional `-target=` filters) against the workspace at
    `workspace_path`, then returns `202 Accepted` immediately. Poll
    `GET /v1/jobs/{job_id}` for the OperationResult carrying the
    command's exit code and raw output; the human-readable plan
    text is `stdout`. The written plan file can then be rendered
    with a `show` job or applied with an `apply` job using the
    same `plan_file`.

    Implementations that require cloud credentials (the reference
    impl uses the standard Terraform provider env vars: ARM_*,
    GOOGLE_*, AWS_*) resolve them while the job runs; terraform's
    own authentication errors surface in the result's `stderr`.

    Args:
        body (PlanRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[JobAccepted | PlanResponse400 | Problem]
    """

    kwargs = _get_kwargs(
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient,
    body: PlanRequest,
) -> JobAccepted | PlanResponse400 | Problem | None:
    """Enqueue a `terraform plan` job for a workspace.

     Enqueues a job that runs `terraform plan -out <plan_file>`
    (with optional `-target=` filters) against the workspace at
    `workspace_path`, then returns `202 Accepted` immediately. Poll
    `GET /v1/jobs/{job_id}` for the OperationResult carrying the
    command's exit code and raw output; the human-readable plan
    text is `stdout`. The written plan file can then be rendered
    with a `show` job or applied with an `apply` job using the
    same `plan_file`.

    Implementations that require cloud credentials (the reference
    impl uses the standard Terraform provider env vars: ARM_*,
    GOOGLE_*, AWS_*) resolve them while the job runs; terraform's
    own authentication errors surface in the result's `stderr`.

    Args:
        body (PlanRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        JobAccepted | PlanResponse400 | Problem
    """

    return (
        await asyncio_detailed(
            client=client,
            body=body,
        )
    ).parsed

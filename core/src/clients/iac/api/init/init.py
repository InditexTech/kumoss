# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from http import HTTPStatus
from typing import Any

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.init_request import InitRequest
from ...models.init_response_400 import InitResponse400
from ...models.job_accepted import JobAccepted
from ...models.problem import Problem
from ...types import Response


def _get_kwargs(
    *,
    body: InitRequest,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/v1/init",
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> InitResponse400 | JobAccepted | Problem | None:
    if response.status_code == 202:
        response_202 = JobAccepted.from_dict(response.json())

        return response_202

    if response.status_code == 400:
        response_400 = InitResponse400.from_dict(response.json())

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
) -> Response[InitResponse400 | JobAccepted | Problem]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient,
    body: InitRequest,
) -> Response[InitResponse400 | JobAccepted | Problem]:
    """Enqueue a `terraform init` job for a workspace.

     Enqueues a job that runs `terraform init` against the workspace
    at `workspace_path`, then returns `202 Accepted` immediately.
    Poll `GET /v1/jobs/{job_id}` for the OperationResult carrying
    the command's exit code and raw output.

    Args:
        body (InitRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[InitResponse400 | JobAccepted | Problem]
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
    body: InitRequest,
) -> InitResponse400 | JobAccepted | Problem | None:
    """Enqueue a `terraform init` job for a workspace.

     Enqueues a job that runs `terraform init` against the workspace
    at `workspace_path`, then returns `202 Accepted` immediately.
    Poll `GET /v1/jobs/{job_id}` for the OperationResult carrying
    the command's exit code and raw output.

    Args:
        body (InitRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        InitResponse400 | JobAccepted | Problem
    """

    return sync_detailed(
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
    body: InitRequest,
) -> Response[InitResponse400 | JobAccepted | Problem]:
    """Enqueue a `terraform init` job for a workspace.

     Enqueues a job that runs `terraform init` against the workspace
    at `workspace_path`, then returns `202 Accepted` immediately.
    Poll `GET /v1/jobs/{job_id}` for the OperationResult carrying
    the command's exit code and raw output.

    Args:
        body (InitRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[InitResponse400 | JobAccepted | Problem]
    """

    kwargs = _get_kwargs(
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient,
    body: InitRequest,
) -> InitResponse400 | JobAccepted | Problem | None:
    """Enqueue a `terraform init` job for a workspace.

     Enqueues a job that runs `terraform init` against the workspace
    at `workspace_path`, then returns `202 Accepted` immediately.
    Poll `GET /v1/jobs/{job_id}` for the OperationResult carrying
    the command's exit code and raw output.

    Args:
        body (InitRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        InitResponse400 | JobAccepted | Problem
    """

    return (
        await asyncio_detailed(
            client=client,
            body=body,
        )
    ).parsed

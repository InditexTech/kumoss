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
from ...models.state_resource_ids_request import StateResourceIdsRequest
from ...models.state_resource_ids_response_400 import StateResourceIdsResponse400
from ...types import Response


def _get_kwargs(
    *,
    body: StateResourceIdsRequest,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/v1/import/state-resource-ids",
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> JobAccepted | Problem | StateResourceIdsResponse400 | None:
    if response.status_code == 202:
        response_202 = JobAccepted.from_dict(response.json())

        return response_202

    if response.status_code == 400:
        response_400 = StateResourceIdsResponse400.from_dict(response.json())

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
) -> Response[JobAccepted | Problem | StateResourceIdsResponse400]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient,
    body: StateResourceIdsRequest,
) -> Response[JobAccepted | Problem | StateResourceIdsResponse400]:
    """Enqueue a job listing the resource IDs tracked in Terraform state.

     Enqueues a job that runs `terraform state pull` against the
    workspace at `workspace_path` and extracts the
    provider-assigned identifier of every managed resource instance
    in the state — its `arn` attribute when it has one, otherwise
    its `id`, so that AWS entries are comparable with the ARNs
    `/v1/import/scope-resource-ids` reports — then returns
    `202 Accepted` immediately. Poll
    `GET /v1/jobs/{job_id}` for the OperationResult: on exit code
    0, `stdout` is a JSON array of resource ID strings (empty when
    the state tracks nothing). If `state pull` fails, its exit
    code and `stderr` are passed through verbatim and `stdout` is
    empty. The workspace must already be initialised (submit an
    `init` job first).

    Args:
        body (StateResourceIdsRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[JobAccepted | Problem | StateResourceIdsResponse400]
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
    body: StateResourceIdsRequest,
) -> JobAccepted | Problem | StateResourceIdsResponse400 | None:
    """Enqueue a job listing the resource IDs tracked in Terraform state.

     Enqueues a job that runs `terraform state pull` against the
    workspace at `workspace_path` and extracts the
    provider-assigned identifier of every managed resource instance
    in the state — its `arn` attribute when it has one, otherwise
    its `id`, so that AWS entries are comparable with the ARNs
    `/v1/import/scope-resource-ids` reports — then returns
    `202 Accepted` immediately. Poll
    `GET /v1/jobs/{job_id}` for the OperationResult: on exit code
    0, `stdout` is a JSON array of resource ID strings (empty when
    the state tracks nothing). If `state pull` fails, its exit
    code and `stderr` are passed through verbatim and `stdout` is
    empty. The workspace must already be initialised (submit an
    `init` job first).

    Args:
        body (StateResourceIdsRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        JobAccepted | Problem | StateResourceIdsResponse400
    """

    return sync_detailed(
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
    body: StateResourceIdsRequest,
) -> Response[JobAccepted | Problem | StateResourceIdsResponse400]:
    """Enqueue a job listing the resource IDs tracked in Terraform state.

     Enqueues a job that runs `terraform state pull` against the
    workspace at `workspace_path` and extracts the
    provider-assigned identifier of every managed resource instance
    in the state — its `arn` attribute when it has one, otherwise
    its `id`, so that AWS entries are comparable with the ARNs
    `/v1/import/scope-resource-ids` reports — then returns
    `202 Accepted` immediately. Poll
    `GET /v1/jobs/{job_id}` for the OperationResult: on exit code
    0, `stdout` is a JSON array of resource ID strings (empty when
    the state tracks nothing). If `state pull` fails, its exit
    code and `stderr` are passed through verbatim and `stdout` is
    empty. The workspace must already be initialised (submit an
    `init` job first).

    Args:
        body (StateResourceIdsRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[JobAccepted | Problem | StateResourceIdsResponse400]
    """

    kwargs = _get_kwargs(
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient,
    body: StateResourceIdsRequest,
) -> JobAccepted | Problem | StateResourceIdsResponse400 | None:
    """Enqueue a job listing the resource IDs tracked in Terraform state.

     Enqueues a job that runs `terraform state pull` against the
    workspace at `workspace_path` and extracts the
    provider-assigned identifier of every managed resource instance
    in the state — its `arn` attribute when it has one, otherwise
    its `id`, so that AWS entries are comparable with the ARNs
    `/v1/import/scope-resource-ids` reports — then returns
    `202 Accepted` immediately. Poll
    `GET /v1/jobs/{job_id}` for the OperationResult: on exit code
    0, `stdout` is a JSON array of resource ID strings (empty when
    the state tracks nothing). If `state pull` fails, its exit
    code and `stderr` are passed through verbatim and `stdout` is
    empty. The workspace must already be initialised (submit an
    `init` job first).

    Args:
        body (StateResourceIdsRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        JobAccepted | Problem | StateResourceIdsResponse400
    """

    return (
        await asyncio_detailed(
            client=client,
            body=body,
        )
    ).parsed

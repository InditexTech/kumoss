# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from http import HTTPStatus
from typing import Any

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.problem import Problem
from ...models.resolve_request import ResolveRequest
from ...models.resolve_response import ResolveResponse
from ...models.resolve_response_400 import ResolveResponse400
from ...types import Response


def _get_kwargs(
    *,
    body: ResolveRequest,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/v1/resolve",
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Problem | ResolveResponse | ResolveResponse400 | None:
    if response.status_code == 200:
        response_200 = ResolveResponse.from_dict(response.json())

        return response_200

    if response.status_code == 400:
        response_400 = ResolveResponse400.from_dict(response.json())

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

    if response.status_code == 502:
        response_502 = Problem.from_dict(response.json())

        return response_502

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Response[Problem | ResolveResponse | ResolveResponse400]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient,
    body: ResolveRequest,
) -> Response[Problem | ResolveResponse | ResolveResponse400]:
    """Resolve a business identifier into an IaC repository reference.

     Translates `identifier` into the repository the rest of Nebula
    operates on, and optionally into the Terraform provider and cloud
    scope the caller would otherwise have to ask the user for.

    `repo_url` is required. `terraform_provider` and `scope_id` are
    best effort: implementations MUST return `null` rather than a
    guess, because the caller skips its corresponding prompt for any
    field that comes back non-null. `identifier` MUST echo the
    request's `identifier` verbatim so callers can correlate.

    Args:
        body (ResolveRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Problem | ResolveResponse | ResolveResponse400]
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
    body: ResolveRequest,
) -> Problem | ResolveResponse | ResolveResponse400 | None:
    """Resolve a business identifier into an IaC repository reference.

     Translates `identifier` into the repository the rest of Nebula
    operates on, and optionally into the Terraform provider and cloud
    scope the caller would otherwise have to ask the user for.

    `repo_url` is required. `terraform_provider` and `scope_id` are
    best effort: implementations MUST return `null` rather than a
    guess, because the caller skips its corresponding prompt for any
    field that comes back non-null. `identifier` MUST echo the
    request's `identifier` verbatim so callers can correlate.

    Args:
        body (ResolveRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Problem | ResolveResponse | ResolveResponse400
    """

    return sync_detailed(
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
    body: ResolveRequest,
) -> Response[Problem | ResolveResponse | ResolveResponse400]:
    """Resolve a business identifier into an IaC repository reference.

     Translates `identifier` into the repository the rest of Nebula
    operates on, and optionally into the Terraform provider and cloud
    scope the caller would otherwise have to ask the user for.

    `repo_url` is required. `terraform_provider` and `scope_id` are
    best effort: implementations MUST return `null` rather than a
    guess, because the caller skips its corresponding prompt for any
    field that comes back non-null. `identifier` MUST echo the
    request's `identifier` verbatim so callers can correlate.

    Args:
        body (ResolveRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Problem | ResolveResponse | ResolveResponse400]
    """

    kwargs = _get_kwargs(
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient,
    body: ResolveRequest,
) -> Problem | ResolveResponse | ResolveResponse400 | None:
    """Resolve a business identifier into an IaC repository reference.

     Translates `identifier` into the repository the rest of Nebula
    operates on, and optionally into the Terraform provider and cloud
    scope the caller would otherwise have to ask the user for.

    `repo_url` is required. `terraform_provider` and `scope_id` are
    best effort: implementations MUST return `null` rather than a
    guess, because the caller skips its corresponding prompt for any
    field that comes back non-null. `identifier` MUST echo the
    request's `identifier` verbatim so callers can correlate.

    Args:
        body (ResolveRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Problem | ResolveResponse | ResolveResponse400
    """

    return (
        await asyncio_detailed(
            client=client,
            body=body,
        )
    ).parsed

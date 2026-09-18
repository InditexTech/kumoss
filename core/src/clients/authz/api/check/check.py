# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from http import HTTPStatus
from typing import Any

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.check_request import CheckRequest
from ...models.check_response import CheckResponse
from ...models.check_response_400 import CheckResponse400
from ...models.problem import Problem
from ...types import Response


def _get_kwargs(
    *,
    body: CheckRequest,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/v1/check",
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> CheckResponse | CheckResponse400 | Problem | None:
    if response.status_code == 200:
        response_200 = CheckResponse.from_dict(response.json())

        return response_200

    if response.status_code == 400:
        response_400 = CheckResponse400.from_dict(response.json())

        return response_400

    if response.status_code == 401:
        response_401 = Problem.from_dict(response.json())

        return response_401

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
) -> Response[CheckResponse | CheckResponse400 | Problem]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient,
    body: CheckRequest,
) -> Response[CheckResponse | CheckResponse400 | Problem]:
    """Decide whether a user may operate on a resource.

     Returns whether the identified user is permitted to operate on
    the named cloud resource. The bundled reference implementation
    decides nothing: it returns the value of
    `NEBULA_AUTHZ_PERMISSIVE` (default `true`) unconditionally. A
    real implementation should resolve the project against its own
    policy source.

    Args:
        body (CheckRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[CheckResponse | CheckResponse400 | Problem]
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
    body: CheckRequest,
) -> CheckResponse | CheckResponse400 | Problem | None:
    """Decide whether a user may operate on a resource.

     Returns whether the identified user is permitted to operate on
    the named cloud resource. The bundled reference implementation
    decides nothing: it returns the value of
    `NEBULA_AUTHZ_PERMISSIVE` (default `true`) unconditionally. A
    real implementation should resolve the project against its own
    policy source.

    Args:
        body (CheckRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        CheckResponse | CheckResponse400 | Problem
    """

    return sync_detailed(
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
    body: CheckRequest,
) -> Response[CheckResponse | CheckResponse400 | Problem]:
    """Decide whether a user may operate on a resource.

     Returns whether the identified user is permitted to operate on
    the named cloud resource. The bundled reference implementation
    decides nothing: it returns the value of
    `NEBULA_AUTHZ_PERMISSIVE` (default `true`) unconditionally. A
    real implementation should resolve the project against its own
    policy source.

    Args:
        body (CheckRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[CheckResponse | CheckResponse400 | Problem]
    """

    kwargs = _get_kwargs(
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient,
    body: CheckRequest,
) -> CheckResponse | CheckResponse400 | Problem | None:
    """Decide whether a user may operate on a resource.

     Returns whether the identified user is permitted to operate on
    the named cloud resource. The bundled reference implementation
    decides nothing: it returns the value of
    `NEBULA_AUTHZ_PERMISSIVE` (default `true`) unconditionally. A
    real implementation should resolve the project against its own
    policy source.

    Args:
        body (CheckRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        CheckResponse | CheckResponse400 | Problem
    """

    return (
        await asyncio_detailed(
            client=client,
            body=body,
        )
    ).parsed

# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from http import HTTPStatus
from typing import Any, cast
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.assign_role_request import AssignRoleRequest
from ...models.problem import Problem
from ...types import UNSET, Response, Unset


def _get_kwargs(
    user_id: str,
    *,
    body: AssignRoleRequest,
    x_user_id: str | Unset = UNSET,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}
    if not isinstance(x_user_id, Unset):
        headers["X-User-Id"] = x_user_id

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/v1/users/{user_id}/roles".format(
            user_id=quote(str(user_id), safe=""),
        ),
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Any | Problem | None:
    if response.status_code == 204:
        response_204 = cast(Any, None)
        return response_204

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

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Response[Any | Problem]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    user_id: str,
    *,
    client: AuthenticatedClient,
    body: AssignRoleRequest,
    x_user_id: str | Unset = UNSET,
) -> Response[Any | Problem]:
    """Admin: assign a role to a user.

    Args:
        user_id (str):
        x_user_id (str | Unset):
        body (AssignRoleRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | Problem]
    """

    kwargs = _get_kwargs(
        user_id=user_id,
        body=body,
        x_user_id=x_user_id,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    user_id: str,
    *,
    client: AuthenticatedClient,
    body: AssignRoleRequest,
    x_user_id: str | Unset = UNSET,
) -> Any | Problem | None:
    """Admin: assign a role to a user.

    Args:
        user_id (str):
        x_user_id (str | Unset):
        body (AssignRoleRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | Problem
    """

    return sync_detailed(
        user_id=user_id,
        client=client,
        body=body,
        x_user_id=x_user_id,
    ).parsed


async def asyncio_detailed(
    user_id: str,
    *,
    client: AuthenticatedClient,
    body: AssignRoleRequest,
    x_user_id: str | Unset = UNSET,
) -> Response[Any | Problem]:
    """Admin: assign a role to a user.

    Args:
        user_id (str):
        x_user_id (str | Unset):
        body (AssignRoleRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | Problem]
    """

    kwargs = _get_kwargs(
        user_id=user_id,
        body=body,
        x_user_id=x_user_id,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    user_id: str,
    *,
    client: AuthenticatedClient,
    body: AssignRoleRequest,
    x_user_id: str | Unset = UNSET,
) -> Any | Problem | None:
    """Admin: assign a role to a user.

    Args:
        user_id (str):
        x_user_id (str | Unset):
        body (AssignRoleRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | Problem
    """

    return (
        await asyncio_detailed(
            user_id=user_id,
            client=client,
            body=body,
            x_user_id=x_user_id,
        )
    ).parsed

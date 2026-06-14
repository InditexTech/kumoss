# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from http import HTTPStatus
from typing import Any

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.problem import Problem
from ...models.user import User
from ...types import UNSET, Response, Unset


def _get_kwargs(
    *,
    x_user_id: str | Unset = UNSET,
    x_user_email: str | Unset = UNSET,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}
    if not isinstance(x_user_id, Unset):
        headers["X-User-Id"] = x_user_id

    if not isinstance(x_user_email, Unset):
        headers["X-User-Email"] = x_user_email

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/v1/users/me",
    }

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Problem | User | None:
    if response.status_code == 200:
        response_200 = User.from_dict(response.json())

        return response_200

    if response.status_code == 401:
        response_401 = Problem.from_dict(response.json())

        return response_401

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Response[Problem | User]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient,
    x_user_id: str | Unset = UNSET,
    x_user_email: str | Unset = UNSET,
) -> Response[Problem | User]:
    """Look up the calling user's identity and roles.

     The caller asserts identity via `X-User-Id` (and optionally
    `X-User-Email`). The service returns the corresponding user
    record (creating an empty one if none exists) plus assigned
    roles.

    When neither header is present, the OSS reference impl returns
    an anonymous user with no roles.

    Args:
        x_user_id (str | Unset):
        x_user_email (str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Problem | User]
    """

    kwargs = _get_kwargs(
        x_user_id=x_user_id,
        x_user_email=x_user_email,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    *,
    client: AuthenticatedClient,
    x_user_id: str | Unset = UNSET,
    x_user_email: str | Unset = UNSET,
) -> Problem | User | None:
    """Look up the calling user's identity and roles.

     The caller asserts identity via `X-User-Id` (and optionally
    `X-User-Email`). The service returns the corresponding user
    record (creating an empty one if none exists) plus assigned
    roles.

    When neither header is present, the OSS reference impl returns
    an anonymous user with no roles.

    Args:
        x_user_id (str | Unset):
        x_user_email (str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Problem | User
    """

    return sync_detailed(
        client=client,
        x_user_id=x_user_id,
        x_user_email=x_user_email,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
    x_user_id: str | Unset = UNSET,
    x_user_email: str | Unset = UNSET,
) -> Response[Problem | User]:
    """Look up the calling user's identity and roles.

     The caller asserts identity via `X-User-Id` (and optionally
    `X-User-Email`). The service returns the corresponding user
    record (creating an empty one if none exists) plus assigned
    roles.

    When neither header is present, the OSS reference impl returns
    an anonymous user with no roles.

    Args:
        x_user_id (str | Unset):
        x_user_email (str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Problem | User]
    """

    kwargs = _get_kwargs(
        x_user_id=x_user_id,
        x_user_email=x_user_email,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient,
    x_user_id: str | Unset = UNSET,
    x_user_email: str | Unset = UNSET,
) -> Problem | User | None:
    """Look up the calling user's identity and roles.

     The caller asserts identity via `X-User-Id` (and optionally
    `X-User-Email`). The service returns the corresponding user
    record (creating an empty one if none exists) plus assigned
    roles.

    When neither header is present, the OSS reference impl returns
    an anonymous user with no roles.

    Args:
        x_user_id (str | Unset):
        x_user_email (str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Problem | User
    """

    return (
        await asyncio_detailed(
            client=client,
            x_user_id=x_user_id,
            x_user_email=x_user_email,
        )
    ).parsed

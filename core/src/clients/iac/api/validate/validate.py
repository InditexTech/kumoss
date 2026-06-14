# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from http import HTTPStatus
from typing import Any

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.problem import Problem
from ...models.validate_request import ValidateRequest
from ...models.validate_response import ValidateResponse
from ...models.validate_response_400 import ValidateResponse400
from ...types import Response


def _get_kwargs(
    *,
    body: ValidateRequest,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/v1/validate",
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Problem | ValidateResponse | ValidateResponse400 | None:
    if response.status_code == 200:
        response_200 = ValidateResponse.from_dict(response.json())

        return response_200

    if response.status_code == 400:
        response_400 = ValidateResponse400.from_dict(response.json())

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
) -> Response[Problem | ValidateResponse | ValidateResponse400]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient,
    body: ValidateRequest,
) -> Response[Problem | ValidateResponse | ValidateResponse400]:
    """Validate the Terraform configuration in a workspace.

     Runs `terraform init`, `terraform validate`, and (if the workspace
    validates) `terraform plan` against the workspace at
    `workspace_path`. Returns the raw plan output and a boolean
    success flag. When `get_drift` is true and the plan succeeds, the
    plan JSON is parsed and any drift is summarised in the `feedback`
    field.

    Implementations that require cloud credentials (the reference
    impl uses the standard Terraform provider env vars: ARM_*,
    GOOGLE_*, AWS_*) MAY return 503 when those are missing rather
    than producing a misleading `validation: false`.

    Args:
        body (ValidateRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Problem | ValidateResponse | ValidateResponse400]
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
    body: ValidateRequest,
) -> Problem | ValidateResponse | ValidateResponse400 | None:
    """Validate the Terraform configuration in a workspace.

     Runs `terraform init`, `terraform validate`, and (if the workspace
    validates) `terraform plan` against the workspace at
    `workspace_path`. Returns the raw plan output and a boolean
    success flag. When `get_drift` is true and the plan succeeds, the
    plan JSON is parsed and any drift is summarised in the `feedback`
    field.

    Implementations that require cloud credentials (the reference
    impl uses the standard Terraform provider env vars: ARM_*,
    GOOGLE_*, AWS_*) MAY return 503 when those are missing rather
    than producing a misleading `validation: false`.

    Args:
        body (ValidateRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Problem | ValidateResponse | ValidateResponse400
    """

    return sync_detailed(
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
    body: ValidateRequest,
) -> Response[Problem | ValidateResponse | ValidateResponse400]:
    """Validate the Terraform configuration in a workspace.

     Runs `terraform init`, `terraform validate`, and (if the workspace
    validates) `terraform plan` against the workspace at
    `workspace_path`. Returns the raw plan output and a boolean
    success flag. When `get_drift` is true and the plan succeeds, the
    plan JSON is parsed and any drift is summarised in the `feedback`
    field.

    Implementations that require cloud credentials (the reference
    impl uses the standard Terraform provider env vars: ARM_*,
    GOOGLE_*, AWS_*) MAY return 503 when those are missing rather
    than producing a misleading `validation: false`.

    Args:
        body (ValidateRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Problem | ValidateResponse | ValidateResponse400]
    """

    kwargs = _get_kwargs(
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient,
    body: ValidateRequest,
) -> Problem | ValidateResponse | ValidateResponse400 | None:
    """Validate the Terraform configuration in a workspace.

     Runs `terraform init`, `terraform validate`, and (if the workspace
    validates) `terraform plan` against the workspace at
    `workspace_path`. Returns the raw plan output and a boolean
    success flag. When `get_drift` is true and the plan succeeds, the
    plan JSON is parsed and any drift is summarised in the `feedback`
    field.

    Implementations that require cloud credentials (the reference
    impl uses the standard Terraform provider env vars: ARM_*,
    GOOGLE_*, AWS_*) MAY return 503 when those are missing rather
    than producing a misleading `validation: false`.

    Args:
        body (ValidateRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Problem | ValidateResponse | ValidateResponse400
    """

    return (
        await asyncio_detailed(
            client=client,
            body=body,
        )
    ).parsed

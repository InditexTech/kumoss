from http import HTTPStatus
from typing import Any

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.access_evaluation_request import AccessEvaluationRequest
from ...models.access_evaluation_response import AccessEvaluationResponse
from ...models.evaluate_response_400 import EvaluateResponse400
from ...models.problem import Problem
from ...types import Response


def _get_kwargs(
    *,
    body: AccessEvaluationRequest,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/access/v1/evaluation",
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> AccessEvaluationResponse | EvaluateResponse400 | Problem | None:
    if response.status_code == 200:
        response_200 = AccessEvaluationResponse.from_dict(response.json())

        return response_200

    if response.status_code == 400:
        response_400 = EvaluateResponse400.from_dict(response.json())

        return response_400

    if response.status_code == 401:
        response_401 = Problem.from_dict(response.json())

        return response_401

    if response.status_code == 403:
        response_403 = Problem.from_dict(response.json())

        return response_403

    if response.status_code == 422:
        response_422 = Problem.from_dict(response.json())

        return response_422

    if response.status_code == 500:
        response_500 = Problem.from_dict(response.json())

        return response_500

    if response.status_code == 502:
        response_502 = Problem.from_dict(response.json())

        return response_502

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Response[AccessEvaluationResponse | EvaluateResponse400 | Problem]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient,
    body: AccessEvaluationRequest,
) -> Response[AccessEvaluationResponse | EvaluateResponse400 | Problem]:
    """Evaluate an access request.

     Returns whether the subject is permitted to perform the named
    action on the given resource, per OpenID AuthZEN 1.0 §5.

    Args:
        body (AccessEvaluationRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[AccessEvaluationResponse | EvaluateResponse400 | Problem]
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
    body: AccessEvaluationRequest,
) -> AccessEvaluationResponse | EvaluateResponse400 | Problem | None:
    """Evaluate an access request.

     Returns whether the subject is permitted to perform the named
    action on the given resource, per OpenID AuthZEN 1.0 §5.

    Args:
        body (AccessEvaluationRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        AccessEvaluationResponse | EvaluateResponse400 | Problem
    """

    return sync_detailed(
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
    body: AccessEvaluationRequest,
) -> Response[AccessEvaluationResponse | EvaluateResponse400 | Problem]:
    """Evaluate an access request.

     Returns whether the subject is permitted to perform the named
    action on the given resource, per OpenID AuthZEN 1.0 §5.

    Args:
        body (AccessEvaluationRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[AccessEvaluationResponse | EvaluateResponse400 | Problem]
    """

    kwargs = _get_kwargs(
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient,
    body: AccessEvaluationRequest,
) -> AccessEvaluationResponse | EvaluateResponse400 | Problem | None:
    """Evaluate an access request.

     Returns whether the subject is permitted to perform the named
    action on the given resource, per OpenID AuthZEN 1.0 §5.

    Args:
        body (AccessEvaluationRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        AccessEvaluationResponse | EvaluateResponse400 | Problem
    """

    return (
        await asyncio_detailed(
            client=client,
            body=body,
        )
    ).parsed

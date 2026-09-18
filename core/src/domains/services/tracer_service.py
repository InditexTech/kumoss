# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import time
from types import CoroutineType
from typing import Any, Concatenate, Protocol
from functools import wraps
from collections.abc import Awaitable, Callable
from contextvars import ContextVar, Token

from opentelemetry.trace import Status, StatusCode

from src.domains.dto import LLMResponseDTO
from src.domains.interfaces.tracer_interface import ITracer, TracedTerraformResult

_tracer_context: ContextVar[ITracer] = ContextVar("tracer")


class TracerService:
    @staticmethod
    def get_current_tracer() -> ITracer:
        """Gets the tracer for the current request context."""
        tracer = _tracer_context.get()
        return tracer

    @staticmethod
    def set_current_tracer(tracer: ITracer) -> Token[ITracer]:
        """Sets the tracer for the current context. Returns a token for resetting."""
        return _tracer_context.set(tracer)

    @staticmethod
    def reset_current_tracer(token: Token[ITracer]):
        """Resets the tracer context using the token."""
        _tracer_context.reset(token)


def trace_terraform[**P, R: TracedTerraformResult](
    func: Callable[P, Awaitable[R]],
) -> Callable[P, CoroutineType[Any, Any, R]]:
    """
    Decorator that automatically traces chain function calls with OpenTelemetry spans.
    """

    @wraps(func)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        tracer = TracerService.get_current_tracer()
        start = time.time()
        output = await func(*args, **kwargs)
        span = tracer.trace_terraform(
            output,
            operation=func.__name__,
            start_time=int(start * 1_000_000_000),
            **kwargs,
        )
        span.set_status(Status(StatusCode.OK))
        span.end()

        return output

    return wrapper


def trace_chain[**P, R](
    func: Callable[P, Awaitable[R]],
) -> Callable[P, CoroutineType[Any, Any, R]]:
    """
    Decorator that automatically traces chain function calls with OpenTelemetry spans.
    """

    @wraps(func)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        tracer = TracerService.get_current_tracer()
        span = tracer.trace_chain(**kwargs)
        output = await func(*args, **kwargs)
        _ = tracer.trace_chain_output(span, output)
        span.set_status(Status(StatusCode.OK))
        span.end()

        return output

    return wrapper


class _TracedLLMProvider(Protocol):
    """State @trace_llm requires on the instance whose method it decorates."""

    _last_invocation_params: dict[str, Any] | None

    @property
    def model(self) -> str: ...


def trace_llm[**P](
    func: Callable[Concatenate[_TracedLLMProvider, P], Awaitable[LLMResponseDTO]],
) -> Callable[
    Concatenate[_TracedLLMProvider, P], CoroutineType[Any, Any, LLMResponseDTO]
]:
    """
    Decorator that automatically traces LLM function calls with comprehensive telemetry data.
    Reads invocation parameters from self._last_invocation_params, set by the
    adapter before each litellm call. Per-instance state, so concurrent requests
    do not interfere.
    """

    @wraps(func)
    async def wrapper(
        self_instance: _TracedLLMProvider, /, *args: P.args, **kwargs: P.kwargs
    ) -> LLMResponseDTO:
        start = time.time()
        output = await func(self_instance, *args, **kwargs)

        span = TracerService.get_current_tracer().trace_llm(
            start_time=int(start * 1_000_000_000),  # epoch in ns
            model=self_instance.model,
            invocation_params=self_instance._last_invocation_params,  # pyright: ignore[reportPrivateUsage]
            response=output,
            **kwargs,
        )
        span.set_status(Status(StatusCode.OK))
        span.end()

        return output

    return wrapper


def trace_tool[**P, R](
    func: Callable[P, Awaitable[R]],
) -> Callable[P, CoroutineType[Any, Any, R]]:
    """
    Decorator that automatically traces tool function calls with OpenTelemetry spans.
    """

    @wraps(func)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        start = time.time()
        output = await func(*args, **kwargs)
        span = TracerService.get_current_tracer().trace_tool(
            int(start * 1_000_000_000), output, *args, **kwargs
        )
        span.set_status(Status(StatusCode.OK))
        span.end()

        return output

    return wrapper


tracer = TracerService()

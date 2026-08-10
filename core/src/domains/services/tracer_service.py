# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import time
from typing import Any
from functools import wraps
from collections.abc import Coroutine
from typing import Callable
from contextvars import ContextVar, Token

from opentelemetry.trace import Status, StatusCode

from src.domains.dto import TerraformValidationDTO
from src.domains.interfaces.tracer_interface import ITracer

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


def trace_terraform(
    func: Callable[[Any], Any],
) -> Callable[[Any], Any]:
    """
    Decorator that automatically traces chain function calls with OpenTelemetry spans.
    """

    @wraps(func)
    async def wrapper(*args, **kwargs) -> TerraformValidationDTO:
        tracer = TracerService.get_current_tracer()
        start = time.time()
        output: TerraformValidationDTO = await func(*args, **kwargs)
        span = tracer.trace_terraform(
            output, start_time=int(start * 1_000_000_000), **kwargs
        )
        span.set_status(Status(StatusCode.OK))
        span.end()

        return output

    return wrapper


def trace_chain(func: Callable) -> Callable:
    """
    Decorator that automatically traces chain function calls with OpenTelemetry spans.
    """

    @wraps(func)
    async def wrapper(*args, **kwargs) -> Coroutine:
        tracer = TracerService.get_current_tracer()
        span = tracer.trace_chain(**kwargs)
        output = await func(*args, **kwargs)
        _ = tracer.trace_chain_output(span, output)
        span.set_status(Status(StatusCode.OK))
        span.end()

        return output

    return wrapper


def trace_llm(func: Callable) -> Callable:
    """
    Decorator that automatically traces LLM function calls with comprehensive telemetry data.
    Reads invocation parameters from self._last_invocation_params, set by the
    adapter before each litellm call. Per-instance state, so concurrent requests
    do not interfere.
    """

    @wraps(func)
    async def wrapper(*args, **kwargs) -> Coroutine:
        self_instance = args[0]

        start = time.time()
        output = await func(*args, **kwargs)

        span = TracerService.get_current_tracer().trace_llm(
            start_time=int(start * 1_000_000_000),  # epoch in ns
            model=self_instance.model,
            invocation_params=self_instance._last_invocation_params,
            response=output,
            **kwargs,
        )
        span.set_status(Status(StatusCode.OK))
        span.end()

        return output

    return wrapper


def trace_tool(func: Callable) -> Callable:
    """
    Decorator that automatically traces tool function calls with OpenTelemetry spans.
    """

    @wraps(func)
    async def wrapper(*args, **kwargs) -> Coroutine:
        start = time.time()
        output = await func(*args, **kwargs)
        span = TracerService.get_current_tracer().trace_tool(
            int(start * 1_000_000_000), output, *args, **kwargs
        )
        span.set_status(Status(StatusCode.OK))
        span.end()

        return output

    return wrapper

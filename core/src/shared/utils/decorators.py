# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import asyncio
from collections.abc import Awaitable, Coroutine
from functools import wraps
from typing import ParamSpec, TypeVar
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from ..logger import logging

# Module-level executor used by execute_pool. Lives next to its only
# consumer rather than in shared/config — it's a runtime object, not
# deployment-tunable configuration.
_pool_executor = ThreadPoolExecutor(max_workers=20)


def execute_pool(func: Callable[..., Any]) -> Callable[..., Any]:
    async def wrapper(*args: list[Any]) -> Coroutine[Any, Any, Any]:
        loop = asyncio.get_running_loop()
        output = await loop.run_in_executor(
            _pool_executor,
            func,
            *args,
        )
        return output

    return wrapper


P = ParamSpec("P")
R = TypeVar("R")

_KW_MARKER = object()


def async_cache(
    func: Callable[P, Awaitable[R | None]],
) -> Callable[P, Awaitable[R | None]]:

    cache: dict[tuple[object, ...], R] = {}

    @wraps(func)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R | None:
        key = args + tuple(kwargs.items())

        if key in cache:
            logging.debug(f"cache hit for session {key}")
            return cache[key]

        result = await func(*args, **kwargs)
        if result is not None:
            cache[key] = result

        return result

    return wrapper

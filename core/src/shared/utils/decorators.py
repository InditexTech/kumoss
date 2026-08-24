# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import asyncio
from collections.abc import Coroutine
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

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

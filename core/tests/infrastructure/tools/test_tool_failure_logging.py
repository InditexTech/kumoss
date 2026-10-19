# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""What a failing tool leaves behind in the log.

``execute_tool`` answers the agent with a short ``error_message`` — it
has to, since that text reaches a model and must not echo backend
detail. The log is therefore the only place the diagnosis can live, so
every failure has to arrive there whole, cause chain included. A typed
``ExceptionHandler`` is the case that matters most: it looks handled,
which is exactly how a rejected certificate or a dead dependency ends
up invisible.

``web_search`` stands in for any tool here — the behaviour under test
belongs to ``execute_tool``, not to the search path.
"""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from src.domains.dto import ToolCallDTO
from src.infrastructure.exceptions import PageReadError
from src.infrastructure.tools.tool_registry_static import ToolRegistryStatic

_LOGGER = "src.shared.logger._logger"


def _chained(outer: BaseException, inner: BaseException) -> BaseException:
    """``outer`` as if it had been raised ``from inner``."""
    outer.__cause__ = inner
    return outer


class TestToolFailureLogging(unittest.IsolatedAsyncioTestCase):
    def _config(self) -> MagicMock:
        config = MagicMock()
        config.web_search.provider = "searxng"
        config.web_search.summarize = False
        return config

    async def _failing_tool(self, error: BaseException):
        config = self._config()
        with patch(
            "src.infrastructure.tools.tool_registry_static.system_config", config
        ):
            registry = ToolRegistryStatic(llm=MagicMock())
            with (
                patch(
                    "src.infrastructure.tools.tool_registry_static.SearchServiceClient"
                ) as client_cls,
                self.assertLogs(_LOGGER, level="ERROR") as logs,
            ):
                client_cls.return_value.search = AsyncMock(side_effect=error)
                result = await registry.execute_tool(
                    ToolCallDTO(
                        id="call_1", name="web_search", parameters={"query": "q"}
                    )
                )
        return result, "".join(logs.output)

    async def test_a_typed_tool_failure_is_logged_with_its_cause(self):
        error = _chained(
            PageReadError(message="could not fetch 'https://a'", error_code=502),
            ConnectionError("certificate verify failed: self-signed certificate"),
        )

        result, logged = await self._failing_tool(error)

        self.assertIn("web_search", logged)
        self.assertIn("could not fetch 'https://a'", logged)
        self.assertIn("certificate verify failed", logged)
        # The agent still only gets the generic message.
        self.assertFalse(result.success)
        self.assertEqual(result.error_message, "could not fetch 'https://a'")

    async def test_an_untyped_tool_failure_is_logged(self):
        # An unexpected error is logged as it is: unlike a typed one it
        # carries its own text, so it needs no unwrapping.
        _, logged = await self._failing_tool(RuntimeError("the adapter blew up"))

        self.assertIn("web_search", logged)
        self.assertIn("the adapter blew up", logged)


if __name__ == "__main__":
    unittest.main()

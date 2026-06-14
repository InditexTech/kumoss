# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from src.shared.exceptions import ExceptionHandler


class LLMError(ExceptionHandler):
    """Base exception for the LLM domain."""

    pass


class LLMResponseError(ExceptionHandler):
    """Raised when an LLM response is invalid or incomplete after retries."""

    pass


class TemplateRendererNotFound(ExceptionHandler):
    """Raised when a prompt template is not found"""

    pass


class TemplateRendererArgErr(ExceptionHandler):
    """Raised when a wrong number of arguments have been passed to the renderer function"""

    pass


class ToolsDefinitionEmpty(ExceptionHandler):
    """Raised when a list of retrieved tools definitions is empty"""

    pass


class HistoryLastTurnError(ExceptionHandler):
    """Raised when trying to fetch the last history Turn on an empty history"""

    pass


class SessionNotInitializeError(ExceptionHandler):
    """Raised when trying to update a non initialized session"""

    pass


class SessionNotFound(ExceptionHandler):
    """Raised when a session with a given ID does not exist"""

    pass


class ToolExecutionsExceeded(ExceptionHandler):
    """Raised when the chain tool executions has reached the limit"""

    pass


class SentinelToolError(ExceptionHandler):
    """Raised when a sentinel tool is not included in the tool list"""

    pass


class SentinelToolNotFound(ExceptionHandler):
    """Raised when an inference with multiple tools don't define a sentinel tool"""

    pass


class ErrorToolResult(ExceptionHandler):
    """Raised when an tool execution result has failed and the process has to be terminated"""

    pass


class ErrorToolServiceNotDefined(ExceptionHandler):
    """Raised when a generation with tools is executed in a class without a tool service instance"""

    pass


class UnhandledInferenceFinishReason(ExceptionHandler):
    """Raised when a generation with tools is executed in a class without a tool service instance"""

    pass

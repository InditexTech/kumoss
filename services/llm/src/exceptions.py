# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Typed errors, ported from the Python core.

``ExceptionHandler`` is a verbatim copy of ``src.shared.exceptions`` in
the core: its ``repr`` (used by the page-read fallback warning) and
``str`` must read exactly as they did there.
"""

from typing import override


class ExceptionHandler(Exception):
    def __init__(self, message: str, error_code: int):
        super().__init__(message)
        self.__message: str = message
        self.__error_code: int = error_code

    @property
    def message(self):
        return self.__message

    @property
    def error_code(self):
        return self.__error_code

    @override
    def __str__(self):
        return f"Error {self.__error_code}: {self.__message}"


class InferenceCallAPIError(ExceptionHandler):
    """Raised when all attemps have been exhausted"""

    pass


class SearchEngineError(ExceptionHandler):
    """Raised when the configured search engine call fails"""

    pass


class PageReadError(ExceptionHandler):
    """Raised when a page could not be read or parsed"""

    pass

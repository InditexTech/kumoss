# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

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

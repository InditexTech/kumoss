# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Self, TypeVar

from attrs import define as _attrs_define

T = TypeVar("T", bound="OperationResult")


@_attrs_define
class OperationResult:
    """Raw outcome of the single terraform command a job ran. The
    service does not interpret it: `exit_code` is the process's
    exit status (non-zero means the command failed), and `stdout` /
    `stderr` are passed through verbatim.

        Attributes:
            exit_code (int): Exit status of the terraform process. 0 means the command
                succeeded; any other value is a terraform-level failure
                (diagnostics in `stderr`).
            stdout (str): The command's standard output, verbatim. For `plan` this is
                the human-readable plan text; for `show` (exit code 0) it
                is the plan's JSON representation.
            stderr (str): The command's standard error, verbatim.
    """

    exit_code: int
    stdout: str
    stderr: str

    def to_dict(self) -> dict[str, Any]:
        exit_code = self.exit_code

        stdout = self.stdout

        stderr = self.stderr

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "exit_code": exit_code,
                "stdout": stdout,
                "stderr": stderr,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        exit_code = d.pop("exit_code")

        stdout = d.pop("stdout")

        stderr = d.pop("stderr")

        operation_result = cls(
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
        )

        return operation_result

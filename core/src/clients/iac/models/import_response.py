# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Self, TypeVar

from attrs import define as _attrs_define

T = TypeVar("T", bound="ImportResponse")


@_attrs_define
class ImportResponse:
    """
    Attributes:
        success (bool): True if `terraform init` and `terraform import` both
            succeeded.
        feedback (str): Human-readable diagnostics. On failure, this contains the
            terraform CLI's stderr. On success, this is typically empty.
    """

    success: bool
    feedback: str

    def to_dict(self) -> dict[str, Any]:
        success = self.success

        feedback = self.feedback

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "success": success,
                "feedback": feedback,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        success = d.pop("success")

        feedback = d.pop("feedback")

        import_response = cls(
            success=success,
            feedback=feedback,
        )

        return import_response

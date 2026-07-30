# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Self, TypeVar

from attrs import define as _attrs_define

T = TypeVar("T", bound="ApplyResponse")


@_attrs_define
class ApplyResponse:
    """
    Attributes:
        success (bool): True if `terraform plan` and `terraform apply` both succeeded.
        feedback (str): Human-readable diagnostics. On failure, this contains the
            terraform CLI's stderr. On success, this is typically empty.
        terraform_output (str): Terraform's output (text). Contains the plan output when the
            plan failed, otherwise the apply output.
    """

    success: bool
    feedback: str
    terraform_output: str

    def to_dict(self) -> dict[str, Any]:
        success = self.success

        feedback = self.feedback

        terraform_output = self.terraform_output

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "success": success,
                "feedback": feedback,
                "terraform_output": terraform_output,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        success = d.pop("success")

        feedback = d.pop("feedback")

        terraform_output = d.pop("terraform_output")

        apply_response = cls(
            success=success,
            feedback=feedback,
            terraform_output=terraform_output,
        )

        return apply_response

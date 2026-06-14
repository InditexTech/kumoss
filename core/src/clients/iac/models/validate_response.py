# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define

T = TypeVar("T", bound="ValidateResponse")


@_attrs_define
class ValidateResponse:
    """
    Attributes:
        validation (bool): True if `terraform init`, `terraform validate`, and
            `terraform plan` (when run) all succeeded AND, when
            `get_drift` was requested, no drift was detected.
        feedback (str): Human-readable diagnostics. On failure, this contains the
            terraform CLI's stderr or the parsed drift summary. On
            success, this is typically empty.
        terraform_plan (str): Terraform's plan output (text). May be empty when validation
            failed before plan ran.
        terraform_targets (list[str]): Echoes the `targets` from the request.
    """

    validation: bool
    feedback: str
    terraform_plan: str
    terraform_targets: list[str]

    def to_dict(self) -> dict[str, Any]:
        validation = self.validation

        feedback = self.feedback

        terraform_plan = self.terraform_plan

        terraform_targets = self.terraform_targets

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "validation": validation,
                "feedback": feedback,
                "terraform_plan": terraform_plan,
                "terraform_targets": terraform_targets,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        validation = d.pop("validation")

        feedback = d.pop("feedback")

        terraform_plan = d.pop("terraform_plan")

        terraform_targets = cast(list[str], d.pop("terraform_targets"))

        validate_response = cls(
            validation=validation,
            feedback=feedback,
            terraform_plan=terraform_plan,
            terraform_targets=terraform_targets,
        )

        return validate_response

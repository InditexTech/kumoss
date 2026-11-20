# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Self, TypeVar

from attrs import define as _attrs_define

if TYPE_CHECKING:
    from ..models.action import Action
    from ..models.resource import Resource
    from ..models.subject import Subject


T = TypeVar("T", bound="AccessEvaluationRequest")


@_attrs_define
class AccessEvaluationRequest:
    """
    Attributes:
        subject (Subject):
        action (Action):
        resource (Resource):
    """

    subject: Subject
    action: Action
    resource: Resource

    def to_dict(self) -> dict[str, Any]:
        subject = self.subject.to_dict()

        action = self.action.to_dict()

        resource = self.resource.to_dict()

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "subject": subject,
                "action": action,
                "resource": resource,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.action import Action
        from ..models.resource import Resource
        from ..models.subject import Subject

        d = dict(src_dict)
        subject = Subject.from_dict(d.pop("subject"))

        action = Action.from_dict(d.pop("action"))

        resource = Resource.from_dict(d.pop("resource"))

        access_evaluation_request = cls(
            subject=subject,
            action=action,
            resource=resource,
        )

        return access_evaluation_request

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from typing_extensions import Self

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.action import Action
    from ..models.request_context import RequestContext
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
        context (RequestContext | Unset):
    """

    subject: Subject
    action: Action
    resource: Resource
    context: RequestContext | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        subject = self.subject.to_dict()

        action = self.action.to_dict()

        resource = self.resource.to_dict()

        context: dict[str, Any] | Unset = UNSET
        if not isinstance(self.context, Unset):
            context = self.context.to_dict()

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "subject": subject,
                "action": action,
                "resource": resource,
            }
        )
        if context is not UNSET:
            field_dict["context"] = context

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.action import Action
        from ..models.request_context import RequestContext
        from ..models.resource import Resource
        from ..models.subject import Subject

        d = dict(src_dict)
        subject = Subject.from_dict(d.pop("subject"))

        action = Action.from_dict(d.pop("action"))

        resource = Resource.from_dict(d.pop("resource"))

        _context = d.pop("context", UNSET)
        context: RequestContext | Unset
        if isinstance(_context, Unset):
            context = UNSET
        else:
            context = RequestContext.from_dict(_context)

        access_evaluation_request = cls(
            subject=subject,
            action=action,
            resource=resource,
            context=context,
        )

        return access_evaluation_request

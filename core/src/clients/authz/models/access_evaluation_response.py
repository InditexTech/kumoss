from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from typing_extensions import Self

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.response_context import ResponseContext


T = TypeVar("T", bound="AccessEvaluationResponse")


@_attrs_define
class AccessEvaluationResponse:
    """
    Attributes:
        decision (bool):
        context (ResponseContext | Unset):
    """

    decision: bool
    context: ResponseContext | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        decision = self.decision

        context: dict[str, Any] | Unset = UNSET
        if not isinstance(self.context, Unset):
            context = self.context.to_dict()

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "decision": decision,
            }
        )
        if context is not UNSET:
            field_dict["context"] = context

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.response_context import ResponseContext

        d = dict(src_dict)
        decision = d.pop("decision")

        _context = d.pop("context", UNSET)
        context: ResponseContext | Unset
        if isinstance(_context, Unset):
            context = UNSET
        else:
            context = ResponseContext.from_dict(_context)

        access_evaluation_response = cls(
            decision=decision,
            context=context,
        )

        access_evaluation_response.additional_properties = d
        return access_evaluation_response

    @property
    def additional_keys(self) -> list[str]:
        return list(self.additional_properties.keys())

    def __getitem__(self, key: str) -> Any:
        return self.additional_properties[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self.additional_properties[key] = value

    def __delitem__(self, key: str) -> None:
        del self.additional_properties[key]

    def __contains__(self, key: str) -> bool:
        return key in self.additional_properties

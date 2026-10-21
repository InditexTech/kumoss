from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from typing_extensions import Self

from ..models.action_name import ActionName

T = TypeVar("T", bound="Action")


@_attrs_define
class Action:
    """
    Attributes:
        name (ActionName):
    """

    name: ActionName

    def to_dict(self) -> dict[str, Any]:
        name = self.name.value

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "name": name,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        name = ActionName(d.pop("name"))

        action = cls(
            name=name,
        )

        return action

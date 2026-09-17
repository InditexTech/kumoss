# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Normalized resource identifiers of a pulled Terraform state."""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from typing import Any, ClassVar, cast

from .exceptions import StateReadError
from .identifiers import unique


class StateResourceIds:
    """What a pulled state document tracks, as comparable identifiers.

    ``read`` takes the document ``state pull`` prints and returns one
    identifier per managed resource instance: the ``arn`` attribute when
    the provider records one (AWS), otherwise ``id``. That makes the list
    comparable with what ``/v1/import/scope-resource-ids`` emits for
    every cloud without knowing which cloud the state belongs to. Data
    sources are skipped, child modules are already flat in the pulled
    document, and duplicates are dropped keeping the first occurrence. An
    empty document (a workspace whose backend holds no state yet) is an
    empty list; a document that is not a JSON object is an error the
    caller reports.
    """

    _KEYS: ClassVar[tuple[str, ...]] = ("arn", "id")

    def read(self, state_json: str) -> list[str]:
        if not state_json.strip():
            return []
        try:
            obj: object = json.loads(state_json)
        except json.JSONDecodeError as exc:
            raise self._unparsable() from exc
        if not isinstance(obj, Mapping):
            raise self._unparsable()
        document = cast(Mapping[str, Any], obj)
        return unique(self._identifiers(document))

    def _unparsable(self) -> StateReadError:
        return StateReadError("state pull returned an unparsable state document")

    def _identifiers(self, document: Mapping[str, Any]) -> Iterator[str]:
        resources = document.get("resources")
        for resource_raw in resources if isinstance(resources, list) else []:  # pyright: ignore[reportUnknownVariableType]
            resource = cast(Any, resource_raw)
            if not isinstance(resource, Mapping) or resource.get("mode") != "managed":  # pyright: ignore[reportUnknownMemberType]
                continue
            instances = resource.get("instances")  # pyright: ignore[reportUnknownMemberType]
            for instance_raw in instances if isinstance(instances, list) else []:  # pyright: ignore[reportUnknownVariableType]
                instance = cast(Any, instance_raw)
                if not isinstance(instance, Mapping):
                    continue
                attributes = instance.get("attributes")  # pyright: ignore[reportUnknownMemberType]
                if not isinstance(attributes, Mapping):
                    continue
                identifier = self._identifier(attributes)  # pyright: ignore[reportUnknownArgumentType]
                if identifier is not None:
                    yield identifier

    def _identifier(self, attributes: Mapping[str, Any]) -> str | None:
        for key in self._KEYS:
            value = attributes.get(key)
            if isinstance(value, str) and value:
                return value
        return None

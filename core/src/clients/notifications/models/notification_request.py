# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define

from ..models.notification_request_severity import NotificationRequestSeverity
from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.link import Link
    from ..models.notification_request_context import NotificationRequestContext


T = TypeVar("T", bound="NotificationRequest")


@_attrs_define
class NotificationRequest:
    """
    Attributes:
        kind (str): Event category. Free-form by design; the convention is dotted
            lowercase (e.g., `iac.terraform.plan_completed`,
            `iac.terraform.apply_completed`, `system.error`). Implementations
            MAY route based on this value.
        severity (NotificationRequestSeverity):
        subject (str): Single-line summary suitable for a notification title.
        body (str): Notification body. Markdown is permitted; implementations decide
            whether to render or pass through verbatim.
        audience (list[str] | Unset): Implementation-specific recipient identifiers (e.g., email
            addresses, Slack handles, Teams group IDs). Implementations MAY
            ignore this field if they route by other means.
        links (list[Link] | Unset): Structured links the implementation can render.
        context (NotificationRequestContext | Unset): Free-form structured context for the implementation to use as it
            sees fit. Implementations MUST NOT assume any particular shape.
    """

    kind: str
    severity: NotificationRequestSeverity
    subject: str
    body: str
    audience: list[str] | Unset = UNSET
    links: list[Link] | Unset = UNSET
    context: NotificationRequestContext | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        kind = self.kind

        severity = self.severity.value

        subject = self.subject

        body = self.body

        audience: list[str] | Unset = UNSET
        if not isinstance(self.audience, Unset):
            audience = self.audience

        links: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.links, Unset):
            links = []
            for links_item_data in self.links:
                links_item = links_item_data.to_dict()
                links.append(links_item)

        context: dict[str, Any] | Unset = UNSET
        if not isinstance(self.context, Unset):
            context = self.context.to_dict()

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "kind": kind,
                "severity": severity,
                "subject": subject,
                "body": body,
            }
        )
        if audience is not UNSET:
            field_dict["audience"] = audience
        if links is not UNSET:
            field_dict["links"] = links
        if context is not UNSET:
            field_dict["context"] = context

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.link import Link
        from ..models.notification_request_context import NotificationRequestContext

        d = dict(src_dict)
        kind = d.pop("kind")

        severity = NotificationRequestSeverity(d.pop("severity"))

        subject = d.pop("subject")

        body = d.pop("body")

        audience = cast(list[str], d.pop("audience", UNSET))

        _links = d.pop("links", UNSET)
        links: list[Link] | Unset = UNSET
        if _links is not UNSET:
            links = []
            for links_item_data in _links:
                links_item = Link.from_dict(links_item_data)

                links.append(links_item)

        _context = d.pop("context", UNSET)
        context: NotificationRequestContext | Unset
        if isinstance(_context, Unset):
            context = UNSET
        else:
            context = NotificationRequestContext.from_dict(_context)

        notification_request = cls(
            kind=kind,
            severity=severity,
            subject=subject,
            body=body,
            audience=audience,
            links=links,
            context=context,
        )

        return notification_request

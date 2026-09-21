# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Slack incoming-webhook delivery backend."""

from __future__ import annotations

import json
from itertools import batched

import httpx

from .models import NotificationRequest

_SEVERITY_COLOR: dict[str, str] = {
    "info": "#36a64f",  # green
    "warning": "#f2c744",  # yellow
    "error": "#d93f3f",  # red
    "critical": "#7a0b0b",  # dark red
}

# Attachment fields are capped well under Slack's per-field limit so one
# oversized context value (a full request text, say) cannot push the rest
# of the card out of view.
_MAX_FIELD_VALUE = 1000
_TRUNCATION_MARK = "…"
_MAX_ACTIONS_PER_ATTACHMENT = 5


def _humanize_key(key: str) -> str:
    """``session_id`` → ``Session id``; ``firstQuery`` → ``First query``."""
    words = key.replace("-", "_").split("_")
    spaced = " ".join(words)
    # split camelCase remnants
    out: list[str] = []
    for ch in spaced:
        if ch.isupper() and out and out[-1] not in (" ",):
            out.append(" ")
        out.append(ch.lower())
    text = "".join(out).strip()
    return text[:1].upper() + text[1:] if text else key


def _stringify(value: object) -> str | None:
    """Render a context value for a Slack field; None for values to skip."""
    if value is None:
        return None
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, str):
        text = value.strip()
    elif isinstance(value, (int, float)):
        text = str(value)
    else:
        text = json.dumps(value, ensure_ascii=False, default=str)
    if not text:
        return None
    if len(text) > _MAX_FIELD_VALUE:
        text = text[: _MAX_FIELD_VALUE - len(_TRUNCATION_MARK)] + _TRUNCATION_MARK
    return text


def _context_fields(context: dict) -> list[dict]:
    """Render the free-form ``context`` object as attachment fields.

    The contract says implementations MUST NOT assume any shape, so every
    entry is rendered generically: humanized key as the title, stringified
    value as the body. Empty / null values are dropped so callers can pass
    optional metadata without producing blank fields. Short values sit
    side by side; long ones (request text, error output) get a full row.
    """
    fields: list[dict] = []
    for key, raw in context.items():
        value = _stringify(raw)
        if value is None:
            continue
        fields.append(
            {
                "title": _humanize_key(str(key)),
                "value": value,
                "short": len(value) <= 40 and "\n" not in value,
            }
        )
    return fields


def _audience_value(audience: list[str]) -> str:
    """Comma-join recipients; past the field cap, cut at a recipient boundary."""
    text = ", ".join(audience)
    if len(text) <= _MAX_FIELD_VALUE:
        return text
    shown: list[str] = []
    for recipient in audience:
        if len(_with_hidden([*shown, recipient], len(audience))) > _MAX_FIELD_VALUE:
            break
        shown.append(recipient)
    return _with_hidden(shown, len(audience))


def _with_hidden(shown: list[str], total: int) -> str:
    return f"{', '.join(shown)} +{total - len(shown)} more"


def _build_payload(notification: NotificationRequest) -> dict:
    """Render a NotificationRequest into a Slack incoming-webhook payload.

    Uses the legacy `attachments` shape because it renders consistently
    across Slack workspaces without requiring Block Kit configuration on
    the receiving side.
    """
    attachment: dict = {
        "fallback": notification.subject,
        "color": _SEVERITY_COLOR.get(notification.severity, "#cccccc"),
        "title": notification.subject,
        "text": notification.body,
        "fields": [
            {"title": "Kind", "value": notification.kind, "short": True},
            {"title": "Severity", "value": notification.severity, "short": True},
        ],
    }

    if notification.audience:
        attachment["fields"].append(
            {
                "title": "Audience",
                "value": _audience_value(notification.audience),
                "short": False,
            }
        )

    attachment["fields"].extend(_context_fields(notification.context))

    attachments = [attachment]
    if notification.links:
        first, *rest = batched(
            (
                {"type": "button", "text": link.label, "url": str(link.url)}
                for link in notification.links
            ),
            _MAX_ACTIONS_PER_ATTACHMENT,
        )
        attachment["actions"] = list(first)
        attachments.extend(
            {
                "fallback": notification.subject,
                "color": attachment["color"],
                "actions": list(chunk),
            }
            for chunk in rest
        )

    return {"attachments": attachments}


async def deliver(
    notification: NotificationRequest,
    webhook_url: str,
    client: httpx.AsyncClient,
) -> None:
    """POST a rendered notification to Slack.

    Errors propagate as ``httpx.HTTPError`` (non-2xx answer or transport
    failure) for the application's exception handler to map to the
    contract's 502.
    """
    response = await client.post(
        webhook_url, json=_build_payload(notification), timeout=10.0
    )
    response.raise_for_status()

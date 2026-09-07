# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Slack incoming-webhook delivery backend."""

from __future__ import annotations

import json
import logging
import time

import httpx

from .models import NotificationRequest

logger = logging.getLogger("nebula.notifications.slack")


_SEVERITY_COLOR: dict[str, str] = {
    "info": "#36a64f",  # green
    "warning": "#f2c744",  # yellow
    "error": "#d93f3f",  # red
    "critical": "#7a0b0b",  # dark red
}

# Slack answers webhook errors with a short plain-text reason such as
# ``invalid_payload`` or ``no_service``; anything longer is not Slack's
# and is truncated before it is echoed to the caller.
_MAX_UPSTREAM_TEXT = 200

# Attachment fields are capped well under Slack's per-field limit so one
# oversized context value (a full request text, say) cannot push the rest
# of the card out of view.
_MAX_FIELD_VALUE = 1000
_TRUNCATION_MARK = "…"


class DeliveryError(Exception):
    """Slack rejected or never received the notification.

    ``detail`` is safe to return to the caller: it never contains the
    webhook URL. The URL *is* the Slack credential (anyone holding it can
    post to the channel) and httpx embeds the request URL in the message
    of every ``HTTPStatusError`` / transport error, so the raw exception
    text must not be surfaced.
    """

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


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
                "value": ", ".join(notification.audience),
                "short": False,
            }
        )

    attachment["fields"].extend(_context_fields(notification.context))

    if notification.links:
        attachment["actions"] = [
            {"type": "button", "text": link.label, "url": str(link.url)}
            for link in notification.links
        ]

    return {"attachments": [attachment]}


async def deliver(
    notification: NotificationRequest,
    webhook_url: str,
    client: httpx.AsyncClient,
) -> int:
    """POST a rendered notification to Slack; return Slack's HTTP status.

    Raises ``DeliveryError`` (with a URL-free ``detail``) when Slack
    answers with a non-2xx status or cannot be reached at all.
    """
    payload = _build_payload(notification)
    if logger.isEnabledFor(logging.DEBUG):
        logger.debug("slack payload: %s", json.dumps(payload, ensure_ascii=False))
    started = time.monotonic()
    try:
        response = await client.post(webhook_url, json=payload, timeout=10.0)
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        upstream = exc.response.text.strip()[:_MAX_UPSTREAM_TEXT]
        detail = f"Slack responded with HTTP {exc.response.status_code}"
        if upstream:
            detail += f": {upstream}"
        raise DeliveryError(detail) from exc
    except httpx.HTTPError as exc:
        # Transport-level failure (DNS, connect, read timeout, ...). The
        # class name says what went wrong without repeating the URL.
        raise DeliveryError(
            f"Slack webhook unreachable ({type(exc).__name__})."
        ) from exc
    elapsed_ms = (time.monotonic() - started) * 1000
    logger.info(
        "slack accepted payload (HTTP %d, %.0f ms)", response.status_code, elapsed_ms
    )
    return response.status_code

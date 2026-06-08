"""Slack incoming-webhook delivery backend."""

from __future__ import annotations

import httpx

from .models import NotificationRequest


_SEVERITY_COLOR: dict[str, str] = {
    "info": "#36a64f",       # green
    "warning": "#f2c744",    # yellow
    "error": "#d93f3f",      # red
    "critical": "#7a0b0b",   # dark red
}


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
) -> None:
    """POST a rendered notification to Slack. Raises httpx.HTTPError on failure."""
    payload = _build_payload(notification)
    response = await client.post(webhook_url, json=payload, timeout=10.0)
    response.raise_for_status()

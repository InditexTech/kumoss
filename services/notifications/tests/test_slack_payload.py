# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Rendering tests for the Slack attachment, in particular the free-form
``context`` object that callers use to attach session metadata."""

from __future__ import annotations

from src.models import NotificationRequest
from src.slack import _build_payload


def _request(**overrides) -> NotificationRequest:
    data = {
        "kind": "support.user_question",
        "severity": "warning",
        "subject": "Support request",
        "body": "Please help",
    }
    data.update(overrides)
    return NotificationRequest(**data)


def _fields(payload: dict) -> dict[str, dict]:
    return {f["title"]: f for f in payload["attachments"][0]["fields"]}


def test_context_entries_become_fields_in_order() -> None:
    payload = _build_payload(
        _request(
            context={
                "session_id": "21434e55-fa1f-43c5-ab4a-ecafb4d3729e",
                "first_query": "Create a storage account in west europe with private endpoint",
                "cloud": "azure",
                "has_deletes_or_recreates": True,
            }
        )
    )
    fields = _fields(payload)
    titles = [f["title"] for f in payload["attachments"][0]["fields"]]

    assert titles[:2] == ["Kind", "Severity"]
    assert titles[2:] == [
        "Session id",
        "First query",
        "Cloud",
        "Has deletes or recreates",
    ]
    assert fields["Session id"]["value"] == "21434e55-fa1f-43c5-ab4a-ecafb4d3729e"
    assert fields["Session id"]["short"] is True
    assert fields["First query"]["short"] is False  # long text gets a full row
    assert fields["Cloud"]["value"] == "azure"
    assert fields["Has deletes or recreates"]["value"] == "yes"


def test_empty_and_null_context_values_are_dropped() -> None:
    payload = _build_payload(
        _request(context={"project": None, "environment": "", "pr": "https://x/1"})
    )
    fields = _fields(payload)
    assert "Project" not in fields
    assert "Environment" not in fields
    assert fields["Pr"]["value"] == "https://x/1"


def test_nested_context_is_json_and_long_values_truncated() -> None:
    payload = _build_payload(
        _request(context={"targets": ["a", "b"], "log": "x" * 5000})
    )
    fields = _fields(payload)
    assert fields["Targets"]["value"] == '["a", "b"]'
    assert len(fields["Log"]["value"]) == 1000
    assert fields["Log"]["value"].endswith("…")


def test_no_context_keeps_legacy_shape() -> None:
    payload = _build_payload(_request(audience=["#ops"]))
    titles = [f["title"] for f in payload["attachments"][0]["fields"]]
    assert titles == ["Kind", "Severity", "Audience"]
    assert "actions" not in payload["attachments"][0]


def test_long_audience_is_cut_at_a_recipient_boundary() -> None:
    audience = [f"user{i:03d}@example.com" for i in range(100)]
    payload = _build_payload(_request(audience=audience))
    value = _fields(payload)["Audience"]["value"]
    shown, _, tail = value.rpartition(" +")
    shown_items = shown.split(", ")

    assert len(value) <= 1000
    assert 0 < len(shown_items) < len(audience)
    assert shown_items == audience[: len(shown_items)]
    assert tail == f"{len(audience) - len(shown_items)} more"


def test_five_links_fit_in_a_single_attachment() -> None:
    payload = _build_payload(
        _request(links=[{"label": f"L{i}", "url": f"https://x/{i}"} for i in range(5)])
    )
    assert len(payload["attachments"]) == 1
    assert len(payload["attachments"][0]["actions"]) == 5


def test_links_past_the_fifth_continue_in_follow_up_attachments() -> None:
    payload = _build_payload(
        _request(links=[{"label": f"L{i}", "url": f"https://x/{i}"} for i in range(12)])
    )
    attachments = payload["attachments"]
    labels = [[a["text"] for a in att["actions"]] for att in attachments]

    assert labels == [
        ["L0", "L1", "L2", "L3", "L4"],
        ["L5", "L6", "L7", "L8", "L9"],
        ["L10", "L11"],
    ]
    assert "fields" in attachments[0]
    for extra in attachments[1:]:
        assert extra["fallback"] == attachments[0]["fallback"]
        assert extra["color"] == attachments[0]["color"]
        assert set(extra) == {"fallback", "color", "actions"}


def test_links_render_as_buttons() -> None:
    payload = _build_payload(
        _request(
            links=[
                {
                    "label": "Open session",
                    "url": "https://nebula.example/home/results/1",
                }
            ]
        )
    )
    assert payload["attachments"][0]["actions"] == [
        {
            "type": "button",
            "text": "Open session",
            "url": "https://nebula.example/home/results/1",
        }
    ]

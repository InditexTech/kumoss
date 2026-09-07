<!--
SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)

SPDX-License-Identifier: Apache-2.0
-->

# notifications (reference implementation)

Reference implementation of [`contracts/openapi/notifications.v1.yaml`](../../contracts/openapi/notifications.v1.yaml).

The OSS default for the Nebula notifications contract: posts to a single
Slack channel via an incoming webhook. Intended to be useful out of the
box for hobbyists and serve as a concrete read-the-source example for
anyone writing an alternative implementation (Teams, email, PagerDuty,
etc.) of the same contract.

## What it does

- `POST /v1/notify` — accepts a notification, renders it as a Slack
  attachment (color-coded by severity, with action buttons for any
  links), posts it to `SLACK_WEBHOOK_URL`, returns `202 Accepted` with
  a delivery ID.
- `GET /healthz` — liveness probe.
- Bearer-token auth on `/v1/notify` if `NEBULA_NOTIFICATIONS_TOKEN` is
  set; otherwise accepts any request (local-dev fallback).
- If Slack answers with a non-2xx status or cannot be reached, the
  response is `502 Bad Gateway` (RFC 7807 body). The detail names
  Slack's status and short reply but never the webhook URL — that URL
  is the Slack credential and must not appear in responses or logs.
- Bearer tokens are compared in constant time (`hmac.compare_digest`).

## Configuration

| Env var                       | Required | Description                                  |
|-------------------------------|----------|----------------------------------------------|
| `SLACK_WEBHOOK_URL`           | yes\*    | Slack incoming-webhook URL.                  |
| `NEBULA_NOTIFICATIONS_TOKEN`  | no       | Bearer token clients must present.           |
| `LOG_LEVEL`                   | no       | Service log level (default `INFO`; `DEBUG` also logs the Slack payload). |

\* If unset the service still boots and `/v1/notify` returns
`503 Service Unavailable`, which is useful for smoke-testing the
contract surface without wiring a real backend.

## Troubleshooting

The service logs to stdout (`docker compose logs -f notifications`).
At `INFO` you should see, in order:

1. On boot: `notifications service ready: slack_webhook_configured=True
   bearer_auth_enforced=True ...`. `False` for either means the matching
   env var is empty in `services/notifications/.env`.
2. Per request: `delivery <id> received: kind=... severity=...`, then
   either `delivery <id> delivered to slack (HTTP 200)` or a warning
   with the reason (`SLACK_WEBHOOK_URL is not configured`, `Slack
   responded with HTTP 4xx: <slack reason>`, `bearer token does not
   match ...`).

If no `received` line appears, the request never reached this
container: check the caller (core logs `sending 'kind' notification to
<endpoint>`), the `services.notifications` block in `config.yaml`, and
that the core image was rebuilt after config changes.

## Run locally

```bash
cd services/notifications
uv venv && source .venv/bin/activate
uv pip install -e '.[dev]'
SLACK_WEBHOOK_URL=https://hooks.slack.example/... \
  uvicorn src.main:app --host 0.0.0.0 --port 8080
```

Then in another shell:

```bash
curl -X POST http://localhost:8080/v1/notify \
  -H 'Content-Type: application/json' \
  -d '{"kind":"system.info","severity":"info","subject":"hi","body":"hello"}'
```

## Run in docker compose

The service is wired into the repo-root `docker-compose.yml`. Set
`SLACK_WEBHOOK_URL` and `NEBULA_NOTIFICATIONS_TOKEN` in your
environment (or a `.env` next to `docker-compose.yml`) and run
`docker compose up`.

## Tests

```bash
cd services/notifications
uv pip install -e '.[dev]'
pytest
```

## Verifying conformance

Any implementation of the notifications contract — this one or your
own — can be checked against the contract using the Schemathesis-based
suite at [`../../contracts/conformance/notifications/`](../../contracts/conformance/notifications/).

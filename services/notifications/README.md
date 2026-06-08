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

## Configuration

| Env var                       | Required | Description                                  |
|-------------------------------|----------|----------------------------------------------|
| `SLACK_WEBHOOK_URL`           | yes\*    | Slack incoming-webhook URL.                  |
| `NEBULA_NOTIFICATIONS_TOKEN`  | no       | Bearer token clients must present.           |

\* If unset the service still boots and `/v1/notify` returns
`503 Service Unavailable`, which is useful for smoke-testing the
contract surface without wiring a real backend.

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

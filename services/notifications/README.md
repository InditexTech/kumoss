<!--
SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)

SPDX-License-Identifier: Apache-2.0
-->

# notifications (reference implementation)

Reference implementation of [`contracts/openapi/notifications.v1.yaml`](../../contracts/openapi/notifications.v1.yaml).

The OSS default for the Kumoss notifications contract: posts to a single
Slack channel via an incoming webhook. Intended to be useful out of the
box for hobbyists and serve as a concrete read-the-source example for
anyone writing an alternative implementation (Teams, email, PagerDuty,
etc.) of the same contract.

## What it does

- `POST /v1/notify` — accepts a notification, renders it as a Slack
  attachment (color-coded by severity, with action buttons for any
  links), posts it to `SLACK_WEBHOOK_URL`, returns `202 Accepted` with
  a delivery ID.
- Slack allows five buttons per attachment, so links past the fifth
  continue in follow-up attachments. Field values are capped at 1000
  characters; an audience list over the cap is cut at a recipient
  boundary and ends with `+N more`.
- `GET /healthz` — liveness probe.
- Bearer-token auth on `/v1/notify` if `KUMOSS_NOTIFICATIONS_TOKEN` is
  set; otherwise accepts any request (local-dev fallback). Leave it
  blank in a shared network only for local experimentation — set a
  real token whenever this service is reachable by anyone other than
  the core.
- If Slack answers with a non-2xx status or cannot be reached, the
  response is `502 Bad Gateway` (RFC 7807 body, title `Downstream
  channel error`, no detail). The webhook URL is the Slack credential
  and httpx embeds it in every error message, so nothing from the
  underlying error is echoed.
- Bearer tokens are compared in constant time (`hmac.compare_digest`).
- The contract documents `400`/`403`/`503` (bad body, forbidden,
  channel unavailable). This reference never produces any of them:
  request validation happens before the handler runs (so a bad body is
  a FastAPI `422`, not `400`), there is no authorization concept beyond
  the bearer token, and `503` is impossible because the process
  refuses to boot without `SLACK_WEBHOOK_URL` configured.

## Configuration

| Env var                       | Required | Description                                  |
|-------------------------------|----------|----------------------------------------------|
| `SLACK_WEBHOOK_URL`           | yes      | Slack incoming-webhook URL. The service refuses to start without it. |
| `KUMOSS_NOTIFICATIONS_TOKEN`  | no       | Bearer token clients must present.           |
| `LOG_LEVEL`                   | no       | Root log level (default `INFO`).             |

Configuration is asserted at startup: a missing webhook URL or an
unknown log level raises `ConfigError` and the process exits, so a
deployment that cannot deliver anything fails at boot rather than on
the first request. In `docker compose`, that means the `notifications`
container exits until `services/notifications/.env` sets the URL; the
core treats its notifications as best-effort and keeps working.

## Troubleshooting

The service only reports problems, as `application/problem+json`
responses to the caller and as warnings or errors on stdout
(`docker compose logs -f notifications`); it does not trace deliveries.

- Container exits at boot with `ConfigError`: set `SLACK_WEBHOOK_URL`
  (and a valid `LOG_LEVEL`) in `services/notifications/.env`.
- `401` at the core: `KUMOSS_NOTIFICATIONS_TOKEN` differs between
  `core/.env` and `services/notifications/.env`.
- `502 Downstream channel error`: Slack rejected the payload or was
  unreachable. Check the webhook URL is still valid in Slack.
- Nothing arrives and the core logs `Failed to send '<kind>'
  notification`: check the `services.notifications` block in
  `config.yaml` and that the core image was rebuilt after changing it.

## Run locally

```bash
cd services/notifications
uv sync
SLACK_WEBHOOK_URL=https://hooks.slack.example/... \
  uv run fastapi run src/main.py --port 8080
```

Then in another shell:

```bash
curl -X POST http://localhost:8080/v1/notify \
  -H 'Content-Type: application/json' \
  -d '{"kind":"system.info","severity":"info","subject":"hi","body":"hello"}'
```

## Run in docker compose

The service is wired into the repo-root `docker-compose.yml`, which
loads `services/notifications/.env` (copy `env.sample` to `.env` in
this directory). Set `SLACK_WEBHOOK_URL` and `KUMOSS_NOTIFICATIONS_TOKEN`
there, enable `services.notifications` in the root `config.yaml`, rebuild
the core image, and run `docker compose up`.

## Tests

```bash
cd services/notifications
uv sync --group tooling
uv run pytest
```

## Verifying conformance

Any implementation of the notifications contract — this one or your
own — can be checked against the contract using the Schemathesis-based
suite at [`../../contracts/conformance/notifications/`](../../contracts/conformance/notifications/).

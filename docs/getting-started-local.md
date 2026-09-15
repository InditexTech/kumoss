<!--
SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)

SPDX-License-Identifier: Apache-2.0
-->

# Getting started: Local/non-production deployment

This guide installs Nebula on one machine with Docker Compose, using the bundled stack as shipped. 

Follow it top to bottom; every step says whether a setting is **mandatory** or **optional**.

Reference documents you will be pointed to along the way: [Configuration reference](configuration.md) (`config.yaml`), [Environment variables and secrets](environment-variables.md) (core and sidecar `.env` files), [LiteLLM providers and models](litellm.md), [OIDC setup](oidc-setup.md), [Monitoring with Phoenix](monitoring.md), [Phoenix prompt templates](phoenix-prompt-templates.md), and the sidecar contracts in [`contracts/openapi/`](../contracts/openapi/).

## 1. When to use this deployment

Use the Compose stack to evaluate Nebula, develop on it, run demos, or test changes on a workstation or a throwaway virtual machine that only trusted people can reach.

Do **not** use it for shared or production environments. As shipped it has no TLS, well-known default credentials for PostgreSQL and RustFS, an unauthenticated Phoenix console, and, unless you enable OIDC, **no authentication at all**: every request runs as a built-in local identity that holds the `devops` operation role and the panel `admin` role. For anything shared, read [Getting started: production](getting-started-production.md).

## 2. Prerequisites

- Git, and Docker Engine or Docker Desktop with Docker Compose v2.
- Internet access for the build.
- Credentials for one LLM provider supported by LiteLLM. The checked-in `config.yaml` selects Google Vertex AI models; you can keep them or switch provider in step 5.
- A personal access token for your Git provider (GitHub, Azure DevOps, or GitLab) with permission to push branches and open pull requests on the repositories you will use. Without it you can still run the filtering and generation steps, but pushes fail.
- Cloud credentials for the cloud your OpenTofu/Terraform code targets. They are used by `plan` and `apply` inside the IaC sidecar.
- Several gigabytes of free disk for images and volumes. The first build compiles the web application and installs OpenTofu and Terraform into the IaC image, so it takes several minutes.

Git and Docker are the only things you install on the host. Everything the first build installs — OpenTofu and Terraform — goes into the `iac` container image, and the web application is compiled inside the `proxy` image.

## 3. Components included in the Compose stack

`docker-compose.yml` starts eleven containers on one bridge network. Only the proxy publishes host ports.

| Service | Image | Role | Persistence |
|---|---|---|---|
| `proxy` | built from `nginx/Dockerfile` | Builds and serves the React web application, forwards `/api` to the core and `/monitoring/` to Phoenix, and forwards port 9000 to object storage for artifact downloads. Publishes ports 80 and 9000. | none |
| `core` | built from `core/Dockerfile` | The FastAPI orchestration API. `config.yaml` is copied into this image at build time. | `workspaces` volume (shared with `iac`) |
| `core-db` | `postgres:17` | Sessions, rounds, artifacts metadata, users and roles. | `core_db_data` volume |
| `redis` | `redis:8.8` | Fail-open cache in front of the database. | none |
| `object-storage` | `rustfs/rustfs:latest` | S3-compatible artifact store (reports, plans, code changes). | `object_storage_data` volume |
| `phoenix` | `arizephoenix/phoenix:20.6.0` | Trace collector and UI, and the runtime prompt registry. Served behind `/monitoring/`. | through `phoenix-db` |
| `phoenix-db` | `postgres:17` | Phoenix's own database (traces and prompt versions). | `phoenix_db_data` volume |
| `iac` | built from `services/iac/Dockerfile` | **Mandatory sidecar.** Runs OpenTofu (default) or Terraform commands as asynchronous jobs on the shared workspace. A reference implementation for this deployment model; production deployments implement the contract to their own requirements. | `workspaces` volume |
| `notifications` | built from `services/notifications/Dockerfile` | **Optional sidecar.** Posts to a Slack incoming webhook. Exits at start-up until `SLACK_WEBHOOK_URL` is set; that is expected while the integration is disabled. | none |
| `mapping` | built from `services/mapping/Dockerfile` | **Optional sidecar, disabled by default.** Identity passthrough. | none |
| `authz` | built from `services/authz/Dockerfile` | **Optional sidecar, disabled by default.** Permissive cloud-project check. | none (its JSON role store is container-local) |

Every sidecar container is built and started regardless of whether the core is configured to call it. A disabled sidecar is simply never contacted.

## 4. Copy required environment files

```bash
git clone https://github.com/InditexTech/nebula.git
cd nebula

# Mandatory: the core and the IaC sidecar
cp core/env.sample core/.env
cp services/iac/env.sample services/iac/.env

# Optional: only if you enable notifications in step 8
cp services/notifications/env.sample services/notifications/.env
```

`core/.env` is **mandatory**: Compose refuses to start the `core` service without it. The sidecar `.env` files are optional for Compose, but the IaC one is needed in practice because the bearer token must match on both sides. Every `.env` file is gitignored; never commit one.

You do not need `services/mapping/.env` or `services/authz/.env` for this deployment model.

## 5. Configure the mandatory `config.yaml` values

`config.yaml` at the repository root is the single configuration file. It is **baked into the core image at build time**, so every edit needs `docker compose build core` (the first `docker compose up --build` includes the current file). All fields are documented in the [configuration reference](configuration.md). Do not change settings whose Compose defaults already work; the list below is what to review.

| Setting | Requirement | What to do |
|---|---|---|
| `llm.model`, `llm.small_model` | **Mandatory review** | LiteLLM model strings (`provider/model-id`). The shipped file selects `vertex_ai/claude-sonnet-4-5` and `vertex_ai/gemini-3.7-flash`. Keep them if you have Vertex AI credentials; otherwise pick another provider and model pair from [LiteLLM providers and models](litellm.md). The provider prefix decides which credential variables step 6 needs. |
| `git.provider` | Optional (default `GITHUB`) | `GITHUB`, `AZURE_DEVOPS`, or `GITLAB`. It must match the host of the repositories you will use, because it selects the pull-request API and the host written into the git credential store. Only the public SaaS hosts are supported (`github.com`, `gitlab.com` without subgroups, `dev.azure.com`), and repository URLs must be HTTPS. |
| `services.iac` | **Always on** (no `enabled` flag) | Every mode runs engine commands through the IaC sidecar, so it cannot be disabled. The shipped file points it at `http://iac:8082` with token variable `NEBULA_IAC_TOKEN`. |
| `services.iac.endpoint`, `services.iac.token_env` | Optional | Change only if you rename the Compose service or the token variable. |
| `services.notifications.enabled` | Optional | Set to `true` only when you complete step 8. |
| `oidc.issuer_url`, `oidc.client_id` | Optional | Leave blank to keep authentication disabled on a trusted workstation. Fill them to test a real login flow; see [OIDC setup](oidc-setup.md). |
| `storage.*`, `telemetry.*`, `redis.*`, `database.*`, `http.cors_origins` | Leave as shipped | They already point at the bundled containers (`object-storage:9000`, `phoenix:6006`, `redis:6379`, `core-db`, origin `http://localhost`). Change them only if the defaults are unsuitable, for example when the browser reaches the host under another name (then update `storage.public_endpoint_url` and `http.cors_origins`). |
| `orchestration.*` | Leave as shipped | Iteration limits and the compliance and high-impact locks. |

A minimal local file that keeps everything else at its default. It repeats the two `orchestration` flags on purpose: their code defaults are `false`, so a file that omits them silently turns off the compliance lock and the high-impact lock that the shipped `config.yaml` enables.

```yaml
environment: "development"

services:
  iac:
    endpoint: "http://iac:8082"
    token_env: "NEBULA_IAC_TOKEN"

orchestration:
  enable_compliance_checker: true
  block_on_high_impact: true

llm:
  model: "anthropic/claude-sonnet-5"
  small_model: "anthropic/claude-haiku-4-5"

telemetry:
  collector_url: "http://phoenix:6006/"

storage:
  provider: "RUSTFS"
  endpoint_url: "http://object-storage:9000"
  public_endpoint_url: "http://localhost:9000"

git:
  provider: "GITHUB"
```

Note that the three optional sidecars default to `enabled: false`, while `services.iac` has no such flag: it is always called, so its `endpoint` and `token_env` must be present (the code defaults for both are empty). Likewise, `orchestration.enable_compliance_checker` and `orchestration.block_on_high_impact` default to `false` in code and to `true` in the shipped file.

## 6. Configure `core/.env`

Every variable is documented in [Environment variables and secrets](environment-variables.md). The effective minimum for this deployment:

| Variable | Requirement | Notes |
|---|---|---|
| LLM provider credentials | **Mandatory** | The variables LiteLLM requires for the provider prefix of `llm.model` and `llm.small_model`, for example `ANTHROPIC_API_KEY`, or `VERTEXAI_PROJECT`, `VERTEXAI_LOCATION`, and `VERTEXAI_CREDENTIALS`. The core refuses to boot with `LLM credentials missing from environment: ...` when it can detect a missing variable. Names per provider: [LiteLLM providers and models](litellm.md#provider-specific-credential-variables). |
| `NEBULA_IAC_TOKEN` | **Mandatory, non-empty** | Bearer token the core sends to the IaC sidecar. Must equal the value in `services/iac/.env`. An empty value aborts the boot. |
| `GIT_USER`, `GIT_TOKEN` | Mandatory for pushes and pull requests | Account and personal access token at the provider in `git.provider`. When either is empty the core boots with a warning and pushes fail later. |
| `NEBULA_SQL_DATABASE_URL` | Mandatory (keep the sample value) | The sample `postgresql://postgres:postgres@core-db:5432/nebula` matches the bundled `core-db` container. |
| `RUSTFS_ACCESS_KEY`, `RUSTFS_SECRET_KEY` | Keep the sample values | `rustfsadmin` / `rustfsadmin` match the bundled `object-storage` container. Change both here and in `docker-compose.yml` together, or not at all. |
| `NEBULA_NOTIFICATIONS_TOKEN` | Only when notifications are enabled | Must equal the value in `services/notifications/.env`. |
| `NEBULA_MAPPING_TOKEN`, `NEBULA_AUTHZ_TOKEN` | Ignored while those sidecars are disabled | The sample placeholders can stay. |

Redis needs no variable: the core falls back to `redis://redis:6379/0`. Nothing OIDC-related goes in this file.

Fictitious example for Anthropic models:

```dotenv
ANTHROPIC_API_KEY=sk-example-not-a-real-key

NEBULA_IAC_TOKEN=local-example-token-not-for-production
NEBULA_NOTIFICATIONS_TOKEN=dev-notifications-token
NEBULA_MAPPING_TOKEN=dev-mapping-token
NEBULA_AUTHZ_TOKEN=dev-authz-token

GIT_USER=nebula-bot
GIT_TOKEN=ghp_example_not_a_real_token

RUSTFS_ACCESS_KEY=rustfsadmin
RUSTFS_SECRET_KEY=rustfsadmin
NEBULA_SQL_DATABASE_URL=postgresql://postgres:postgres@core-db:5432/nebula
```

## 7. Configure `services/iac/.env`

| Variable | Requirement | Notes |
|---|---|---|
| `NEBULA_IAC_TOKEN` | **Must match `core/.env`** | The sidecar checks the bearer on every `/v1/*` call when this is set; a mismatch returns `401` to the core and every session fails at validation. An empty value disables the check on the sidecar side, which is acceptable only on an isolated workstation. |
| `IAC_BINARY` | Optional, default `tofu` | `IAC_BINARY=tofu` (the bundled default) runs OpenTofu 1.12.6 (MPL-2.0). `IAC_BINARY=terraform` selects the bundled HashiCorp Terraform 1.16.0, which is BUSL-1.1 licensed; selecting it makes your use subject to that license. The service refuses to start if the binary cannot be found. |
| Cloud credentials | Depends on your Terraform providers | Set the variables your providers read: `ARM_CLIENT_ID`, `ARM_CLIENT_SECRET`, `ARM_TENANT_ID` (and usually `ARM_SUBSCRIPTION_ID`) for Azure; `GOOGLE_CREDENTIALS` or `GOOGLE_APPLICATION_CREDENTIALS` for Google Cloud; `AWS_ACCESS_KEY_ID` plus `AWS_SECRET_ACCESS_KEY` and `AWS_REGION`, or `AWS_PROFILE`, for AWS. [`services/iac/PROVIDERS.md`](../services/iac/PROVIDERS.md) lists the minimum set per cloud and authentication method. |

Missing or invalid cloud credentials do **not** stop the container. The engine runs anyway, and its own authentication error appears in the session as a failed `plan` or `apply`.

Fictitious example targeting AWS:

```dotenv
NEBULA_IAC_TOKEN=local-example-token-not-for-production
IAC_BINARY=tofu

AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE
AWS_SECRET_ACCESS_KEY=example-not-a-real-secret-access-key
AWS_REGION=eu-west-1
```

## 8. Optionally configure notifications

Skip this step unless you want Slack messages when a compliance check fails, a report is classified as high impact, an apply fails, or a user sends a support request from the web application's header.

1. In `config.yaml`, set `services.notifications.enabled: true`. Keep the shipped endpoint `http://notifications:8080` and token variable `NEBULA_NOTIFICATIONS_TOKEN`.
2. In `core/.env`, set `NEBULA_NOTIFICATIONS_TOKEN` to a non-empty value.
3. In `services/notifications/.env`, set the **same** `NEBULA_NOTIFICATIONS_TOKEN` and a `SLACK_WEBHOOK_URL`. The container refuses to start without the webhook URL.
4. Rebuild the core image (step 9 does this).

```dotenv
NEBULA_NOTIFICATIONS_TOKEN=local-example-notifications-token
SLACK_WEBHOOK_URL=https://hooks.slack.example.invalid/services/T000/B000/example
LOG_LEVEL=INFO
```

Treat the webhook URL as a secret: anyone holding it can post to the channel. Notifications are best-effort; a failed delivery is logged by the core and never fails a session.

## 9. Build and start Nebula

```bash
docker compose up --build
```

Add `-d` to run in the background. The first build downloads base images, installs the Python dependencies of the core and sidecars, downloads both IaC engines and the three cloud CLIs, and compiles the React application inside the nginx image.

After **any later change to `config.yaml`**, rebuild the core image and restart it:

```bash
docker compose build core
docker compose up -d core
```

Changes to a `.env` file only need the affected container restarted (`docker compose up -d core`, `docker compose up -d iac`). During core development, `docker compose up --watch` syncs `core/` into the running container; it does not sync `config.yaml`.

## 10. Verify services

```bash
docker compose ps
```

Expected: `proxy`, `core`, `core-db`, `redis`, `object-storage`, `phoenix`, `phoenix-db`, `iac`, `mapping`, and `authz` running. A `notifications` container that has exited is normal while the integration is disabled.

```bash
docker compose logs -f core
```

Wait for the start-up sequence to finish: database initialisation, Redis, the object-storage bucket, Phoenix prompt seeding (`Prompt seeding complete: N created, M already present`), git credentials, and finally `Application startup complete`. Boot is strict: if any of those steps fails the container exits with the reason in the log.

```bash
curl http://localhost/api/v1/auth/config
```

This is the only public API route. With authentication disabled it returns a JSON document with an empty `issuer_url`.

## 11. Open the web application and Phoenix

| URL | What it serves |
|---|---|
| <http://localhost> | Nebula web application and the API under `/api/v1/...` |
| <http://localhost/monitoring/> | Phoenix: traces of every run and the prompt registry |
| `http://localhost:9000` | Presigned artifact downloads opened by the web application; not a page to visit |

Open <http://localhost>. With authentication disabled you land directly in the wizard as the local developer. Enter a repository your Git token can push to, choose the cloud and scope, describe the infrastructure you need, and follow the session. What each mode does is explained in [Operating modes](modes.md); your sessions and the admin panel are described in [Admin portal](admin-portal.md).

Open <http://localhost/monitoring/> to see the traces of the run under the `dev-terraform-day2` project and the seeded prompts under **Prompts**. Phoenix receives prompts, plans, and generated code in clear text and has no authentication of its own in this stack; see [Monitoring with Phoenix](monitoring.md).

## 12. Stop or reset the stack

### Stop Nebula
```bash
docker compose down            # stop; named volumes are kept
```

This keeps the named volumes (databases, artifacts, workspaces), so sessions and prompts survive a restart. The authz sidecar's own JSON role store is container-local and is lost when that container is recreated; it is unrelated to Nebula's operation and panel roles, which live in `core-db`. See [services/authz/README.md](../services/authz/README.md) if you need the sidecar's roles to persist.

### Delete Nebula volumes
```bash
docker compose down -v         # stop and delete all volumes
```

**Deleting the volumes removes the session database, the artifacts, the Phoenix traces and the prompts you edited in Phoenix**, and any in-progress workspaces. The next start seeds the prompts again from `core/prompts/seed/`. There are no database migrations: after pulling a version that changes the schema, recreate the `core_db_data` volume or migrate it by hand.

## 13. Troubleshooting

- **Core exits with `LLM credentials missing from environment`.** The variables for the provider prefix in `llm.model` or `llm.small_model` are not in `core/.env`. See [LiteLLM troubleshooting](litellm.md#troubleshooting).
- **Core exits with `Services the core calls have no bearer token`.** `NEBULA_IAC_TOKEN`, or the `NEBULA_*_TOKEN` of an enabled optional sidecar, is empty in `core/.env`.
- **Core exits with `Missing env variable for nebula database`.** `NEBULA_SQL_DATABASE_URL` is empty in `core/.env`.
- **Core exits with `Phoenix unreachable after 8 attempts`.** Prompt seeding could not reach `telemetry.collector_url`. Check that `phoenix` is running and restart the core.
- **Every session fails at validation with a `401` from the IaC sidecar.** `NEBULA_IAC_TOKEN` differs between `core/.env` and `services/iac/.env`.
- **`iac` container exits at start-up.** `IAC_BINARY` names a binary that is not in the image; use `tofu` or `terraform`.
- **`notifications` container exits immediately.** Expected while the sidecar is disabled. If you enabled it, set `SLACK_WEBHOOK_URL`.
- **A `config.yaml` change has no effect.** Rebuild the core image with `docker compose build core`; `curl http://localhost/api/v1/auth/config` shows what the core actually serves.
- **Plan or apply fails with a provider authentication error.** Cloud credentials in `services/iac/.env` are absent or invalid.
- **`plan` fails with `permission denied` on a state or plan file.** The `workspaces` volume was created by an older stack that ran as root. Run `docker compose down`, then `docker run --rm -v nebula_workspaces:/workspaces alpine chown -R 10001:10001 /workspaces`, and start again.
- **Push or pull-request creation fails.** Check `GIT_USER`, `GIT_TOKEN`, that `git.provider` matches the repository host, and the token's permissions.
- **A session aborts with `Prompt not found: <name>`.** The prompt is missing in Phoenix or has no version tagged with the `environment` value. See [Phoenix prompt templates](phoenix-prompt-templates.md).
- **The browser cannot download an artifact.** Port 9000 must be reachable from the browser under the host in `storage.public_endpoint_url` (`http://localhost:9000` by default).

## 14. Next steps

- Hand the [user guide](user-guide.md) and [FAQ](faq.md) to the people who will make requests.
- Review and adapt the seeded prompts; they encode a generic policy, not yours: [Phoenix prompt templates](phoenix-prompt-templates.md).
- Try a real login flow with your identity provider: [OIDC setup](oidc-setup.md).
- Learn the role model and the admin panel: [Admin portal](admin-portal.md).
- Before sharing the instance with anyone, switch to the production model: [Getting started: production](getting-started-production.md).

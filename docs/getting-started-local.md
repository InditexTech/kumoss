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

- Git, and Docker Engine with Docker Compose v2.
- Internet access for the build.
- Credentials for one LLM provider supported by LiteLLM.
- A personal access token for your Git provider with permission to push branches and open pull requests.
- Cloud credentials for the cloud your OpenTofu/Terraform code targets, in **two grants**, both given to the IaC sidecar in step 6:
  - **Provider credentials** — the resources `plan` and `apply` create.
  - **State-backend credentials** — the remote state file `init` reads and writes. This deployment assumes the default: **the repository you point Nebula at declares its own backend** (`terraform { backend ... }`), so this grant must reach the bucket or container that block names. If you would rather have Nebula keep state for you, or supply the backend some other way, see [state backends](terraform-state-backends.md).

Git and Docker are the only things you install on the host. Everything the first build installs — OpenTofu and Terraform — goes into the `iac` container image, and the web application is compiled inside the `proxy` image.

## 3. Copy required environment files

```bash
git clone https://github.com/InditexTech/nebula.git
cd nebula

# Mandatory: the core and the IaC sidecar
cp core/env.sample core/.env
cp services/iac/env.sample services/iac/.env

# Optional: only if you enable notifications in step 8
cp services/notifications/env.sample services/notifications/.env
```

`core/.env` is **mandatory**: Compose refuses to start the `core` service without it. The sidecar `.env` files are optional for Compose, but the IaC one is needed in practice. Every `.env` file is gitignored; never commit one.

You do not need `services/mapping/.env` or `services/authz/.env` for this deployment model.

## 4. Configure the mandatory `config.yaml` values

`config.yaml` at the repository root is the single configuration file. It is **baked into the core image at build time**, so every edit needs `docker compose build core`. All fields are documented in the [configuration reference](configuration.md). Do not change default settings; the list below is what to review.

| Setting | Requirement | What to do |
|---|---|---|
| `llm.model`, `llm.small_model` | **Mandatory review** | LiteLLM model strings (`provider/model-id`). The shipped file selects `vertex_ai/claude-sonnet-4-5` and `vertex_ai/gemini-3.7-flash`. Keep them if you have Vertex AI credentials; otherwise pick another provider and model pair from [LiteLLM providers and models](litellm.md). The provider prefix decides which credential variables step 6 needs. |
| `git.provider` | Optional (default `GITHUB`) | `GITHUB`, `AZURE_DEVOPS`, or `GITLAB`. It must match the host of the repositories you will use, because it selects the pull-request API and the host written into the git credential store. Only the public SaaS hosts are supported (`github.com`, `gitlab.com` without subgroups, `dev.azure.com`), and repository URLs must be HTTPS. |
| `services.iac` | **Always on** (no `enabled` flag) | Every mode runs engine commands through the IaC sidecar, so it cannot be disabled. The shipped file points it at `http://iac:8082` with token variable `NEBULA_IAC_TOKEN`. |
| `services.iac.endpoint`, `services.iac.token_env` | Optional | Change only if you rename the Compose service or the token variable. |
| `services.notifications.enabled` | Optional | Set to `true` only when you complete step 8. |
| `oidc.issuer_url`, `oidc.client_id` | Optional | Leave blank to keep authentication disabled on a trusted workstation. Fill them to test a real login flow; see [OIDC setup](oidc-setup.md). |
| `storage.*`, `telemetry.*`, `redis.*`, `database.*`, `http.cors_origins` | Leave as shipped | They already point at the bundled containers (`object-storage:9000`, `phoenix:6006`, `redis:6379`, `core-db`, origin `http://localhost`). Change them only if the defaults are unsuitable, for example when the browser reaches the host under another name (then update `storage.public_endpoint_url` and `http.cors_origins`). |
| `storage.terraform_state_bucket` | Leave as shipped (blank) | Blank means state lives in the backend your repository declares, which is what this guide assumes. Set a bucket name only if you want Nebula to own state instead — one line on the bundled RustFS, and rebuild the core image afterwards: [state backends](terraform-state-backends.md). |
| `orchestration.*` | Leave as shipped | Iteration limits and the compliance and high-impact locks. |

A minimal local file that keeps everything else at its default. It repeats the two `orchestration` flags on purpose: their code defaults are `false`, so a file that omits them silently turns off the compliance lock and the high-impact lock that the shipped `config.yaml` enables. `storage.terraform_state_bucket` is spelled out for the same reason, in the other direction: its code default is a bucket name, so dropping the key would turn Nebula-managed state on.

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
  # Blank (as shipped): each repository declares its own backend.
  # Keep the key — deleting it turns Nebula-managed state on.
  terraform_state_bucket:

git:
  provider: "GITHUB"
```

Note that the three optional sidecars default to `enabled: false`, while `services.iac` has no such flag: it is always called, so its `endpoint` and `token_env` must be present (the code defaults for both are empty). Likewise, `orchestration.enable_compliance_checker` and `orchestration.block_on_high_impact` default to `false` in code and to `true` in the shipped file, and `storage.terraform_state_bucket` defaults to `nebula-terraform-state` in code and ships blank.

## 5. Configure `core/.env`

Every variable is documented in [Environment variables and secrets](environment-variables.md). The effective minimum for this deployment:

| Variable | Requirement | Notes |
|---|---|---|
| LLM provider credentials | **Mandatory** | The variables LiteLLM requires for the provider prefix of `llm.model` and `llm.small_model`, for example `ANTHROPIC_API_KEY`, or `VERTEXAI_PROJECT`, `VERTEXAI_LOCATION`, and `VERTEXAI_CREDENTIALS`. The core refuses to boot with `LLM credentials missing from environment: ...` when it can detect a missing variable. Names per provider: [LiteLLM providers and models](litellm.md#provider-specific-credential-variables). |
| `NEBULA_IAC_TOKEN` | **Mandatory, non-empty** | Bearer token the core sends to the IaC sidecar. Must equal the value in `services/iac/.env`. An empty value aborts the boot. |
| `GIT_USER`, `GIT_TOKEN` | Mandatory for pushes and pull requests | Account and personal access token at the provider in `git.provider`. When either is empty the core boots with a warning and pushes fail later. |
| `NEBULA_SQL_DATABASE_URL` | Mandatory (keep the sample value) | The sample `postgresql://postgres:postgres@core-db:5432/nebula` matches the bundled `core-db` container. |
| `RUSTFS_ACCESS_KEY`, `RUSTFS_SECRET_KEY` | Keep the sample values | `rustfsadmin` / `rustfsadmin` match the bundled `object-storage` container. They serve the artifacts bucket (and the state bucket too, if you switch state to Nebula). Change both here and in `docker-compose.yml` together, or not at all. |
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

## 6. Configure `services/iac/.env`

| Variable | Requirement | Notes |
|---|---|---|
| `NEBULA_IAC_TOKEN` | **Must match `core/.env`** | The sidecar checks the bearer on every `/v1/*` call when this is set; a mismatch returns `401` to the core and every session fails at validation. An empty value disables the check on the sidecar side, which is acceptable only on an isolated workstation. |
| `IAC_BINARY` | Optional, default `tofu` | `IAC_BINARY=tofu` (the bundled default) runs OpenTofu 1.12.6 (MPL-2.0). `IAC_BINARY=terraform` selects the bundled HashiCorp Terraform 1.16.0, which is BUSL-1.1 licensed; selecting it makes your use subject to that license. The service refuses to start if the binary cannot be found. |
| `IAC_BACKEND_CONFIG` | Leave unset | Only for deployments that supply the backend's *values* from a file mounted in this container instead of the repository's own block: [state backends](terraform-state-backends.md#model-3--sidecar-supplied-backend-configuration). |
| **Provider credentials** | Mandatory for `plan` and `apply` | The variables your Terraform providers read: `ARM_CLIENT_ID`, `ARM_CLIENT_SECRET`, `ARM_TENANT_ID` (and usually `ARM_SUBSCRIPTION_ID`) for Azure; `GOOGLE_CREDENTIALS` or `GOOGLE_APPLICATION_CREDENTIALS` for Google Cloud; `AWS_ACCESS_KEY_ID` plus `AWS_SECRET_ACCESS_KEY` and `AWS_REGION`, or `AWS_PROFILE`, for AWS. [`services/iac/PROVIDERS.md`](../services/iac/PROVIDERS.md) lists the minimum set per cloud and authentication method. |
| **State-backend credentials** | Mandatory for `init` | Access to the state store your repository's `terraform { backend ... }` block names — see *Backend minimums* in [`PROVIDERS.md`](../services/iac/PROVIDERS.md) and [Two sets of credentials on the sidecar](terraform-state-backends.md#two-sets-of-credentials-on-the-sidecar). |

Missing or invalid cloud credentials do **not** stop the container.

### Examples
For more information see [`PROVIDERS.md`](../services/iac/PROVIDERS.md).

#### AWS

```dotenv
# The resources the modules create and the S3 bucket the repository's
# backend block names.
AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE
AWS_SECRET_ACCESS_KEY=example-not-a-real-secret-access-key
AWS_REGION=eu-west-1
```

#### AZURE

```dotenv
# Provider grant: a service principal with a client secret.
ARM_SUBSCRIPTION_ID=00000000-0000-0000-0000-000000000000
ARM_TENANT_ID=11111111-1111-1111-1111-111111111111
ARM_CLIENT_ID=22222222-2222-2222-2222-222222222222
ARM_CLIENT_SECRET=example-not-a-real-client-secret

# Access key of the storage account for state backend block
# Drop it and add ARM_USE_AZUREAD=true instead to let the principal
# itself authenticate to the state container over Entra ID RBAC.
ARM_ACCESS_KEY=ZXhhbXBsZS1ub3QtYS1yZWFsLXN0b3JhZ2UtYWNjb3VudC1rZXk=
```

#### GCP

Targeting Google Cloud, with the state bucket in a second project:

```dotenv
# Provider grant: a service-account key as inline JSON.
GOOGLE_PROJECT=demo-platform-project
GOOGLE_CREDENTIALS={"type":"service_account","project_id":"demo-platform-project","private_key":"<service-account-private-key-pem>","client_email":"nebula@demo-platform-project.iam.gserviceaccount.example.invalid"}

# State-backend grant.
# Omit it and `init` reuses GOOGLE_CREDENTIALS.

GOOGLE_BACKEND_CREDENTIALS={"type":"service_account","project_id":"demo-state-project","private_key":"<state-account-private-key-pem>","client_email":"nebula-state@demo-state-project.iam.gserviceaccount.example.invalid"}
```

`GOOGLE_CREDENTIALS` and `GOOGLE_BACKEND_CREDENTIALS` take the key JSON;

## 7. Optionally configure notifications

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

Wait for the start-up sequence to finish: database initialisation, Redis, the object-storage artifacts bucket, Phoenix prompt seeding (`Prompt seeding complete: N created, M already present`), git credentials, and finally `Application startup complete`. Boot is strict: if any of those steps fails the container exits with the reason in the log.

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

**Deleting the volumes removes the session database, the artifacts, the Phoenix traces and the prompts you edited in Phoenix and any in-progress workspaces**,. Terraform state is untouched: it lives in the backend your repository declares.

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
- **`init` fails on the state backend, or every plan wants to recreate existing resources.** By default the backend is the repository's own: one that declares a backend needs that backend's credentials in `services/iac/.env`, and one that declares none plans against local state that dies with the workspace. Other causes, and the Nebula-managed case, are in [Troubleshooting state backends](terraform-state-backends.md#troubleshooting).
- **`iac` container exits with `IAC_BACKEND_CONFIG points at ...`.** Unset the variable, or mount the file at that path inside the container and make it readable by uid `10001`.

## 14. Next steps

- Hand the [user guide](user-guide.md) and [FAQ](faq.md) to the people who will make requests.
- Review and adapt the seeded prompts; they encode a generic policy, not yours: [Phoenix prompt templates](phoenix-prompt-templates.md).
- Try a real login flow with your identity provider: [OIDC setup](oidc-setup.md).
- Learn the role model and the admin panel: [Admin portal](admin-portal.md).
- Decide where Terraform state should live before you point Nebula at anything real: [Terraform/OpenTofu state backends](terraform-state-backends.md).
- Before sharing the instance with anyone, switch to the production model: [Getting started: production](getting-started-production.md).

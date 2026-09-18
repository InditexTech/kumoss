<!--
SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)

SPDX-License-Identifier: Apache-2.0
-->

# Environment variables and secrets

Nebula keeps every secret in environment variables. `config.yaml` holds only non-secret settings and, where a secret is needed, the *name* of the variable that carries it (fields ending in `_env`). This guide documents every variable in `core/env.sample` and in the four sidecar `env.sample` files, plus the variables that the IaC engine and the LLM providers read on their own.

Each `env.sample` is a template: copy it to a `.env` file next to it (`core/.env`, `services/<name>/.env`). Docker Compose loads those `.env` files per container. `core/.env` is required for the stack to start; the sidecar files are optional and the containers fall back to their built-in defaults when a file is missing.

All example values in this guide are fictitious. Never commit a `.env` file; they are gitignored.

Which files you need depends on the deployment model: [Getting started: local/non-production](getting-started-local.md) needs `core/.env` and `services/iac/.env` (plus the notifications file when enabled); [Getting started: production](getting-started-production.md) replaces the files with a secret store but keeps the same variable names.

Related guides: [Configuration](configuration.md), [LiteLLM providers and models](litellm.md), [OIDC setup](oidc-setup.md).

## Core (`core/env.sample`)

The core reads variables through the names configured in `config.yaml`. The table lists the default names; if you rename a `*_env` field, rename the variable accordingly.

| Variable | Requirement | Default / fallback | Meaning | Activated by | Must match | Checked |
|---|---|---|---|---|---|---|
| LLM provider credentials (for example `ANTHROPIC_API_KEY`, `VERTEXAI_PROJECT`) | Mandatory for the provider selected by `llm.model` and `llm.small_model` | none | Credentials that LiteLLM reads for the configured provider. Names follow LiteLLM conventions; see [LiteLLM providers and models](litellm.md). | `llm.model`, `llm.small_model`, `llm.model_list` | nothing | At boot for providers LiteLLM can validate; otherwise on the first LLM call |
| `NEBULA_IAC_TOKEN` | Mandatory (the IaC sidecar is always called; it has no `enabled` flag) | sample value `dev-iac-token` | Bearer token the core sends to the IaC sidecar. | always | `NEBULA_IAC_TOKEN` in `services/iac/.env` | At boot: an empty token aborts startup |
| `NEBULA_MAPPING_TOKEN` | Conditional | sample value `dev-mapping-token` | Bearer token for the mapping sidecar. | `services.mapping.enabled: true` | `NEBULA_MAPPING_TOKEN` in `services/mapping/.env` | At boot when enabled |
| `NEBULA_NOTIFICATIONS_TOKEN` | Conditional | sample value `dev-notifications-token` | Bearer token for the notifications sidecar. | `services.notifications.enabled: true` | `NEBULA_NOTIFICATIONS_TOKEN` in `services/notifications/.env` | At boot when enabled |
| `NEBULA_AUTHZ_TOKEN` | Conditional | sample value `dev-authz-token` | Bearer token for the authorization sidecar. | `services.authz.enabled: true` | `NEBULA_AUTHZ_TOKEN` in `services/authz/.env` | At boot when enabled |
| `GIT_USER` | Optional but needed for pushes | empty | Account username at the Git provider selected by `git.provider`. | `git.provider` (default `GITHUB`) | nothing | At boot the core logs a warning when empty; pushes fail later unless credentials come from elsewhere |
| `GIT_TOKEN` | Optional but needed for pushes | empty | Personal access token for that account. Written with `GIT_USER` into `~/.git-credentials` inside the core container at boot. | `git.provider` | nothing | Same as `GIT_USER` |
| `RUSTFS_ACCESS_KEY` | Conditional | `rustfsadmin` when `storage.provider` is `RUSTFS`; empty otherwise | Access key for the S3-compatible store, used for the artifacts bucket and — where Nebula-managed state is enabled (`storage.terraform_state_bucket` set; blank as shipped) — for the state bucket too, in which case it is also embedded into the backend block the IaC sidecar executes. | `storage.provider: RUSTFS` (or `S3` with static keys) | `RUSTFS_ACCESS_KEY` on the `object-storage` service in `docker-compose.yml` | At boot: the core creates or checks every configured bucket and aborts if the store is unusable |
| `RUSTFS_SECRET_KEY` | Conditional | `rustfsadmin` when `storage.provider` is `RUSTFS`; empty otherwise | Secret key for the artifact store. For `S3`, leave both keys unset to use the AWS SDK default credential chain (an instance role or workload identity), or set static keys under these same variable names unless you rename `storage.access_key_env` / `storage.secret_key_env`. | as above | `RUSTFS_SECRET_KEY` on `object-storage` | At boot |
| `STORAGE_ACCOUNT_KEY` | Conditional | empty | Shared key of the Azure storage account; also signs download URLs. The account name is derived from `storage.endpoint_url`. | `storage.provider: STORAGE_ACCOUNT` | nothing | At boot: configuration validation fails if empty |
| `NEBULA_SQL_DATABASE_URL` | Mandatory | sample value points at the bundled `core-db` container | Connection URL of Nebula's PostgreSQL database. | `database.nebula_database_url_env` | credentials of the `core-db` service in `docker-compose.yml` | At boot: configuration validation fails if empty, and database initialisation fails if unreachable |
| `NEBULA_REDIS_URL` | Optional | `redis://redis:6379/0` from `redis.default_url` | Redis URL for the session cache. Set it only when the URL embeds a password or points outside the compose network. Cache operations fail open at runtime, but the boot-time ping must succeed. | `redis.redis_url_env` | nothing | At boot: Redis initialisation fails if unreachable |
| `NEBULA_CONFIG` | Optional; not present in `env.sample` | `/etc/nebula/config.yaml` | Path, inside the container, of the configuration file to load. The file must exist at that path (for example through a mounted volume); a missing file silently falls back to built-in defaults. | always | nothing | At boot |
| `APP_VERSION` | Optional; not present in `env.sample` | `0.0.0-dev` | Version string reported by the API's OpenAPI document. Set it from your release pipeline. | always | nothing | never |

Two related facts about the sample file:

- The pre-filled `dev-*-token` placeholders are accepted because the bundled sidecars ship with an empty expected token, which disables their bearer check. That is acceptable only on an isolated workstation.
- Nothing OIDC-related goes in `core/.env`. The single-page application is a public client using PKCE (Proof Key for Code Exchange), and the core validates tokens with the issuer's public keys. All OIDC settings live in `config.yaml`.

## IaC sidecar (`services/iac/env.sample`)

| Variable | Requirement | Default | Meaning | Checked |
|---|---|---|---|---|
| `NEBULA_IAC_TOKEN` | Recommended; mandatory outside an isolated workstation | empty (accepts any bearer) | Token the sidecar requires on every `/v1/*` call. Must equal the core's `NEBULA_IAC_TOKEN`. | Per request: a mismatch returns `401` to the core |
| `IAC_BINARY` | Optional | `tofu` | Name or absolute path of the IaC engine CLI. `tofu` runs the bundled OpenTofu; `terraform` runs the bundled HashiCorp Terraform (BUSL-1.1 licensed; your use is subject to its terms). Any Terraform-compatible engine on `PATH` works. | At boot: the service refuses to start if the binary cannot be found |
| `IAC_BACKEND_CONFIG` | Optional | empty (unset) | Path **inside the sidecar container** to a `.hcl` or `.tfbackend` file of state-backend values, passed to every `init` as `-backend-config=<path>`. Mount the file into the container yourself. It supplies values only — the backend *type* still comes from the workspace's own `terraform { backend "..." }` block — and it has no effect once Nebula-managed state is switched on (`storage.terraform_state_bucket` set), because the core's `backend_override.tf` wins. Blank or whitespace counts as unset. See [Terraform/OpenTofu state backends](terraform-state-backends.md#model-3--sidecar-supplied-backend-configuration). | At boot: the service refuses to start unless the path is a readable file |

The job retention period (how long a finished job stays pollable at `GET /v1/jobs/{job_id}`, one hour) is a constant in `services/iac/src/config.py`, not an environment variable. Jobs live in memory, so a restart also forgets them.

### Cloud credentials for the IaC engine

The IaC sidecar does not interpret cloud credentials. It launches the engine with its **entire container environment inherited and no allowlist**, so every variable in `services/iac/.env` (including `NEBULA_IAC_TOKEN`) is visible to the Terraform and OpenTofu **providers** and to any `external` or `local-exec` code in the repositories you run. The providers read their credentials directly during `init`, `plan`, and `apply`. Missing or invalid credentials never stop the container; the command runs and the engine's own authentication error appears in the job's `stderr`, which the session shows to the user. Keep only the variables the engine needs in that file, and treat the sidecar's environment as exposed to the IaC code it executes.

The sample file lists no cloud variables; add the ones your modules need. [`services/iac/PROVIDERS.md`](../services/iac/PROVIDERS.md) gives the minimum set per cloud and authentication method (service principal, OIDC federation, managed identity, named profile, and so on) plus the state-backend minimums, and [`services/iac/FULL_PROVIDERS.md`](../services/iac/FULL_PROVIDERS.md) lists every variable each provider and backend reads. The table below is a short orientation; the sidecar imposes nothing beyond what the provider supports.

| Cloud | Typical variables | Provider chain (examples, not a complete list) |
|---|---|---|
| Azure (`azurerm`, `azuread`) | `ARM_CLIENT_ID`, `ARM_CLIENT_SECRET`, `ARM_TENANT_ID`, `ARM_SUBSCRIPTION_ID` | Service principal with client secret. Certificate, OIDC federation, and managed identity are other documented provider options. |
| Google Cloud (`google`) | `GOOGLE_APPLICATION_CREDENTIALS` or `GOOGLE_CREDENTIALS` | `GOOGLE_CREDENTIALS` holds the service-account key as JSON content; `GOOGLE_APPLICATION_CREDENTIALS` holds a path to a key file readable inside the container. Set one of them. |
| AWS (`aws`) | `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`, or `AWS_PROFILE` | Static keys, or a profile from a mounted credentials file. Instance roles and web-identity federation are other documented provider options. |
| Oracle Cloud (`oci`) | `OCI_*` or `TF_VAR_*` | The provider's documented mechanisms, for example an OCI configuration file mounted into the container, or instance principals. |
| Kubernetes (`kubernetes`, `helm`) | `KUBE_CONFIG_PATH` | A mounted kubeconfig, or in-cluster service-account credentials. |

The bundled image ships OpenTofu and Terraform only; it no longer includes the `az`, `gcloud`, or `aws` command-line tools, and the sidecar's `/v1/import*` endpoints answer `501 Not Implemented`. See [Operating modes](modes.md) for what the core calls today.

Credential files you mount must be readable by the unprivileged user the image runs as (`nebula`, uid and gid `10001` by default).

### Credentials for the state backend

The sidecar is the process that reads and writes Terraform state, so state-backend credentials are always a sidecar concern.

- **By default** (`storage.terraform_state_bucket` blank) the backend comes from the target repository, and the sidecar must hold whatever that backend needs — S3 keys or a role, an Azure identity, a GCS service account. Nothing on the core side helps here.
- With Nebula-managed state on, and the core's rendered backend block **containing** static keys (`RUSTFS`, or `S3`/`STORAGE_ACCOUNT` with keys set in `core/.env`), the sidecar needs nothing extra for state.
- With Nebula-managed state on and the block **omitting** them (`provider: S3` with `RUSTFS_ACCESS_KEY`/`RUSTFS_SECRET_KEY` blank), the engine resolves credentials from the sidecar's own environment: `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`, `AWS_PROFILE`, or an attached instance role or IRSA token. Granting that role to the **core** container only is the common mistake — the core just creates the bucket at boot.
- With Nebula-managed state on, the sidecar must also reach `storage.endpoint_url`. In the Compose stack `core` and `iac` share `bridge-network`, so `http://object-storage:9000` resolves; elsewhere, allow that egress.

Where state lives, and how each provider is configured, is covered in [Terraform/OpenTofu state backends](terraform-state-backends.md).

## Mapping sidecar (`services/mapping/env.sample`)

| Variable | Requirement | Default | Meaning | Checked |
|---|---|---|---|---|
| `NEBULA_MAPPING_TOKEN` | Recommended when the sidecar is enabled | empty (accepts any bearer) | Token required on `POST /v1/resolve`. Must equal the core's `NEBULA_MAPPING_TOKEN`. | Per request |

The bundled mapping service is an identity passthrough: it returns the identifier it receives as both repository URL and project name (the project name is truncated to 128 characters). While `services.mapping.enabled` is `false` (the default) the core performs that same mapping itself and never calls the service. Once enabled, a sidecar that times out or is unreachable makes the wizard's resolve step fail with `504` or `502`; there is no silent fallback.

## Notifications sidecar (`services/notifications/env.sample`)

| Variable | Requirement | Default | Meaning | Checked |
|---|---|---|---|---|
| `NEBULA_NOTIFICATIONS_TOKEN` | Recommended when the sidecar is enabled | empty (accepts any bearer) | Token required on `POST /v1/notify`. Must equal the core's `NEBULA_NOTIFICATIONS_TOKEN`. | Per request |
| `SLACK_WEBHOOK_URL` | **Mandatory for the bundled container to start** | empty | Slack incoming-webhook URL the service posts to. Treat it as a secret: anyone holding it can post to the channel. The service never logs it. | At boot: the container exits with `ConfigError` when empty |
| `LOG_LEVEL` | Optional | `INFO` | Root log level (`DEBUG`, `INFO`, `WARNING`, `ERROR`). | At boot: an unknown level name aborts startup |

The core sends four kinds of notification on its own: `iac.compliance.failed` and `iac.impact.high` at the end of a generate round, `iac.apply.failure` when an apply fails, and `system.exception.failure` when a background run raises. Users can also send free-form support requests through `POST /api/v1/notifications` (see [Admin portal](admin-portal.md#support-requests)). The audience of every notification is the session owner (or the caller) plus every user with a panel role of `editor` or higher. Delivery is best-effort: the core logs `Failed to send '<kind>' notification` and continues. The bundled sidecar delivers synchronously to Slack with a 10-second budget and answers `502` when Slack rejects the message.

The bundled notifications container **refuses to start without `SLACK_WEBHOOK_URL`, even when the core integration is disabled**. Because Compose starts every sidecar regardless of `config.yaml`, a notifications container that exits immediately is expected and harmless while `services.notifications.enabled` is `false`. Remove the service from your Compose file or provide a webhook URL to avoid the restart noise.

## Authorization sidecar (`services/authz/env.sample`)

| Variable | Requirement | Default | Meaning | Checked |
|---|---|---|---|---|
| `NEBULA_AUTHZ_TOKEN` | Recommended when the sidecar is enabled | empty (accepts any bearer) | Token required on `/v1/*`. Must equal the core's `NEBULA_AUTHZ_TOKEN`. | Per request |
| `NEBULA_AUTHZ_ROOT_ADMIN_EMAIL` | Optional | empty | When set, the sidecar grants its own `admin` role to a user record keyed by this email at startup. | At boot |
| `NEBULA_AUTHZ_PERMISSIVE` | Optional | `true` | `true` (case-insensitive): `POST /v1/check` answers `authorized: true` for every request. Any other value: it answers `authorized: false` for every request. Neither value implements a real policy. | At boot |
| `NEBULA_AUTHZ_ROLE_STORE` | Optional | `/data/roles.json` | Path of the JSON file holding the sidecar's user-to-roles map. The path is container-local in the shipped Compose file (no volume is mounted), so assignments are lost when the container is recreated; point it at a mounted path if you need them to survive. | On first write |

Two things to keep apart:

- The bundled authorization sidecar is a **permissive reference implementation**. It exists so that the contract in `contracts/openapi/authz.v1.yaml` has a runnable example. The core consults it only from `POST /v1/auth/authorize` (a cloud-project access check) and only when `services.authz.enabled` is `true`. Enabling it without replacing the logic changes nothing about who is allowed to do what. While disabled, the core answers "authorized" without any call; once enabled, an unreachable or slow sidecar makes the preflight fail with `502` or `504` rather than allowing the request.
- The sidecar's `admin` and `user` roles, its root-admin bootstrap, and its `/v1/users` endpoints belong to the sidecar alone. Nebula's own operation roles (`developer`, `devops`) and admin-panel roles (`viewer`, `editor`, `admin`) live in the core database and are documented in the [Admin portal](admin-portal.md) guide.

## Cloud-provider credentials at a glance

| Consumer | Where | Purpose |
|---|---|---|
| Terraform or OpenTofu providers | `services/iac/.env` (see `services/iac/PROVIDERS.md`) | `init`, `validate`, `plan`, `show`, `apply` against your cloud |
| AWS SDK (boto3) in the core | `core/.env` (`RUSTFS_*` or the default chain) | Artifact storage when `storage.provider` is `RUSTFS` or `S3` |
| Azure Storage shared key in the core | `core/.env` (`STORAGE_ACCOUNT_KEY`) | Artifact storage when `storage.provider` is `STORAGE_ACCOUNT` |
| LiteLLM in the core | `core/.env` | Cloud-hosted LLM providers (Vertex AI, Bedrock, Azure OpenAI, and so on) |

Cloud credentials for the IaC engine and for the LLM provider are independent. A stack that generates AWS infrastructure with an Azure OpenAI model needs AWS credentials in `services/iac/.env` and Azure OpenAI credentials in `core/.env`.

## LLM-provider credentials

Variable names follow LiteLLM's provider conventions and are selected by the `llm.model` and `llm.small_model` strings. The complete per-provider table, the `os.environ/VARIABLE_NAME` syntax for custom names, and the limits of boot-time validation are documented in [LiteLLM providers and models](litellm.md).

## Credential handling and production recommendations

- **Generate bearer tokens with a cryptographic generator.** For example:

  ```bash
  openssl rand -hex 32
  ```

  Paste the output into both `core/.env` and the matching sidecar `.env`. Generate a distinct value per sidecar. Do not reuse the `dev-*-token` placeholders or an empty sidecar token outside an isolated workstation: an empty sidecar token disables its bearer check entirely.
- **Never put secrets in `config.yaml`.** It is baked into the core image and is meant to be shareable. Use the `*_env` fields to rename variables if your platform imposes naming conventions.
- **Keep sidecars private.** The bundled sidecars compare bearer tokens in constant time, but they are still simple services: keep them on a private network that only the core can reach, and rotate tokens on a schedule.
- **Only the IaC and core images run unprivileged.** The bundled mapping, notifications, and authorization images run as root; apply your platform's pod or container security defaults to them.
- **Prefer a secret manager or orchestrator secrets** (Docker secrets, Kubernetes Secrets, a vault) over plaintext `.env` files in shared and production deployments. Mount files with permissions readable only by uid `10001`.
- **Scope Git tokens narrowly.** `GIT_TOKEN` is single-tenant: one token pushes every session's branch and opens every pull request. Give it the minimum repository permissions your provider offers.
- **Rotate the RustFS keys and database password** from the bundled `rustfsadmin` and `postgres` defaults in `docker-compose.yml` before exposing the stack beyond a workstation.
- **Restrict who can reach the stack while OIDC is disabled.** With a blank `oidc.issuer_url`, every request is treated as a fully privileged local developer. See [OIDC setup](oidc-setup.md).

## Example `.env` sets

All values below are fictitious. Replace every token and URL.

### Core plus IaC sidecar only (shipped defaults, Anthropic models)

`config.yaml` excerpt for this example:

```yaml
llm:
  model: "anthropic/claude-sonnet-5"
  small_model: "anthropic/claude-haiku-4-5"
```

`core/.env`:

```dotenv
# LLM provider
ANTHROPIC_API_KEY=sk-example-not-a-real-key

# Sidecar bearer tokens (only iac is enabled in the shipped config.yaml)
NEBULA_IAC_TOKEN=0000000000000000000000000000000000000000000000000000000000000001
NEBULA_MAPPING_TOKEN=unused-while-disabled
NEBULA_NOTIFICATIONS_TOKEN=unused-while-disabled
NEBULA_AUTHZ_TOKEN=unused-while-disabled

# Git push credentials
GIT_USER=nebula-bot
GIT_TOKEN=ghp_example_not_a_real_token

# Bundled RustFS and PostgreSQL defaults
RUSTFS_ACCESS_KEY=rustfsadmin
RUSTFS_SECRET_KEY=rustfsadmin
NEBULA_SQL_DATABASE_URL=postgresql://postgres:postgres@core-db:5432/nebula
```

`services/iac/.env` (AWS example):

```dotenv
NEBULA_IAC_TOKEN=0000000000000000000000000000000000000000000000000000000000000001
IAC_BINARY=tofu

# Unset: the backend comes from the workspace — the target repository's
# own block, or the override the core writes when Nebula-managed state
# is on, which wins over this file (docs/terraform-state-backends.md).
# Set it only with storage.terraform_state_bucket blank (the shipped
# value), and mount the file in this container.
# IAC_BACKEND_CONFIG=/etc/nebula/backend.hcl

# These credentials serve both the providers and, when the rendered
# backend block omits static keys, the S3 state backend.
AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE
AWS_SECRET_ACCESS_KEY=example-not-a-real-secret-access-key
AWS_REGION=eu-west-1
```

### All sidecars enabled (Vertex AI models, Azure infrastructure)

`config.yaml` excerpt:

```yaml
llm:
  model: "vertex_ai/claude-sonnet-4-5"
  small_model: "vertex_ai/gemini-3.7-flash"
services:
  notifications:
    enabled: true
  mapping:
    enabled: true
  authz:
    enabled: true
  iac:
    enabled: true
```

`core/.env`:

```dotenv
# LLM provider (Google Vertex AI)
VERTEXAI_PROJECT=demo-platform-project
VERTEXAI_LOCATION=europe-west1
VERTEXAI_CREDENTIALS=/run/secrets/vertex-sa.json

# One distinct token per sidecar
NEBULA_IAC_TOKEN=0000000000000000000000000000000000000000000000000000000000000001
NEBULA_MAPPING_TOKEN=0000000000000000000000000000000000000000000000000000000000000002
NEBULA_NOTIFICATIONS_TOKEN=0000000000000000000000000000000000000000000000000000000000000003
NEBULA_AUTHZ_TOKEN=0000000000000000000000000000000000000000000000000000000000000004

GIT_USER=nebula-bot
GIT_TOKEN=example-not-a-real-gitlab-token

RUSTFS_ACCESS_KEY=rustfsadmin
RUSTFS_SECRET_KEY=rustfsadmin
NEBULA_SQL_DATABASE_URL=postgresql://postgres:postgres@core-db:5432/nebula
```

`services/iac/.env` (Azure example):

```dotenv
NEBULA_IAC_TOKEN=0000000000000000000000000000000000000000000000000000000000000001
IAC_BINARY=tofu

ARM_CLIENT_ID=00000000-0000-0000-0000-000000000000
ARM_CLIENT_SECRET=example-not-a-real-client-secret
ARM_TENANT_ID=00000000-0000-0000-0000-000000000001
ARM_SUBSCRIPTION_ID=00000000-0000-0000-0000-000000000002
```

`services/mapping/.env`:

```dotenv
NEBULA_MAPPING_TOKEN=0000000000000000000000000000000000000000000000000000000000000002
```

`services/notifications/.env`:

```dotenv
NEBULA_NOTIFICATIONS_TOKEN=0000000000000000000000000000000000000000000000000000000000000003
SLACK_WEBHOOK_URL=https://hooks.slack.example.invalid/services/T000/B000/example
LOG_LEVEL=INFO
```

`services/authz/.env`:

```dotenv
NEBULA_AUTHZ_TOKEN=0000000000000000000000000000000000000000000000000000000000000004
NEBULA_AUTHZ_ROOT_ADMIN_EMAIL=platform-admin@example.invalid
NEBULA_AUTHZ_PERMISSIVE=true
NEBULA_AUTHZ_ROLE_STORE=/data/roles.json
```

### Other LLM providers (drop-in replacements for the LLM block)

Azure OpenAI:

```dotenv
AZURE_API_KEY=sk-example-not-a-real-key
AZURE_API_BASE=https://demo-platform.openai.azure.example.invalid
AZURE_API_VERSION=2025-01-01-preview
```

Self-hosted OpenAI-compatible server (model strings `openai/<model>`):

```dotenv
OPENAI_API_KEY=none
OPENAI_API_BASE=https://llm.example.invalid/v1
```

### Other cloud providers (drop-in replacements for the IaC block)

Google Cloud:

```dotenv
GOOGLE_CREDENTIALS={"type":"service_account","project_id":"demo-platform-project","private_key":"<service-account-private-key-pem>","client_email":"nebula@demo-platform-project.iam.gserviceaccount.example.invalid"}
```

Kubernetes (kubeconfig mounted into the container):

```dotenv
KUBE_CONFIG_PATH=/home/nebula/.kube/config
```

<!--
SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)

SPDX-License-Identifier: Apache-2.0
-->

# Configuration reference (`config.yaml`)

`config.yaml` at the repository root is Nebula's single configuration file for the core service. This guide documents every supported section and field. The authoritative schema is the Pydantic model in `core/src/shared/config/system_config.py`; when this page and the code disagree, the code wins and this page has a bug.

Which fields you must touch depends on the deployment model: see [Getting started: local/non-production](getting-started-local.md) and [Getting started: production](getting-started-production.md).

Related guides: [Environment variables and secrets](environment-variables.md), [LiteLLM providers and models](litellm.md), [OIDC setup](oidc-setup.md), [Monitoring with Phoenix](monitoring.md), [Phoenix prompt templates](phoenix-prompt-templates.md), [Operating modes](modes.md), [Admin portal](admin-portal.md), and the sidecar READMEs under `services/`.

## How the file is loaded

- The core Dockerfile copies the repository's `config.yaml` to `/etc/nebula/config.yaml` **at image build time**. The file is baked into the image. Editing it on the host does nothing until you run `docker compose build core` and restart the container. `docker compose watch` syncs only `core/`, not the configuration.
- The `NEBULA_CONFIG` environment variable overrides the path. The path is interpreted **inside the container**, and the file must actually be present there (for example through a bind mount or a mounted secret). If the path is missing, or is a directory (which is what Docker creates when you bind-mount a non-existent host file), the core silently falls back to the built-in defaults.
- Every field has a default in code, so the core can boot with no configuration file at all. Note that the built-in default disables **every optional** sidecar (`notifications`, `mapping`, `authz`). The IaC sidecar has no `enabled` flag and is always called: its own code defaults are `endpoint: "http://iac:8082"` and `token_env: "NEBULA_IAC_TOKEN"`, independent of whether a `config.yaml` is loaded at all.
- Validation runs once at startup. A validation error aborts the boot with a message containing the `ConfigError` text quoted in the tables below; only the **first** failing configuration section is reported, so fixing one error can reveal another on the next boot attempt.
- **Secrets never belong in `config.yaml`.** Fields whose name ends in `_env` hold the *name* of an environment variable; the value is read from the environment at boot or at use time.

Changing any field therefore means: edit `config.yaml`, rebuild the core image, restart. "Requires rebuild" in the tables below always refers to that sequence. If you instead mount the file at the path in `NEBULA_CONFIG`, the equivalent is: update the mounted file and restart the core — no image rebuild needed, because the container reads the file from disk at startup rather than from the baked-in copy.

## Requirement summary

| Category | Fields |
|---|---|
| **Mandatory** (the core refuses to boot otherwise) | The environment variable named by `database.nebula_database_url_env` must be set; the variable named by `services.iac.token_env` must be set (the IaC sidecar is always called and has no `enabled` flag); the credentials that LiteLLM requires for `llm.model` and `llm.small_model` must be set for providers LiteLLM can validate. |
| **Conditionally mandatory** | `oidc.client_id` when `oidc.issuer_url` is set; the `token_env` variable of every other enabled sidecar; the variable named by `storage.account_key_env` when `storage.provider` is `STORAGE_ACCOUNT`; a derivable account name in `storage.endpoint_url` for `STORAGE_ACCOUNT`; a remote backend declared by every target repository while `storage.terraform_state_bucket` is blank — which is how it ships, so this applies unless you opt in to Nebula-managed state. |
| **Optional with defaults** | Everything else. |

## `environment`

| YAML path | Type | Default | Requirement |
|---|---|---|---|
| `environment` | one of `development`, `staging`, `production` | `development` | Optional |

Meaning: a label for the deployment tier. Any other value fails validation.

Operational effect: it selects the Phoenix tracing project prefix (`dev-`, `pre-`, `pro-`; see [Monitoring](monitoring.md)) and it is the **tag** used both when seeding prompts into Phoenix and when fetching them at runtime (see [Phoenix prompt templates](phoenix-prompt-templates.md)). It does **not** enable any security control: setting `production` does not turn on authentication, authorization, or stricter defaults. Changing it after prompts have been seeded requires tagging prompt versions with the new value in Phoenix, otherwise runtime prompt lookups fail.

Requires rebuild: yes.

## `oidc`

Authentication settings for the single-page application and the API. Full per-provider instructions are in [OIDC setup](oidc-setup.md).

| YAML path | Type | Default | Requirement | Meaning and effect |
|---|---|---|---|---|
| `oidc.issuer_url` | string | `""` | Optional | OIDC issuer URL. **Blank disables authentication entirely**: every request, from anyone who can reach the API, resolves to a fixed local development identity (`dev@nebula.local`) that holds the top role of both role groups (`devops` and panel `admin`). When set, the core validates bearer JWTs against the issuer's JWKS, discovered lazily on the first request. |
| `oidc.client_id` | string | `""` | **Required when `issuer_url` is set** | Public client id of the SPA. Validation error otherwise: `oidc.issuer_url is set but oidc.client_id is empty; set oidc.client_id (and optionally oidc.audience) in config.yaml.` |
| `oidc.audience` | string | `""` | Optional | Expected `aud` claim. Blank accepts `client_id` and `api://<client_id>`. Needed for identity providers that issue tokens for a separately named API (Auth0, Okta). |
| `oidc.scope` | string | `"openid profile email"` | Optional | Scopes the SPA requests. A `{client_id}` placeholder is expanded at load time (and fails validation if `client_id` is blank). When left at the default and the issuer host is `login.microsoftonline.com`, `api://{client_id}/.default` is appended automatically. |
| `oidc.clock_skew_seconds` | integer | `60` | Optional | Leeway applied to `exp`, `iat`, and `nbf` validation. |

Related environment variables: none. The SPA is a public PKCE client and the core needs only the issuer's public keys. Requires rebuild: yes. The public route `GET /api/v1/auth/config` returns the effective values.

## `admin`

| YAML path | Type | Default | Requirement | Meaning and effect |
|---|---|---|---|---|
| `admin.default_root_email` | string | `""` | Optional | Bootstrap administrator. A user whose access token carries an `email` claim equal to this address (case-insensitive) **and** `email_verified: true` is elevated to `devops` plus panel `admin` on login, and re-checked on every request. Elevation is one-way: clearing the field never demotes anyone. Identity providers that never emit `email_verified` (Entra ID, Auth0, Okta) cannot use this; grant the first admin in the database instead, as described in [OIDC setup](oidc-setup.md#bootstrap-admin). Ignored while authentication is disabled. |

Requires rebuild: yes. This is the core's mechanism and is unrelated to the authorization sidecar's `NEBULA_AUTHZ_ROOT_ADMIN_EMAIL`.

## `services`

Wiring for the four sidecars. Each sidecar implements an OpenAPI contract in `contracts/openapi/`, and any implementation of the contract can replace the bundled one by changing `endpoint`.

Common fields, available under `services.notifications`, `services.mapping`, `services.authz`, and `services.iac`. The `enabled` flag exists only for the three optional sidecars; `services.iac` has none because the core cannot run without it.

| YAML path | Type | Code default | Shipped `config.yaml` | Requirement | Meaning and effect |
|---|---|---|---|---|---|
| `services.<name>.enabled` (not for `iac`) | boolean | `false` | `false` for `notifications`, `mapping`, `authz` | Optional | Whether the core calls the sidecar. A disabled sidecar is never contacted: mapping is done locally, notifications are dropped, authorization answers "authorized". Compose still starts the container. An `enabled` key under `services.iac` is ignored. |
| `services.<name>.endpoint` | string (base URL) | `""` for `notifications`, `mapping`, `authz`; **`http://iac:8082`** for `iac` (its own code default, not just the shipped value) | `http://notifications:8080`, `http://mapping:8081`, `http://authz:8083`, `http://iac:8082` | Conditional (needed when enabled; always for `iac`) | Base URL the core calls, resolvable from inside the core container. |
| `services.<name>.token_env` | string (variable name) | `""` for `notifications`, `mapping`, `authz`; **`NEBULA_IAC_TOKEN`** for `iac` (its own code default) | `NEBULA_NOTIFICATIONS_TOKEN`, `NEBULA_MAPPING_TOKEN`, `NEBULA_AUTHZ_TOKEN`, `NEBULA_IAC_TOKEN` | Conditional (always for `iac`) | Name of the environment variable holding the bearer token sent on every call. **A sidecar the core will call whose variable resolves to an empty value aborts the boot** with `Services the core calls have no bearer token in the environment: services.<name> → $<VAR>. Set the listed env vars; the optional sidecars can also be flipped to enabled: false (services.iac cannot — it is mandatory).` |
| `services.<name>.timeout` | float (seconds) | `30.0` | `30.0` | Optional | Per-request HTTP budget. Every sidecar call returns promptly (long work runs as jobs the core polls), so this covers one round trip only. Honoured by the IaC and notifications clients; the mapping and authorization clients currently use fixed budgets of 10 and 15 seconds and ignore this field. |

Fields specific to the IaC sidecar:

| YAML path | Type | Default | Requirement | Meaning and effect |
|---|---|---|---|---|
| `services.iac.job_poll_interval` | float (seconds) | `5.0` | Optional | How often the core polls `GET /v1/jobs/{job_id}` for a submitted engine command. |
| `services.iac.job_timeout` | float (seconds) | `3600.0` | Optional | Maximum total wait for **one** job. It must cover both the time the job spends queued (jobs on the same workspace run one at a time, in order) and the command itself. The bundled sidecar imposes no timeout of its own on the engine process, so this value is the only bound. A validation run submits several jobs in sequence (init, validate, plan, and show when drift is requested), each with its own `job_timeout`. |

**The IaC sidecar is mandatory.** Every operating mode runs engine commands through it, so its configuration has no `enabled` flag: `endpoint` and `token_env` are always required and the service is always contacted.

Related environment variables: the ones named by each `token_env`, in `core/.env`, with the same value in the sidecar's `.env`. See [Environment variables](environment-variables.md). Requires rebuild: yes.

## `orchestration`

Iteration limits and behaviour switches for the core's agent loops. Raise the limits carefully: they bound the cost of a runaway session.

| YAML path | Type | Code default | Shipped `config.yaml` | Requirement | Meaning and effect |
|---|---|---|---|---|---|
| `orchestration.enable_compliance_checker` | boolean | `false` | `true` | Optional | Runs the compliance auditor once a generate round has been validated and its report written: a second, independent small-model agent reads the session's first request and the raw plan, and checks them against the rules in the `general-compliance-report` prompt. The session is **locked** if any finding comes back with severity `error` or `critical`; `warning` findings are recorded in the report but do not lock. A lock also sends an `iac.compliance.failed` notification. When `false` the audit is skipped entirely and reported as an empty passing result, so it can never lock. Generate rounds only — drift rounds do not audit, and apply does not re-audit. |
| `orchestration.block_on_high_impact` | boolean | `false` | `true` | Optional | **Locks** the session when the generate report's impact banner comes back `high`, and sends an `iac.impact.high` notification. The banner itself — `low`, `medium`, or `high`, judged against the `general-compliance-impact` prompt criteria — is part of every report either way; this flag decides only whether it gates. It is evaluated independently of the auditor above: the round ends locked if *either* condition fires. |
| `orchestration.max_drift_reports` | integer | `3` | `3` | Optional | Maximum detect-and-remediate iterations in a drift session. |
| `orchestration.max_validation_iteration` | integer | `5` | `5` | Optional | Maximum generate-then-validate attempts per generation task before the round fails with `Validation loop exceeded.` |
| `orchestration.max_tool_chain_executions` | integer | `70` | `70` | Optional | Maximum tool-call iterations inside one agent chain before it aborts. |
| `orchestration.max_session_events_iteration` | integer | `2160` | `2160` | Optional | Number of polls a server-sent-events subscription performs before it closes. The loop sleeps 4 or 5 seconds depending on the branch taken, so 2160 iterations run for roughly three hours rather than exactly `2160 × 5s`. |
| `orchestration.drift_group_operations` | integer | `8` | `8` | Optional | How many drift operations are grouped into one remediation task. |
| `orchestration.pull_request_readiness_seconds` | integer | `10` | `10` | Optional | How many one-second polls the GitHub provider performs waiting for a pull request to become mergeable before failing with `readiness polling exhausted`. |

**What the two gates lock, and what they do not.** Both switches write the same session flag, so their effect is identical: a locked session answers `409` to `POST /v1/iac/apply` and to `PUT /v1/repository/pr/merge`. *Creating* a pull request is not lock-checked, and the audited code has already been pushed to the working branch by then, so the gate guards the apply boundary rather than the commit. The lock clears when a later generate round passes with a non-`high` banner, or when a panel `editor` toggles it in the [admin portal](admin-portal.md); drift rounds never set or clear it. Because both default to `false` in code and `true` in the shipped file, an `orchestration` block that omits them silently turns both gates off — spell them out in any file you write yourself. The full round-by-round flow is in [Compliance gate](architecture.md#compliance-gate).

Requires rebuild: yes. See [Operating modes](modes.md) for where each limit applies.

## `llm`

Model selection through LiteLLM. Details, provider tables, and router examples are in [LiteLLM providers and models](litellm.md).

| YAML path | Type | Code default | Shipped `config.yaml` | Requirement | Meaning and effect |
|---|---|---|---|---|---|
| `llm.model` | string (LiteLLM model string, or a `model_name` alias when `model_list` is set) | `anthropic/claude-sonnet-5` | `azure_ai/claude-sonnet-4-5` | Optional (credentials mandatory) | High-quality model used by the IaC generator, target generator, and report generator chains. |
| `llm.small_model` | string | `anthropic/claude-haiku-4-5` | `azure_ai/claude-haiku-4-5` | Optional (credentials mandatory) | Cheaper model used by every other chain and by tool-internal LLM calls. |
| `llm.temperature` | float | `0.1` | `0.1` | Optional | Applied to both roles (forced to `1.0` when a chain requests extended thinking). |
| `llm.max_output_tokens` | integer | `32000` | `32000` | Optional | Completion cap sent on every call. |
| `llm.model_list` | list of LiteLLM Router entries | `[]` | not set | Optional | Advanced routing: load balancing across entries that share a `model_name`, per-entry endpoints, and `os.environ/VAR` credential references. Router-level fallbacks between different models are **not** configurable today; the core passes only `model_list` to the Router. When non-empty, `model` and `small_model` must match a `model_name` and boot validation runs against the listed entries. |

Validation: at boot the core asks LiteLLM which environment variables each configured model needs and fails with `LLM credentials missing from environment: ...` if any is unset. Some providers have no validation mapping and fail on the first call instead; see the [LiteLLM guide](litellm.md#startup-credential-validation-and-its-limits).

Related environment variables: the provider's credential variables in `core/.env`. Requires rebuild: yes for the YAML; a credential change only needs a container restart.

## `paths`

| YAML path | Type | Default | Requirement | Meaning and effect |
|---|---|---|---|---|
| `paths.upload_folder` | path | `/workspaces` | Optional | Directory where the core clones repositories, one session directory each. Must be writable by the core and **shared with the IaC sidecar at the same path**: in the compose stack both containers mount the `workspaces` volume at `/workspaces`, and both images run as the same unprivileged user (`nebula`, uid and gid `10001`). |
| `paths.session_plan_filename` | string matching `^[A-Za-z0-9._-]{1,128}$` | `session.plan` | Optional | Name of the plan artifact written by `plan` into the session workspace, carried by the pinned workspace, and executed by `apply`. It must be a **single safe filename**: no path separators, no spaces, at most 128 characters. Keep the `.plan` suffix so the gitignore rules the core injects continue to cover it. |

Requires rebuild: yes.

## `database`

| YAML path | Type | Default | Requirement | Meaning and effect |
|---|---|---|---|---|
| `database.nebula_database_url_env` | string (variable name) | `NEBULA_SQL_DATABASE_URL` | Optional (the variable it names is **mandatory**) | Name of the environment variable that holds the actual PostgreSQL connection URL. URLs embed credentials, which is why the URL itself is not in this file. Boot fails with `Missing env variable for nebula database` when the variable is empty, and database initialisation fails when it is unreachable. A `postgresql://` scheme is rewritten to `postgresql+asyncpg://`, and a `sslmode=` query parameter to asyncpg's `ssl=`, so URLs copied from a managed PostgreSQL service work as-is. |

Schema note: there are no migrations; tables are created with `create_all`. A database volume created by an older schema must be migrated by hand or dropped.

Requires rebuild: yes for the field name; the URL value lives in `core/.env`.

## `redis`

Redis is a cache in front of the database. Timeouts are deliberately short so a slow Redis fails fast and reads fall through to PostgreSQL.

| YAML path | Type | Default | Requirement | Meaning and effect |
|---|---|---|---|---|
| `redis.redis_url_env` | string (variable name) | `NEBULA_REDIS_URL` | Optional | Name of the variable holding the Redis URL (which may embed a password). |
| `redis.default_url` | string | `redis://redis:6379/0` | Optional | **Fallback used when the variable is unset or empty.** The default points at the compose service, so the stack needs no Redis variable. |
| `redis.max_connections` | integer | `20` | Optional | Connection pool size. |
| `redis.socket_connect_timeout` | float (seconds) | `2.0` | Optional | Connect timeout. |
| `redis.socket_timeout` | float (seconds) | `2.0` | Optional | Read and write timeout. |
| `redis.pool_timeout` | float (seconds) | `2.0` | Optional | How long a request may wait for a free pooled connection. |

Boot fails if Redis cannot be reached during initialisation. Requires rebuild: yes.

## `telemetry`

OpenTelemetry export and, in the current implementation, also the address of the Phoenix prompt registry. See [Monitoring with Phoenix](monitoring.md) and [Phoenix prompt templates](phoenix-prompt-templates.md).

| YAML path | Type | Code default | Shipped `config.yaml` | Requirement | Meaning and effect |
|---|---|---|---|---|---|
| `telemetry.collector_url` | string (base URL **ending in `/`**) | `http://localhost:6006/` | `http://phoenix:6006/` | Optional | Base URL of the trace collector. The core appends `v1/traces` by plain string concatenation, so the value must end with a slash: `http://phoenix:6006/` becomes `http://phoenix:6006/v1/traces`. The **same URL** is used as the Phoenix client base URL for prompt seeding and fetching, so today it must point at a Phoenix server even if you export traces elsewhere. |
| `telemetry.otel_attribute_count_limit` | integer | `1024` | `1024` | Optional | Maximum number of attributes per span (attribute *count*, not length). When exceeded the SDK drops the oldest attributes first, which on LLM spans are the session and user identifiers and the span kind. |
| `telemetry.otel_console_exporter` | boolean | `false` | `false` | Optional | Also print every span to the core's standard output. Spans contain prompts and plans; do not enable this where logs are shared. |

The code default only works when the core runs outside Docker on the same host as Phoenix. Requires rebuild: yes.

## `http`

| YAML path | Type | Default | Requirement | Meaning and effect |
|---|---|---|---|---|
| `http.cors_origins` | list of strings | `["http://localhost"]` | Optional | Browser origins allowed by CORS. The compose stack serves the SPA from nginx on port 80, so `http://localhost` is enough. Add `http://localhost:5173` when running the Vite dev server against the API container. Set your real origin for a deployed instance. |

Requires rebuild: yes.

## `storage`

Object storage for generated artifacts (reports, plans, code changes) and — only if you opt in — for Terraform/OpenTofu state. The browser downloads artifacts through presigned URLs. `storage.terraform_state_bucket` ships blank, so by default Nebula configures no backend and each repository keeps its own; set it to a bucket name and state moves into a **second bucket** in the same store, sharing the provider and the credentials with artifacts. See [Terraform/OpenTofu state backends](terraform-state-backends.md) for the state side in full.

| YAML path | Type | Default | Requirement | Meaning and effect |
|---|---|---|---|---|
| `storage.provider` | one of `RUSTFS`, `S3`, `STORAGE_ACCOUNT` (enum names) or `rustfs`, `s3`, `storage_account` (enum values) | `RUSTFS` | Optional | Backend. `RUSTFS`: the bundled RustFS or any S3-compatible server with a custom endpoint. `S3`: real AWS S3 on its regional endpoint (both URLs below are ignored; the region builds the endpoint). `STORAGE_ACCOUNT`: an Azure storage account using a shared key. |
| `storage.bucket` | string | `nebula-artifacts` | Optional | Artifacts bucket name, or blob container name for `STORAGE_ACCOUNT`. Created at boot if missing. |
| `storage.terraform_state_bucket` | string | blank as shipped in `config.yaml` (the key carries no value); `nebula-terraform-state` if the key is absent | Optional | Bucket (or blob container) holding Terraform/OpenTofu state, separate from `storage.bucket`. **Blank — the shipped value — means Nebula manages no state**, and no value, `""`, and whitespace-only are all blank: no bucket is created, no override is written, and each repository must declare its own remote backend, whose credentials belong to the IaC sidecar. Set it to a bucket name to opt in: the bucket is created at boot if missing and the core writes a `backend_override.tf` into every workspace before `init`, addressing it with the key `<project_id>/terraform.tfstate`. Backend type follows `storage.provider` (`s3` for `RUSTFS`/`S3`, `azurerm` for `STORAGE_ACCOUNT`). Note that **deleting the key** is not the same as blanking it: the field default turns managed state back on. See [Terraform/OpenTofu state backends](terraform-state-backends.md). |
| `storage.endpoint_url` | string | `http://object-storage:9000` | Conditional | Endpoint the core's SDK calls from inside the compose network. For `STORAGE_ACCOUNT` it must be the account blob endpoint (`https://<account>.blob.core.windows.net`, or the emulator form `http://<host>:<port>/<account>`); the account name is derived from it. Boot fails with `storage.endpoint_url must be an account blob endpoint ...` when it cannot be derived. |
| `storage.public_endpoint_url` | string | `http://localhost:9000` | Conditional | Host the **browser** reaches. Presigned S3 URLs bind the host header, so this must be the externally visible address of the store (in the compose stack, nginx forwards port 9000 to RustFS). |
| `storage.region` | string | `us-east-1` | Optional | Region for signing (`RUSTFS`) or for building the endpoint (`S3`). Ignored for `STORAGE_ACCOUNT`. |
| `storage.access_key_env` | string (variable name) | `RUSTFS_ACCESS_KEY` | Optional | Variable holding the access key. Falls back to `rustfsadmin` for `RUSTFS` when unset; empty for `S3`, which then uses the AWS SDK default credential chain. A non-empty value always wins, so **blank `RUSTFS_ACCESS_KEY` and `RUSTFS_SECRET_KEY` in `core/.env` when switching to `S3`** (the sample ships them set to `rustfsadmin`). |
| `storage.secret_key_env` | string (variable name) | `RUSTFS_SECRET_KEY` | Optional | Variable holding the secret key, same fallback rules. |
| `storage.account_key_env` | string (variable name) | `STORAGE_ACCOUNT_KEY` | Optional (the variable is **mandatory** for `STORAGE_ACCOUNT`) | Variable holding the Azure shared key. Boot fails with `storage.provider STORAGE_ACCOUNT requires env var STORAGE_ACCOUNT_KEY.` when empty. |
| `storage.connect_timeout` | float (seconds) | `3.0` | Optional | Per-request connect budget. |
| `storage.read_timeout` | float (seconds) | `10.0` | Optional | Per-request read budget. |
| `storage.max_attempts` | integer | `3` | Optional | Retry count (botocore standard mode). |
| `storage.presign_expiry_seconds` | integer in `[108000, 604800]` | `172800` (48 hours) | Optional | Lifetime of presigned download URLs. **Must stay between 108000 (30 hours) and 604800 (7 days).** The floor keeps URLs valid for longer than the 24-hour cached session detail that embeds them; the ceiling is the SigV4 limit. Boot fails with `storage.presign_expiry_seconds must be between 108000 ... and 604800 ...` otherwise. |

While Nebula-managed state is on, these fields have a second consumer: `endpoint_url`, `region`, and the credential variables are rendered into the backend block that the **IaC sidecar** executes. Two consequences follow. The sidecar container must be able to reach `storage.endpoint_url` (in the Compose stack both containers sit on `bridge-network`, so `http://object-storage:9000` resolves). And unless **both** `access_key_env` and `secret_key_env` resolve to non-empty values, the backend block omits the credential lines entirely — a single one being set is not enough — and the engine falls back to the **sidecar's** ambient credentials; an instance profile on the core alone is not enough.

Requires rebuild: yes. Related environment variables in `core/.env`: `RUSTFS_ACCESS_KEY`, `RUSTFS_SECRET_KEY`, `STORAGE_ACCOUNT_KEY`.

## `git`

Credentials and identity for the branches Nebula pushes and the pull requests it opens. Single-tenant: one token serves every session.

| YAML path | Type | Default | Requirement | Meaning and effect |
|---|---|---|---|---|
| `git.provider` | one of `GITHUB`, `AZURE_DEVOPS`, `GITLAB` (enum names) or `github.com`, `dev.azure.com`, `gitlab.com` (enum values) | `GITHUB` | Optional | Git hosting provider. Selects the pull-request API implementation and the host written into `~/.git-credentials`. Any other value, including an empty string, fails validation. The pull-request adapters support only the public SaaS hosts: `github.com`, `gitlab.com` (top-level namespace and project, no subgroups), and `dev.azure.com`. GitHub Enterprise Server, self-managed GitLab, and `*.visualstudio.com` URLs are rejected as malformed at pull-request time. |
| `git.pat_user_env` | string (variable name) | `GIT_USER` | Optional | Variable holding the account username. |
| `git.pat_token_env` | string (variable name) | `GIT_TOKEN` | Optional | Variable holding the personal access token. |
| `git.author_name` | string | `Nebula` | Optional | Commit author name. |
| `git.author_email` | string | `nebula@noreply.invalid` | Optional | Commit author e-mail. |

At boot the core always sets the global git author identity. If both credential variables are non-empty it also writes `https://<user>:<token>@<provider-host>` to `~/.git-credentials` and enables the `store` credential helper. If either is empty it logs a warning and continues; pushes then need credentials from another source (a pre-populated `~/.git-credentials`, or mounted SSH keys with an `ssh://` repository URL). Note that SSH covers clone and push only: pull-request creation and merge call the provider's REST API with `GIT_TOKEN` and require an HTTPS repository URL on the public host, so an SSH-only setup cannot open or merge pull requests. Repository URLs that embed a user name or token are rejected by the API.

Requires rebuild: yes for the YAML; token values live in `core/.env`.

## Example: minimal local development

Safe on an isolated workstation. Authentication is disabled, so everyone reaching port 80 is the local developer with full roles.

```yaml
environment: "development"

oidc:
  issuer_url: ""
  client_id: ""

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
  # Opt-in (ships blank): lets Nebula keep Terraform state in the
  # bundled RustFS, in its own bucket, so a scratch repository with no
  # backend of its own works out of the box. Leave it blank to use the
  # backend each repository declares.
  terraform_state_bucket: "nebula-terraform-state"

git:
  provider: "GITHUB"
```

Everything omitted keeps its default. Credentials go in `core/.env`.

## Example: production-shaped deployment (fictitious)

Illustrates the shape of a hardened configuration. Values are fictitious; `environment: production` only changes tagging, so every control below must be set explicitly.

```yaml
environment: "production"

oidc:
  issuer_url: "https://login.example.invalid/realms/platform"
  client_id: "nebula-web"
  clock_skew_seconds: 60

admin:
  default_root_email: "platform-admin@example.invalid"

services:
  notifications:
    enabled: true
    endpoint: "https://notifications.nebula.example.invalid"
    token_env: "NEBULA_NOTIFICATIONS_TOKEN"
  mapping:
    enabled: true
    endpoint: "https://mapping.nebula.example.invalid"
    token_env: "NEBULA_MAPPING_TOKEN"
  authz:
    enabled: true
    endpoint: "https://authz.nebula.example.invalid"
    token_env: "NEBULA_AUTHZ_TOKEN"
  iac:
    endpoint: "http://iac:8082"
    token_env: "NEBULA_IAC_TOKEN"
    job_timeout: 3600.0

orchestration:
  enable_compliance_checker: true
  block_on_high_impact: true

# Credentials stay in core/.env under the provider's default variable
# names (here AZURE_API_KEY, AZURE_API_BASE, AZURE_API_VERSION); no
# model_list is needed for that. Use llm.model_list for load balancing
# across entries that share a model_name, custom credential env var
# names, or per-entry endpoints (docs/litellm.md) — there is no
# router-level fallback support.
llm:
  model: "azure/main-deployment"
  small_model: "azure/small-deployment"
  temperature: 0.1
  max_output_tokens: 32000

telemetry:
  collector_url: "https://phoenix.nebula.example.invalid/"

http:
  cors_origins:
    - "https://nebula.example.invalid"

storage:
  provider: "STORAGE_ACCOUNT"
  bucket: "nebula-artifacts"
  # Opt-in (ships blank): Nebula owns state instead of the target
  # repositories. Blob container separate from the artifacts container
  # so state escapes any artifact lifecycle policy — enable versioning
  # and soft delete on it. Blank it again — no value, or "" — when the
  # repositories already declare their own backends; never delete the
  # key, because the field default would re-enable it.
  terraform_state_bucket: "nebula-terraform-state"
  endpoint_url: "https://demoplatformartifacts.blob.core.windows.net"
  public_endpoint_url: "https://demoplatformartifacts.blob.core.windows.net"
  presign_expiry_seconds: 172800

git:
  provider: "GITLAB"
  author_name: "Nebula"
  author_email: "nebula@noreply.invalid"
```

Points that this example relies on but that the file cannot express: the mapping and authz endpoints must be real implementations of their contracts (the bundled ones are a passthrough and a permissive stub); Phoenix must be reachable at `collector_url` for prompt seeding; the Phoenix UI must be protected separately because it receives prompts and plans; and every `*_TOKEN`, `STORAGE_ACCOUNT_KEY`, `NEBULA_SQL_DATABASE_URL`, `GIT_TOKEN`, and the `AZURE_API_*` credentials must come from a secret store. See [Environment variables and secrets](environment-variables.md).

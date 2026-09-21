<!--
SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)

SPDX-License-Identifier: Apache-2.0
-->

# Getting started: production deployment

This guide is for teams deploying Nebula for shared organizational use. It explains what a production deployment consists of, which decisions you must make for each component, and which settings and secrets you must supply. It does not repeat the field-by-field references; it points at them:

- [Configuration reference](configuration.md) for every `config.yaml` field.
- [Environment variables and secrets](environment-variables.md) for every core and sidecar variable.
- [LiteLLM providers and models](litellm.md) for LLM providers and credentials.
- [OIDC setup](oidc-setup.md) for authentication.
- [Monitoring with Phoenix](monitoring.md) for tracing.
- [Phoenix prompt templates](phoenix-prompt-templates.md) for the prompt registry.
- [`contracts/openapi/`](../contracts/openapi/) and [`contracts/conformance/`](../contracts/conformance/) for the sidecar contracts and their conformance suites.

Everything in this guide describes the implementation as it exists in the repository today. Where a capability is a recommendation rather than something the repository provides, it is labelled as such.

## At a glance

If you read nothing else, these are the production decisions this guide expands on:

| # | Decision | Where |
|---|---|---|
| 1 | Run one core replica, one IaC sidecar per shared workspace volume; there is no multi-replica mode | [15](#15-runtime-and-scaling-constraints) |
| 2 | Enable OIDC; a blank issuer makes every caller a fully privileged user | [7](#7-authentication-oidc) |
| 3 | Treat the four sidecars as integration boundaries: implement IaC to your requirements, replace mapping and authorization or leave them disabled, integrate notifications | [4](#4-sidecars-as-production-integration-boundaries) |
| 4 | Move every secret to a secret store; keep the variable names | [6](#6-secrets-inventory) |
| 5 | Use managed PostgreSQL, Redis, object storage (S3, Azure, or S3-compatible), and a persistent, access-controlled Phoenix; Phoenix is required at boot | [12](#12-data-services-and-persistence) |
| 6 | Reproduce the ingress rules: SSE path unbuffered, `/monitoring/` restricted, public object-storage endpoint, CORS origin, IdP redirect URIs | [13](#13-networking-and-tls) |
| 7 | Give the IaC engine a scoped workload identity and container execution controls; decide who owns the Terraform state backend | [4](#iac-mandatory), [11](#11-cloud-credentials-for-the-iac-engine), [state backends](terraform-state-backends.md) |
| 8 | Review the seeded prompts before the first user session; they encode a generic policy | [16](#16-hardening-checklist) |
| 9 | Plan upgrades by hand: no database migrations, seeds never overwrite prompts, `environment` is a prompt tag | [17](#17-backups-and-upgrades) |

The repository ships **no Kubernetes manifests or Helm charts**; the Compose file is the reference topology you translate to your platform.

## 1. What production means for Nebula

Nebula plans and applies infrastructure with real cloud credentials, pushes to your repositories, and sends every prompt, plan, and generated file to a tracing backend. A production deployment therefore has to control who can reach it, which cloud identity it acts with, where its data lives, and how it is operated.

Production is **not** the local Compose stack with `environment: production`. That field only selects the Phoenix project prefix and the prompt tag (see [Configuration](configuration.md#environment)). It enables no authentication, no authorization, and no stricter default.

The differences from the [local model](getting-started-local.md), in one table:

| Area | Local/non-production | Production |
|---|---|---|
| Platform | Docker Compose on one host | A production platform such as Kubernetes, expressed by you from the reference topology below |
| Authentication | May stay disabled | **OIDC enabled**; nothing else is acceptable because a blank issuer makes every caller a `devops` + panel `admin` user |
| Sidecars | Bundled IaC, optionally bundled notifications | All four treated as integration boundaries: reviewed, configured, hardened, replaced where needed |
| Secrets | Gitignored `.env` files | Kubernetes Secrets or an equivalent secret manager, injected as environment variables |
| Data services | Bundled PostgreSQL, Redis, RustFS, Phoenix on local volumes, with the well-known default credentials the samples ship | Managed or operated services with persistence, backups, access control, and credentials from your secret store |
| Terraform state | Nebula-managed state in the bundled RustFS by default, or each repository's own backend if you set `storage.terraform_state_bucket` to `""` | A deliberate choice of owner: the repositories' own backends, a Nebula-managed bucket on `S3`/`STORAGE_ACCOUNT`, or one central backend file mounted into the sidecar ([state backends](terraform-state-backends.md)) |
| Networking | Plain HTTP on `localhost` | TLS, a real origin, an ingress that handles server-sent events, a protected Phoenix, a public object-storage endpoint |

## 2. What the repository does and does not provide

Provided:

- Container images for every Nebula component, built from the Dockerfiles in `core/`, `nginx/`, and `services/*/`.
- `docker-compose.yml`, which is the **reference topology**: it shows every container, port, volume, and dependency. Use it as the specification of what to deploy, not as the deployment.
- OpenAPI contracts and Schemathesis conformance suites for the four sidecars, so you can verify your own implementations.

**Not provided:** Kubernetes manifests, Helm charts, Kustomize overlays, Terraform modules for the platform itself, database migrations, or a multi-replica execution model. Do not look for a `deploy/` or `charts/` directory; there is none. You write the platform definition for your environment using the requirements in this guide.

## 3. Reference topology

The Compose stack defines eleven services on one network. In production each row below is a deployment decision.

| Component | Reference image | Must be reachable by | Persistence | Production decision |
|---|---|---|---|---|
| Core API | `core/Dockerfile` (Python 3.13, port 8000, user `nebula` 10001) | Ingress (`/api`), nothing else | Shared workspace volume | Run **one replica** (see [section 15](#15-runtime-and-scaling-constraints)). Inject `config.yaml` at build time or mount it at `NEBULA_CONFIG`. |
| Web application and edge | `nginx/Dockerfile` builds the React app and serves it; forwards `/api`, the SSE path, `/monitoring/`, and port 9000 | Users | none | Keep it, or serve the built bundle from your own ingress. Reproduce its routing rules ([section 13](#13-networking-and-tls)). |
| PostgreSQL (core) | `postgres:17` | Core | **Required** | Managed PostgreSQL recommended. Set `NEBULA_SQL_DATABASE_URL`. |
| Redis | `redis:8.8` | Core | Not required (cache) | Managed Redis or in-cluster. Must be reachable when the core boots. |
| Object storage | `rustfs/rustfs:latest` | Core (SDK) and **browsers** (presigned URLs) | **Required** | Prefer AWS S3 or an Azure Storage Account through `storage.provider`; RustFS or another S3-compatible store is also supported. |
| Phoenix | `arizephoenix/phoenix:20.12.0` behind `PHOENIX_HOST_ROOT_PATH=/monitoring` | Core (traces and prompt API), operators (UI) | **Required** (through its PostgreSQL) | Operate it with persistence and access control. It is required at core start-up. |
| PostgreSQL (Phoenix) | `postgres:17` | Phoenix | **Required** | Managed PostgreSQL recommended; set `PHOENIX_SQL_DATABASE_URL` on Phoenix. |
| IaC sidecar | `services/iac/Dockerfile` (OpenTofu 1.12.6, Terraform 1.16.0; port 8082; user `nebula` 10001) | Core only | Shared workspace volume | **Mandatory.** **As a starting point** — harden the image and container, or implement the contract yourself to your organization's requirements. |
| Mapping sidecar | `services/mapping/Dockerfile` (port 8081, user `nebula` 10001) | Core only | none | Replace with an implementation against your catalogue, or leave disabled. |
| Notifications sidecar | `services/notifications/Dockerfile` (port 8080, user `nebula` 10001) | Core only | none | Use the bundled Slack implementation with a production webhook, or replace it. |
| Authorization sidecar | `services/authz/Dockerfile` (port 8083, user `nebula` 10001) | Core only | none (container-local JSON role file; mount a path via `NEBULA_AUTHZ_ROLE_STORE` to keep it) | Replace with your policy implementation; the bundled one is permissive. |

All five Nebula-built images (core, iac, mapping, notifications, authz) run as the unprivileged `nebula` user, uid/gid 10001. The `nginx/Dockerfile` proxy image is the exception: it has no `USER` directive and starts as root, dropping privileges only for its worker processes; give it a non-root base image or a Kubernetes `runAsNonRoot`/`securityContext` treatment if your policy requires the master process itself to be non-root.

Two volumes matter beyond databases:

- **The shared workspace** (`/workspaces` in both the core and IaC containers, `paths.upload_folder`). The core clones repositories there and the IaC sidecar runs the engine against the same paths. It must be **one filesystem mounted read-write by both containers at the same path**, owned by uid/gid `10001`. On Kubernetes that means a `ReadWriteMany` volume or the two containers in the same pod sharing a volume, with a matching `fsGroup`/`runAsUser`. Contents are ephemeral (each run's directory is deleted afterwards), but the pinned plan of every session lives there between a generate round and its apply, so the volume must survive pod restarts.
- **Phoenix's database**, which holds your curated prompts as well as traces. Losing it means re-seeding from the repository defaults and losing every prompt edit.

## 4. Sidecars as production integration boundaries

Each sidecar is an OpenAPI contract. The core calls it with a bearer token from the environment variable named by `services.<name>.token_env`, and the sidecar validates that token. Any implementation of the contract can be used by changing `services.<name>.endpoint`. Use the conformance suites in [`contracts/conformance/`](../contracts/conformance/) to verify a replacement.

Common rules for every **enabled** sidecar:

- Set a distinct, random bearer token (for example `openssl rand -hex 32`) on **both** sides. The core refuses to boot when the IaC sidecar's or an enabled optional sidecar's token variable is empty. On the sidecar side, an empty token disables the check entirely, which is never acceptable in production.
- The bundled sidecars compare tokens in constant time, but they remain simple reference services. Keep every sidecar on a private network segment reachable only by the core, and never expose one through the ingress.
- The `services.<name>.timeout` field is honoured by the IaC and notifications clients; the mapping and authorization clients use fixed budgets of 10 and 15 seconds.
- Every sidecar exposes `GET /healthz` for liveness probes.

### IaC (mandatory)

The bundled executor is **a starting point, not production-ready**: harden the image and container (the checked-in compose applies no hardening), review the credential pass-through, or implement the contract yourself. It is functionally complete (it runs every command the core needs), but it encodes no organizational policy: it executes provider plugins from generated HCL with whatever identity is in its environment, on a shared filesystem, with no approval step, no engine timeout, and in-memory job state.

For production the recommendation is to **implement the IaC contract ([`contracts/openapi/iac.v1.yaml`](../contracts/openapi/iac.v1.yaml)) according to your organization's requirements**, not only to harden the bundled image. Typical reasons: running the engine on your existing Terraform or OpenTofu execution platform, using a workspace and state strategy other than a shared volume, enforcing per-project cloud identities, adding policy or approval hooks around `plan` and `apply`, auditing every command, or supporting clouds and CLIs the bundled image does not include. The contract is small (one command per asynchronous job, polled by the core), and the conformance suite in [`contracts/conformance/iac/`](../contracts/conformance/iac/) verifies a replacement.

If you nevertheless start from the bundled image, its **identity and execution environment** are the security decisions you must make:

- **Cloud identity.** The engine reads whatever credentials the provider supports from the container environment (`ARM_*`, `GOOGLE_*`, `AWS_*`, mounted files). Use a workload identity (Kubernetes service account federation, pod identity, instance roles) scoped to the projects Nebula may change, rather than static keys. Missing credentials do not stop the container; the engine fails at `plan` or `apply` with its own error.
- **Execution controls.** The image already runs as an unprivileged user. The checked-in Compose file applies nothing else. For production, run the container with all Linux capabilities dropped, `no-new-privileges`, a read-only root filesystem with writable `/tmp` and `/home/nebula`, and CPU, memory, and process limits. These were validated on a feature branch of this repository but are **not** part of the checked-in Compose file; treat them as a requirement you implement on your platform.
- **No engine timeout.** The sidecar does not bound the engine process itself; `services.iac.job_timeout` in the core (default one hour per job) is the only bound. Set it deliberately.
- **Egress.** `init` downloads providers from `registry.opentofu.org` (or `registry.terraform.io` when `IAC_BINARY=terraform`), and `plan`/`apply` reach your cloud APIs. Corporate TLS inspection of the registry host breaks provider downloads unless the CA is mounted into the container.
- **Jobs are in memory.** A restart forgets queued and finished jobs; run one instance per shared workspace and do not scale it horizontally.
- **Engine choice.** `IAC_BINARY=tofu` (default) runs OpenTofu; `terraform` runs the bundled HashiCorp Terraform 1.16.0, which is BUSL-1.1 licensed and makes your use subject to its terms.
- **State backend.** The sidecar is always the process that *executes* the backend, so it always needs reach to it and credentials for it — whichever model you pick. By default (`storage.terraform_state_bucket` set to `nebula-terraform-state`, as shipped) the core configures it: state goes to that bucket in the same object store as artifacts, keyed per project, and the sidecar needs network reach to `storage.endpoint_url` plus, where the rendered block omits static keys, its own credentials for the bucket. Set `storage.terraform_state_bucket` to `""` to leave the backend to each target repository instead, with no Nebula configuration involved. For one central backend defined outside Nebula, mount a file and point `IAC_BACKEND_CONFIG` at it. All three models: [Terraform/OpenTofu state backends](terraform-state-backends.md).
- **Blast radius of the sidecar's environment.** `NEBULA_IAC_TOKEN` and every other variable in the IaC sidecar's environment are reachable by the provider plugins the generated HCL invokes, and by any `local-exec` provisioner in that HCL — generated code runs with the same privileges as the sidecar process. The job's `workspace_path` is not restricted to `/workspaces` by the sidecar itself. Treat the sidecar as reachable only from the core and give it nothing more than the cloud identity it needs.

### Mapping (optional)

The bundled implementation is a **direct passthrough**: the identifier the user types is returned as the repository URL, and it answers nothing else. It adds nothing over leaving the integration disabled, in which case the core performs the same mapping itself. Enable it only with an implementation that resolves your business identifiers (CMDB, Backstage, a catalogue) against the canonical IaC repository. Once enabled, a slow or unreachable sidecar makes the wizard's resolve step fail with `504`/`502`.

Your implementation may also answer `terraform_provider` and `scope_id` (the cloud subscription, project, account, compartment, or cluster). Both are optional and both are a promise: the wizard stops asking the user for any field your service fills in, so a value it cannot stand behind is a wrong answer nobody gets the chance to correct. Return `null` — meaning "I do not know" — whenever the catalogue is silent, and never infer a provider from the shape of the repository URL.

### Notifications (optional, recommended)

The bundled implementation posts to one Slack incoming webhook and is suitable for production once the webhook and token come from your secret store. The core emits `iac.compliance.failed`, `iac.impact.high`, `iac.apply.failure`, and `system.exception.failure`, plus user-originated support requests from the web application; the audience is the session owner (or caller) plus every user with panel role `editor` or higher. If your operational channel is not Slack (Teams, e-mail, PagerDuty, an ITSM tool), implement the contract in [`contracts/openapi/notifications.v1.yaml`](../contracts/openapi/notifications.v1.yaml). Delivery is best-effort: a failure is logged and never fails a session.

### Authorization (optional, must be replaced if enabled)

The bundled implementation answers `authorized: true` to every cloud-project check (`NEBULA_AUTHZ_PERMISSIVE=true`) or `authorized: false` to every check (any other value). Neither is a policy. **Do not enable the bundled authorization sidecar as your production access-control policy.**

Understand what this integration is and is not:

- It is consulted only by the wizard's preflight `POST /api/v1/auth/authorize`, which sends the cloud, project name, environment, and the caller's e-mail (or OIDC subject) to `POST /v1/check`. It answers whether that user may work on that cloud project.
- It is **not** Nebula's own access control. Who can log in, which operations a user may run, and who can see or act on a session are decided by OIDC plus the operation and panel roles stored in the core database ([Admin portal](admin-portal.md)).
- While disabled, the core answers "authorized" without calling anything. Once enabled, an unreachable sidecar produces a `502`/`504` error in the wizard, not an allow.

Implement the contract in [`contracts/openapi/authz.v1.yaml`](../contracts/openapi/authz.v1.yaml) against your entitlement source and enable it.

## 5. Configuration checklist (`config.yaml`)

`config.yaml` is baked into the core image at build time, or mounted at the path in `NEBULA_CONFIG`. It contains no secrets and can live in version control. Review every section; the [configuration reference](configuration.md) has the fields and a [production-shaped example](configuration.md#example-production-shaped-deployment-fictitious).

| Section | Production requirement |
|---|---|
| `environment` | `production` (or `staging`). Decide before the first boot: it is the tag every prompt fetch uses, and changing it later requires re-tagging every prompt in Phoenix. |
| `oidc` | `issuer_url` and `client_id` set; `audience` for Auth0 and Okta; `scope` when the default does not fit. |
| `admin` | `default_root_email` for identity providers that emit `email_verified`; otherwise plan the one-off SQL grant ([OIDC setup](oidc-setup.md#bootstrap-admin)). |
| `services.iac` | Endpoint of your IaC sidecar, token variable name, `job_timeout` chosen for your largest plans. There is no `enabled` flag; the sidecar is always called. |
| `services.notifications`, `services.mapping`, `services.authz` | Enabled only with a production-grade implementation behind `endpoint`; each with its own token variable. |
| `orchestration` | Keep `enable_compliance_checker: true` and `block_on_high_impact: true` unless you have another approval gate; the code defaults are `false`. Review the iteration limits, which bound the cost of a runaway session. |
| `llm` | Two model strings (or `model_list` aliases) for the provider you contract with; `max_output_tokens` within the provider's limits. |
| `paths` | `upload_folder` identical in the core and IaC containers. |
| `database`, `redis` | Variable names only; values are secrets. `redis.default_url` points at the Compose service name, so set `NEBULA_REDIS_URL` when Redis lives elsewhere. |
| `telemetry.collector_url` | Your Phoenix base URL, ending in `/`. It is used both for OTLP export and for the prompt API. |
| `http.cors_origins` | Your real origin, for example `https://nebula.example.invalid`. |
| `storage` | Provider, artifacts bucket or container, the endpoint the core calls, and the **public** endpoint browsers reach. Also `terraform_state_bucket`: set to `nebula-terraform-state` as shipped, which puts Nebula in charge of state; set it to `""` to leave state to each repository's own backend instead ([state backends](terraform-state-backends.md)). |
| `git` | Provider matching your repository host, author identity. |

Changing any of these means rebuilding the core image (or updating the mounted file) and restarting the core.

## 6. Secrets inventory

Keep the variable names; replace the `.env` files with your platform's secret injection. Every value below is a secret or credential.

| Secret | Consumed by | Variable(s) | Notes |
|---|---|---|---|
| LLM provider credentials | Core | Provider-specific, for example `ANTHROPIC_API_KEY`, `AZURE_API_KEY` + `AZURE_API_BASE` + `AZURE_API_VERSION`, `VERTEXAI_PROJECT` + `VERTEXAI_LOCATION` + `VERTEXAI_CREDENTIALS` | Names per provider in [LiteLLM providers and models](litellm.md). Checked at boot for most providers. |
| IaC bearer token | Core and IaC sidecar | `NEBULA_IAC_TOKEN` | Must match on both sides. |
| Notifications bearer token | Core and notifications sidecar | `NEBULA_NOTIFICATIONS_TOKEN` | When enabled. |
| Mapping bearer token | Core and mapping sidecar | `NEBULA_MAPPING_TOKEN` | When enabled. |
| Authorization bearer token | Core and authorization sidecar | `NEBULA_AUTHZ_TOKEN` | When enabled. |
| Git credentials | Core | `GIT_USER`, `GIT_TOKEN` | One token for every session: a service account with the minimum permissions to push branches and open and merge pull requests on the repositories in scope. |
| Database URL | Core | `NEBULA_SQL_DATABASE_URL` | Embeds the password. `postgresql://` and `sslmode=` are rewritten for the async driver. |
| Redis URL | Core | `NEBULA_REDIS_URL` | When Redis needs a password or lives outside the cluster network. |
| Object-storage credentials | Core | `RUSTFS_ACCESS_KEY` + `RUSTFS_SECRET_KEY` (S3-compatible and static S3 keys), or nothing for the AWS default credential chain, or `STORAGE_ACCOUNT_KEY` (Azure) | Variable names can be changed through `storage.*_env`. They serve the artifacts bucket and, where Nebula-managed state is enabled, the state bucket — in which case a non-empty value is also embedded into the backend block the IaC sidecar executes. |
| Cloud credentials for the engine | IaC sidecar | `ARM_*`, `GOOGLE_*`, `AWS_*`, mounted files, or workload identity | Read by the providers, not by Nebula. They must also cover the **state backend** — Nebula's bucket by default, when the rendered backend block carries no static keys, or the repository's own if you set `storage.terraform_state_bucket` to `""`. The role must be on the sidecar, not only the core. |
| Slack webhook URL | Notifications sidecar | `SLACK_WEBHOOK_URL` | Anyone holding it can post to the channel. |
| Phoenix database URL | Phoenix | `PHOENIX_SQL_DATABASE_URL` | Phoenix's own setting. |

Rules: generate tokens with a cryptographic generator, one per sidecar; rotate on a schedule and immediately on suspicion; never put a secret in `config.yaml`, in an image, or in a log; make mounted credential files readable by uid `10001`.

## 7. Authentication (OIDC)

Mandatory. Follow [OIDC setup](oidc-setup.md) for your identity provider. In summary:

1. Register a public single-page-application client using the authorization code flow with PKCE. No client secret exists.
2. Register `<origin>/auth/callback` as the redirect URI and `<origin>` as the post-logout URI, where `<origin>` is your TLS origin.
3. Set `oidc.issuer_url`, `oidc.client_id`, and, for Auth0 and Okta, `oidc.audience`. Rebuild or remount the configuration.
4. Bootstrap the first administrator: `admin.default_root_email` works when the access token carries `email` and `email_verified: true` (Keycloak); for Entra ID, Auth0, and Okta, run the documented SQL grant after the user's first login.
5. Manage every other user from the admin portal's Users tab. New users arrive as `developer` with no panel role.

The core validates tokens against the issuer's JWKS on every request and needs outbound access to the issuer's discovery and JWKS endpoints. Access-token lifetime at the identity provider is the revocation latency: a disabled user keeps access until the token expires.

## 8. Project-level authorization

Decide whether users may operate on any cloud project their credentials reach, or whether Nebula must ask your entitlement system first. In the second case, implement the authorization contract as described in [section 4](#authorization-optional-must-be-replaced-if-enabled) and enable `services.authz`. Remember that this check runs in the wizard's preflight; the IaC sidecar's cloud identity is what ultimately bounds what can be changed.

## 9. LLM credentials

Choose the provider and models in `config.yaml` and supply the credentials as secrets to the core. Read [startup credential validation and its limits](litellm.md#startup-credential-validation-and-its-limits): some providers are not validated at boot, and custom variable names in `llm.model_list` still require the provider's default variables to be present. Every prompt, including repository file contents the agent reads, is sent to the provider; choose an endpoint and data-handling terms accordingly. The core needs outbound HTTPS to the provider.

## 10. Git credentials

`GIT_USER` and `GIT_TOKEN` are written to `~/.git-credentials` inside the core container at boot and used for every push, pull-request creation, and merge. Use a dedicated service account, restrict the token to the repositories Nebula may change, and set `git.provider` to the matching host (`GITHUB`, `AZURE_DEVOPS`, or `GITLAB`). The core needs outbound HTTPS to the Git host. Repository URLs entered by users must not embed credentials; the API rejects them. Azure DevOps users must remove the `<org>@` prefix that the portal's clone URL carries.

**Supported hosts.** The pull-request adapters target the public SaaS hosts only: `github.com`, `gitlab.com` (top-level namespace and project; subgroups are rejected), and `dev.azure.com`. GitHub Enterprise Server, self-managed GitLab, and `*.visualstudio.com` URLs are not supported today and fail at pull-request time with `Malformed repository URL`. SSH keys can replace `GIT_TOKEN` for clone and push only; pull-request creation and merge always use the REST API over HTTPS.

## 11. Cloud credentials for the IaC engine

Separate from the LLM and storage credentials. Give the IaC sidecar an identity that can read and change exactly the resources Nebula manages, per cloud:

| Cloud | Recommended | Static alternative in the sample file |
|---|---|---|
| Azure | Workload identity federation or managed identity for the `azurerm` provider | `ARM_CLIENT_ID`, `ARM_CLIENT_SECRET`, `ARM_TENANT_ID`, `ARM_SUBSCRIPTION_ID` |
| Google Cloud | Workload identity | `GOOGLE_CREDENTIALS` (key JSON) or `GOOGLE_APPLICATION_CREDENTIALS` (mounted key file) |
| AWS | IAM role for the pod or instance | `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION` |
| Oracle Cloud, Kubernetes | The provider's own mechanisms (configuration file, instance principals, mounted kubeconfig) | none in the sample |

That identity covers the **resources**. The **state backend** is a second grant on a different resource and must be satisfied on the same sidecar: `init` authenticates to the state store before any provider is configured, so an identity that can create infrastructure but cannot read state fails at the first command. The two often share variables — an `s3` backend and the `aws` provider both read `AWS_ACCESS_KEY_ID` — but the state store commonly lives in another account, subscription, or project, and some backends read variables the providers ignore (`ARM_ACCESS_KEY`, `ARM_SAS_TOKEN`, `GOOGLE_BACKEND_CREDENTIALS`) precisely so the identities can differ. Minimums for both: [`services/iac/PROVIDERS.md`](../services/iac/PROVIDERS.md); the rationale: [Two sets of credentials on the sidecar](terraform-state-backends.md#two-sets-of-credentials-on-the-sidecar).

The `apply` step runs with `-auto-approve` against the plan a human reviewed; there is no second confirmation inside the engine. The human gates are the pull-request review, the session lock, and the explicit apply action ([Operating modes](modes.md)).

## 12. Data services and persistence

**PostgreSQL (core).** The system of record: users and roles, sessions and their ownership, rounds, statuses, conversation history, pull requests, and artifact metadata. Use a managed instance with backups and TLS. There are **no migrations**: the schema is created with `create_all` at start-up, and a schema change between versions requires a manual migration or a fresh database. Plan upgrades accordingly.

**Redis.** A cache; the database remains authoritative and cache operations fail open at runtime. The boot-time connectivity check must succeed, so Redis has to exist, but it needs no persistence.

**Object storage.** `storage.bucket` holds reports, plans, drift output, and code-change artifacts under `sessions/<session>/rounds/<round>/`. A second bucket, `storage.terraform_state_bucket`, holds Terraform/OpenTofu state under `<project_id>/terraform.tfstate` — it ships set to `nebula-terraform-state`, so this is on by default; set it explicitly to `""` to leave state to each repository's own backend instead. Every configured bucket is created at boot if missing, and the core **fails to boot** if the store is unusable. Choose `storage.provider`:

- `S3`: AWS S3 on its regional endpoint, credentials from the default chain or static keys. State uses the `s3` backend with `use_lockfile = true`.
- `STORAGE_ACCOUNT`: an Azure storage account with a shared key. State uses the `azurerm` backend with native blob leases.
- `RUSTFS`: RustFS or any S3-compatible server with a custom endpoint.

Browsers download artifacts through **presigned URLs** built against `storage.public_endpoint_url`, so that endpoint must be reachable from users' browsers over TLS, and the bucket policy must allow presigned reads. Links are valid for `storage.presign_expiry_seconds` (48 hours by default). Apply lifecycle and retention rules; Nebula never deletes stored artifacts (it only removes an object whose database record failed to be written).

Since Nebula-managed state is on by default, treat the **state bucket differently from the artifacts bucket**. It is never browser-facing and needs no presigned reads; it must be reachable from the **IaC sidecar**, not from users; and it should carry versioning and soft delete, be excluded from any artifact expiry rule, and be included in your restore drills — it is the record of what Nebula has built. Nebula never deletes a state object. Details and per-provider IAM minimums: [Terraform/OpenTofu state backends](terraform-state-backends.md#operations).

**Phoenix.** Required at core start-up (prompt seeding retries for about 27 seconds and then aborts the boot) and on every request (prompt fetch). Run it with its own PostgreSQL, back that database up, and put the UI and API behind access control: Phoenix has **no authentication of its own**, and it holds prompts, plans, generated code, repository metadata, and user identifiers. The core sets no exporter headers; OTLP header env vars may be honoured by the OpenTelemetry SDK but this is not verified here — put an authenticating proxy or collector in front of Phoenix if you need auth. Note that the same `telemetry.collector_url` serves both trace export and the prompt API ([Monitoring](monitoring.md#configuration)).

**Checked-in defaults you must not carry into production.** The compose file hard-codes several credentials and settings that are fine only on an isolated workstation:

- `POSTGRES_PASSWORD=postgres` on both `core-db` and `phoenix-db`, and the matching password embedded in `PHOENIX_SQL_DATABASE_URL`. Replace all three with a generated password from your secret store, and update `NEBULA_SQL_DATABASE_URL` and `PHOENIX_SQL_DATABASE_URL` to match.
- `RUSTFS_ACCESS_KEY` / `RUSTFS_SECRET_KEY` default to `rustfsadmin` / `rustfsadmin`. Rotate both to generated values (and update the core's `RUSTFS_ACCESS_KEY`/`RUSTFS_SECRET_KEY`) before onboarding real data.
- `RUSTFS_CONSOLE_ENABLE=true` exposes the RustFS web console. Disable it, or make sure port 9000's console path is never reachable outside the cluster network — only the presigned-URL data path belongs on the public endpoint.
- Floating image tags (`rustfs/rustfs:latest`, `ghcr.io/astral-sh/uv:latest` in every Python Dockerfile, `node:24-alpine`, `postgres:17`, `redis:8.8`) are convenient for local use but not reproducible. Pin every image you run in production by digest.

## 13. Networking and TLS

Terminate TLS at your ingress and expose one origin for the web application and API. Reproduce the routing the reference nginx configuration implements:

| Path | Upstream | Requirements |
|---|---|---|
| `/` | Static bundle built from `client/web` | Single-page application fallback to `index.html`. The reference config sets `expires 1d` on this location, which also caches `index.html` for a day — serve `index.html` itself with `Cache-Control: no-cache` (or an equivalent short-lived directive) so a new deploy is picked up promptly, while still caching hashed static assets aggressively. |
| `/api/` | Core, port 8000 | The core is mounted with `root_path=/api`. Long timeouts (the reference uses 600 seconds). |
| `/api/v1/events/subscribe/` | Core, port 8000 | Server-sent events: **response buffering off**, HTTP/1.1, no compression, read timeout long enough for a run (600 seconds in the reference; the stream itself lives up to three hours). |
| `/monitoring/` | Phoenix, port 6006, with `PHOENIX_HOST_ROOT_PATH=/monitoring` | **Restrict access** (identity-aware proxy, VPN, or network policy). The admin portal links to `/monitoring/projects`. |
| Object-storage public endpoint | The bucket's endpoint (`storage.public_endpoint_url`) | Reachable by browsers; the reference forwards port 9000 to RustFS and adds an unconditional `Access-Control-Allow-Origin: *` header. Do not reproduce the wildcard CORS header in production — scope it to your real origin. With S3 or Azure this is the provider's own endpoint and its own CORS configuration applies instead. |

Other settings that follow from the origin:

- `http.cors_origins` must list the origin; the API sets `allow_credentials` and reflects it.
- The identity provider must have `<origin>/auth/callback` and `<origin>` registered.
- The core's OpenAPI document (`/api/openapi.json`) and Swagger UI (`/api/docs`) are public by design; block them at the ingress if your policy requires it.
- No component enforces rate limiting; add it at the ingress.
- The reference nginx config caps request bodies at `client_max_body_size 4m` on port 80. Keep an explicit limit at your own ingress; Nebula's requests (repository descriptions, not file uploads) are small, but an unbounded body size is an easy denial-of-service vector.
- Sidecars, databases, Redis, object storage's internal endpoint, and Phoenix's OTLP port must **not** be exposed through the ingress. Use network policies so that only the core reaches the sidecars.

Outbound connections you must allow: the core to the LLM provider, the Git host, the identity provider, object storage, and Phoenix; the IaC sidecar to the provider registry (`registry.opentofu.org` or `registry.terraform.io`) and to the cloud APIs; the notifications sidecar to `hooks.slack.com` (or your channel).

## 14. Images and configuration delivery

- Build the images from the repository with your registry's tags. The core image copies `config.yaml` from the repository root at build time; to keep one image per version and vary configuration per environment, mount the file instead and set `NEBULA_CONFIG` to its path inside the container. The path must be a regular file, or the core silently falls back to built-in defaults, which disable every *optional* sidecar (notifications, mapping, authz). The IaC sidecar has no `enabled` flag and is always called: if the fallback also leaves its bearer token unresolved, the core fails to boot; but if the token is set and only the endpoint falls back to the built-in default (`http://iac:8082`, unreachable from most environments), the core boots successfully and the failure only surfaces on the first IaC call (init/validate/plan/apply), not at boot.
- Build the core and IaC images with the **same** `NEBULA_UID` and `NEBULA_GID` build arguments (default `10001`) and run both with that identity.
- Set `APP_VERSION` on the core to your release version; it is reported in the OpenAPI document.
- `docker compose watch` and bind-mounted source directories are development conveniences; do not use them in production.

## 15. Runtime and scaling constraints

These are properties of the current implementation, not tuning options:

- **Run one core replica.** Sessions execute as in-process background tasks of the API process; the only concurrency control is a compare-and-set flag on the session row; the SSE endpoint polls the database of the same process. A second replica would not share in-flight work and would leave sessions half-run when a pod is replaced. Size the single pod for your expected parallel sessions (each holds a repository clone and several model calls).
- **Run one IaC sidecar per workspace volume.** Jobs and their results are held in memory and serialized per workspace path.
- **Restarts interrupt runs.** A session that was running when the core restarted keeps its last status; its in-flight flag is released only by the process that set it. Expect to inspect such sessions in the admin portal after a rolling restart.
- **Start-up is strict** and ordered: database, Redis, the object-storage artifacts bucket, the Terraform state bucket (created by default, since `storage.terraform_state_bucket` ships non-blank; skipped only if you blank it explicitly to `""`), Phoenix prompt seeding, then git credentials. Readiness should be derived from the API answering `GET /api/v1/auth/config`; the core has no dedicated health route.
- **The checked-in compose has no healthchecks and no restart policies** for `core`, its dependencies, or the sidecars (only `proxy` sets `restart: on-failure`); the core's own DB connection has no retry, Redis retry is under a second, and Phoenix-seeding retry is only about 27.5 seconds. A core that loses a start-up race exits and **stays down** under Compose. On your platform, give the core: a restart policy, a startup probe with a generous failure threshold (allow for the ~30-second Phoenix wait), and a liveness probe on `GET /api/v1/auth/config` — otherwise a transient dependency race at boot becomes a permanent outage.
- **A remote state backend is mandatory, and by default Nebula provides it.** The workspace is deleted after each run and the pinned workspace after apply, and the seeded `.gitignore` excludes `*.tfstate`, so local state would be lost otherwise. `storage.terraform_state_bucket` ships set to `nebula-terraform-state`, so the core writes a `backend_override.tf` into each workspace pointing at that bucket under a per-project key. Set the key to `""` to make it yours to provide instead: every repository you onboard must then declare its own remote backend and the sidecar must be able to authenticate to it — verify this before the first real session. Either way, **Nebula never migrates state** between backends — `init` always runs `-reconfigure`. See [Terraform/OpenTofu state backends](terraform-state-backends.md).

## 16. Hardening checklist

Items the repository leaves to the platform. Apply them; none is optional for a shared deployment.

- OIDC enabled; `GET /api/v1/auth/config` shows a non-empty issuer.
- Distinct random bearer tokens on every enabled sidecar, sidecars unreachable except from the core.
- IaC container: dropped capabilities, `no-new-privileges`, read-only root filesystem, resource limits, workload identity instead of static cloud keys, egress limited to registries and cloud APIs.
- IaC sidecar implemented to your organization's requirements, or the bundled reference consciously accepted for production after review.
- Mapping, notifications, and authorization containers already run as the unprivileged `nebula` user (10001) in the bundled images; the `proxy` (nginx) image starts as root and drops privileges only for its workers — give it a non-root image or a Kubernetes `runAsNonRoot` treatment if your policy requires it.
- Phoenix behind authentication or network isolation; retention policy for traces.
- TLS everywhere users and browsers connect; managed database and storage endpoints with TLS.
- Artifacts bucket private except for presigned reads; lifecycle rules.
- State bucket private with no public path at all, versioning and soft delete enabled, no lifecycle expiry, access limited to the core (bucket creation) and the IaC sidecar (read/write).
- Git token scoped to the repositories in scope; LLM provider configured under acceptable data-handling terms.
- Seeded prompts reviewed and adapted before the first user session; they encode a generic policy, including the compliance rules and forbidden actions ([Phoenix prompt templates](phoenix-prompt-templates.md)).

## 17. Backups and upgrades

Back up: the core PostgreSQL database, the Phoenix PostgreSQL database (prompts and traces), the artifacts bucket, and — with the highest priority — wherever **Terraform state** lives, since losing it means losing the record of the infrastructure Nebula manages. That is the state bucket if you enabled Nebula-managed state, and otherwise the backend each repository declares, which is covered by whoever owns it. The workspace volume needs no backup beyond surviving restarts.

Upgrading Nebula:

1. Read the release notes for schema changes; there are no automatic migrations. One known breaking change: a `core_db_data` volume created before OIDC support landed keyed sessions by `username`; it must be migrated by hand or dropped before you point a current core at it.
2. Rebuild or pull the images and the configuration for the new version.
3. New prompt seed files are created in Phoenix on the next core start; existing prompts are never overwritten, so review the seed changes and apply the ones you want as new prompt versions in Phoenix.
4. Do not change `environment` on an existing deployment without first tagging every prompt version with the new value.

## 18. Verification checklist

After the first deployment:

```bash
# Public route: issuer must be non-empty in production
curl https://nebula.example.invalid/api/v1/auth/config

# Protected route: must answer 401 without a token
curl -i https://nebula.example.invalid/api/v1/users/me

# Sidecar liveness from inside the cluster network
curl http://iac:8082/healthz
```

Then, as the bootstrap administrator:

1. Sign in; confirm the user page shows the Admin section and the admin portal lists users.
2. Run a generate session against a test repository and a test cloud project; confirm the branch, the pull request, the report, and the traces in Phoenix under `pro-terraform-day2`.
   Also confirm state landed where you intended: with the shipped default (Nebula-managed state), the core logs `Terraform state: <provider> bucket=<bucket> key=<project_id>/terraform.tfstate` before `init` and that object must exist in the state bucket afterwards; if you set `storage.terraform_state_bucket` to `""`, check the backend the repository declares instead, and confirm `init` did not silently fall back to local state. Either way the pull request must contain **no** `backend_override.tf` and no `*.tfstate`.
3. Trigger a compliance failure or a high-impact change and confirm the session is locked and the notification arrives.
4. Apply from a session that passed, and confirm the plan that ran is the one reviewed.
5. Restart the core and confirm it boots (prompt seeding reports `already present`) and that sessions resume normally.

## 19. Troubleshooting

- **Core exits with `Services the core calls have no bearer token`.** The IaC sidecar's token variable, or that of a sidecar enabled in `config.yaml`, is empty in the core's environment.
- **Core exits with `Phoenix unreachable after 8 attempts`.** Phoenix is not reachable at `telemetry.collector_url` from the core, or the URL lacks the trailing slash.
- **Core boots with every optional sidecar disabled although `config.yaml` enables them.** `NEBULA_CONFIG` points at a missing path or a directory; the core fell back to defaults (the IaC sidecar is always called regardless, and its own default endpoint is unlikely to resolve, which surfaces as a different failure).
- **Users get `401 Token validation failed ... audience`.** See [OIDC troubleshooting](oidc-setup.md#troubleshooting); usually the API scope or `audience` setting.
- **The session view never updates.** The ingress buffers the SSE path; disable buffering for `/api/v1/events/subscribe/`.
- **Artifact links fail in the browser.** `storage.public_endpoint_url` is not reachable from browsers, or the presigned host differs from the endpoint users reach.
- **Every plan fails with `permission denied` on state or plan files.** The shared workspace is not writable by uid `10001`, or the two containers run as different users.
- **`init` fails downloading providers.** Egress to `registry.opentofu.org` (or `registry.terraform.io`) is blocked or TLS-inspected.
- **Every session plans against empty state and nothing is recorded.** This happens when a deployment has explicitly set `storage.terraform_state_bucket` to `""` and the target repository declares no backend of its own: `init` then falls back to local state, whose file dies with the workspace. Add a backend to the repository, or remove the explicit `""` (a bucket name, or dropping the key, re-enables Nebula-managed state) and rebuild the core image.
- **`init` fails with `InvalidAccessKeyId` after switching `storage.provider` to `S3`.** `RUSTFS_ACCESS_KEY` and `RUSTFS_SECRET_KEY` are still set to `rustfsadmin`, so those keys were embedded into the state backend block. Blank both and rebuild the core image.
- **`init` fails on the state backend with `AccessDenied` or a credentials error.** The **IaC sidecar** lacks credentials or permissions for the state bucket, or cannot reach `storage.endpoint_url`. Granting the role to the core alone is not enough. See [Credentials required](terraform-state-backends.md#credentials-required).
- **Every plan proposes creating resources that already exist.** The project's state key changed, or state was not migrated after a backend change; `init` always uses `-reconfigure` and never migrates. See [Changing backend configuration](terraform-state-backends.md#changing-backend-configuration).
- **`Error acquiring the state lock`.** Another run holds it, or a crashed run left it stale; clear it deliberately ([Locking](terraform-state-backends.md#locking)).
- **`init` fails on a missing backend configuration file.** `IAC_BACKEND_CONFIG` is not validated at startup, so the sidecar starts and the error appears in the first job that runs `init`. The file is not mounted at that path inside the container, or is not readable by uid `10001`.
- **A run stopped without a failure message.** A prompt was missing in Phoenix for the deployment's `environment` tag; see [Runtime lookup](phoenix-prompt-templates.md#runtime-lookup).

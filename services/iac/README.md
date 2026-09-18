<!--
SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)

SPDX-License-Identifier: Apache-2.0
-->

# iac (reference implementation)

Reference implementation of [`contracts/openapi/iac.v1.yaml`](../../contracts/openapi/iac.v1.yaml).

The OSS default for the Nebula IaC contract: a raw IaC-engine executor
that runs individual engine CLI commands (**OpenTofu** by default,
**Terraform** as the bundled alternative) against a workspace path on a
docker-compose shared volume, as **asynchronous jobs**. Every POST enqueues exactly
one command and returns `202 Accepted` with a `job_id` immediately;
clients poll `GET /v1/jobs/{job_id}` for the raw
`{exit_code, stdout, stderr}` result. Sequencing commands and
interpreting their output is the caller's job (the core's `Terraform`
adapter, `core/src/infrastructure/terraform/terraform.py`, owns the
init → validate → plan → show pipeline and drift parsing). Jobs
targeting the same workspace run one at a time in submission (FIFO)
order.

## What it does

The commands below are shown for the default engine (`tofu`); when the
service is configured with `IAC_BINARY=terraform` it runs the same
subcommands against that binary instead (e.g. `terraform init`).

- `POST /v1/init` — enqueues `tofu init`.
- `POST /v1/validate` — enqueues `tofu validate`.
- `POST /v1/plan` — enqueues `tofu plan -out <plan_file>` with
  optional `-target=` filters.
- `POST /v1/show` — enqueues `tofu show -json <plan_file>`; on
  exit code 0 the result's `stdout` is the plan JSON.
- `POST /v1/apply` — enqueues
  `tofu apply -no-color -input=false -auto-approve <plan_file>`; the
  plan file is applied non-interactively, so `-auto-approve` is always
  passed.
- `POST /v1/import`, `POST /v1/import/state-resource-ids` and
  `POST /v1/import/scope-resource-ids` — **not implemented**. They
  answer `501` with a `Problem` body without inspecting the request
  (no auth check, no body validation) and never enqueue a job.
- `GET /v1/jobs/{job_id}` — job status (`queued` / `running` /
  `succeeded` / `failed`) plus `result` (succeeded) or `error`
  (failed). Engine-level failures end the job `succeeded` with a
  non-zero `exit_code` in the result; service-level faults end it
  `failed` with a `Problem` in `error`. Terminal jobs are kept in
  memory for `Config.job_ttl` seconds (1 hour), then poll as 404 (as
  after a restart).
- `GET /healthz` — liveness probe (unauthenticated).
- Bearer-token auth, when `NEBULA_IAC_TOKEN` is set, on the five
  job-submitting endpoints (`init`, `validate`, `plan`, `show`,
  `apply`) and on the job-polling endpoint `GET /v1/jobs/{job_id}`.
  The three `/v1/import*` routes carry no auth dependency and answer
  `501` before any token is looked at.

## Scope injection

`init`, `plan` and `apply` reach a cloud API, so they must carry
`scope_id` (the cloud scope the command targets) and
`terraform_provider` (which cloud that is); the contract requires both
and a missing or empty value is a `422`. `validate` and `show` make no
cloud API call, so their bodies declare neither field — every request
schema forbids unknown properties, so sending one is also a `422`.

Generated provider blocks name no scope, so for `init`, `plan` and
`apply` the service injects `scope_id` into the engine subprocess's
environment for that command only — where the cloud has a
provider-level variable that names a scope:

| `terraform_provider` | Environment variable  | Scope it sets |
|----------------------|-----------------------|---------------|
| `azure`              | `ARM_SUBSCRIPTION_ID` | subscription  |
| `gcp`                | `GOOGLE_PROJECT`      | project       |
| `aws`                | none                  | —             |
| `oci`                | none                  | —             |
| `kubernetes`         | none                  | —             |

Only Azure and GCP have one. An AWS account is implicit in the
credentials the provider resolves, and an OCI compartment or a
Kubernetes namespace is a resource argument rather than a provider
setting — no environment variable redirects a command to one. For those
three the service injects nothing and the command runs against whatever
scope its ambient credentials select, so a deployment that serves them
is responsible for making those credentials agree with `scope_id`; it
can also scope by another mechanism (an AWS AssumeRole into the
account, a provider alias, a credential broker), which the contract
explicitly allows.

Where an overlay is applied it goes on top of the service's own
environment, so it wins over an `ARM_SUBSCRIPTION_ID` (etc.) set on the
container — ambient provider credentials are otherwise untouched.

## State backend

The service does not choose where state goes. `init` reads the backend
from the workspace it is handed, which is the caller's to prepare. By
default that is simply the `terraform { backend ... }` block the cloned
repository carries, and this container must hold the credentials for
it — Nebula's core ships `storage.terraform_state_bucket` blank and
writes nothing.

When that setting names a bucket, the core writes a
`backend_override.tf` into the workspace before calling `init`, pinning
state to the object store it already holds the credentials for.
Terraform merges `*_override.tf` over the rest of the configuration, so
an override both introduces a backend where the workspace declares none
and replaces one that it does declare — any caller can use the same
trick.

`IAC_BACKEND_CONFIG` is the escape hatch for a deployment that owns the
decision instead. Set it to the path (inside this container) of a
backend configuration file — `.hcl` or `.tfbackend`, mounted in — and
`init` runs with `-backend-config=<path>`, with the backend *type*
still coming from the workspace's own `terraform { backend }` block.
The service checks at startup that the path is a readable file and
refuses to boot if it is not, for the same reason the engine binary is
checked there. Note the precedence: the values in this file win over a
`backend_override.tf` in the workspace, which in turn wins over the
repository's own `terraform { backend }` block. Keys absent from a
higher layer fall through, so combining this file with a caller-written
override merges the two instead of picking one — treat them as
alternatives.

**Reinitialization.** `init` always runs `-reconfigure`, so a workspace
whose backend changed between calls is rebound to the new one instead
of failing with *"Backend configuration changed"* (which
`-input=false` could not answer interactively). State already in the
target backend is adopted; state held under the previous backend is
**not** migrated — move it yourself (`terraform state push`, or a
manual `init -migrate-state`) if it matters.

The operator-facing view of the same feature — the three ownership
models, the rendered override per storage provider, state keys,
locking, credentials, and troubleshooting — is
[docs/terraform-state-backends.md](../../docs/terraform-state-backends.md).

## Configuration

| Env var                                       | Required | Description                                            |
|-----------------------------------------------|----------|--------------------------------------------------------|
| `NEBULA_IAC_TOKEN`                            | no       | Bearer token clients must present.                     |
| `IAC_BINARY`                                  | no       | Name or absolute path of the IaC engine CLI. Default: `tofu` (OpenTofu); set `terraform` for the bundled Terraform. See "Choosing the IaC engine". |
| `IAC_BACKEND_CONFIG`                          | no       | Path (inside this container) to a backend configuration file `init` passes to `-backend-config`. Unset, the backend comes from the workspace itself. See "State backend". |
| Provider creds: `ARM_*` (Azure), `GOOGLE_*` (GCP), `AWS_*` (AWS), `OCI_*` / `TF_VAR_*` (OCI), `KUBE_*` (Kubernetes) | no       | The engine's providers read these directly (identical for OpenTofu and Terraform). Provide whichever your modules need; without them, `plan`/`apply` fail with the engine's own auth errors in the result's `stderr`. The per-request scope variable (see "Scope injection") is layered on top of these. |

Everything else is a property of the service, not of a deployment, and
lives in [`src/config.py`](src/config.py): `job_ttl` (how long a
terminal job stays pollable) and `log_level` (root log level, `INFO`).

## Choosing the IaC engine

The bundled image ships both engines; `IAC_BINARY` selects one at
runtime, with no rebuild needed to switch:

- **OpenTofu 1.12.6** (MPL-2.0) — the default (`IAC_BINARY=tofu`).
  Installed from the official
  `ghcr.io/opentofu/opentofu:<version>-minimal` image, pinned by digest
  in the [Dockerfile](Dockerfile).
- **HashiCorp Terraform 1.16.0** (BUSL-1.1) — `IAC_BINARY=terraform`.
  Fetched from `releases.hashicorp.com` at build time and
  checksum-verified; your use of it is subject to its license terms.

The service itself is engine-agnostic: it only shells out to
`init` / `validate` / `plan` / `show` / `apply`, whose flags are
identical across both engines, so any Terraform-compatible engine on
PATH (or at an absolute path) works.

Notes when pointing a workspace previously managed by Terraform at the
default OpenTofu engine:

- Providers resolve from `registry.opentofu.org` (hostless sources like
  `hashicorp/azurerm` work unchanged); allow that egress alongside or
  instead of `registry.terraform.io`.
- A repo with a committed `.terraform.lock.hcl` generated by Terraform
  may need one `tofu init -upgrade` to regenerate provider checksums;
  the failure, if any, surfaces in the `init` job's `stderr`.
- State remains readable in both directions until OpenTofu first
  applies; after that, going back to Terraform requires restoring a
  state backup (see the
  [official migration guide](https://opentofu.org/docs/intro/migration/)).

## Workspace assumption

The service operates on `workspace_path` as visible *inside* its
container. The OSS reference docker-compose deployment mounts a named
volume `workspaces` at `/workspaces` in both the `core` and `iac`
containers, so the core writes the cloned repo there and references the
same path when submitting jobs. Other deployments may use a
PersistentVolumeClaim (k8s), an NFS mount, or an entirely different
workspace-staging mechanism — same contract, different mechanics.

## Runtime user and workspace ownership

The image runs as an unprivileged user, `nebula` (uid/gid `10001`, set
by the `NEBULA_UID` / `NEBULA_GID` build args): the engine executes
provider plugins and provisioners from generated code, so it must not
run as root.

Because the engine writes `.terraform/`, `.terraform.lock.hcl`, plan
files and state next to the configuration, **workspace directories must
be writable by that uid**. In the compose stack this holds because the
core image is built with the same `NEBULA_UID` / `NEBULA_GID` and also
runs as `nebula`, so everything the core clones is owned by the same
user. Override the two build args together or not at all.

- **Existing volumes.** A `workspaces` volume created by a stack that
  ran as root keeps root-owned directories the engine can no longer
  write to (`plan` fails with `permission denied` on
  `terraform.tfstate` or the plan file).
- **Other deployments.** The requirement does not change with the
  topology: whatever backs the shared workspace (a PersistentVolumeClaim,
  an NFS export, a bind mount or any other staging mechanism) must be
  owned by the unprivileged user the images were built with (`nebula`,
  uid/gid `10001` by default), and every component that stages repos
  into it must run as that same identity. How a platform expresses that
  (a pod security context, export options, a one-off `chown`) is
  deployment-specific; the ownership itself is not.
- **Provider credentials.** Credential files you mount (`~/.azure`,
  `~/.config/gcloud`, `~/.aws` under `$HOME`, or whatever the
  `GOOGLE_APPLICATION_CREDENTIALS` path points at) must be readable by
  uid `10001`.

## Security notes

The service is deliberately thin, which pushes several properties onto
the deployment. All of these are true of the bundled reference
implementation as checked in:

- **The engine subprocess inherits the entire container environment.**
  `_run` builds the child environment as `{**os.environ, **env}`
  ([`src/engine.py:130`](src/engine.py)) with no allowlist, so every
  variable the container holds — including `NEBULA_IAC_TOKEN` — is
  visible to provider plugins and to any `external` data source or
  `local-exec` provisioner in the code being executed. Keep only what
  the engine needs in `services/iac/.env`.
- **The per-request scope overwrites ambient configuration.**
  `ARM_SUBSCRIPTION_ID` (Azure) and `GOOGLE_PROJECT` (GCP) set on the
  container are replaced for the duration of each `init`, `plan` and
  `apply` with the request's `scope_id`
  ([`src/engine.py:54-76`](src/engine.py)). The caller, not the
  deployment, therefore chooses the subscription or project for those
  two clouds.
- **There is no engine timeout.** `_run` awaits
  `proc.communicate()` unconditionally, and the job registry imposes no
  deadline, so a hung `plan` or `apply` occupies its workspace queue
  until the process exits or the container is restarted.
- **`workspace_path` may be any existing directory in the container.**
  The only validation is "is this an existing directory"
  ([`src/main.py:147-161`](src/main.py)) — there is no root prefix or
  traversal check. Anyone who can submit a job can run the engine
  against any readable path, so the sidecar must be reachable **only**
  by the core, on a private network, with `NEBULA_IAC_TOKEN` set.
- **There is no provider plugin cache.** Every `init` downloads the
  providers it needs into the workspace's `.terraform/`, which costs
  time and registry egress on every call. Operators who want a shared
  cache can set `TF_PLUGIN_CACHE_DIR` to a writable directory under the
  image's `HOME` (`/home/nebula`) and keep it on a volume; nothing in
  the repository does this today.
- **The checked-in `docker-compose.yml` applies no container
  hardening** to this service: no `cap_drop`, no `read_only` root
  filesystem, no CPU or memory limits. The image's unprivileged user is
  the only mitigation in the box.

For production expectations see
[IaC (mandatory)](../../docs/getting-started-production.md#iac-mandatory)
and the
[hardening checklist](../../docs/getting-started-production.md#16-hardening-checklist).

## Run locally

Outside the image you supply the engine yourself: `Config` resolves
`IAC_BINARY` through `shutil.which` at startup and raises `ConfigError`
— the service refuses to start — if the binary is not on `PATH` (or not
an absolute path to one).

```bash
cd services/iac
uv sync
IAC_BINARY=$(command -v tofu || command -v terraform) \
  uv run uvicorn src.main:app --host 0.0.0.0 --port 8082 --timeout-keep-alive 75
```

```bash
job_id=$(curl -s -X POST http://localhost:8082/v1/init \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $NEBULA_IAC_TOKEN" \
  -d '{"workspace_path":"/path/to/your/iac/dir",
       "scope_id":"00000000-0000-0000-0000-000000000000",
       "terraform_provider":"azure"}' | jq -r .job_id)
curl -H "Authorization: Bearer $NEBULA_IAC_TOKEN" \
  http://localhost:8082/v1/jobs/$job_id   # repeat until succeeded/failed
```

The `Authorization` header is only needed when `NEBULA_IAC_TOKEN` is
set; with it unset the service accepts any (or no) token.
`workspace_path` is resolved inside the service's own filesystem and
must already be an existing directory there — otherwise the POST
answers `404` synchronously and no job is enqueued.

## Tests

```bash
cd services/iac
uv sync --group tooling
uv run pytest
```

## Verifying conformance

The implementation-agnostic Schemathesis suite at
[`../../contracts/conformance/iac/`](../../contracts/conformance/iac/)
runs against any implementation of the IaC contract.

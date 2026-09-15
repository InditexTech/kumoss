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
interpreting their output is the caller's job (the core's
`TerraformValidator` owns the init → validate → plan → show pipeline
and drift parsing). Jobs targeting the same workspace run one at a
time in submission (FIFO) order.

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
- `POST /v1/apply` — enqueues `tofu apply <plan_file>`.
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
- `GET /healthz` — liveness probe.
- Bearer-token auth on all `/v1/*` endpoints if `NEBULA_IAC_TOKEN` is
  set.

## Scope injection

`init`, `plan` and `apply` reach a cloud API, so they must carry
`scope_id` (the cloud scope the command targets) and
`terraform_provider` (which cloud that is); the contract requires both
and a missing or empty value is a `422`. `validate` and `show` make no
cloud API call, so their bodies declare neither field — every request
schema forbids unknown properties, so sending one is also a `422`.

Generated provider blocks name no scope, so for `init`, `plan` and
`apply` the service injects `scope_id` into the engine subprocess's
environment for that command only, under the variable
`terraform_provider` selects:

| `terraform_provider` | Environment variable  |
|----------------------|-----------------------|
| `azure`              | `ARM_SUBSCRIPTION_ID` |
| `gcp`                | `GOOGLE_PROJECT`      |
| `aws`                | `AWS_ACCOUNT_ID`      |
| `oci`                | `OCI_TENANCY_OCID`    |
| `kubernetes`         | none                  |

`kubernetes` names no cloud scope, so nothing is injected for it. The
overlay is applied on top of the service's own environment, so it wins
over an `ARM_SUBSCRIPTION_ID` (etc.) set on the container — ambient
provider credentials are otherwise untouched.

## Configuration

| Env var                                       | Required | Description                                            |
|-----------------------------------------------|----------|--------------------------------------------------------|
| `NEBULA_IAC_TOKEN`                            | no       | Bearer token clients must present.                     |
| `IAC_BINARY`                                  | no       | Name or absolute path of the IaC engine CLI. Default: `tofu` (OpenTofu); set `terraform` for the bundled Terraform. See "Choosing the IaC engine". |
| Provider creds: `ARM_*`, `GOOGLE_*`, `AWS_*`, `OCI_*` | no       | The engine's providers read these directly (identical for OpenTofu and Terraform). Provide whichever your modules need; without them, `plan`/`apply` fail with the engine's own auth errors in the result's `stderr`. The per-request scope variable (see "Scope injection") is layered on top of these. |

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

## Run locally

```bash
cd services/iac
uv sync
uv run uvicorn src.main:app --host 0.0.0.0 --port 8082 --timeout-keep-alive 75
```

```bash
job_id=$(curl -s -X POST http://localhost:8082/v1/init \
  -H 'Content-Type: application/json' \
  -d '{"workspace_path":"/path/to/your/iac/dir",
       "scope_id":"00000000-0000-0000-0000-000000000000",
       "terraform_provider":"azure"}' | jq -r .job_id)
curl http://localhost:8082/v1/jobs/$job_id   # repeat until succeeded/failed
```

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

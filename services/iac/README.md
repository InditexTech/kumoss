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
- `POST /v1/import` — enqueues `tofu import <address>
  <resource_id>`.
- `POST /v1/import/state-resource-ids` — enqueues `tofu state
  pull`; on exit code 0 the result's `stdout` is a JSON array of the
  provider ids of every managed resource instance in the state.
- `POST /v1/import/scope-resource-ids` — enqueues a cloud scope query
  via the CLI matching `terraform_provider` (`az` Resource Graph /
  `gcloud` Cloud Asset Inventory / `aws` Resource Groups Tagging
  API); on exit code 0 the result's `stdout` is a JSON array of the
  resource IDs that exist in `scope_id`. Cloud query failures end the
  job `succeeded` with a non-zero `exit_code`, like engine-level
  failures.
- `GET /v1/jobs/{job_id}` — job status (`queued` / `running` /
  `succeeded` / `failed`) plus `result` (succeeded) or `error`
  (failed). Engine-level failures end the job `succeeded` with a
  non-zero `exit_code` in the result; service-level faults end it
  `failed` with a `Problem` in `error`. Terminal jobs are kept in
  memory for `NEBULA_IAC_JOB_TTL` seconds, then poll as 404 (as after
  a restart).
- `GET /healthz` — liveness probe.
- Bearer-token auth on all `/v1/*` endpoints if `NEBULA_IAC_TOKEN` is
  set.

## Configuration

| Env var                                       | Required | Description                                            |
|-----------------------------------------------|----------|--------------------------------------------------------|
| `NEBULA_IAC_TOKEN`                            | no       | Bearer token clients must present.                     |
| `IAC_BINARY`                                  | no       | Name or absolute path of the IaC engine CLI. Default: `tofu` (OpenTofu); set `terraform` for the bundled Terraform. See "Choosing the IaC engine". |
| `NEBULA_IAC_JOB_TTL`                          | no       | Seconds a finished job stays pollable before it 404s. Default: `3600`. |
| Provider creds: `ARM_*`, `GOOGLE_*`, `AWS_*` | no       | The engine's providers read these directly (identical for OpenTofu and Terraform). Provide whichever your modules need; without them, `plan`/`apply`/`import` fail with the engine's own auth errors in the result's `stderr`. The cloud CLIs behind `scope-resource-ids` use their own ambient auth (`az login` state, `gcloud` credentials, `AWS_*`); their auth errors surface the same way. |

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
`init` / `validate` / `plan` / `show` / `apply` / `import` /
`state pull`, whose flags are identical across both engines, so any
Terraform-compatible engine on PATH (or at an absolute path) works.

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
run as root. The docker-compose stack hardens the container further —
`cap_drop: [ALL]`, `no-new-privileges`, a read-only root filesystem
(only `/workspaces`, `/tmp` and `$HOME` are writable, the latter two as
tmpfs) and CPU / memory / pid limits; see the `iac` service in
[`docker-compose.yml`](../../docker-compose.yml).

Because the engine writes `.terraform/`, `.terraform.lock.hcl`, plan
files and state next to the configuration, **workspace directories must
be writable by that uid**. In the compose stack this holds because the
core image is built with the same `NEBULA_UID` / `NEBULA_GID` and also
runs as `nebula`, so everything the core clones is owned by the same
user. Override the two build args together or not at all, and keep the
`uid=` / `gid=` options of the `/home/nebula` tmpfs in
`docker-compose.yml` in sync with them.

- **Existing volumes.** A `workspaces` volume created by a stack that
  ran as root keeps root-owned directories the engine can no longer
  write to (`plan` fails with `permission denied` on
  `terraform.tfstate` or the plan file). Fix it once, with the stack
  stopped:
  `docker run --rm -v nebula_workspaces:/w alpine chown -R 10001:10001 /w`,
  or drop the volume (it only holds transient clones):
  `docker volume rm nebula_workspaces`.
- **Other deployments.** On Kubernetes set `runAsUser: 10001` and
  `fsGroup: 10001` in the `securityContext` of the iac pod and of
  whatever writes the shared PersistentVolumeClaim; export an NFS
  workspace with matching ownership.
- **Cloud CLIs.** `az`, `gcloud` and `aws` keep their per-user state
  under `$HOME` (`~/.azure`, `~/.config/gcloud`, `~/.aws`). The
  `resource-graph` az extension is installed system-wide in
  `/opt/azure-cli-extensions` (`AZURE_EXTENSION_DIR`) so the runtime
  user finds it. Credential files you mount must be readable by uid
  `10001`.

## Run locally

```bash
cd services/iac
uv venv && source .venv/bin/activate
uv pip install -e '.[dev]'
uvicorn src.main:app --host 0.0.0.0 --port 8082
```

```bash
job_id=$(curl -s -X POST http://localhost:8082/v1/init \
  -H 'Content-Type: application/json' \
  -d '{"workspace_path":"/path/to/your/iac/dir"}' | jq -r .job_id)
curl http://localhost:8082/v1/jobs/$job_id   # repeat until succeeded/failed
```

## Tests

```bash
cd services/iac
uv pip install -e '.[dev]'
pytest
```

## Verifying conformance

The implementation-agnostic Schemathesis suite at
[`../../contracts/conformance/iac/`](../../contracts/conformance/iac/)
runs against any implementation of the IaC contract.

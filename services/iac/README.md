<!--
SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)

SPDX-License-Identifier: Apache-2.0
-->

# iac (reference implementation)

Reference implementation of [`contracts/openapi/iac.v1.yaml`](../../contracts/openapi/iac.v1.yaml).

The OSS default for the Nebula IaC contract: a raw terraform executor
that runs individual terraform CLI commands against a workspace path
on a docker-compose shared volume, as **asynchronous jobs**. Every
POST enqueues exactly one command and returns `202 Accepted` with a
`job_id` immediately; clients poll `GET /v1/jobs/{job_id}` for the raw
`{exit_code, stdout, stderr}` result. Sequencing commands and
interpreting their output is the caller's job (the core's
`TerraformValidator` owns the init → validate → plan → show pipeline
and drift parsing). Jobs targeting the same workspace run one at a
time in submission (FIFO) order.

## What it does

- `POST /v1/init` — enqueues `terraform init`.
- `POST /v1/validate` — enqueues `terraform validate`.
- `POST /v1/plan` — enqueues `terraform plan -out <plan_file>` with
  optional `-target=` filters.
- `POST /v1/show` — enqueues `terraform show -json <plan_file>`; on
  exit code 0 the result's `stdout` is the plan JSON.
- `POST /v1/apply` — enqueues `terraform apply <plan_file>`.
- `POST /v1/import` — enqueues `terraform import <address>
  <resource_id>`.
- `POST /v1/import/state-resource-ids` — enqueues `terraform state
  pull`; on exit code 0 the result's `stdout` is a JSON array of the
  provider ids of every managed resource instance in the state.
- `POST /v1/import/scope-resource-ids` — enqueues a cloud scope query
  via the CLI matching `terraform_provider` (`az` Resource Graph /
  `gcloud` Cloud Asset Inventory / `aws` Resource Groups Tagging
  API); on exit code 0 the result's `stdout` is a JSON array of the
  resource IDs that exist in `scope_id`. Cloud query failures end the
  job `succeeded` with a non-zero `exit_code`, like terraform-level
  failures.
- `GET /v1/jobs/{job_id}` — job status (`queued` / `running` /
  `succeeded` / `failed`) plus `result` (succeeded) or `error`
  (failed). Terraform-level failures end the job `succeeded` with a
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
| `TERRAFORM_BINARY`                            | no       | Override the terraform binary path. Default: `terraform`. |
| `NEBULA_IAC_JOB_TTL`                          | no       | Seconds a finished job stays pollable before it 404s. Default: `3600`. |
| Provider creds: `ARM_*`, `GOOGLE_*`, `AWS_*` | no       | Terraform reads these directly. Provide whichever your modules need; without them, `plan`/`apply`/`import` fail with terraform's own auth errors in the result's `stderr`. The cloud CLIs behind `scope-resource-ids` use their own ambient auth (`az login` state, `gcloud` credentials, `AWS_*`); their auth errors surface the same way. |

## Workspace assumption

The service operates on `workspace_path` as visible *inside* its
container. The OSS reference docker-compose deployment mounts a named
volume `workspaces` at `/workspaces` in both the `api` and `iac`
containers, so the core writes the cloned repo there and references the
same path when submitting jobs. Other deployments may use a
PersistentVolumeClaim (k8s), an NFS mount, or an entirely different
workspace-staging mechanism — same contract, different mechanics.

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
  -d '{"workspace_path":"/path/to/your/terraform/dir"}' | jq -r .job_id)
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

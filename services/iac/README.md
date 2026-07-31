<!--
SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)

SPDX-License-Identifier: Apache-2.0
-->

# iac (reference implementation)

Reference implementation of [`contracts/openapi/iac.v1.yaml`](../../contracts/openapi/iac.v1.yaml).

The OSS default for the Nebula IaC contract: runs terraform CLI
pipelines against a workspace path on a docker-compose shared volume,
as **asynchronous jobs**. Every POST returns `202 Accepted` with a
`job_id` immediately; clients poll `GET /v1/jobs/{job_id}` for the
result. Jobs targeting the same workspace run one at a time in
submission (FIFO) order.

## What it does

- `POST /v1/validate` — enqueues `terraform init` → `validate` → (when
  cloud credentials are present) `plan`; the job's `ValidateResult`
  carries `validation`, `feedback`, `terraform_plan`,
  `terraform_targets`. Optional drift parsing via `get_drift`.
- `POST /v1/apply` — enqueues `init` → `plan` → `apply`; the job's
  `ApplyResult` carries `success`, `feedback`, `terraform_output`.
- `POST /v1/import` — enqueues `init` → `import`; the job's
  `ImportResult` carries `success`, `feedback`.
- `GET /v1/jobs/{job_id}` — job status (`queued` / `running` /
  `succeeded` / `failed`) plus `result` (succeeded) or `error`
  (failed). Terraform-level failures (a failing init/validate/plan/
  apply/import, or drift) end the job `succeeded` with a false success
  flag in the result; service-level faults end it `failed` with a
  `Problem` in `error`. Terminal jobs are kept in memory for
  `NEBULA_IAC_JOB_TTL` seconds, then poll as 404 (as after a restart).
- `GET /healthz` — liveness probe.
- Bearer-token auth on all `/v1/*` endpoints if `NEBULA_IAC_TOKEN` is
  set.
- Skips `terraform plan` when no cloud-provider env vars are present
  (so the service is useful for syntax validation in
  no-credentials environments without producing misleading errors).
  Override with `NEBULA_IAC_ALLOW_PLAN_WITHOUT_CREDS=true`.

## Configuration

| Env var                                       | Required | Description                                            |
|-----------------------------------------------|----------|--------------------------------------------------------|
| `NEBULA_IAC_TOKEN`                            | no       | Bearer token clients must present.                     |
| `TERRAFORM_BINARY`                            | no       | Override the terraform binary path. Default: `terraform`. |
| `NEBULA_IAC_ALLOW_PLAN_WITHOUT_CREDS`         | no       | Run `terraform plan` even when no provider creds are set. Default: `false`. |
| `NEBULA_IAC_JOB_TTL`                          | no       | Seconds a finished job stays pollable before it 404s. Default: `3600`. |
| Provider creds: `ARM_*`, `GOOGLE_*`, `AWS_*` | no       | Terraform reads these directly. Provide whichever your modules need. |

## Workspace assumption

The service operates on `workspace_path` as visible *inside* its
container. The OSS reference docker-compose deployment mounts a named
volume `workspaces` at `/workspaces` in both the `api` and `iac`
containers, so the core writes the cloned repo there and references the
same path when calling `/v1/validate`. Other deployments may use a
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
job_id=$(curl -s -X POST http://localhost:8082/v1/validate \
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

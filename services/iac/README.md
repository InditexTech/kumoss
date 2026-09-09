<!--
SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)

SPDX-License-Identifier: Apache-2.0
-->

# iac (reference implementation)

Reference implementation of [`contracts/openapi/iac.v1.yaml`](../../contracts/openapi/iac.v1.yaml).

The OSS default for the Nebula IaC contract: a raw IaC-engine executor
that runs individual engine CLI commands (**OpenTofu** by default,
Terraform via the `IAC_BINARY` knob in `src/config.py`) against a workspace path on a
docker-compose shared volume, as **asynchronous jobs**. Every
POST enqueues exactly one command and returns `202 Accepted` with a
`job_id` immediately; clients poll `GET /v1/jobs/{job_id}` for the raw
`{exit_code, stdout, stderr}` result. Sequencing commands and
interpreting their output is the caller's job (the core's
`TerraformValidator` owns the init → validate → plan → show pipeline
and drift parsing). Jobs targeting the same workspace run one at a
time in submission (FIFO) order.

## What it does

The commands below are shown for the default engine (`tofu`); when
`IAC_BINARY` in `src/config.py` is set to `terraform` it runs the same
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
  memory for `JOB_TTL_SECONDS` seconds (`src/config.py`), then poll as 404 (as after
  a restart).
- `GET /healthz` — liveness probe.
- Bearer-token auth on all `/v1/*` endpoints if `NEBULA_IAC_TOKEN` is
  set.

## Configuration

Settings are split by kind, mirroring the core's `config.yaml` / `.env`
split:

- **Secrets and deployment-specific values** come from the environment
  (`env.sample` → `.env`). The service reads only the variables in the
  first table below.
- **Knobs** (deployment-tunable, non-secret) are constants at the top of
  [`src/config.py`](src/config.py). They are not read from the
  environment; setting e.g. `LOG_LEVEL=DEBUG` in `.env` has no effect.
  The image copies `src/` at build time, so changing a knob means
  editing the file and rebuilding the `iac` image.
- **Pass-through** variables are neither: the service never reads them,
  but the engine and the cloud CLIs do, straight from the process
  environment, so they stay in `.env`.

### Environment variables (read by the service)

| Env var                                       | Required | Description                                            |
|-----------------------------------------------|----------|--------------------------------------------------------|
| `NEBULA_IAC_TOKEN`                            | no       | Bearer token clients must present. Empty disables auth. |
| `ARM_CLIENT_ID`, `ARM_CLIENT_SECRET`, `ARM_TENANT_ID` | no | Azure service principal. When all three are set the service runs `az login` at startup and on refresh. See "Cloud credentials and `scope_id`". |
| `GOOGLE_APPLICATION_CREDENTIALS` or `GOOGLE_CREDENTIALS` | no | GCP service-account key, as a file path or inline JSON. When set the service runs `gcloud auth activate-service-account` at startup and on refresh. |
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` | no       | AWS static keys. No login step; inherited by the engine and the `aws` CLI. Both are read by the service and both are required for AWS to count as a configured provider: setting only one aborts startup, and `AWS_PROFILE` or an instance role alone is not detected (scoped jobs then fail with `422` unless another provider is configured). |
| `AWS_TERRAFORM_ROLE_NAME`                     | no       | IAM resource path of a role to assume via STS for AWS `scope_id`s, as `arn:aws:iam::{scope_id}:{value}`. Must include the `role/` prefix, e.g. `role/nebula-terraform`. |
| `TF_BACKEND_CONFIG`                           | no       | Path, relative to the workspace, of a backend configuration file passed to `init` as `-backend-config=<path>`. Empty uses the backend block in the HCL as-is. |

### Environment variables (pass-through, not read by the service)

| Env var                                       | Description                                            |
|-----------------------------------------------|--------------------------------------------------------|
| `ARM_ACCESS_KEY`                              | Storage account access key for the `azurerm` backend, when the service principal lacks Storage Blob Data Contributor on the state storage account. |
| `GOOGLE_BACKEND_IMPERSONATE_SERVICE_ACCOUNT`  | Service account to impersonate for GCS backend state access. |
| `AWS_DEFAULT_REGION`, `AWS_PROFILE`           | Read by the engine's AWS provider and the `aws` CLI. |
| Other `ARM_*`, `GOOGLE_*`, `AWS_*`, `TF_*`    | Passed through to the engine's providers and backends unchanged (identical for OpenTofu and Terraform). |

### Knobs in `src/config.py` (non-secret)

| Constant                                      | Default | Description                                            |
|-----------------------------------------------|---------|--------------------------------------------------------|
| `IAC_BINARY`                                  | `tofu`  | Name or absolute path of the IaC engine CLI. `tofu` (OpenTofu) or `terraform` for the bundled Terraform. See "Choosing the IaC engine". |
| `JOB_TTL_SECONDS`                             | `3600`  | Seconds a finished job stays pollable before it 404s. |
| `SUBPROCESS_TIMEOUT_SECONDS`                  | `2700`  | Seconds a single engine command may run before the job fails with a `504` error. `0` disables. |
| `LOG_LEVEL`                                   | `INFO`  | Log level. Engine stdout/stderr is never logged; it is returned in the job result, and each job logs one terminal line with its `exit_code`. |
| `CLOUD_LOGIN_REFRESH_MIN`                     | `45`    | Minutes after which the next `scope-resource-ids` job re-runs the cloud CLI logins before executing. Engine jobs do not log in (see "Cloud credentials and `scope_id`"). |
| `CLOUD_LOGIN_RETRIES`, `CLOUD_LOGIN_RETRY_DELAY_SEC` | `3`, `2.0` | Retries for a failed re-login and the initial backoff delay in seconds (doubles each retry). Startup never retries. |

## Cloud credentials and `scope_id`

The service authenticates the cloud CLIs itself; it does not rely on
ambient `az login` / `gcloud auth` state in the container.

- **Startup login is all-or-nothing.** At boot, every provider whose
  credentials are *complete* (all three `ARM_*` values; a GCP key) is
  logged in. A provider with no credentials is skipped with an info
  log; a provider with *some* of its variables set aborts startup
  before any CLI runs, naming every missing variable. A provider with
  complete credentials whose login **fails aborts startup**: the service exits rather than accepting jobs it would fail
  later with opaque engine auth errors. All configured providers are
  attempted before failing, so one startup log shows every broken
  credential.
- **Refresh applies to CLI jobs only.** Engine commands (`init`,
  `validate`, `plan`, `show`, `apply`, `import`, `state-resource-ids`)
  authenticate from the env vars the service injects (`ARM_*`,
  `GOOGLE_*`, `AWS_*`), never from the CLI session, so they run without
  a login check. Only `scope-resource-ids`, which shells out to `az` /
  `gcloud` / `aws` itself, re-runs the logins first once
  `CLOUD_LOGIN_REFRESH_MIN` minutes (`src/config.py`) have elapsed.
  Because a token refresh failure is usually transient, failed providers
  are retried `CLOUD_LOGIN_RETRIES` times with exponential backoff
  starting at `CLOUD_LOGIN_RETRY_DELAY_SEC` seconds, re-attempting only
  the ones that failed. Only when every retry fails does the job end
  `failed` with a `500` error; the next job tries again. Consequence: a
  backend that relies on the CLI session (`azurerm` with `use_cli`,
  `gcs` on gcloud ADC) is not supported; configure backend credentials
  through env vars instead.
- **`scope_id` is required on every engine command.** Provider
  blocks in generated code do not carry a subscription/project/account,
  so `init`, `validate`, `plan`, `show`, `apply`, `import` and
  `state-resource-ids` all require `scope_id` (Azure: subscription id,
  GCP: project id, AWS: account id); a missing or empty value is a
  schema `422` at submit time. The service injects it into the
  engine's environment as `ARM_SUBSCRIPTION_ID` and `GOOGLE_PROJECT`,
  and, if `AWS_TERRAFORM_ROLE_NAME` is set and AWS credentials are
  configured, assumes `arn:aws:iam::{scope_id}:{role}` and injects the
  temporary keys. Because the scope always comes from the request,
  `ARM_SUBSCRIPTION_ID` and `GOOGLE_PROJECT` are deliberately not
  service configuration: do not set them in the service's environment.
- **At least one provider must be configured.** If no provider has
  complete credentials, every job ends `failed` with a `422` `Problem`
  listing the missing variables per provider, because there is nothing
  the scope could apply to. The engine is not invoked.
- **Cross-cloud plans are not supported.** A workspace targets one
  cloud. When AWS credentials and a role name are configured alongside
  Azure or GCP credentials, an Azure/GCP `scope_id` still triggers an
  AssumeRole attempt that cannot succeed (it is not an account id).
  That failure is logged at debug level and ignored; the job continues
  with the scope injected for the provider it targets. When AWS is the
  **only** configured provider, the `scope_id` can only be an AWS
  account, so a failed AssumeRole (denied, wrong role name, STS outage)
  ends the job `failed` with a `500` naming the role ARN. It is never
  ignored there: doing so would run the engine on the service's static
  keys, i.e. against whatever account those keys belong to.
- **`scope-resource-ids`** also requires `scope_id`, but there it names
  the scope being *listed* rather than the scope a command runs against.

## Choosing the IaC engine

The bundled image ships both engines; the `IAC_BINARY` constant in
`src/config.py` selects one (edit it and rebuild the image to switch):

- **OpenTofu 1.12.6** (MPL-2.0) — the default (`IAC_BINARY = "tofu"`).
  Installed from the official
  `ghcr.io/opentofu/opentofu:<version>-minimal` image, pinned by digest
  in the [Dockerfile](Dockerfile).
- **HashiCorp Terraform 1.16.0** (BUSL-1.1) — `IAC_BINARY = "terraform"`.
  Fetched from `releases.hashicorp.com` at build time (version via the
  `TERRAFORM_VERSION` build arg) and checksum-verified; your use of it
  is subject to its license terms.

The service itself is engine-agnostic: it only shells out to
`init` / `validate` / `plan` / `show` / `apply` / `import` /
`state pull`, whose flags are identical across both engines, so any
Terraform-compatible engine on PATH (or at an absolute path) works.
`TF_BACKEND_CONFIG` and the `TF_*` provider variables are honoured by
both engines.

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

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
- `POST /v1/import` — enqueues `tofu import <address> <resource_id>`.
  The resource block for `address` must already exist in the
  workspace; the engine reports it if not.
- `POST /v1/import/state-resource-ids` — enqueues `tofu state pull`
  and, on exit code 0, answers a JSON array of the IDs of every
  managed resource instance the state tracks. The workspace must
  already be initialised.
- `POST /v1/import/scope-resource-ids` — the one endpoint that runs no
  engine command: it queries the cloud's own inventory API and answers
  a JSON array of the resource IDs under `scope_id`, minus the ones
  another control plane owns. See "Import discovery" below.
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

`init`, `plan`, `apply`, `import` and `import/scope-resource-ids`
reach a cloud API, so they must carry `scope_id` (the cloud scope the
command targets) and `terraform_provider` (which cloud that is); the
contract requires both and a missing or empty value is a `422`.
`validate`, `show` and `import/state-resource-ids` take no scope, so
their bodies declare neither field — every request schema forbids
unknown properties, so sending one is also a `422`.

Generated provider blocks name no scope, so for `init`, `plan`,
`apply` and `import` the service injects `scope_id` into the engine
subprocess's environment for that command only — where the cloud has a
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

`import/scope-resource-ids` is the exception: it launches no
subprocess, so there is no environment to overlay. Its `scope_id` is
the argument of the inventory query itself — the subscription,
project or account whose contents are listed.

## Import discovery

`POST /v1/import/scope-resource-ids` answers the question "what already
exists here that Terraform does not manage yet?". It talks to each
cloud's inventory API directly over HTTPS — no `az`, `gcloud` or `aws`
binary is involved, and none is present in the image. Tokens come from
the official auth libraries (`azure-identity`, `google-auth`, boto3's
default chain) reading the same `ARM_*`, `GOOGLE_*` and `AWS_*`
variables the engine's providers use, so most deployments that can run
`plan` can run discovery unchanged. Two Azure rows are the exception —
interactive `az login` and the CI runner's `ARM_OIDC_REQUEST_URL`
exchange have no discovery equivalent; see `PROVIDERS.md`.

| `terraform_provider` | Source                                                     | Scope is             |
|----------------------|------------------------------------------------------------|----------------------|
| `azure`              | Resource Graph `providers/Microsoft.ResourceGraph/resources` | subscription ID    |
| `gcp`                | Cloud Asset Inventory `searchAllResources` + Resource Manager `getIamPolicy` | project ID |
| `aws`                | Resource Explorer `ListResources`                          | account ID           |
| `oci`, `kubernetes`  | none                                                       | —                    |

`oci` and `kubernetes` are answered with exit code 2 and
`no scope discovery for provider '<p>'` in `stderr`. That is a
deliberate outcome, not a crash: the job still ends `succeeded`, and
the exit code tells the caller the provider is unsupported rather than
that a cloud call failed.

### What is left out

Resources whose lifecycle belongs to another control plane are excluded
at the query, so the caller never sees them. Importing them would put
Terraform in a fight it loses.

- **Azure**: resource groups with a `managedBy` (Databricks, HDInsight,
  Batch), AKS node resource groups (`MC_*`), `NetworkWatcherRG`, and
  everything inside them; App Service smart-detector alert rules; any
  resource carrying a `hidden-link*` tag.
- **GCP**: the project asset itself; anything labelled `goog-*`
  (which covers GKE-created disks and `goog-terraform-provisioned`);
  resources whose name ends in a `gke-*` segment (node instances,
  instance groups, templates, firewall rules); Dataproc, Cloud
  Functions, Cloud Run and Cloud Build staging buckets.
- **AWS**: every `ec2:network-interface` (ENIs are almost always
  created by another service — Lambda, RDS, ELB, EKS — and are
  imported with their owner, not on their own); service-linked and
  AWS SSO reserved IAM roles; anything tagged `aws:*` (CloudFormation
  and CDK stacks), `eks:*`, `kubernetes.io/*`, `k8s.io/*`,
  `alpha.eksctl.io/*` or the AWS Load Balancer Controller's
  `*.k8s.aws/*` tags; and resources owned by another account that the
  view can see.

### ID normalization

The service, not the caller, decides the ID shape.

- **Azure** emits full ARM resource IDs, plus resource-group and
  role-assignment IDs. ARM IDs are case-insensitive in their provider
  and type segments, so compare them case-insensitively against state.
- **GCP** emits asset names with the `//service.googleapis.com/`
  prefix stripped and any `projects/<number>` rewritten to
  `projects/<project-id>`, because Cloud Asset Inventory reports some
  services by project number while Terraform IDs use the ID. Project
  IAM produces one entry per role and member,
  `<project-id>/<role>/<member>`, matching the `id`
  `google_project_iam_member` stores in state so the two listings line
  up. Importing one takes the provider's own space-delimited
  identifier, `<project-id> <role> <member>`. `deleted:` members and
  Google's own service agents are dropped; service accounts belonging
  to the project itself are kept.
- **AWS** emits ARNs. `POST /v1/import/state-resource-ids` prefers a
  resource's `arn` attribute over its `id` for the same reason, so the
  two lists are directly comparable.

### Prerequisites and permissions

- **Azure**: `Reader` on the subscription is enough. Resource Graph
  needs no separate enablement.
- **GCP**: enable `cloudasset.googleapis.com` and
  `cloudresourcemanager.googleapis.com` on the project that owns the
  credentials — no `x-goog-user-project` header is sent, so quota and
  API enablement are evaluated there, not on the project being listed.
  On the listed project the identity needs `roles/cloudasset.viewer`
  and `roles/viewer`, which grants the
  `resourcemanager.projects.get` and
  `resourcemanager.projects.getIamPolicy` the lister calls.
- **AWS**: **Resource Explorer must be enabled for the account.**
  Create an *aggregator* index in one region, a local index in every
  region you want discovered, and a default view in the aggregator
  region; the console's quick setup creates all of these. A region with
  no local index contributes nothing to the listing. Then grant the
  identity `resource-explorer-2:ListIndexes`,
  `resource-explorer-2:GetDefaultView`,
  `resource-explorer-2:ListResources`
  and `sts:GetCallerIdentity`.
  Without it the job ends with exit code 1 and
  `AWS Resource Explorer is not enabled for account <id>`.
  `AWS_REGION` (or `AWS_DEFAULT_REGION`) must be set: it is where the
  index lookup starts. Only the account the ambient credentials belong
  to can be listed; a `scope_id` naming another account is refused
  before any listing call.

### Known gaps

- Azure Resource Graph lists top-level ARM resources only. Child
  resources — subnets, NSG rules, VM extensions — are not rows and are
  not emitted; the parent's ID is.
- A few GCP resource types have a Terraform ID shape that differs from
  the normalized asset name. `google_project_service` is the known
  case.
- GCP conditional IAM bindings are emitted without their condition.
- An AWS ARN is not the import ID for most resource types
  (`aws_instance` takes the instance ID, `aws_s3_bucket` the bucket
  name). Turning an ARN into the argument for `POST /v1/import` is the
  caller's job.
- ARM resource IDs are reported exactly as Resource Graph returns
  them, and providers disagree about the casing of the
  `resourceGroups` segment. Diffing an Azure listing against state can
  therefore report a difference that is only a difference in case —
  something AWS and GCP listings do not do. The service does not
  normalize the casing: lowercasing an ARM ID can make it unusable as
  the `resource_id` argument to `POST /v1/import`.
- GCP discovery accepts modern project ids only. A legacy
  domain-scoped id (`example.com:my-project`) is rejected before any
  API call and ends the job with exit code 1.
- Azure sovereign clouds, and the `az login` and CI-injected OIDC
  request-URL flows, are not supported for discovery. Provider
  commands still accept them.
- Each cloud is paged to a bounded number of requests (100 pages for
  Azure, 200 for GCP and AWS). A scope large enough to exceed that
  ends the job with exit code 1 rather than truncating the list
  silently.

## State backend

The service does not choose where state goes. `init` reads the
backend from the workspace it is handed, which is the caller's to
prepare: Nebula's core writes a `backend_override.tf` into the
workspace before calling `init`, pinning state to the object store it
already holds the credentials for (see the core's
`storage.terraform_state_bucket`). Terraform merges `*_override.tf`
over the rest of the configuration, so an override both introduces a
backend where the workspace declares none and replaces one that it
does declare — any caller can use the same trick.

`IAC_BACKEND_CONFIG` is the escape hatch for a deployment that owns the
decision instead. Set it to the path (inside this container) of a
backend configuration file — `.hcl` or `.tfbackend`, mounted in — and
`init` runs with `-backend-config=<path>`, with the backend *type*
still coming from the workspace's own `terraform { backend }` block.
The service checks at startup that the path is a readable file and
refuses to boot if it is not, for the same reason the engine binary is
checked there. Note that a `backend_override.tf` in the workspace wins
over the values in this file: the two are alternatives, not layers.

**Reinitialization.** `init` always runs `-reconfigure`, so a workspace
whose backend changed between calls is rebound to the new one instead
of failing with *"Backend configuration changed"* (which
`-input=false` could not answer interactively). State already in the
target backend is adopted; state held under the previous backend is
**not** migrated — move it yourself (`terraform state push`, or a
manual `init -migrate-state`) if it matters.

## Configuration

| Env var                                       | Required | Description                                            |
|-----------------------------------------------|----------|--------------------------------------------------------|
| `NEBULA_IAC_TOKEN`                            | no       | Bearer token clients must present.                     |
| `IAC_BINARY`                                  | no       | Name or absolute path of the IaC engine CLI. Default: `tofu` (OpenTofu); set `terraform` for the bundled Terraform. See "Choosing the IaC engine". |
| `IAC_BACKEND_CONFIG`                          | no       | Path (inside this container) to a backend configuration file `init` passes to `-backend-config`. Unset, the backend comes from the workspace itself. See "State backend". |
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

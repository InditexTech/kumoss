<!--
SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)

SPDX-License-Identifier: Apache-2.0
-->

# State backends

The authoritative reference for **where Nebula keeps Terraform/OpenTofu state**: the `storage.terraform_state_bucket` setting in `config.yaml`, the `IAC_BACKEND_CONFIG` variable on the IaC sidecar, and how the two interact.

**Contents**

- [Why remote state matters here](#why-remote-state-matters-here)
- [What ships by default](#what-ships-by-default)
- [The three ownership models](#the-three-ownership-models)
- [Model 1 — repository-declared backend (shipped default)](#model-1--repository-declared-backend-shipped-default)
- [Model 2 — Nebula-managed state (opt-in)](#model-2--nebula-managed-state-opt-in)
- [Model 3 — sidecar-supplied backend configuration](#model-3--sidecar-supplied-backend-configuration)
- [How core and sidecar configuration interact](#how-core-and-sidecar-configuration-interact)
- [Changing backend configuration](#changing-backend-configuration)
- [What Nebula does not do](#what-nebula-does-not-do)
- [Operations](#operations)
- [Troubleshooting](#troubleshooting)
- [Reference](#reference)

## Why remote state matters here

Nebula's workspaces are **ephemeral by design**: every call clones the repository into a fresh directory on the shared `workspaces` volume and deletes it in a `finally` block, and the workspace pinned for an apply is removed once the apply completes. Nothing there survives. Hence a remote backend is not optional:

1. **A local state file would be lost.** `terraform.tfstate` written next to the configuration dies with the clone directory, and the next session plans against empty state — proposing to create infrastructure that already exists.
2. **State must be shared across runs, not across directories.** Two sessions on the same project get two different clone paths, so only something that describes *the project* can bring their state together. Nebula derives that identity itself (see [State keys](#state-keys)).

The seeded `.gitignore` excludes `*.tfstate`, `*.tfstate.*`, and `*_override.tf`, so state and the generated backend file never reach a commit or a pull request.

## What ships by default

**The shipped `config.yaml` sets `storage.terraform_state_bucket:`, so Nebula configures no backend at all.** The backend is yours to provide: every repository Nebula operates on must declare its own remote backend, and the IaC sidecar must hold the credentials to reach it. A repository with no backend block falls back to local state, which is lost with the workspace.

If you  are starting from empty state and just want somewhere for it to go **set `storage.terraform_state_bucket` to a bucket name** and Nebula takes over: it creates the bucket, writes the backend, and assigns a state key per project. The bucket is created in the provider defined in `storage.provider: "RUSTFS"` with RustFS as default.
```yaml
# Opt in to Nebula-managed state. Nothing else to configure on RUSTFS.
storage:
  provider: "RUSTFS"
  terraform_state_bucket: "nebula-terraform-state"
```

> **Keep the key, even when it is empty.** Blank means either no value — the shipped spelling — or `""`; both leave state to the repository. Deleting the key does not: the field's default in code is `nebula-terraform-state`, so a `config.yaml` without `terraform_state_bucket` turns Nebula-managed state back **on**.

## The three ownership models

Exactly one party decides where state goes. Pick deliberately.

| # | Model | Who decides | Selected by |
|---|---|---|---|
| **1** | **Repository-declared backend** — *shipped default* | Each **repository's own HCL** | `terraform_state_bucket` blank and `IAC_BACKEND_CONFIG` unset |
| **2** | **Nebula-managed state** — *opt-in* | The **core**, from `storage.*` | `terraform_state_bucket` set to a bucket name |
| **3** | **Sidecar-supplied backend configuration** — *opt-in* | The **deployment**, via a mounted file | `terraform_state_bucket` blank and `IAC_BACKEND_CONFIG` set |

Which one is appropriate:

| Deployment | Recommended model | Why |
|---|---|---|
| Local / non-production, no backend set up yet | **2** with `RUSTFS` | One line of configuration, no cloud account, no credentials; state survives restarts in the bundled store. |
| Local / non-production against a real cloud project | **1**, as shipped | Reuses the backend your repositories already declare, so local runs and CI plan against the same state. |
| Production, repositories already have backends you must not change | **1**, as shipped | Nebula writes nothing; each repository keeps the backend its team declared. |
| Production, Nebula owns the projects it generates | **2** with `S3` or `STORAGE_ACCOUNT` | One managed store, one credential set, one lifecycle policy, state keys assigned automatically. |
| Production, one central backend for every project, defined outside Nebula | **3** | Backend values live in a file your platform mounts and rotates. |

## Model 1 — repository-declared backend (shipped default)

The shipped `config.yaml` leaves the state bucket blank:

```yaml
storage:
  provider: "RUSTFS"
  bucket: "nebula-artifacts"
  terraform_state_bucket:
```

A key with no value, `""`, and whitespace-only (`"   "`) are all equally blank; deleting the key is not, because its default in code is `nebula-terraform-state`, which would turn model 2 on. What this means:

- No state bucket or container is created at boot.
- **No `backend_override.tf` is written.** Each workspace keeps the backend its own committed configuration declares.
- **Every repository Nebula operates on must declare a working remote backend** — `azurerm`, `s3`, `gcs`, or any other the engine supports. With **no** backend block the engine falls back to local state, lost with the workspace, so the next session plans against nothing.
- The engine resolves that backend with the **IaC sidecar's** credentials — a second grant alongside the provider credentials (see below).

A typical repository therefore carries its own backend block, which Nebula reads and leaves alone:

```hcl
terraform {
  backend "s3" {
    bucket       = "acme-team-tfstate"
    key          = "envs/prod/terraform.tfstate"
    region       = "eu-west-1"
    use_lockfile = true
  }
}
```

Nothing here is Nebula-specific: the same backend serves your CI and your engineers' laptops, which is the main reason to prefer this model when the repositories already have one.

### Two sets of credentials on the sidecar

`services/iac/.env` must satisfy **two different authentications**, and a setup that only covers the first fails at `init`, before a single resource is planned:

| What | Used by | Grants access to |
|---|---|---|
| **Provider credentials** | `plan`, `apply` | The cloud resources your modules create |
| **State-backend credentials** | `init` | The state store the repository's backend block names |

They are separate because they address separate resources. Often the *same* variables serve both — an `s3` backend and the `aws` provider both read `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` — but even then the identity behind them must be granted access to the state bucket, which commonly lives in a different account, subscription, or project. Some backends read variables the providers never look at, precisely so the two identities can differ:

| Backend | Backend-only variables |
|---|---|
| `azurerm` | `ARM_ACCESS_KEY` (storage account key), `ARM_SAS_TOKEN`, `ARM_USE_AZUREAD` |
| `gcs` | `GOOGLE_BACKEND_CREDENTIALS`, `GOOGLE_IMPERSONATE_SERVICE_ACCOUNT` |
| `s3` | `AWS_PROFILE` / `AWS_ROLE_ARN` pointing at the state account |

Per-cloud, per-authentication-method minimums for both sets are in [`services/iac/PROVIDERS.md`](../services/iac/PROVIDERS.md) (provider minimums, then *Backend minimums*); the variable-level view is in [Cloud credentials for the IaC engine](environment-variables.md#cloud-credentials-for-the-iac-engine).

Model 2 can spare you the second set: Nebula writes the backend itself, and where the rendered block embeds static keys — the `RUSTFS` case, and `S3`/`STORAGE_ACCOUNT` with keys in `core/.env` — the sidecar needs nothing for state. Where it does not embed them, the sidecar still has to resolve them; see [Credentials required](#credentials-required).

## Model 2 — Nebula-managed state (opt-in)

Set the state bucket to a name and Nebula owns state instead:

```yaml
storage:
  provider: "RUSTFS"
  bucket: "nebula-artifacts"
  terraform_state_bucket: "nebula-terraform-state"
  endpoint_url: "http://object-storage:9000"
  public_endpoint_url: "http://localhost:9000"
  region: "us-east-1"
```

This is the quickest way to get a working remote backend when there is none yet: on `RUSTFS` the bucket name is the only value you supply, and the repositories need no backend block at all.

State goes to the **same object-storage provider as artifacts**, in a **separate bucket** (a blob container on `STORAGE_ACCOUNT`). The separation is deliberate: state must not inherit the lifecycle, expiry, or presign policy you apply to generated reports and plans.

### What Nebula manages automatically

| When | What happens |
|---|---|
| Core start-up | The state bucket (or container) is **created if missing**, with the same credentials used for artifacts. If the store is unusable the core **fails to boot**, alongside the database, Redis, and artifact-bucket checks. |
| Before every `init` | The core writes a `backend_override.tf` into the workspace, addressing the state bucket with a key derived from the project. |
| Per project | The state key is assigned from a digest of the repository, cloud scope, and root-module path — no configuration, no per-repository setup. |
| On apply | The pinned workspace is *moved*, not copied, so the override and the initialized `.terraform/` travel with it: the apply writes to the same state the plan was made against, without re-running `init`. |
| On every run | `backend_override.tf` is excluded by the seeded `.gitignore`, so it never reaches a commit or a pull request. |

The override wins over whatever the repository declares: Terraform and OpenTofu merge `*_override.tf` **over** the rest of the configuration, so one file both *introduces* a backend where the repository declares none and *replaces* one it does declare. Nebula never edits the repository's committed HCL. The core logs the target on every `init`:

```
Terraform state: rustfs bucket=nebula-terraform-state key=<project_id>/terraform.tfstate
```

### Per-provider configuration

The backend type follows `storage.provider`. There is no separate setting for it, and no combination in which state and artifacts live in different stores.

#### `RUSTFS` — the bundled store, or any S3-compatible server

The default `storage.provider`, and the least work: in the Compose stack the bucket name is the only value to add.

```yaml
storage:
  provider: "RUSTFS"
  terraform_state_bucket: "nebula-terraform-state"
  endpoint_url: "http://object-storage:9000"
  region: "us-east-1"
```

Rendered into each workspace as `backend_override.tf`:

```hcl
terraform {
  backend "s3" {
    bucket = "nebula-terraform-state"
    key    = "<project_id>/terraform.tfstate"
    region = "us-east-1"

    access_key = "rustfsadmin"
    secret_key = "rustfsadmin"

    endpoints = {
      s3 = "http://object-storage:9000"
    }

    use_path_style              = true
    skip_credentials_validation = true
    skip_region_validation      = true
    skip_requesting_account_id  = true
    skip_metadata_api_check     = true
    skip_s3_checksum            = true
    use_lockfile                = true
  }
}
```

The `skip_*` flags exist because a non-AWS S3 implementation has no account-id endpoint, no EC2 instance-metadata service, and no region validation; the checksum skip accommodates servers without S3 trailing checksums. `use_path_style` addresses buckets as `<endpoint>/<bucket>` rather than as a virtual host.


#### `S3` — AWS S3

```yaml
storage:
  provider: "S3"
  bucket: "acme-nebula-artifacts"
  terraform_state_bucket: "acme-nebula-tfstate"
  region: "eu-west-1"
```

`endpoint_url` and `public_endpoint_url` are ignored: Terraform and the AWS SDK both build the regional endpoint from `region`. With static keys configured:

```hcl
terraform {
  backend "s3" {
    bucket = "acme-nebula-tfstate"
    key    = "<project_id>/terraform.tfstate"
    region = "eu-west-1"

    access_key = "AKIAEXAMPLE"
    secret_key = "examplesecret"

    use_lockfile = true
  }
}
```

With **no** static keys — the recommended production shape — the credential lines are omitted entirely and the engine resolves credentials as any AWS SDK client does, from an instance profile, IRSA, or a workload identity on the **IaC sidecar's** container:

```hcl
terraform {
  backend "s3" {
    bucket = "acme-nebula-tfstate"
    key    = "<project_id>/terraform.tfstate"
    region = "eu-west-1"

    use_lockfile = true
  }
}
```

> **Blank the RustFS keys when you switch to `S3`.** `storage.access_key_env` and `storage.secret_key_env` still name `RUSTFS_ACCESS_KEY` and `RUSTFS_SECRET_KEY` by default, and `core/env.sample` ships them set to `rustfsadmin`. A non-empty value always wins, so leaving them set embeds `rustfsadmin` into the backend block and every `init` fails against AWS.

#### `STORAGE_ACCOUNT` — Azure Blob Storage

```yaml
storage:
  provider: "STORAGE_ACCOUNT"
  bucket: "nebula-artifacts"
  terraform_state_bucket: "nebula-terraform-state"
  endpoint_url: "https://acmenebula.blob.core.windows.net"
  public_endpoint_url: "https://acmenebula.blob.core.windows.net"
```

`terraform_state_bucket` names a **blob container**, not a bucket. The account name is derived from `endpoint_url`; `region` is ignored.

```hcl
terraform {
  backend "azurerm" {
    storage_account_name = "acmenebula"
    container_name       = "nebula-terraform-state"
    key                  = "<project_id>/terraform.tfstate"
    access_key           = "azure-shared-key"
  }
}
```

> **The shared key is mandatory and is always embedded.** The core refuses to boot with `provider: STORAGE_ACCOUNT` and an empty `STORAGE_ACCOUNT_KEY` (`storage.provider STORAGE_ACCOUNT requires env var STORAGE_ACCOUNT_KEY.`), because the artifact adapter needs that key to sign SAS download URLs. The renderer contains an Entra ID branch (`use_azuread_auth = true`) for a keyless account, but **no supported configuration reaches it** in this release. Treat managed identity for Azure *state* as unavailable today; if you need it, use [model 3](#model-3--sidecar-supplied-backend-configuration).

### Credentials required

Two different components touch the state store, and they authenticate separately.

| Component | What it does | Credentials it uses |
|---|---|---|
| **Core** | Creates/checks the state bucket at boot | `storage.*_env` variables in `core/.env` — `RUSTFS_ACCESS_KEY`/`RUSTFS_SECRET_KEY`, the AWS default chain, or `STORAGE_ACCOUNT_KEY` |
| **IaC sidecar** | Reads and writes state on every `init`, `plan`, and `apply` | The static keys embedded in `backend_override.tf` when present; otherwise the sidecar container's own ambient credentials (`AWS_*`, IRSA, instance profile) |

This split is easy to get wrong: with `provider: S3` and no static keys, giving the **core** an instance role is not enough — the engine runs in the **IaC sidecar**, so that container needs the role too. The sidecar must also be able to **reach** `storage.endpoint_url`; in the Compose stack both `core` and `iac` are on `bridge-network`, so `http://object-storage:9000` resolves, but on another platform allow that egress explicitly.

Minimum permissions on the state bucket, in practice:

| Provider | Permissions |
|---|---|
| AWS S3 | `s3:ListBucket` on the bucket; `s3:GetObject`, `s3:PutObject`, `s3:DeleteObject` on `<bucket>/*` (this covers the `.tflock` object). Add `s3:CreateBucket` only if you want the core to create the bucket at boot rather than pre-creating it. |
| Azure Blob Storage | The account shared key, which conveys full container access. |
| RustFS / other S3-compatible | The access/secret key pair configured for the store. |

`services/iac/PROVIDERS.md` lists the per-cloud backend minimums in more detail, including the variables to set when state lives in a different account or project from the resources.

### State keys

State is keyed by **project**, not by session or directory:

```
<state_bucket>/<project_id>/terraform.tfstate
```

`project_id` is the SHA-256 hex digest of three newline-joined values:

1. the **normalized repository URI**, as `host/path`
2. the **cloud scope** (`scope_id` — subscription, project, or account), trimmed and lowercased
3. the **normalized root-module path** within the repository (`iac_path`)

Normalization means two spellings of the same project never split into two states: the repository URI is lowercased, loses a `.git` suffix, loses embedded push credentials, and accepts SCP-style SSH form; the module path is trimmed of surrounding and duplicate slashes.

| These all resolve to one project |
|---|
| `https://github.com/acme/infra.git` |
| `https://github.com/acme/infra` |
| `https://x-access-token:ghp_secret@github.com/acme/infra.git` |
| `HTTPS://GitHub.com/Acme/Infra.git` |
| `git@github.com:acme/infra.git` |

An empty `iac_path` is a valid project — the root module is the repository root. Because all three inputs matter, a change to **any** of them is a different project and therefore a different state file.


### Locking

State locking is enabled and is **native to the store** — Nebula provisions no extra infrastructure for it.

| Provider | Mechanism | Notes |
|---|---|---|
| `RUSTFS`, `S3` | `use_lockfile = true` | The engine's S3-native lock: a `<key>.tflock` object written with a conditional put next to the state. **No DynamoDB table** is used or needed. Requires OpenTofu ≥ 1.10 or Terraform ≥ 1.10 (the bundled engines are 1.12.6 and 1.16.0) and an S3 implementation that supports conditional writes. |
| `STORAGE_ACCOUNT` | Blob lease | Native to the `azurerm` backend and always on; no flag is rendered. |

## Model 3 — sidecar-supplied backend configuration

For a deployment that owns the backend decision centrally, the IaC sidecar accepts a backend configuration file. The path is resolved **inside the sidecar container**, so mount the file there:

```dotenv
# services/iac/.env
IAC_BACKEND_CONFIG=/etc/nebula/backend.hcl
```

```yaml
# docker-compose.override.yml
services:
  iac:
    volumes:
      - ./backend.hcl:/etc/nebula/backend.hcl:ro
```

`init` then runs with `-backend-config=/etc/nebula/backend.hcl`. The file holds backend *values* only — a `.hcl` or `.tfbackend` partial configuration:

```hcl
bucket = "acme-central-tfstate"
region = "eu-west-1"
```

Three constraints follow from how `-backend-config` works:

1. **The backend *type* still comes from the workspace.** The repository must declare `terraform { backend "s3" {} }` (possibly with an empty body); a file alone cannot introduce a backend where none is declared.
2. **You are responsible for state keys.** Terraform's `key` is a single value, so if every project reads the same file, every project shares one state file unless the repositories declare distinct keys themselves. Per-project keying is a feature of model 2 only.
3. **Blank means unset.** An empty or whitespace-only `IAC_BACKEND_CONFIG` is treated as not set.

The sidecar **verifies at startup** that the path is a readable file and refuses to boot otherwise:

```
IAC_BACKEND_CONFIG points at '/etc/nebula/backend.hcl', which is not a readable
file inside this container. Mount the backend configuration file there or unset
the variable.
```

This is the same fail-fast policy applied to `IAC_BINARY`: a mounting mistake is caught once at boot rather than on every request. The file must be readable by uid `10001` (`nebula`), the unprivileged user the image runs as.

## How core and sidecar configuration interact

The two settings are **alternatives, not layers**.

```
storage.terraform_state_bucket (core)        IAC_BACKEND_CONFIG (iac sidecar)
            │                                            │
            ▼                                            ▼
  writes backend_override.tf                  adds -backend-config=<path>
  into the workspace                          to the init command line
            │                                            │
            └──────────────► Terraform merge ◄───────────┘
                                   │
                   *_override.tf wins over both the
                   repository's HCL and -backend-config values
```

Precedence, highest first: **`backend_override.tf`** written by the core (model 2), then **`-backend-config` values** from `IAC_BACKEND_CONFIG` (model 3), then **the repository's own `terraform { backend }` block** (model 1).

So setting both is a misconfiguration: the mounted file is silently ineffective for any field the override also sets. **Leave `terraform_state_bucket` blank whenever you set `IAC_BACKEND_CONFIG`** — which is what ships, so this only matters if you turned managed state on.

| `terraform_state_bucket` | `IAC_BACKEND_CONFIG` | Effective model |
|---|---|---|
| blank *(shipped)* | unset *(shipped)* | **1** — repository-declared |
| set | unset | **2** — Nebula-managed |
| blank | set | **3** — sidecar-supplied |
| set | set | **2** — the mounted file is overridden; misconfiguration |

## Changing backend configuration

**Any change to `config.yaml` needs an image rebuild** (`docker compose build core && docker compose up -d core`), because the file is baked into the core image. To vary it per environment without rebuilding, mount `config.yaml` and point `NEBULA_CONFIG` at it — see [Images and configuration delivery](getting-started-production.md#14-images-and-configuration-delivery).

**Switching models moves nothing.** Turning managed state on does not import the state your repositories' backends hold; turning it off leaves whatever Nebula stored in its bucket, where those backends will not look for it. Migrate first, or accept that the affected projects start from empty state.

`init` **always** runs with `-reconfigure` (`tofu init -no-color -input=false -reconfigure`): Nebula runs the engine non-interactively, and `-input=false` cannot answer the *"Backend configuration changed"* prompt, so without it any workspace whose backend differs from its previous initialization would fail hard. What that means for you:

- **State already in the new backend is adopted.** Re-pointing a project at a backend that already holds its state is safe and needs no action.
- **State under the previous backend is not migrated.** `-reconfigure` deliberately skips the migration `-migrate-state` would perform. Nebula never copies state between backends.
- **A project therefore starts from empty state** after any change that alters its backend or its key — switching `storage.provider`, renaming `terraform_state_bucket`, moving the root module, changing the cloud scope — and the next plan proposes creating resources that already exist.

Migrate deliberately, before the next session runs, with the engine itself:

```bash
tofu state pull > project.tfstate           # against the old backend
tofu init -reconfigure -backend-config=...  # point at the new backend
tofu state push project.tfstate
```

`tofu init -migrate-state` run by hand in an equivalent workspace works too. Either way, keep the pulled file as a backup and verify with a plan that shows no changes before letting Nebula run again.

## What Nebula does not do

State ownership stops at "write the backend and key". Everything below is yours:

- **No state migration.** Never, between any two backends. See above.
- **No versioning or backups.** Nebula does not enable bucket versioning, object lock, soft delete, or point-in-time restore on the state bucket. Turn them on yourself — for state this matters far more than for artifacts.
- **No lifecycle or retention policy**, and no deletion: Nebula never removes a state object, so state for a decommissioned project persists until you delete it.
- **No DynamoDB lock table.** Locking uses the S3-native lockfile; there is nothing to provision.
- **No `gcs` backend adapter.** `ObjectStorageProvider` has exactly three members (`RUSTFS`, `S3`, `STORAGE_ACCOUNT`). A Google Cloud Storage bucket can only be reached through its S3-compatible interoperability endpoint with `provider: RUSTFS`, which the repository does not test. For a first-class `gcs` backend, use model 1 or 3 — and since model 1 ships as the default, that is simply what you already have.
- **No state encryption beyond the store's own.** State contains resource attributes and can contain secrets; rely on bucket-level encryption at rest and restrict access accordingly.
- **No import of existing state.** The `/v1/import*` endpoints of the IaC contract are unimplemented and answer `501`.

## Operations

This section assumes model 2. Under the shipped default the state bucket is not Nebula's, so its operation — versioning, access, backups — belongs to whoever owns the backend each repository declares.

**Find a project's state.** The core logs the target before every `init`:

```bash
docker compose logs core | grep "Terraform state:"
# Terraform state: rustfs bucket=nebula-terraform-state key=<project_id>/terraform.tfstate
```

**Inspect the bundled store.** RustFS speaks the S3 API, so any S3 client works. From the host, through the nginx server on port 9000 (it forwards the `Host` header unchanged, so SigV4 signatures verify):

```bash
# One-off: the backend uses path-style addressing, so the client must too.
aws configure set default.s3.addressing_style path

AWS_ACCESS_KEY_ID=rustfsadmin AWS_SECRET_ACCESS_KEY=rustfsadmin \
AWS_DEFAULT_REGION=us-east-1 \
  aws --endpoint-url http://localhost:9000 \
  s3 ls s3://nebula-terraform-state/ --recursive
```

**Reset local state.** `docker compose down -v` removes the `object_storage_data` volume and with it all state *and* all artifacts. That is usually what you want on a workstation and never what you want elsewhere.

**In production**, on the state bucket: versioning and soft delete on; encryption at rest with your own key if policy requires it; access restricted to the core and the IaC sidecar identities; excluded from any lifecycle expiry you apply to the artifacts bucket; and included in your backup and restore drills — this bucket is the record of what Nebula has built.


## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Every session plans against empty state, and nothing is ever recorded | Model 1 (the shipped default) with a repository that declares no backend: `init` succeeds against the *local* backend, and the state file dies with the throwaway clone. | Add a `terraform { backend ... }` block to the repository, or turn on model 2 by setting `storage.terraform_state_bucket`. |
| Core fails at boot: `Failed to initialize object storage` | Only with model 2 on: the state bucket cannot be created or reached — wrong credentials, missing `CreateBucket` permission, or an unreachable endpoint. | Pre-create the bucket, or grant creation rights. The artifact bucket and the state bucket are checked in the same step, so verify both. |
| `init` fails with `InvalidAccessKeyId` after switching to `provider: S3` | `RUSTFS_ACCESS_KEY` / `RUSTFS_SECRET_KEY` are still set to `rustfsadmin` in `core/.env` and got embedded into the backend block. | Blank both variables, rebuild the core image, and let the AWS default chain resolve credentials — on the **IaC sidecar**. |
| `init` fails with a credentials or `AccessDenied` error, and the override contains no `access_key` | The **IaC sidecar** container has no ambient cloud credentials, or they lack access to the state bucket. | Give the sidecar the role/keys, not just the core. See [Credentials required](#credentials-required). |
| `init` fails to dial the endpoint (`connection refused`, DNS failure) | The sidecar cannot reach `storage.endpoint_url`. | Put the sidecar on the same network as the store, or allow that egress. In Compose both must be on `bridge-network`. |
| Every plan proposes creating resources that already exist | The project's state key changed, or state was never migrated after a backend change. | Check the logged `key=` against what is in the bucket; migrate the old state. See [Changing backend configuration](#changing-backend-configuration). |
| `Error acquiring the state lock` | Another run holds the lock, or a crashed run left it stale. | Wait; if stale, `force-unlock` or remove the `.tflock` object / break the blob lease. |
| Two repositories collide on one state file | Only under model 3, where a shared `-backend-config` file supplies one `key`. | Declare distinct keys per repository, or use model 2. |
| Sidecar will not start: `IAC_BACKEND_CONFIG points at ... not a readable file` | The path is wrong, the file is not mounted, or it is not readable by uid `10001`. | Fix the mount and ownership, or unset the variable. |
| A `backend_override.tf` shows up in a pull request | The repository's own `.gitignore` predates Nebula and the merge did not take effect. | Nebula appends its template to an existing `.gitignore`; confirm `*_override.tf` is present in the branch. |
| Session fails with a Terraform backend error before `init` runs | The core could not write `backend_override.tf` into the workspace. | Check ownership of the `workspaces` volume: it must be writable by uid/gid `10001`. A volume from a stack that ran as root needs `chown -R 10001:10001`. |

## Reference

### `config.yaml`

| Key | Default | Meaning |
|---|---|---|
| `storage.provider` | `RUSTFS` | Selects the backend type for state as well as artifacts: `RUSTFS`/`S3` → `s3`, `STORAGE_ACCOUNT` → `azurerm`. |
| `storage.terraform_state_bucket` | blank *(shipped)* — field default `nebula-terraform-state` | Blank is the shipped value and leaves state to the repository: no value (the shipped spelling), `""`, and whitespace-only all count. Set a bucket name (blob container on `STORAGE_ACCOUNT`) to turn Nebula-managed state on; it is created at boot if missing. **Deleting the key falls back to the field default and turns managed state on.** |
| `storage.endpoint_url` | `http://object-storage:9000` | Rendered into the `endpoints.s3` block for `RUSTFS`; supplies the account name for `STORAGE_ACCOUNT`; ignored for `S3`. Must be reachable **from the IaC sidecar**. |
| `storage.region` | `us-east-1` | Rendered as the backend `region` for `RUSTFS` and `S3`. Ignored for `STORAGE_ACCOUNT`. |
| `storage.access_key_env` / `storage.secret_key_env` | `RUSTFS_ACCESS_KEY` / `RUSTFS_SECRET_KEY` | When **both** resolve non-empty, the keys are embedded in the backend block; otherwise the credential lines are omitted. |
| `storage.account_key_env` | `STORAGE_ACCOUNT_KEY` | Azure shared key, embedded as the backend `access_key`. Mandatory for `STORAGE_ACCOUNT`. |

`storage.bucket`, `storage.public_endpoint_url`, and `storage.presign_expiry_seconds` affect artifacts only and play no part in the state backend. Changing any of these requires rebuilding the core image, because `config.yaml` is baked in.

### `services/iac/.env`

| Variable | Default | Meaning |
|---|---|---|
| `IAC_BACKEND_CONFIG` | unset | Path **inside the sidecar container** to a `.hcl`/`.tfbackend` backend configuration file passed to `init` as `-backend-config`. Validated readable at startup. Ineffective while Nebula-managed state is on (model 2). |
| `IAC_BINARY` | `tofu` | The engine that executes the backend. OpenTofu 1.12.6 or the bundled Terraform 1.16.0; both support `use_lockfile`. |

### Related documentation

- [Configuration reference — `storage`](configuration.md#storage) — every field, default, and validation rule.
- [Environment variables and secrets](environment-variables.md) — `core/.env` and the sidecar `.env` files.
- [IaC sidecar README — State backend](../services/iac/README.md#state-backend) — the contract-level view.
- [`services/iac/PROVIDERS.md`](../services/iac/PROVIDERS.md) — per-cloud backend credential minimums.
- [Architecture — Data, Storage, and State](architecture.md#data-storage-and-state) — where state sits among Nebula's stores.
- [Getting started: production](getting-started-production.md#12-data-services-and-persistence) — persistence expectations.

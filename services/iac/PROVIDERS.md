<!--
SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)

SPDX-License-Identifier: Apache-2.0
-->
# Provider and backend minimums

The **minimum variable set** per cloud and per authentication method: the
shortest list of environment variables that makes the Terraform/OpenTofu
provider authenticate, plus the same for each state backend. Use it to
decide what to put in `services/iac/.env`. It is a cheat sheet, not an
exhaustive list — for every variable a provider or backend *reads*, see
[`FULL_PROVIDERS.md`](FULL_PROVIDERS.md). How the sidecar treats that
environment (it is inherited wholesale by the engine, and the per-request
scope overwrites two of these variables) is in
[`README.md` — Security notes](README.md#security-notes).

Variable names are taken from the providers' own documentation and are
the provider's contract, not Nebula's; confirm them against the registry
docs for your pinned provider version.

> **CI-only rows.** Rows marked *CI-only* below, and the whole
> "Copy-paste: typical CI setups" section, describe variables that a CI
> runner injects into a short-lived job. They are **not applicable to
> this long-running sidecar**, which has no CI identity: prefer workload
> identity (AKS/GKE/EKS), an instance profile or managed identity, or
> credential files mounted into the container.

## Azure — provider minimum

| Scenario | Required |
|---|---|
| SPN + secret | `ARM_SUBSCRIPTION_ID`, `ARM_TENANT_ID`, `ARM_CLIENT_ID`, `ARM_CLIENT_SECRET` |
| SPN + certificate | `ARM_SUBSCRIPTION_ID`, `ARM_TENANT_ID`, `ARM_CLIENT_ID`, `ARM_CLIENT_CERTIFICATE_PATH`, `ARM_CLIENT_CERTIFICATE_PASSWORD` |
| OIDC (GitHub Actions) — *CI-only* | `ARM_USE_OIDC=true`, `ARM_SUBSCRIPTION_ID`, `ARM_TENANT_ID`, `ARM_CLIENT_ID` |
| OIDC (Azure DevOps) — *CI-only* | above + `ARM_ADO_PIPELINE_SERVICE_CONNECTION_ID` |
| Managed identity (system-assigned) | `ARM_USE_MSI=true`, `ARM_SUBSCRIPTION_ID` |
| Managed identity (user-assigned) | `ARM_USE_MSI=true`, `ARM_SUBSCRIPTION_ID`, `ARM_CLIENT_ID` |
| AKS workload identity | `ARM_USE_AKS_WORKLOAD_IDENTITY=true`, `ARM_SUBSCRIPTION_ID`, `ARM_CLIENT_ID`, `ARM_TENANT_ID` |
| Local dev (`az login`) | `ARM_SUBSCRIPTION_ID` only |

`ARM_SUBSCRIPTION_ID` is in every row — mandatory in azurerm v4+. The OIDC rows omit `ARM_OIDC_REQUEST_URL`/`_TOKEN` because the CI runner injects them; that is also why those rows do not transfer to the sidecar. For a container, AKS workload identity or a user-assigned managed identity is the equivalent. Note that `ARM_SUBSCRIPTION_ID` set in `services/iac/.env` is overwritten per request with the session's `scope_id` (see [`README.md` — Security notes](README.md#security-notes)).

## AWS — provider minimum

| Scenario | Required |
|---|---|
| Static keys | `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION` |
| Temporary / STS creds | above + `AWS_SESSION_TOKEN` |
| Named profile | `AWS_PROFILE`, `AWS_REGION` |
| OIDC (GitHub Actions) — *CI-only* | `AWS_REGION` only — the action writes the rest |
| OIDC (manual) | `AWS_ROLE_ARN`, `AWS_WEB_IDENTITY_TOKEN_FILE`, `AWS_REGION` |
| EKS IRSA | `AWS_REGION` only — injected by the webhook |
| EC2 instance role | `AWS_REGION` only |
| ECS task role | `AWS_REGION` only |
| LocalStack | `AWS_ACCESS_KEY_ID=test`, `AWS_SECRET_ACCESS_KEY=test`, `AWS_REGION`, `AWS_ENDPOINT_URL` |

`AWS_REGION` is the only universal requirement. Never an account ID. For the sidecar, the rows that work unchanged are static keys, a named profile with a mounted credentials file, EKS IRSA, and an EC2 or ECS role.

## GCP — provider minimum

| Scenario | Required |
|---|---|
| Service account key | `GOOGLE_CREDENTIALS` (or `GOOGLE_APPLICATION_CREDENTIALS`), `GOOGLE_PROJECT` |
| Workload Identity Federation | `GOOGLE_APPLICATION_CREDENTIALS` (WIF config path), `GOOGLE_PROJECT` |
| WIF + impersonation | above + `GOOGLE_IMPERSONATE_SERVICE_ACCOUNT` |
| GCE / GKE / Cloud Run attached SA | `GOOGLE_PROJECT` only |
| Local dev (`gcloud auth application-default login`) | `GOOGLE_PROJECT` only |
| Short-lived token | `GOOGLE_OAUTH_ACCESS_TOKEN`, `GOOGLE_PROJECT` |

`GOOGLE_PROJECT` in every row — and, like `ARM_SUBSCRIPTION_ID`, it is overwritten per request with the session's `scope_id` on the sidecar (see [`README.md` — Security notes](README.md#security-notes)). `GOOGLE_REGION`/`GOOGLE_ZONE` are optional but omitting them forces explicit `region`/`zone` on many resources.

## OCI — provider minimum

| Scenario | Required |
|---|---|
| API key | `TF_VAR_tenancy_ocid`, `TF_VAR_user_ocid`, `TF_VAR_fingerprint`, `TF_VAR_private_key_path`, `TF_VAR_region` |
| Config file profile | `TF_VAR_auth=ApiKey` (default), `TF_VAR_config_file_profile` |
| Instance principal | `TF_VAR_auth=InstancePrincipal`, `TF_VAR_region` |
| Resource principal (Functions) | `TF_VAR_auth=ResourcePrincipal` — `OCI_RESOURCE_PRINCIPAL_*` injected by runtime |
| OKE workload identity | `TF_VAR_auth=OkeWorkloadIdentity`, `TF_VAR_region` |

Add `TF_VAR_compartment_ocid` in practice — not a provider setting, but nearly every resource needs it.

## Kubernetes — provider minimum

Variable names as documented by the Terraform `kubernetes` provider (the `helm` provider accepts the same ones under its `kubernetes` block).

| Scenario | Required |
|---|---|
| Single kubeconfig | `KUBE_CONFIG_PATH` — path to a kubeconfig readable inside the container |
| Several kubeconfigs merged | `KUBE_CONFIG_PATHS` — `:`-separated list of paths |
| Explicit API server + token | `KUBE_HOST`, `KUBE_TOKEN` (plus `KUBE_CLUSTER_CA_CERT_DATA`, or `KUBE_INSECURE=true` for an untrusted certificate) |
| In-cluster service account | none — the provider reads the pod's mounted service-account token |

`KUBE_CONFIG_PATH` is the `kubernetes` provider's own environment variable, not a `kubectl` one. There is **no scope variable for Kubernetes**: a namespace is a resource argument, so the sidecar injects nothing and the command runs against whatever context the kubeconfig or service account selects — make that agree with the session's scope yourself. Mounted kubeconfigs must be readable by uid `10001` (`nebula`).

## Backend minimums

### azurerm

| Scenario | Required env |
|---|---|
| Storage account key | `ARM_ACCESS_KEY` |
| SAS token | `ARM_SAS_TOKEN` |
| SPN + Entra ID (RBAC) | `ARM_USE_AZUREAD=true`, `ARM_TENANT_ID`, `ARM_CLIENT_ID`, `ARM_CLIENT_SECRET`, `ARM_SUBSCRIPTION_ID` |
| OIDC + Entra ID | `ARM_USE_OIDC=true`, `ARM_USE_AZUREAD=true`, `ARM_TENANT_ID`, `ARM_CLIENT_ID`, `ARM_SUBSCRIPTION_ID` |
| Managed identity | `ARM_USE_MSI=true`, `ARM_USE_AZUREAD=true`, `ARM_SUBSCRIPTION_ID` |
| Local dev (`az login`) | none — plus `ARM_USE_AZUREAD=true` for RBAC-only accounts |

Non-env HCL always needed: `storage_account_name`, `container_name`, `key`. `resource_group_name` is needed only when the backend has to look the storage account up through the Azure management plane; it is not required for direct data-plane access with a storage account key, a SAS token, or Entra ID. Nebula's rendered `backend_override.tf` omits it (`core/src/infrastructure/terraform/backend.py`, `__azurerm_override`).

### s3

| Scenario | Required env |
|---|---|
| Static keys | `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` |
| Named profile | `AWS_PROFILE` |
| OIDC / IRSA / instance role | none |
| Separate state account | `AWS_PROFILE` pointing at that account, or `AWS_ROLE_ARN` + token file |

Region comes from the backend block's `region`, not `AWS_REGION` — so a minimal CI setup can need zero backend env vars. Non-env HCL: `bucket`, `key`, `region`, and `use_lockfile = true` (TF 1.10+) or `dynamodb_table`.

### gcs

| Scenario | Required env |
|---|---|
| Service account key | `GOOGLE_BACKEND_CREDENTIALS` or `GOOGLE_CREDENTIALS` |
| WIF | `GOOGLE_APPLICATION_CREDENTIALS` |
| Attached SA / `gcloud` ADC | none |
| Separate state project | `GOOGLE_BACKEND_CREDENTIALS` or `GOOGLE_IMPERSONATE_SERVICE_ACCOUNT` |

No project or region needed — bucket names are globally unique. Non-env HCL: `bucket`, `prefix`.

## Copy-paste: typical CI setups (not applicable to the sidecar)

These three snippets assume a CI runner that injects the remaining
credentials into a short-lived job — `ARM_OIDC_REQUEST_URL`/`_TOKEN` from
GitHub Actions or Azure DevOps, the AWS web-identity token from
`aws-actions/configure-aws-credentials`, the WIF config file from
`google-github-actions/auth`. **Do not copy them into
`services/iac/.env`**: the sidecar is a long-running container with no CI
identity, so the missing half never arrives. Use workload identity, an
instance profile or managed identity, or mounted credential files
instead. They are kept here because Nebula's generated code is often run
from CI as well.

Azure, GitHub Actions OIDC, RBAC state access:

```bash
export ARM_USE_OIDC=true
export ARM_USE_AZUREAD=true
export ARM_TENANT_ID=...
export ARM_CLIENT_ID=...
export ARM_SUBSCRIPTION_ID=...
```

AWS, GitHub Actions OIDC:

```bash
export AWS_REGION=eu-west-1
# aws-actions/configure-aws-credentials supplies the rest
```

GCP, GitHub Actions WIF:

```bash
export GOOGLE_PROJECT=my-app-prod
export GOOGLE_REGION=europe-west1
# google-github-actions/auth sets GOOGLE_APPLICATION_CREDENTIALS
```

## Two things that trip people up

**Azure needs the most variables by a wide margin.** AWS and GCP collapse to one or two in keyless CI because their SDKs auto-discover identity and the account/project is either implicit or a single value. Azure always needs tenant + client + subscription explicitly.

**Backend env vars are usually a subset of provider ones** — with `ARM_ACCESS_KEY` and `GOOGLE_BACKEND_CREDENTIALS` being the deliberate exceptions for splitting identities. If you set the full provider set, `init` almost always works too; the reverse is not true.

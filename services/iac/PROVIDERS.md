<!--
SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)

SPDX-License-Identifier: Apache-2.0
-->
## Azure — provider minimum

| Scenario | Required |
|---|---|
| SPN + secret | `ARM_SUBSCRIPTION_ID`, `ARM_TENANT_ID`, `ARM_CLIENT_ID`, `ARM_CLIENT_SECRET` |
| SPN + certificate | `ARM_SUBSCRIPTION_ID`, `ARM_TENANT_ID`, `ARM_CLIENT_ID`, `ARM_CLIENT_CERTIFICATE_PATH`, `ARM_CLIENT_CERTIFICATE_PASSWORD` |
| OIDC (GitHub Actions) | `ARM_USE_OIDC=true`, `ARM_SUBSCRIPTION_ID`, `ARM_TENANT_ID`, `ARM_CLIENT_ID` |
| OIDC (Azure DevOps) | above + `ARM_ADO_PIPELINE_SERVICE_CONNECTION_ID` |
| Managed identity (system-assigned) | `ARM_USE_MSI=true`, `ARM_SUBSCRIPTION_ID` |
| Managed identity (user-assigned) | `ARM_USE_MSI=true`, `ARM_SUBSCRIPTION_ID`, `ARM_CLIENT_ID` |
| AKS workload identity | `ARM_USE_AKS_WORKLOAD_IDENTITY=true`, `ARM_SUBSCRIPTION_ID`, `ARM_CLIENT_ID`, `ARM_TENANT_ID` |
| Local dev (`az login`) | `ARM_SUBSCRIPTION_ID` only |

`ARM_SUBSCRIPTION_ID` is in every row — mandatory in azurerm v4+. OIDC rows omit `ARM_OIDC_REQUEST_URL`/`_TOKEN` because the CI runner injects them.

## AWS — provider minimum

| Scenario | Required |
|---|---|
| Static keys | `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION` |
| Temporary / STS creds | above + `AWS_SESSION_TOKEN` |
| Named profile | `AWS_PROFILE`, `AWS_REGION` |
| OIDC (GitHub Actions) | `AWS_REGION` only — the action writes the rest |
| OIDC (manual) | `AWS_ROLE_ARN`, `AWS_WEB_IDENTITY_TOKEN_FILE`, `AWS_REGION` |
| EKS IRSA | `AWS_REGION` only — injected by the webhook |
| EC2 instance role | `AWS_REGION` only |
| ECS task role | `AWS_REGION` only |
| LocalStack | `AWS_ACCESS_KEY_ID=test`, `AWS_SECRET_ACCESS_KEY=test`, `AWS_REGION`, `AWS_ENDPOINT_URL` |

`AWS_REGION` is the only universal requirement. Never an account ID.

## GCP — provider minimum

| Scenario | Required |
|---|---|
| Service account key | `GOOGLE_CREDENTIALS` (or `GOOGLE_APPLICATION_CREDENTIALS`), `GOOGLE_PROJECT` |
| Workload Identity Federation | `GOOGLE_APPLICATION_CREDENTIALS` (WIF config path), `GOOGLE_PROJECT` |
| WIF + impersonation | above + `GOOGLE_IMPERSONATE_SERVICE_ACCOUNT` |
| GCE / GKE / Cloud Run attached SA | `GOOGLE_PROJECT` only |
| Local dev (`gcloud auth application-default login`) | `GOOGLE_PROJECT` only |
| Short-lived token | `GOOGLE_OAUTH_ACCESS_TOKEN`, `GOOGLE_PROJECT` |

`GOOGLE_PROJECT` in every row. `GOOGLE_REGION`/`GOOGLE_ZONE` are optional but omitting them forces explicit `region`/`zone` on many resources.

## OCI — provider minimum

| Scenario | Required |
|---|---|
| API key | `TF_VAR_tenancy_ocid`, `TF_VAR_user_ocid`, `TF_VAR_fingerprint`, `TF_VAR_private_key_path`, `TF_VAR_region` |
| Config file profile | `TF_VAR_auth=ApiKey` (default), `TF_VAR_config_file_profile` |
| Instance principal | `TF_VAR_auth=InstancePrincipal`, `TF_VAR_region` |
| Resource principal (Functions) | `TF_VAR_auth=ResourcePrincipal` — `OCI_RESOURCE_PRINCIPAL_*` injected by runtime |
| OKE workload identity | `TF_VAR_auth=OkeWorkloadIdentity`, `TF_VAR_region` |

Add `TF_VAR_compartment_ocid` in practice — not a provider setting, but nearly every resource needs it.

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

Non-env HCL always needed: `resource_group_name`, `storage_account_name`, `container_name`, `key`.

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

## Copy-paste: typical CI setups

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

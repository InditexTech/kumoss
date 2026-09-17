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

**Do not set `ARM_SUBSCRIPTION_ID` yourself.** The rows list it because the provider requires it, but this service supplies it: `init`, `plan`, `apply` and `import` carry a `scope_id`, and the service injects it as `ARM_SUBSCRIPTION_ID` into the engine subprocess for that one command, overriding whatever the container has. Set the credential variables in each row and leave the subscription to the request. See "Scope injection" in `README.md`.

Import discovery (`/v1/import/scope-resource-ids`) reads the *credential* variables through `azure-identity` — the subscription it lists comes from the request's `scope_id`, never from the environment. Two exceptions: the `az login` row has no equivalent (discovery needs an SPN, a managed identity or a workload identity), and the OIDC rows need the assertion itself in `ARM_OIDC_TOKEN` or `ARM_OIDC_TOKEN_FILE_PATH` — the `ARM_OIDC_REQUEST_URL` exchange the CI runner performs is not reimplemented here. `ARM_ADO_PIPELINE_SERVICE_CONNECTION_ID` is likewise provider-only.

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

`AWS_REGION` is the only universal requirement. Never an account ID — and unlike Azure and GCP, nothing here is injected from `scope_id`, because no environment variable redirects the provider to an account. Every command runs against whatever account the credentials above resolve to, so making them agree with the `scope_id` callers send is the deployment's job (`README.md`, "Scope injection").

Import discovery additionally requires AWS Resource Explorer to be enabled for the account, with an aggregator index and a default view. Every row above works for it, since boto3's default chain resolves the same credentials the provider does. Discovery does not select the account either: it calls STS and fails if the resolved account is not the requested `scope_id`. See "Import discovery" in `README.md`.

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

**Do not set `GOOGLE_PROJECT` yourself**, for the same reason as `ARM_SUBSCRIPTION_ID` above: the service injects the request's `scope_id` under that name for `init`, `plan`, `apply` and `import`. It sets `GOOGLE_PROJECT` specifically, which outranks the `GOOGLE_CLOUD_PROJECT`/`GCLOUD_PROJECT`/`CLOUDSDK_CORE_PROJECT` aliases (`FULL_PROVIDERS.md`), so an ambient alias cannot quietly win. Set the credential variables in each row and leave the project to the request.

Import discovery reads the *credential* variables through `google-auth`, including `GOOGLE_OAUTH_ACCESS_TOKEN` and `GOOGLE_IMPERSONATE_SERVICE_ACCOUNT`, and falls back to application-default credentials exactly as the provider does — so the `gcloud auth application-default login` row works for it too. The project it lists is the request's `scope_id`; the project that application-default credentials name is deliberately discarded. It needs `cloudasset.googleapis.com` and `cloudresourcemanager.googleapis.com` enabled on that project.

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

Add `subscription_id` too when the state storage account lives in a different subscription than the resources being managed. The backend resolves the account through `ARM_SUBSCRIPTION_ID`, and `init` runs with that variable overlaid from the request's `scope_id` — so a backend that does not name its subscription explicitly looks for the storage account in the *workload's* subscription and fails. Pin it in the backend block or in the file `IAC_BACKEND_CONFIG` points at. The `ARM_ACCESS_KEY` and `ARM_SAS_TOKEN` rows are unaffected: they address the account directly rather than resolving it through a subscription.

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

These are the provider-level sets, for running the engine yourself. Under this service, drop `ARM_SUBSCRIPTION_ID` and `GOOGLE_PROJECT` — the request's `scope_id` supplies them.

Azure, GitHub Actions OIDC, RBAC state access:

```bash
export ARM_USE_OIDC=true
export ARM_USE_AZUREAD=true
export ARM_TENANT_ID=...
export ARM_CLIENT_ID=...
export ARM_SUBSCRIPTION_ID=...   # omit under this service
```

AWS, GitHub Actions OIDC:

```bash
export AWS_REGION=eu-west-1
# aws-actions/configure-aws-credentials supplies the rest
```

GCP, GitHub Actions WIF:

```bash
export GOOGLE_PROJECT=my-app-prod   # omit under this service
export GOOGLE_REGION=europe-west1
# google-github-actions/auth sets GOOGLE_APPLICATION_CREDENTIALS
```

## Three things that trip people up

**Azure needs the most variables by a wide margin.** AWS and GCP collapse to one or two in keyless CI because their SDKs auto-discover identity and the account/project is either implicit or a single value. Azure always needs tenant + client + subscription explicitly — though under this service the subscription arrives with the request rather than from the environment.

**Backend env vars are usually a subset of provider ones** — with `ARM_ACCESS_KEY` and `GOOGLE_BACKEND_CREDENTIALS` being the deliberate exceptions for splitting identities. If you set the full provider set, `init` almost always works too; the reverse is not true.

**The scope this service injects reaches the azurerm backend as well**, because provider and backend read the same `ARM_SUBSCRIPTION_ID`. Split state — a state account outside the managed subscription — therefore needs `subscription_id` in the backend config, not just provider credentials. GCP has no equivalent problem: the `gcs` backend needs no project.

<!--
SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)

SPDX-License-Identifier: Apache-2.0
-->
# Full provider and backend variable reference

Every environment variable each Terraform/OpenTofu provider and each
state backend **reads**, grouped by authentication method — the complete
surface, not the shortest working set. Reach for it when you are
debugging an unexpected credential resolution, splitting provider from
backend identity, or auditing what the sidecar's environment exposes. For
the minimum list per cloud and auth method, use
[`PROVIDERS.md`](PROVIDERS.md); for how this environment reaches the
engine (inherited wholesale, with two variables overwritten per request),
see [`README.md` — Security notes](README.md#security-notes).

Variable names and semantics below are taken from the providers' and
backends' own documentation; they are the provider's contract, not
Nebula's. Confirm against the registry docs for your pinned version.

> **CI-injected variables.** Several rows (`ARM_OIDC_REQUEST_URL`,
> `ARM_OIDC_REQUEST_TOKEN`, `ARM_ADO_PIPELINE_SERVICE_CONNECTION_ID`,
> `AWS_WEB_IDENTITY_TOKEN_FILE` in its GitHub Actions form,
> `OCI_RESOURCE_PRINCIPAL_*`) exist because a CI runner or a serverless
> runtime writes them into a short-lived job. They are **not applicable
> to the long-running IaC sidecar**, which has no CI identity — use
> workload identity, an instance profile or managed identity, or mounted
> credential files there instead.

## 1. Provider environment variables

One table per cloud — a single combined table would be ~90% empty cells. Grouped by auth method, since within each cloud the methods are mutually exclusive.

### Azure (`azurerm`, `azuread`, `azapi` — all share the `ARM_` prefix)

| Variable | Group | Purpose |
|---|---|---|
| `ARM_SUBSCRIPTION_ID` | Core | Target subscription. **Mandatory** in provider v4+ |
| `ARM_TENANT_ID` | Core | Entra ID tenant |
| `ARM_CLIENT_ID` | Core | App/SPN or managed identity client ID |
| `ARM_CLIENT_ID_FILE_PATH` | Core | Read client ID from a file |
| `ARM_ENVIRONMENT` | Core | `public`, `usgovernment`, `china` |
| `ARM_METADATA_HOST` | Core | Custom metadata endpoint (Azure Stack) |
| `ARM_AUXILIARY_TENANT_IDS` | Core | Comma-separated, for cross-tenant |
| `ARM_CLIENT_SECRET` | SPN + secret | Client secret |
| `ARM_CLIENT_SECRET_FILE_PATH` | SPN + secret | Read secret from file |
| `ARM_CLIENT_CERTIFICATE` | SPN + cert | Base64 PKCS#12 bundle |
| `ARM_CLIENT_CERTIFICATE_PATH` | SPN + cert | Path to `.pfx` |
| `ARM_CLIENT_CERTIFICATE_PASSWORD` | SPN + cert | Cert password |
| `ARM_USE_OIDC` | OIDC | Enable OIDC/workload identity federation |
| `ARM_OIDC_TOKEN` | OIDC | ID token value |
| `ARM_OIDC_TOKEN_FILE_PATH` | OIDC | Path to ID token |
| `ARM_OIDC_REQUEST_URL` | OIDC | Token request URL (GitHub/ADO) |
| `ARM_OIDC_REQUEST_TOKEN` | OIDC | Bearer token for the above |
| `ARM_ADO_PIPELINE_SERVICE_CONNECTION_ID` | OIDC | Azure DevOps service connection |
| `ARM_USE_MSI` | Managed identity | Enable IMDS auth |
| `ARM_MSI_ENDPOINT` | Managed identity | Override IMDS endpoint |
| `ARM_USE_AKS_WORKLOAD_IDENTITY` | AKS | Workload identity in AKS pods |
| `ARM_USE_CLI` | Local dev | Use `az login` session (default `true`) |
| `ARM_RESOURCE_PROVIDER_REGISTRATIONS` | Behaviour | `core`, `extended`, `all`, `none` (v4+) |
| `ARM_SKIP_PROVIDER_REGISTRATION` | Behaviour | Deprecated predecessor of the above |
| `ARM_STORAGE_USE_AZUREAD` | Behaviour | Entra ID instead of shared keys for storage data plane |
| `ARM_PARTNER_ID` | Telemetry | Partner attribution GUID |
| `ARM_DISABLE_TERRAFORM_PARTNER_ID` | Telemetry | Opt out |
| `ARM_DISABLE_CORRELATION_REQUEST_ID` | Telemetry | Opt out |

### AWS (`aws`)

| Variable | Group | Purpose |
|---|---|---|
| `AWS_ACCESS_KEY_ID` | Static keys | Access key |
| `AWS_SECRET_ACCESS_KEY` | Static keys | Secret key |
| `AWS_SESSION_TOKEN` | Static keys | Required for temporary/STS creds |
| `AWS_REGION` | Core | Region — **mandatory** unless in provider block |
| `AWS_DEFAULT_REGION` | Core | Fallback |
| `AWS_PROFILE` | Profiles | Named profile |
| `AWS_SHARED_CREDENTIALS_FILE` | Profiles | Override `~/.aws/credentials` |
| `AWS_CONFIG_FILE` | Profiles | Override `~/.aws/config` |
| `AWS_SDK_LOAD_CONFIG` | Profiles | Legacy (provider v3 only) |
| `AWS_ROLE_ARN` | Assume role / OIDC | Role to assume |
| `AWS_ROLE_SESSION_NAME` | Assume role / OIDC | Session name |
| `AWS_WEB_IDENTITY_TOKEN_FILE` | OIDC | IRSA / GitHub Actions token path |
| `AWS_CONTAINER_CREDENTIALS_RELATIVE_URI` | ECS | Task role |
| `AWS_CONTAINER_CREDENTIALS_FULL_URI` | ECS / EKS Pod Identity | Credential endpoint |
| `AWS_CONTAINER_AUTHORIZATION_TOKEN` | ECS / EKS | Token for the above |
| `AWS_CONTAINER_AUTHORIZATION_TOKEN_FILE` | ECS / EKS | Token from file |
| `AWS_EC2_METADATA_DISABLED` | IMDS | `true` skips IMDS (faster failures) |
| `AWS_EC2_METADATA_SERVICE_ENDPOINT` | IMDS | Custom IMDS endpoint |
| `AWS_EC2_METADATA_SERVICE_ENDPOINT_MODE` | IMDS | `IPv4` / `IPv6` |
| `AWS_MAX_ATTEMPTS` | Behaviour | Retry count |
| `AWS_RETRY_MODE` | Behaviour | `legacy`, `standard`, `adaptive` |
| `AWS_CA_BUNDLE` | Behaviour | Custom CA for proxies |
| `AWS_ENDPOINT_URL` | Behaviour | Global endpoint override |
| `AWS_ENDPOINT_URL_<SERVICE>` | Behaviour | Per-service override (LocalStack) |
| `AWS_USE_FIPS_ENDPOINT` | Behaviour | FIPS endpoints |
| `AWS_USE_DUALSTACK_ENDPOINT` | Behaviour | IPv6 dual-stack |
| `AWS_STS_REGIONAL_ENDPOINTS` | Behaviour | `regional` / `legacy` |

No `AWS_ACCOUNT_ID` — the account is implicit in the credential.

### GCP (`google`, `google-beta`)

| Variable | Group | Purpose |
|---|---|---|
| `GOOGLE_CREDENTIALS` | Key-based | JSON key contents *or* path |
| `GOOGLE_CLOUD_KEYFILE_JSON` | Key-based | Alias |
| `GCLOUD_KEYFILE_JSON` | Key-based | Alias |
| `GOOGLE_APPLICATION_CREDENTIALS` | ADC / WIF | Key file or Workload Identity Federation config |
| `GOOGLE_OAUTH_ACCESS_TOKEN` | Token | Short-lived bearer token |
| `GOOGLE_IMPERSONATE_SERVICE_ACCOUNT` | Impersonation | Target SA to impersonate |
| `GOOGLE_PROJECT` | Targeting | Default project — **required** unless in provider block |
| `GOOGLE_CLOUD_PROJECT` | Targeting | Alias |
| `GCLOUD_PROJECT` | Targeting | Alias |
| `CLOUDSDK_CORE_PROJECT` | Targeting | Alias |
| `GOOGLE_REGION` / `GCLOUD_REGION` / `CLOUDSDK_COMPUTE_REGION` | Targeting | Default region |
| `GOOGLE_ZONE` / `GCLOUD_ZONE` / `CLOUDSDK_COMPUTE_ZONE` | Targeting | Default zone |
| `GOOGLE_BILLING_PROJECT` | Quota | Project billed for API calls |
| `USER_PROJECT_OVERRIDE` | Quota | Enables the above |
| `GOOGLE_REQUEST_REASON` | Behaviour | Audit log reason string |
| `GOOGLE_REQUEST_TIMEOUT` | Behaviour | Per-request timeout |
| `GOOGLE_UNIVERSE_DOMAIN` | Behaviour | Non-`googleapis.com` universes (sovereign) |

### OCI (`oracle/oci`)

Unusual quirk: this provider uses `TF_VAR_*` names as its own env-var defaults, which is why OCI examples look different from every other cloud.

| Variable | Group | Purpose |
|---|---|---|
| `TF_VAR_tenancy_ocid` | API key | Tenancy OCID |
| `TF_VAR_user_ocid` | API key | User OCID |
| `TF_VAR_fingerprint` | API key | Public key fingerprint |
| `TF_VAR_private_key_path` | API key | Path to PEM private key |
| `TF_VAR_private_key` | API key | PEM contents inline |
| `TF_VAR_private_key_password` | API key | Passphrase |
| `TF_VAR_region` | Core | e.g. `eu-frankfurt-1` |
| `TF_VAR_auth` | Core | `ApiKey`, `SecurityToken`, `InstancePrincipal`, `ResourcePrincipal`, `OkeWorkloadIdentity` |
| `TF_VAR_config_file_profile` | Config file | Profile in `~/.oci/config` |
| `OCI_CONFIG_FILE` / `OCI_CLI_CONFIG_FILE` | Config file | Override config path |
| `OCI_CLI_PROFILE` | Config file | Profile (SDK/CLI level) |
| `OCI_RESOURCE_PRINCIPAL_VERSION` | Resource principal | Set by OCI Functions runtime |
| `OCI_RESOURCE_PRINCIPAL_RPST` | Resource principal | Session token |
| `OCI_RESOURCE_PRINCIPAL_PRIVATE_PEM` | Resource principal | Private key |
| `OCI_RESOURCE_PRINCIPAL_REGION` | Resource principal | Region |

Compartment OCID is a *resource* argument, not an env var — commonly passed as `TF_VAR_compartment_ocid`, which is an ordinary Terraform variable rather than a provider setting.

### Kubernetes (`kubernetes`, `helm`)

Names as documented by the Terraform `kubernetes` provider; the `helm` provider reads the same set for its embedded `kubernetes` block.

| Variable | Group | Purpose |
|---|---|---|
| `KUBE_CONFIG_PATH` | Kubeconfig | Path to a single kubeconfig file |
| `KUBE_CONFIG_PATHS` | Kubeconfig | `:`-separated list of kubeconfigs to merge |
| `KUBE_CTX` | Kubeconfig | Context to select within the kubeconfig |
| `KUBE_CTX_CLUSTER` | Kubeconfig | Override the context's cluster |
| `KUBE_CTX_AUTH_INFO` | Kubeconfig | Override the context's user |
| `KUBE_HOST` | Direct | API server URL |
| `KUBE_TOKEN` | Direct | Bearer token (service account or otherwise) |
| `KUBE_USER` / `KUBE_PASSWORD` | Direct | HTTP basic auth, where the cluster still allows it |
| `KUBE_CLIENT_CERT_DATA` / `KUBE_CLIENT_KEY_DATA` | Direct | Client certificate auth (PEM contents) |
| `KUBE_CLUSTER_CA_CERT_DATA` | Direct | Cluster CA certificate (PEM contents) |
| `KUBE_INSECURE` | Direct | `true` skips TLS verification |
| `KUBE_TLS_SERVER_NAME` | Direct | Override the TLS server name |
| `KUBE_PROXY_URL` | Behaviour | Proxy to reach the API server through |
| *(none)* | In-cluster | With no variables set, the provider falls back to the pod's mounted service-account token and CA |

There is **no scope variable for Kubernetes** — a namespace is a resource argument, so the sidecar injects nothing (see [`README.md` — Scope injection](README.md#scope-injection)).

## 2. Backend storage environment variables

| Variable | Backend | Purpose |
|---|---|---|
| `ARM_SUBSCRIPTION_ID` | azurerm | Subscription of the state storage account |
| `ARM_TENANT_ID` | azurerm | Tenant |
| `ARM_CLIENT_ID` | azurerm | SPN / managed identity |
| `ARM_CLIENT_SECRET` | azurerm | SPN secret |
| `ARM_CLIENT_CERTIFICATE_PATH` | azurerm | SPN cert |
| `ARM_CLIENT_CERTIFICATE_PASSWORD` | azurerm | Cert password |
| `ARM_ACCESS_KEY` | azurerm | Storage account key (simplest CI option) |
| `ARM_SAS_TOKEN` | azurerm | SAS token alternative |
| `ARM_USE_AZUREAD` | azurerm | Entra ID auth to blob instead of keys |
| `ARM_USE_MSI` | azurerm | Managed identity |
| `ARM_MSI_ENDPOINT` | azurerm | Override IMDS |
| `ARM_USE_OIDC` | azurerm | OIDC / WIF |
| `ARM_OIDC_TOKEN` | azurerm | ID token |
| `ARM_OIDC_TOKEN_FILE_PATH` | azurerm | ID token path |
| `ARM_OIDC_REQUEST_URL` | azurerm | Token request URL |
| `ARM_OIDC_REQUEST_TOKEN` | azurerm | Bearer for the above |
| `ARM_USE_AKS_WORKLOAD_IDENTITY` | azurerm | AKS workload identity |
| `ARM_ENVIRONMENT` | azurerm | Cloud environment |
| `ARM_METADATA_HOST` | azurerm | Azure Stack metadata |
| `ARM_SNAPSHOT` | azurerm | Snapshot blob before write |
| `AWS_ACCESS_KEY_ID` | s3 | Access key |
| `AWS_SECRET_ACCESS_KEY` | s3 | Secret key |
| `AWS_SESSION_TOKEN` | s3 | Temporary creds |
| `AWS_REGION` / `AWS_DEFAULT_REGION` | s3 | Bucket region |
| `AWS_PROFILE` | s3 | Named profile (often a *different* one than the provider) |
| `AWS_SHARED_CREDENTIALS_FILE` | s3 | Credentials file path |
| `AWS_CONFIG_FILE` | s3 | Config file path |
| `AWS_ROLE_ARN` | s3 | Role to assume for state access |
| `AWS_WEB_IDENTITY_TOKEN_FILE` | s3 | OIDC token |
| `AWS_CA_BUNDLE` | s3 | Custom CA |
| `AWS_ENDPOINT_URL_S3` | s3 | Custom S3 endpoint (MinIO, OCI Object Storage) |
| `AWS_ENDPOINT_URL_DYNAMODB` | s3 | Custom DynamoDB endpoint (legacy locking) |
| `AWS_ENDPOINT_URL_STS` | s3 | Custom STS endpoint |
| `AWS_S3_ENDPOINT` | s3 | Legacy alias |
| `AWS_DYNAMODB_ENDPOINT` | s3 | Legacy alias |
| `AWS_METADATA_URL` | s3 | Legacy IMDS override |
| `GOOGLE_BACKEND_CREDENTIALS` | gcs | Backend-only credentials (key JSON or path) |
| `GOOGLE_CREDENTIALS` | gcs | Falls back to provider var |
| `GOOGLE_APPLICATION_CREDENTIALS` | gcs | ADC / WIF config |
| `GOOGLE_CLOUD_KEYFILE_JSON` | gcs | Alias |
| `GCLOUD_KEYFILE_JSON` | gcs | Alias |
| `GOOGLE_OAUTH_ACCESS_TOKEN` | gcs | Bearer token |
| `GOOGLE_IMPERSONATE_SERVICE_ACCOUNT` | gcs | Impersonation |
| `GOOGLE_ENCRYPTION_KEY` | gcs | Customer-supplied AES-256 key for state |
| `GOOGLE_KMS_ENCRYPTION_KEY` | gcs | Cloud KMS key for state |

## Caveats worth internalising

**Backend *location* is never settable via env vars.** Only credentials are. `bucket`/`key`, `storage_account_name`/`container_name`, `bucket`/`prefix` must be literal HCL, `-backend-config=...`, or a `.tfbackend` file. `TF_VAR_*` does not work for backends because backend blocks are evaluated before variables exist.

```bash
terraform init -backend-config=env/prod.s3.tfbackend
```

**`gcs` needs no project** — global bucket namespace. `azurerm` and `s3` both need region/subscription context.

**Backend and provider credentials can and often should differ.** `GOOGLE_BACKEND_CREDENTIALS` and `AWS_PROFILE` switching exist precisely for this. Azure has no `ARM_BACKEND_*` equivalent, so separation there means either `ARM_ACCESS_KEY` for the backend (leaving the SPN vars for the provider) or wrapper scripts that swap env between `init` and `plan`.

**Version drift is real.** `ARM_SUBSCRIPTION_ID` became mandatory in azurerm v4; `ARM_SKIP_PROVIDER_REGISTRATION` was superseded; `dynamodb_table` gave way to `use_lockfile`. Treat this as a working reference and confirm against the registry docs for your pinned provider version.

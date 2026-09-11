<!--
SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)

SPDX-License-Identifier: Apache-2.0
-->

<!-- Add relevant badges here -->
![GitHub License](https://img.shields.io/github/license/InditexTech/base-archetype)

# base-archetype

Short description of what this project does and why it exists.

> One or two sentences that explain its purpose in a clear, accessible way.

<!-- Add video/image/demo here -->


## LiteLLM Models and Params Reference


To configure the LLMs, set `llm.model` and `llm.small_model` in `config.yaml`
to `provider/model-id` strings (the **Model String Format** column below) and
export that provider's **Default LiteLLM Env Vars** (middle column) in
`core/.env`. The core fails boot when litellm reports required env vars
missing; note that some providers (e.g. `azure_ai`) have no litellm

validation mapping, so missing credentials surface on the first LLM call
instead. For advanced routing — fallbacks, load balancing, or custom
credential env var names — use the optional `llm.model_list` key (see
[Advanced: `llm.model_list`](#advanced-llmmodel_list) below); the
**Standard `litellm_params` Keys** column applies only there.

### 1. Major Cloud Platforms (Hyperscalers)


| Provider | Model String Format (`model:`) | Default LiteLLM Env Vars | Standard `litellm_params` Keys | Base URL / Notes |
| :--- | :--- | :--- | :--- | :--- |
| **Azure AI Foundry** (Claude, Llama, etc.) | `azure_ai/<model-name>` | `AZURE_AI_API_KEY`<br>`AZURE_AI_API_BASE` | `api_key`<br>`api_base` | `https://<resource>.services.ai.azure.com/anthropic` (or `/models`) |
| **Azure OpenAI** | `azure/<deployment-name>` | `AZURE_API_KEY`<br>`AZURE_API_BASE`<br>`AZURE_API_VERSION` | `api_key`<br>`api_base`<br>`api_version` | `https://<resource>.openai.azure.com` |
| **Google Vertex AI** | `vertex_ai/<model-name>` | `VERTEXAI_PROJECT`<br>`VERTEXAI_LOCATION`<br>`VERTEXAI_CREDENTIALS` | `vertex_project`<br>`vertex_location`<br>`vertex_credentials` | `VERTEXAI_CREDENTIALS` holds the service-account JSON — a file path or the raw JSON content. Alternatively omit it and use ADC (`GOOGLE_APPLICATION_CREDENTIALS` file path, workload identity, …). |
| **Google AI Studio (Gemini API)** | `gemini/<model-name>` | `GEMINI_API_KEY` | `api_key` | Direct Google AI Studio API key. |
| **AWS Bedrock** | `bedrock/<model-id>` | `AWS_ACCESS_KEY_ID`<br>`AWS_SECRET_ACCESS_KEY`<br>`AWS_REGION_NAME` | `aws_access_key_id`<br>`aws_secret_access_key`<br>`aws_region_name` | Model IDs like `anthropic.claude-3-5-sonnet-20241022-v2:0`. |
| **AWS SageMaker** | `sagemaker/<endpoint-name>` | `AWS_ACCESS_KEY_ID`<br>`AWS_SECRET_ACCESS_KEY`<br>`AWS_REGION_NAME` | `aws_access_key_id`<br>`aws_secret_access_key`<br>`aws_region_name` | Targeted SageMaker deployed endpoint. |
| **Cloudflare Workers AI** | `cloudflare/<model-name>` | `CLOUDFLARE_API_KEY`<br>`CLOUDFLARE_ACCOUNT_ID` | `api_key`<br>`api_base` | Direct access to serverless models on Cloudflare. |

---

### 2. Frontier Model Labs (Direct API)

| Provider | Model String Format (`model:`) | Default LiteLLM Env Vars | Standard `litellm_params` Keys | Base URL / Notes |
| :--- | :--- | :--- | :--- | :--- |
| **Anthropic** | `anthropic/<model-name>` | `ANTHROPIC_API_KEY` | `api_key` | e.g., `anthropic/claude-3-5-sonnet-20241022` |
| **OpenAI** | `openai/<model-name>` | `OPENAI_API_KEY`<br>`OPENAI_API_BASE` | `api_key`<br>`api_base` | `api_base` defaults to `https://api.openai.com/v1`. |
| **xAI (Grok)** | `xai/<model-name>` | `XAI_API_KEY` | `api_key` | e.g., `xai/grok-beta` |
| **Mistral AI** | `mistral/<model-name>` | `MISTRAL_API_KEY` | `api_key` | e.g., `mistral/mistral-large-latest` |
| **Cohere** | `cohere/<model-name>` or `cohere_chat/<model-name>` | `COHERE_API_KEY` | `api_key` | e.g., `cohere/command-r-plus` |

---

### 3. Hosted Inference & Fast Token Providers

| Provider | Model String Format (`model:`) | Default LiteLLM Env Vars | Standard `litellm_params` Keys | Notes |
| :--- | :--- | :--- | :--- | :--- |
| **Groq** | `groq/<model-name>` | `GROQ_API_KEY` | `api_key` | e.g., `groq/llama-3.3-70b-versatile` |
| **DeepSeek** | `deepseek/<model-name>` | `DEEPSEEK_API_KEY` | `api_key` | e.g., `deepseek/deepseek-chat`, `deepseek/deepseek-reasoner` |
| **Together AI** | `together_ai/<model-name>` | `TOGETHERAI_API_KEY` | `api_key` | e.g., `together_ai/meta-llama/Llama-3.3-70B-Instruct-Turbo` |
| **Fireworks AI** | `fireworks_ai/<model-name>` | `FIREWORKS_AI_API_KEY` | `api_key` | e.g., `fireworks_ai/accounts/fireworks/models/llama-v3p3-70b-instruct` |
| **OpenRouter** | `openrouter/<model-name>` | `OPENROUTER_API_KEY` | `api_key` | e.g., `openrouter/anthropic/claude-3.5-sonnet` |
| **Perplexity AI** | `perplexity/<model-name>` | `PERPLEXITYAI_API_KEY` | `api_key` | e.g., `perplexity/sonar-pro` |
| **Cerebras** | `cerebras/<model-name>` | `CEREBRAS_API_KEY` | `api_key` | e.g., `cerebras/llama3.3-70b` |
| **SambaNova** | `sambanova/<model-name>` | `SAMBANOVA_API_KEY` | `api_key` | e.g., `sambanova/Meta-Llama-3.3-70B-Instruct` |
| **DeepInfra** | `deepinfra/<model-name>` | `DEEPINFRA_API_KEY` | `api_key` | e.g., `deepinfra/meta-llama/Meta-Llama-3.1-70B-Instruct` |
| **Anyscale** | `anyscale/<model-name>` | `ANYSCALE_API_KEY` | `api_key` | e.g., `anyscale/meta-llama/Llama-3-70b-chat-hf` |
| **Replicate** | `replicate/<model-name>` | `REPLICATE_API_KEY` (or `REPLICATE_API_TOKEN`) | `api_key` | e.g., `replicate/meta/meta-llama-3-70b-instruct` |
| **Voyage AI** (Embeddings) | `voyage/<model-name>` | `VOYAGE_API_KEY` | `api_key` | e.g., `voyage/voyage-3` |
| **AI21** | `ai21/<model-name>` | `AI21_API_KEY` | `api_key` | e.g., `ai21/jamba-1.5-large` |


---

### 4. Enterprise Data Platforms


| Provider | Model String Format (`model:`) | Default LiteLLM Env Vars | Standard `litellm_params` Keys | Notes |
| :--- | :--- | :--- | :--- | :--- |
| **Databricks** | `databricks/<endpoint-name>` | `DATABRICKS_API_KEY`<br>`DATABRICKS_API_BASE` | `api_key`<br>`api_base` | `api_base` format: `https://<workspace>.cloud.databricks.com/serving-endpoints` |
| **IBM WatsonX** | `watsonx/<model-id>` | `WATSONX_APIKEY`<br>`WATSONX_URL`<br>`WATSONX_PROJECT_ID` | `api_key`<br>`api_base`<br>`watsonx_project_id` | `api_base` is the regional URL (e.g., `https://us-south.ml.cloud.ibm.com`). |
| **Snowflake Cortex** | `snowflake/<model-name>` | `SNOWFLAKE_ACCOUNT_ID`<br>`SNOWFLAKE_USER`<br>`SNOWFLAKE_PASSWORD` | `snowflake_account_id`<br>`snowflake_user`<br>`snowflake_password` | Supports Llama, Mistral hosted in Snowflake. |


---


### 5. Self-Hosted, Local, and OpenAI-Compatible Engines

| Provider | Model String Format (`model:`) | Default LiteLLM Env Vars | Standard `litellm_params` Keys | Base URL / Notes |
| :--- | :--- | :--- | :--- | :--- |
| **Ollama** | `ollama/<model-name>` | `OLLAMA_API_BASE` | `api_base` | Default base: `http://localhost:11434`. (No API key needed). |
| **vLLM** | `openai/<model-name>` | `OPENAI_API_KEY`<br>`OPENAI_API_BASE` | `api_key`<br>`api_base` | Point `api_base` to `http://<host>:<port>/v1`. Use dummy `api_key: "none"`. |
| **TGI (HuggingFace Text Gen)** | `huggingface/<model-name>` or `tgi/<endpoint>` | `HUGGINGFACE_API_KEY` | `api_key`<br>`api_base` | Endpoint URL from HF Dedicated Endpoints or local TGI. |
| **Hugging Face Serverless** | `huggingface/<repo/model>` | `HUGGINGFACE_API_KEY` (or `HF_TOKEN`) | `api_key` | Standard Hugging Face inference tokens. |
| **Generic OpenAI-Compatible** | `openai/<model-name>` | `OPENAI_API_KEY`<br>`OPENAI_API_BASE` | `api_key`<br>`api_base` | Works with LocalAI, LM Studio, FastChat, TabbyAPI, etc. |


### Advanced: `llm.model_list`

`llm.model_list` follows the [LiteLLM Router
format](https://docs.litellm.ai/docs/routing) and is only needed for
fallbacks, load balancing, or credential env var names that differ from the
provider defaults. When set, `llm.model` and `llm.small_model` must match a
`model_name` entry (reference list <https://models.litellm.ai/>), and credential values use the `os.environ/VAR_NAME`

syntax so secrets stay in env vars. Each provider's keys are listed in the
**Standard `litellm_params` Keys** column of the tables above (full
reference: <https://docs.litellm.ai/docs/providers>):

```yaml
llm:
  model: "anthropic/claude-sonnet-5"
  small_model: "anthropic/claude-sonnet-5"
  model_list:
    - model_name: "anthropic/claude-sonnet-5"
      litellm_params:
        model: "anthropic/claude-sonnet-5"
        api_key: "os.environ/MY_ANTHROPIC_KEY_VAR"
```


Note: boot validation checks the provider's *default* env var names even for
`model_list` entries (a litellm limitation), so when using custom-named vars
the default-named ones must also be set for the core to boot.

## Features

- 🔧 Key functionality or tools
- 📦 What problem it solves
- 🚀 Target audience or use case

## Getting Started

Nebula ships with two configuration tiers, and it matters from the
start which one you are setting up.

The **default local setup** below is enough to generate and apply
infrastructure end to end. All four sidecars (`iac`, `mapping`,
`notifications`, `authz`) come bundled with their `config.yaml`

defaults, but only `iac` is mandatory and enabled out of the box. `iac` and
`notifications` ship complete, working reference implementations;
`mapping` ships a simple direct passthrough usable as shipped for teams
that address repositories by URL; `authz` ships a permissive
placeholder that must be replaced before it enforces anything.
`mapping`, `notifications` and `authz` all start **disabled**. Nebula
also seeds an initial set of [Phoenix prompt templates](#phoenix-prompt-templates)
at first boot: default guidelines and resource templates per cloud,
covering naming conventions, security best practices and compliance
rules for the main resource types, so a fresh install can generate
compliant code without any prompt authoring.

A **full or production configuration** goes further on both axes.
Every sidecar your organization needs must be enabled, and `mapping`
and `authz` in particular usually need to be reimplemented against
your own systems (repository catalogue, access policy), since their
bundled versions are a passthrough and a permissive stub, not real
business logic. Just as important, the seeded
[Phoenix prompt templates](#phoenix-prompt-templates) must be reviewed
and adapted to your organization's own conventions — they are a
working starting point, not your policy. A full configuration therefore
spans `config.yaml`, the `.env` files of the core and all four

sidecars, **and** your organization's own Phoenix prompt templates:
none of these on their own is "fully configured" without the others.


This guide runs the complete Nebula stack locally with Docker Compose:
the core API, the four sidecar services (`iac`, `mapping`,
`notifications`, `authz`), two PostgreSQL databases, Redis, RustFS
object storage, Phoenix, and the nginx proxy that serves the web app.
Every `env.sample` file documents every supported variable; this guide

only highlights the ones that normally need attention. Review the full
sample files before starting the stack.

### Core and sidecars: what you run as-is and what you adapt

Nebula has two kinds of components:

- **Core components are run as-is.** The core API, the web app, the

  nginx proxy, PostgreSQL, Redis, RustFS and Phoenix are the platform.
  Installations configure them through `config.yaml` and the `.env`
  files; they are not meant to be modified per installation.
- **The four sidecars are integration points.** `iac`, `mapping`,
  `notifications` and `authz` each implement an OpenAPI contract in
  [`contracts/openapi/`](./contracts/openapi/). They are where an
  organization plugs in its own systems: any implementation of the

  contract can replace the bundled one by pointing
  `services.<name>.endpoint` in `config.yaml` at it.

The bundled implementations differ in how far they take you:

| Sidecar | Required | Default in `config.yaml` | Bundled implementation |
|---|---|---|---|
| `iac` | **Mandatory** | enabled | Complete and working: runs OpenTofu (or Terraform) with the cloud credentials you supply. Usable as shipped. |
| `notifications` | Optional | disabled | Complete and working: posts to a Slack incoming webhook. Enable it and provide a webhook URL to use it as shipped, or replace it with another channel implementation. |
| `mapping` | Optional | disabled | Simple direct mapping: the repository URL you enter is used as-is, with no catalogue lookup. While disabled the core does the same mapping itself; implement the contract to resolve business identifiers against your own catalogue. |
| `authz` | Optional | disabled | Permissive placeholder: answers "authorized" to everything. Must be implemented with your access policy before enabling; see [Important authorization default](#important-authorization-default). |


With the shipped defaults the core talks to `iac` only. A sidecar
disabled in `config.yaml` is never contacted: the core answers those
calls locally and sends no request to the service. Enabling one means
setting `services.<name>.enabled: true`, rebuilding the core image, and
configuring the sidecar's `.env` as described in step 3. Compose still
builds and starts every sidecar container unless you remove it from
`docker-compose.yml`; a disabled sidecar that exits (for example

`notifications` without a webhook URL) is harmless.

### Prerequisites

- Git.
- Docker Engine or Docker Desktop with Docker Compose v2 (`docker compose`).
- Credentials for at least one LLM provider supported by LiteLLM (see
  [LiteLLM Models and Params Reference](#litellm-models-and-params-reference)).
- A personal access token for your Git provider (GitHub, Azure DevOps,
  or GitLab) so Nebula can push branches and open pull requests.
- Cloud-provider credentials for the cloud your Terraform code targets,
  used by `plan`, `apply` and `import`.


OpenTofu is bundled in the `iac` image as the default IaC engine. The
image also bundles HashiCorp Terraform, selectable with
`IAC_BINARY=terraform`; Terraform is BUSL-1.1 licensed and your use of
it is subject to its license terms (see
[services/iac/README.md](./services/iac/README.md), "Choosing the IaC
engine"). Nothing else needs to be installed on the host: OpenTofu,
Terraform, Python, Node.js and all service dependencies run inside the
containers.

### 1. Create the environment files

```bash
git clone https://github.com/InditexTech/nebula.git
cd nebula

# Mandatory: the core and the iac sidecar
cp core/env.sample core/.env
cp services/iac/env.sample services/iac/.env

# Only for the sidecars you enable in config.yaml (all disabled by default)
cp services/mapping/env.sample services/mapping/.env
cp services/notifications/env.sample services/notifications/.env
cp services/authz/env.sample services/authz/.env
```

`core/.env` is mandatory: Compose refuses to start without it.
`services/iac/.env` is needed because `iac` is the one mandatory
sidecar. The other three `.env` files only matter once you enable the
corresponding sidecar; Compose tolerates their absence and the

containers start with their defaults.

> **Secrets.** The `.env` files are gitignored and must never be
> committed. Everything in them is a secret: LLM API keys, the Git
> token, cloud credentials, the Slack webhook URL and the service bearer
> tokens.

### 2. Configure the core service (`core/.env`)

**LLM credentials.** `llm.model` and `llm.small_model` in `config.yaml`
select the models; `core/.env` must hold the credentials LiteLLM expects
for that provider (variable names follow LiteLLM's provider
conventions). The checked-in `config.yaml` selects Google Vertex AI
models (`vertex_ai/...`), so set `VERTEXAI_PROJECT`, `VERTEXAI_LOCATION`
and `VERTEXAI_CREDENTIALS` (service-account JSON as a file path or raw

content). The `ANTHROPIC_API_KEY` line pre-filled in `core/env.sample`
only applies if you switch to `anthropic/...` models. Changing a model
identifier usually means changing the credential variables too; the
[reference tables](#litellm-models-and-params-reference) list both per
provider.

**Git credentials.** Used for authenticated pushes and pull-request
operations against the provider selected by `git.provider` in
`config.yaml` (`GITHUB` by default; `AZURE_DEVOPS` and `GITLAB` are the
other values):

```dotenv

GIT_USER=
GIT_TOKEN=
```


`GIT_USER` is the account username of the configured provider and
`GIT_TOKEN` its personal access token. Required token permissions depend
on the provider and on your repository policy. At boot the core writes
these into `~/.git-credentials` for `https://<provider-host>`; if either
is empty it logs a warning and pushes fail unless you supply
credentials another way (mounted SSH keys, a pre-populated
`~/.git-credentials`, or a token-bearing repository URI). The `.env`
variables are the standard path for the local Compose stack.

**Sidecar bearer tokens.** The core authenticates every outbound call
to an enabled sidecar with a bearer token; each value in `core/.env`
must match the value in that sidecar's `.env`. With the shipped
defaults only `NEBULA_IAC_TOKEN` is used; the other three are checked
only when their sidecar is enabled:

| Core variable | Must match | When |
|---|---|---|
| `NEBULA_IAC_TOKEN` | `services/iac/.env` → `NEBULA_IAC_TOKEN` | Always (`iac` is mandatory) |
| `NEBULA_MAPPING_TOKEN` | `services/mapping/.env` → `NEBULA_MAPPING_TOKEN` | `services.mapping.enabled: true` |
| `NEBULA_NOTIFICATIONS_TOKEN` | `services/notifications/.env` → `NEBULA_NOTIFICATIONS_TOKEN` | `services.notifications.enabled: true` |
| `NEBULA_AUTHZ_TOKEN` | `services/authz/.env` → `NEBULA_AUTHZ_TOKEN` | `services.authz.enabled: true` |

Every enabled sidecar needs a matching, non-empty token: the core
refuses to boot if an enabled service's token resolves to an empty
value. Generate values with `openssl rand -hex 32`. The samples ship
placeholders (`dev-iac-token`, ...) in `core/.env` and empty values in
the sidecar `.env` files; an empty sidecar token makes that sidecar
accept any bearer, which is acceptable only for an isolated local
environment. Shared and production deployments must use independently
generated secrets on both sides.

**Settings that need no change for the default stack.**
`NEBULA_SQL_DATABASE_URL` already points at the bundled `core-db`

container, and `RUSTFS_ACCESS_KEY` / `RUSTFS_SECRET_KEY` match the
bundled RustFS credentials in `docker-compose.yml`. Redis needs no
variable at all (the Compose service URL is the default).

### 3. Configure the sidecars

**iac (`services/iac/.env`).** `NEBULA_IAC_TOKEN` must match the core.
`IAC_BINARY=tofu` (the default) runs the bundled OpenTofu;
`IAC_BINARY=terraform` runs the bundled Terraform. Cloud credentials are
read directly by the Terraform/OpenTofu providers during `plan`,
`apply`, `import` and related commands. Set only the family your
Terraform configuration uses:

| Cloud | Variables in the sample |
|---|---|
| Azure | `ARM_CLIENT_ID`, `ARM_CLIENT_SECRET`, `ARM_TENANT_ID` |
| Google Cloud | `GOOGLE_CREDENTIALS` (service-account key, as JSON content, not a path) |
| AWS | `AWS_ACCESS_KEY_ID`, `AWS_PROFILE`; add whatever else your AWS provider authentication needs, such as the matching secret key |

Missing or invalid cloud credentials do not stop the container: `plan`
and `apply` run and fail with the engine's own authentication error in
the job's `stderr`.

**mapping (`services/mapping/.env`, optional, disabled by default).**
While disabled, the core performs a simple direct mapping itself: the
repository URL you enter in the wizard is used as-is, with no catalogue
lookup and no request to any service, which is all teams that address
repositories by URL need. The bundled sidecar does exactly the same
mapping and serves as the template for a real implementation. To
resolve business identifiers against your own catalogue, implement the

[mapping contract](./contracts/openapi/mapping.v1.yaml), set
`services.mapping.enabled: true` and `services.mapping.endpoint` in

`config.yaml`, rebuild the core image, and make `NEBULA_MAPPING_TOKEN`
match between `core/.env` and `services/mapping/.env` (see
[services/mapping/README.md](./services/mapping/README.md)).

**notifications (`services/notifications/.env`, optional, disabled by
default).** While disabled, the core sends no notifications at all and
the browser-facing notifications route answers `503`. When enabled,
Nebula notifies compliance-check failures, high-impact detections and
apply failures, plus the support requests users submit from the web app. To enable it, set
`services.notifications.enabled: true` in `config.yaml`, rebuild the
core image, and fill in:

```dotenv
NEBULA_NOTIFICATIONS_TOKEN=
SLACK_WEBHOOK_URL=
```

`NEBULA_NOTIFICATIONS_TOKEN` must match the core. `SLACK_WEBHOOK_URL` is
the Slack incoming-webhook URL the bundled service posts to. It is
required only when you enable the sidecar, but the bundled container
always needs it to start: without it the `notifications` container exits
at boot, which is harmless while the integration is disabled. Treat the
URL as a secret; anyone holding it can post to the channel, and the
service never logs it. Another channel (Teams, e-mail, PagerDuty, ...)
can replace the bundled service by implementing the
[notifications contract](./contracts/openapi/notifications.v1.yaml). See
[services/notifications/README.md](./services/notifications/README.md).

**authz (`services/authz/.env`, optional, disabled by default).** Read
the next section before touching this file.

### Important authorization default

`config.yaml` ships with the project-authorization integration turned
off:

```yaml
services:
  authz:
    enabled: false
```

> **Project-level authorization is disabled by default.** In the
> default local installation, Nebula does not validate whether the
> authenticated user is authorized to operate on a particular cloud
> project or environment. The wizard's preflight
> `POST /api/v1/auth/authorize` returns "authorized" without contacting
> the sidecar.

Keep these points apart:

- **Authentication and authorization are different controls.**
  Enabling OIDC (step 5) authenticates users and activates Nebula's own
  identity, session-ownership and role checks (`developer`/`devops` for
  IaC operations, `viewer`/`editor`/`admin` for the admin panel). It does
  **not** enable cloud-project authorization.
- The core does not call the `authz` sidecar while
  `services.authz.enabled` is `false`. Compose starts the container
  anyway; a running container does not mean the core uses it.
- The bundled `authz` service is a **permissive reference
  integration**, not an organization-specific cloud entitlement system.
  With `NEBULA_AUTHZ_PERMISSIVE=true` (its default) it answers
  "authorized" for every request; `NEBULA_AUTHZ_PERMISSIVE=false` makes
  it deny everything, which is useful to make misconfiguration visible
  but still enforces no real policy.
- Organizations that need project-level authorization must set
  `services.authz.enabled: true`, rebuild the core image, make

  `NEBULA_AUTHZ_TOKEN` match between `core/.env` and
  `services/authz/.env`, and configure or replace the sidecar with an
  implementation of the [authz contract](./contracts/openapi/authz.v1.yaml)
  that enforces their access policy. See
  [services/authz/README.md](./services/authz/README.md).

### 4. Configure models in `config.yaml`

`config.yaml` at the repository root is the single configuration file.
The core reads it from `/etc/nebula/config.yaml`, the location the
Docker build copies it to; set the `NEBULA_CONFIG` environment variable
in `core/.env` to load the file from a different path inside the
container (for example a mounted volume) instead.

```yaml
llm:
  model: "<litellm-provider>/<model-id>"
  small_model: "<litellm-provider>/<model-id>"
```

- `model` handles the complex generation and analysis tasks;
  `small_model` handles lighter orchestration tasks (filtering, status
  messages, PR text, the compliance audit).

- Both are LiteLLM model identifiers (`provider/model-id`). Model IDs
  and credential variables must belong to the same provider; the
  [LiteLLM Models and Params Reference](#litellm-models-and-params-reference)
  above lists the model string format and the credential variables for

  every supported provider.
- Provider secrets go in `core/.env`, never in `config.yaml`.
- The core validates the selected models' credentials at startup and
  fails to boot when LiteLLM reports required variables missing.
  Providers without a LiteLLM validation mapping (for example
  `azure_ai`) surface missing credentials on the first LLM call instead.
- Fallbacks, load balancing and custom credential variable names are
  optional and use `llm.model_list`; see

  [Advanced: `llm.model_list`](#advanced-llmmodel_list).

### 5. Configure OIDC, if required

The checked-in default disables authentication:

```yaml
oidc:
  issuer_url: ""
  client_id: ""
```

> **Local development runs as a privileged built-in identity.** With a
> blank `oidc.issuer_url` every request, from anyone who can reach port
> 80, is resolved to Nebula's local developer identity holding the top
> role of both role groups (`devops` and panel `admin`). This mode is

> for trusted local development only and is not appropriate for a shared
> or production deployment.

To enable login, set at least the issuer and the public client id:

```yaml
oidc:
  issuer_url: "https://your-identity-provider.example/..."
  client_id: "your-public-client-id"

  clock_skew_seconds: 60
```

- The web app is a public client using Authorization Code with PKCE.
  There is no client secret anywhere, so nothing OIDC-related goes in
  `core/.env`.
- Register `<origin>/auth/callback` as the redirect URI at your identity
  provider (`http://localhost/auth/callback` for this stack) and
  `<origin>` as the post-logout URI.
- `oidc.audience` and `oidc.scope` are optional overrides needed by
  some providers (Auth0, Okta). `admin.default_root_email` can bootstrap
  the first administrator, but only when the access token carries a
  matching `email` claim with `email_verified: true`; other providers
  need a one-off SQL grant.
- Per-provider steps (Microsoft Entra ID, Keycloak, Auth0, Okta),
  bootstrap-admin details and troubleshooting:
  [docs/oidc-setup.md](./docs/oidc-setup.md).

- OIDC authenticates users and enables Nebula's identity and role
  checks. It does not configure project-level cloud authorization (see
  [Important authorization default](#important-authorization-default)).

> **`config.yaml` is baked into the core image.** The Dockerfile copies
> it to `/etc/nebula/config.yaml` during the build, and it is not
> hot-reloaded. After changing OIDC, model selection, service
> enablement, the Git provider or any other `config.yaml` value, rebuild
> the core image:
>
> ```bash
> docker compose build core
> ```
>
> The initial `docker compose up --build` below already incorporates the
> current file.

### 6. Start Nebula

With the `.env` files filled in (model credentials, Git credentials,
the `iac` token, cloud credentials, plus the settings of any sidecar you
enabled) and `config.yaml` adjusted if needed:


```bash
docker compose up --build
```

The first build downloads base images, installs Python dependencies for
the core and sidecars, and compiles the React app inside the nginx
image, so it takes several minutes. Add `-d` to run in the background,
or use `docker compose up --watch` to sync `core/` changes into the
running container during development.

Stop the stack with:


```bash
docker compose down
```

This keeps the named volumes (databases, artifacts, authz roles), so
sessions and prompts survive a restart.

### 7. Open and verify the application


Only the proxy publishes host ports:

| URL | What it serves |
|---|---|
| <http://localhost> | Nebula web application and the API under `/api/v1/...` |
| <http://localhost/monitoring/> | Phoenix: traces of every run and the [prompt registry](#phoenix-prompt-templates) |
| `http://localhost:9000` | Presigned artifact download URLs (opened by the web app, not a page to visit) |

Checks:

```bash
docker compose ps                     # proxy, core, iac and the data services "running"; a disabled notifications sidecar exiting is expected
curl http://localhost/api/v1/auth/config   # public route: returns the OIDC settings served to the SPA
docker compose logs -f core           # wait for "Application startup complete"
```


Then open <http://localhost>. In the default (no-OIDC) mode you land
directly in the wizard as the local developer; with OIDC enabled you
are redirected to your identity provider first. Enter a repository your

Git token can push to, describe the infrastructure you need, and follow
the session progress in the UI.

### Troubleshooting

- **Core exits at boot with `LLM credentials missing from environment`.**
  The provider variables for `llm.model` / `llm.small_model` are not
  set in `core/.env`, or the model identifier was changed without
  changing the credential variables.
- **Core exits at boot with `Enabled services have no bearer token`.**
  An enabled sidecar's `NEBULA_*_TOKEN` is empty in `core/.env`. Set it,
  and set the same value in that sidecar's `.env`. A `401` from a
  sidecar at runtime means the two values differ.
- **`notifications` container exits immediately.** Expected while the
  sidecar is disabled (the default); the core never calls it. If you
  enabled it, set `SLACK_WEBHOOK_URL` in `services/notifications/.env`.
- **Enabled a sidecar but the core still ignores it.** The core image
  was not rebuilt after changing `services.<name>.enabled` in
  `config.yaml`; run `docker compose build core` and restart.
- **Plan or apply fails with a provider authentication error.** Cloud
  credentials in `services/iac/.env` are absent or invalid for the cloud
  your Terraform code targets. The engine's message is in the job
  `stderr` shown in the session.
- **Push or pull-request creation fails.** Check `GIT_USER` and
  `GIT_TOKEN` in `core/.env`, that `git.provider` in `config.yaml`
  matches the repository host, and that the token has permission to
  push to and open pull requests on that repository.
- **OIDC (or any `config.yaml`) change has no effect.** The core image
  was not rebuilt: run `docker compose build core` and restart.
  `curl http://localhost/api/v1/auth/config` shows what the core is
  actually serving.
- **Login works but users can operate on any cloud project.** Expected:
  project authorization is a separate integration and is disabled by
  default (`services.authz.enabled: false`). See
  [Important authorization default](#important-authorization-default).
- **Core exits at boot on database, Redis, object storage or Phoenix.**
  Startup is strict: the core aborts if any of these is unreachable.
  Check `docker compose ps` and the failing service's logs; a
  `core_db_data` volume created before the current schema must be
  migrated by hand or recreated.

## Contributing


We welcome contributions!

Please read our [CONTRIBUTING.md](./CONTRIBUTING.md) and follow the [Code of Conduct](./CODE_OF_CONDUCT.md).

## Roadmap

See [ROADMAP.md](./ROADMAP.md) for planned features and development goals.

<!-- or -->

## Acknowledgments

<!-- Mention any projects used as inspiration, key dependencies... -->

## License

This project is licensed under the [Apache-2.0 License](./LICENSE).

© 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)

## Phoenix Prompt Templates


Nebula does not hard-code cloud knowledge in the core: the instructions
that tell the LLM agents how to name, configure and secure resources
live as prompts in Phoenix's runtime prompt registry, fetched by the
core on every request. What ships in the repository is only the
**initial seed** for that registry.

### Where they live

Seed files sit under [`core/prompts/seed/`](./core/prompts/seed/), one
YAML file per prompt, at the fixed path
`<scope>/<type>/<name>.yaml`:

- **`scope`** — `general`, or a cloud: `aws`, `azure`, `gcp`, `oci`,
  `kubernetes`.
- **`type`** — `guidelines` (conventions that apply across resources:
  naming/abbreviations, permissions, networking, forbidden actions, the
  per-cloud resource catalogue) or `resources` (one file per resource
  type, its default configuration); `general` additionally has
  `compliance` (the blocking policy: the rules the compliance-audit
  agent checks a report against, and the impact levels the report
  generator assigns to each change group).

- **`name`** — the prompt's identifier within its scope and type
  (`snake_case`, derived from the filename).

Scope, type and name are derived from the file's path, not declared
inside it, so a misfiled prompt cannot misreport its own identity. Each
file has just two keys: `description` (shown in the Phoenix UI) and
`body` (the Markdown prompt text).

### Examples


| File | Scope / type | What it defines |
|---|---|---|
| [`aws/resources/s3_bucket.yaml`](./core/prompts/seed/aws/resources/s3_bucket.yaml) | aws / resources | Default S3 bucket configuration: naming convention, mandatory encryption, versioning, and public-access blocking. |
| [`azure/resources/storage_account.yaml`](./core/prompts/seed/azure/resources/storage_account.yaml) | azure / resources | Default Storage Account configuration and naming. |
| [`kubernetes/guidelines/permissions.yaml`](./core/prompts/seed/kubernetes/guidelines/permissions.yaml) | kubernetes / guidelines | Pod Security Admission levels and RBAC conventions applied to every generated manifest. |
| [`gcp/guidelines/resources_list.yaml`](./core/prompts/seed/gcp/guidelines/resources_list.yaml) | gcp / guidelines | Catalogue of GCP resource templates the agent may select from. |
| [`general/compliance/report.yaml`](./core/prompts/seed/general/compliance/report.yaml) | general / compliance | Business rules (with rule IDs and severities) the compliance-audit agent checks every generated report against. |
| [`general/compliance/impact.yaml`](./core/prompts/seed/general/compliance/impact.yaml) | general / compliance | Criteria the report generator uses to label each change group `low`, `medium` or `high`; a `high` level blocks the session. |

Browse [`core/prompts/seed/`](./core/prompts/seed/) for the complete,
current set — one directory per cloud, plus `general/`.

### How seeding works, and how to adapt it


At startup the core loads every seed file and creates in Phoenix only
the prompts that do not already exist there; prompts already present
(including ones you have edited) are left untouched. Created prompts
are tagged with the core's `environment` (`config.yaml`'s top-level
`environment` key), and the core fetches prompts by that same tag at
request time — so, unlike `config.yaml`, editing a prompt takes effect
immediately, with no core rebuild.

Adapting the bundled prompts to your organization's conventions means
one of:

- **Editing an existing prompt directly in Phoenix** (the prompt
  registry UI at `/monitoring/` in the default stack) — the durable way
  to do it, since seeding never overwrites a prompt that already
  exists.
- **Adding or changing seed YAML files** before the *first* boot
  against a given Phoenix database, so your version is what gets
  created. This only affects prompts Phoenix does not already have; for
  an already-seeded deployment, edit in Phoenix instead.


Either way, review and rewrite the naming conventions, security
defaults and compliance rules in these prompts for your organization
before relying on a deployment for anything beyond local evaluation —
see the tiers described at the top of
[Getting Started](#getting-started).

<!--
SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)

SPDX-License-Identifier: Apache-2.0
-->

![GitHub License](https://img.shields.io/github/license/InditexTech/nebula)

# Nebula

Nebula turns natural-language requests into reviewed, compliant Infrastructure as Code (IaC). Platform engineers and application developers describe the infrastructure they need, while Nebula’s agents generate Terraform-compatible HCL directly in the appropriate repository, guided by the organization’s architecture, security, and networking standards.

Its governed delivery rail and agent harness make infrastructure delivery safe to extend beyond specialist platform teams. Nebula validates and plans both requested infrastructure changes and automatically generated drift remediations using the existing OpenTofu or Terraform toolchain and the target runtime environment. Nebula reports the proposed changes and their impact, evaluates them against deterministic compliance rules, opens a pull request, and applies the reviewed plan only after human authorization.

> Nebula is an orchestration platform: a FastAPI core, a React web application, and four replaceable sidecar services that implement OpenAPI contracts for the IaC engine, repository mapping, notifications, and authorization. Prompts live in Phoenix, an LLM observability tool that also stores Nebula's traces.

## What you deploy

Nebula has two kinds of components.

### Core platform components

Core components are run as shipped and configured through `config.yaml` and the `.env` files.

**You never reimplement them**; in production you just replace the bundled datastores.

| Component | Purpose |
|---|---|
| `core` | FastAPI orchestration API: sessions, agent chains, validation, reports, pull requests, apply, users and roles. |
| `proxy` (nginx) | React web application
| `core-db` (postgres) | Sessions, rounds, artifacts metadata, users and roles. |
| `redis` | Fail-open cache in front of the database. |
| `object-storage` (RustFS) | Artifacts: reports, plans, code changes. Can also hold Terraform/OpenTofu state, in a separate bucket, when you opt in to Nebula-managed state. |
| `phoenix` + `phoenix-db` | Trace collector and UI, and the runtime prompt registry. |

### Sidecars

Sidecars are integration points between Nebula and your organization.

Each implements a contract in [`contracts/openapi/`](contracts/openapi/), and any implementation of the contract can replace the bundled one by pointing `services.<name>.endpoint` in `config.yaml` at it.

**The bundled implementations exist so the stack runs end to end out of the box** — they are references, not organizational policy.

| Sidecar | Shipped `config.yaml` | Bundled implementation (local deployment) | Production-ready? |
|---|---|---|---|
| `iac` | **enabled** (mandatory) | Reference executor: runs OpenTofu (default) or the bundled Terraform | **Yes** — Harden your image and configure the env vars accordingly. You can also implement new contract. |
| `notifications` | disabled | Slack only: renders a Slack-format message and posts it to one incoming webhook. | **Yes, for Slack only** — For Teams, email, PagerDuty, or any other system, implement the contract. |
| `mapping` | disabled | Identity passthrough: the repository URL you enter is used as-is. While disabled, the core performs the same mapping itself. | **N/A** — leave disabled, or implement the contract against your catalogue. |
| `authz` | disabled | Permissive placeholder: answers "authorized" to every cloud-project check. | **No** — never enable it as your access policy; implement the contract against your policy source. |

A disabled sidecar is never contacted.

The end-to-end flow, the core's layering, and the data model are described in [Architecture](docs/architecture.md).

## Choose your deployment model

Nebula supports **two deployment models**: **Local/non-production** and **Production**.

**Decide which one you need before touching any configuration, because they differ in what you must configure, harden, and replace.**

### QuickStart (local)

Quickstart targets the Local/non-production deployment mode.

It runs on any system with Docker and uses the bundled stack as shipped

What you must configure is small and listed here in full:

- `config.yaml` — the two model strings (`llm.model` and `llm.small_model`).
- `core/.env` — LLM credentials, Git credentials.
- `services/iac/.env` — Two separate sets of cloud credentials:
  - Provider credentials:  `plan` and `apply` use.
  - State-backend credentials: Read and write the remote state file. See [state backends](docs/terraform-state-backends.md#two-sets-of-credentials-on-the-sidecar) and the minimums in [`services/iac/PROVIDERS.md`](services/iac/PROVIDERS.md).
- Optionally, to enable notifications: `services.notifications` in `config.yaml`, `services/notifications/.env` with a matching `NEBULA_NOTIFICATIONS_TOKEN`, and `SLACK_WEBHOOK_URL`.

Everything else runs as bundled.

**Start here:** [Getting started: local/non-production](docs/getting-started-local.md)

### Production

Production is **not** the local Docker Compose stack with `environment: production` in `config.yaml`. That setting only changes how traces and prompts are tagged; it enables no security control.

In production, all four sidecars are integration boundaries between Nebula and your organization, and each must be reviewed, configured, hardened, or customized as the table above states.

**Production requires you to configure all relevant `config.yaml`**

Production should run on an appropriate platform such as Kubernetes. **This repository does not include Kubernetes manifests or Helm charts.**

**Start here:** [Getting started: production](docs/getting-started-production.md)

## Documentation

**Use Nebula** (end users)

| Guide | Read it when you need to |
|---|---|
| [User guide](docs/user-guide.md) | Make a request, write it so it is accepted, follow the session, read the report, handle a lock, open and merge the pull request, apply, and get support. |
| [FAQ](docs/faq.md) | Quick answers to the questions users ask most. |
| [Operating modes](docs/modes.md) | Learn precisely what Generate, Partial Drift, Full Drift, and Import Infrastructure do today. |

**Operate Nebula**

| Guide | Read it when you need to |
|---|---|
| [Admin portal](docs/admin-portal.md) | Review your own sessions, and as a panel user review any user's sessions, lock or unlock applies, and manage roles. |
| [OIDC setup](docs/oidc-setup.md) | Enable login with Entra ID, Keycloak, Auth0, or Okta and bootstrap the first admin. |
| [Monitoring with Phoenix](docs/monitoring.md) | Read traces, configure the collector, understand what data is exported. |
| [Phoenix prompt templates](docs/phoenix-prompt-templates.md) | Customise the prompts that encode your conventions and compliance rules. |

**Reference**

| Guide | Read it when you need to |
|---|---|
| [Configuration reference](docs/configuration.md) | Understand every `config.yaml` field, its default, and its validation rules. |
| [Environment variables and secrets](docs/environment-variables.md) | Fill in `core/.env` and the sidecar `.env` files; handle credentials safely. |
| [Terraform/OpenTofu state backends](docs/terraform-state-backends.md) | Decide where IaC state lives, configure it per provider, and understand keys, locking, and backend changes. |
| [LiteLLM providers and models](docs/litellm.md) | Choose LLM providers and models, set their credentials, use router fallbacks. |
| [Architecture](docs/architecture.md) | See how the pieces fit: components, the core's layering, and the end-to-end flow from a request to an applied plan. |
| Sidecar OpenAPI contracts | [`contracts/openapi/`](contracts/openapi/) (specs), [`contracts/conformance/`](contracts/conformance/) (Schemathesis suites), and the READMEs of [`services/iac`](services/iac/README.md), [`services/mapping`](services/mapping/README.md), [`services/notifications`](services/notifications/README.md), [`services/authz`](services/authz/README.md). |

## Contributing

We welcome contributions! Please read [CONTRIBUTING.md](CONTRIBUTING.md) and follow the [Code of Conduct](CODE_OF_CONDUCT.md). Security issues are handled as described in [SECURITY.md](SECURITY.md). Planned work is tracked in the repository's issues.

## Acknowledgments

Nebula builds on [LiteLLM](https://docs.litellm.ai/) for model access, [Arize Phoenix](https://docs.arize.com/phoenix) for tracing and prompt management, [OpenTofu](https://opentofu.org/) as the default IaC engine, and [FastAPI](https://fastapi.tiangolo.com/) and [React](https://react.dev/) for the core and the web application.

## License

This project is licensed under the [Apache-2.0 License](LICENSE).

© 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)

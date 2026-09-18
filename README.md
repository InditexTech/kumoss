<!--
SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)

SPDX-License-Identifier: Apache-2.0
-->

![GitHub License](https://img.shields.io/github/license/InditexTech/nebula)

# Nebula

**Status:** pre-1.0. There are no tagged releases yet; `main` is the supported line and breaking changes are announced in pull requests.

Nebula turns natural-language requests into reviewed, compliant Infrastructure as Code (IaC). Platform engineers and application developers describe the infrastructure they need, while Nebula’s agents generate Terraform-compatible HCL directly in the appropriate repository, guided by the organization’s architecture, security, and networking standards.

Its structured review process and agent-based generation make infrastructure delivery safe to extend beyond specialist platform teams. Nebula validates and plans both requested infrastructure changes and automatically generated drift remediations using the existing OpenTofu or Terraform toolchain and the target runtime environment. Nebula reports the proposed changes and their impact, audits them with an LLM compliance auditor whose findings (and, optionally, a high-impact verdict) lock the session until a panel editor unlocks it, opens a pull request, and applies the reviewed plan only after an explicit apply request from a `developer` (the requester may apply their own plan; there is no separate approver step).

> Nebula is an orchestration platform: a FastAPI core, a React web application, and four replaceable sidecar services that implement OpenAPI contracts for the IaC engine, repository mapping, notifications, and authorization. Prompts live in Phoenix, an LLM observability tool that also stores Nebula's traces.

## What you deploy

Nebula has two kinds of components.

![What you deploy: the core platform components (proxy, core, core-db, redis, object-storage, phoenix) run as shipped; the four sidecars (iac, notifications, mapping, authz) each implement an OpenAPI contract and connect Nebula to your organization's LLM providers, Git hosting, cloud accounts, and Slack](docs/images/readme-components.png)

*Green: core platform components you run as shipped. Orange: sidecars behind OpenAPI contracts — solid for the mandatory `iac` sidecar, dashed for the three that are disabled by default. Grey: systems in your organization. Source: [`docs/images/readme-components.mmd`](docs/images/readme-components.mmd); the detailed view is in [Architecture](docs/architecture.md).*

### Core platform components

Core components are run as shipped and configured through `config.yaml` and the `.env` files.

**You never reimplement them**; in production you just replace the bundled datastores.

| Component | Purpose |
|---|---|
| `core` | FastAPI orchestration API: sessions, agent chains, validation, reports, pull requests, apply, users and roles. |
| `proxy` (nginx) | Serves the React web application, publishes the API and Monitoring endpoints and the internal object storage. |
| `core-db` | Postgres 17 storing sessions, rounds, artifact metadata, users and roles. |
| `redis` | Cache for core-db. |
| `object-storage` | Artifacts: reports, plans, code changes. Also holds Terraform/OpenTofu state, in a separate bucket, when Nebula-managed state is enabled. |
| `phoenix` + `phoenix-db` | AI Observability stack. Also used as prompt registry. |

### Sidecars

Sidecars are integration points between Nebula and your organization.

Each implements a contract in [`contracts/openapi/`](contracts/openapi/), and any implementation of the contract can replace the bundled one by pointing `services.<name>.endpoint` in `config.yaml` at it.

**The bundled implementations exist so the stack runs end to end out of the box** — they are references, not organizational policy.

| Sidecar | Shipped `config.yaml` | Bundled implementation (local deployment) | Production-ready? |
|---|---|---|---|
| `iac` | **enabled** (mandatory) | Reference interface to execute IaC: OpenTofu (default) or bundled Terraform | **As a starting point** — harden the image and container, or implement the contract yourself. |
| `notifications` | disabled | Reference interface for Slack: renders a Slack-format message and posts it to one incoming webhook. | **Yes, for Slack only** — For Teams, email, PagerDuty, or any other system, implement the contract. |
| `mapping` | disabled | Reference interface for routing to Git repositories: Repository URL you enter is used as-is. While disabled, the core performs the same mapping itself. | **N/A** — leave disabled, or implement the contract against your catalogue. |
| `authz` | disabled | Service interface to apply authorization policies; the bundled reference answers "authorized" to every check. | **No** — never enable it as your access policy; implement the contract against your policy source. |

A disabled sidecar is never contacted. The compose stack still builds and starts every sidecar container; an exited `notifications` container without `SLACK_WEBHOOK_URL` is expected.

The end-to-end flow, the core's layering, and the data model are described in [Architecture](docs/architecture.md).

## Choose your deployment model

Nebula supports **two deployment models**: **Local/non-production** and **Production**.

**Decide which one you need before touching any configuration, because they differ in what you must configure, harden, and replace.**

### QuickStart (local)

Quickstart targets the Local/non-production deployment mode.

It runs on any system with Docker and uses the bundled stack as shipped.

What you must configure is small and listed here in full:

- `config.yaml` — the two model strings (`llm.model` and `llm.small_model`).
- `core/.env` — LLM credentials, Git credentials.
- `services/iac/.env` — Two separate sets of cloud credentials:
  - Provider credentials: what `plan` and `apply` use to read and create the resources themselves.
  - State-backend credentials: what `init` uses to read and write the remote state file. See [state backends](docs/terraform-state-backends.md#two-sets-of-credentials-on-the-sidecar) and the minimums in [`services/iac/PROVIDERS.md`](services/iac/PROVIDERS.md).
- Optionally, to enable notifications: `services.notifications` in `config.yaml`, `services/notifications/.env` with a matching `NEBULA_NOTIFICATIONS_TOKEN`, and `SLACK_WEBHOOK_URL`.

Everything else runs as bundled. On the core side, the sidecar bearer tokens (`NEBULA_IAC_TOKEN` and friends) must be non-empty and already come filled in with sample values. On the sidecar side, the samples ship the matching token blank, which turns that sidecar's own token check off — fine on a private compose network, never in a shared deployment.

**This mode runs with authentication disabled** — every request resolves to a built-in `devops` + panel `admin` identity — and ships well-known credentials (`postgres:postgres`, `rustfsadmin`), no TLS, and an unauthenticated Phoenix console at `/monitoring/`. Never expose this stack beyond a trusted workstation.

**Start here:** [Getting started: local/non-production](docs/getting-started-local.md)

### Production

Production is **not** the local Docker Compose stack with `environment: production` in `config.yaml`. That setting only changes how traces and prompts are tagged; it enables no security control.

In production, all four sidecars are integration boundaries between Nebula and your organization, and each must be reviewed, configured, hardened, or customized as the table above states.

**Production requires you to configure every relevant `config.yaml` section, the core's secrets, each enabled sidecar's environment, OIDC, project-level authorization, LLM, Git and cloud credentials, persistence for PostgreSQL, Redis and object storage, TLS, secrets management, backups, upgrades, and observability — see the production guide's checklist.**

Production should run on an appropriate platform such as Kubernetes. **This repository does not include Kubernetes manifests or Helm charts.**

**Start here:** [Getting started: production](docs/getting-started-production.md)

## Documentation

**Start here**

| Guide | Read it when you need to |
|---|---|
| [Getting started: local/non-production](docs/getting-started-local.md) | Bring up the full Docker Compose stack on a workstation for evaluation or development. |
| [Getting started: production](docs/getting-started-production.md) | Plan and configure a hardened, production deployment. |

**Use Nebula** (end users)

| Guide | Read it when you need to |
|---|---|
| [User guide](docs/user-guide.md) | Make a request, write it so it is accepted, follow the session, read the report, handle a lock, open and merge the pull request, apply, and get support. |
| [FAQ](docs/faq.md) | Quick answers to the questions users ask most. |
| [Operating modes](docs/modes.md) | Learn precisely what Generate, Partial Drift, Full Drift, and Import Infrastructure do today, and how Nebula finds the Terraform roots in a repository. |

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
| [Configuration reference (`config.yaml`)](docs/configuration.md) | Understand every `config.yaml` field, its default, and its validation rules. |
| [Environment variables and secrets](docs/environment-variables.md) | Fill in `core/.env` and the sidecar `.env` files; handle credentials safely. |
| [State backends](docs/terraform-state-backends.md) | Decide where IaC state lives, configure it per provider, and understand keys, locking, and backend changes. |
| [LiteLLM providers and models](docs/litellm.md) | Choose LLM providers and models, set their credentials, and understand which model handles which step. |
| [Architecture](docs/architecture.md) | See how the pieces fit: components, the core's layering, and the end-to-end flow from a request to an applied plan. |
| Sidecar OpenAPI contracts | [`contracts/openapi/`](contracts/openapi/) (specs), [`contracts/conformance/`](contracts/conformance/) (Schemathesis suites), and the READMEs of [`services/iac`](services/iac/README.md), [`services/mapping`](services/mapping/README.md), [`services/notifications`](services/notifications/README.md), [`services/authz`](services/authz/README.md). |

## Contributing

We welcome contributions! Please read [CONTRIBUTING.md](CONTRIBUTING.md) and follow the [Code of Conduct](CODE_OF_CONDUCT.md). Security issues are handled as described in [SECURITY.md](SECURITY.md). Planned work is tracked in the repository's issues.

## Acknowledgments

Nebula builds on [LiteLLM](https://docs.litellm.ai/) for model access, [Arize Phoenix](https://arize.com/docs/phoenix) for tracing and prompt management, [OpenTofu](https://opentofu.org/) as the default IaC engine, and [FastAPI](https://fastapi.tiangolo.com/) and [React](https://react.dev/) for the core and the web application.

## License

This project is licensed under the [Apache-2.0 License](LICENSE).

© 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)

<!--
SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)

SPDX-License-Identifier: Apache-2.0
-->

![GitHub License](https://img.shields.io/github/license/InditexTech/nebula)

# Nebula

Nebula turns natural-language requests into reviewed, compliant Infrastructure as Code (IaC). Platform engineers and application developers describe the infrastructure they need, while Nebula’s agents generate Terraform-compatible HCL directly in the appropriate repository, guided by the organization’s architecture, security, and networking standards.

Its governed delivery rail and agent harness make infrastructure delivery safe to extend beyond specialist platform teams. Nebula validates and plans both requested infrastructure changes and automatically generated drift remediations using the existing OpenTofu or Terraform toolchain and the target runtime environment. Nebula reports the proposed changes and their impact, runs an independent compliance audit whose pass/fail verdict is computed in code from the reported findings, opens a pull request, and applies the reviewed plan only after human authorization.

> Nebula is an orchestration platform: a FastAPI core, a React web application, and four replaceable sidecar services that implement OpenAPI contracts for the IaC engine, repository mapping, notifications, and authorization. Prompts live in Phoenix, an LLM observability tool that also stores Nebula's traces.

## What you deploy

Nebula has two kinds of components.

### Core platform components

Core components are run as shipped and configured through `config.yaml` and the `.env` files.

**You never reimplement them**; in production you just replace the bundled datastores.

| Component | Purpose |
|---|---|
| `core` | FastAPI orchestration API: sessions, agent chains, validation, reports, pull requests, apply, users and roles. |
| `proxy` (nginx) | Serves the React web application it builds, forwards `/api` to the core and `/monitoring/` to Phoenix, and forwards port 9000 to object storage for artifact downloads. |
| `core-db` (PostgreSQL 17) | Sessions, rounds, artifacts metadata, users and roles. |
| `redis` | Fail-open cache in front of the database. |
| `object-storage` (RustFS, S3-compatible) | Artifacts: reports, plans, code changes. AWS S3 or an Azure Storage Account can replace it. |
| `phoenix` + `phoenix-db` | Trace collector and UI, and the runtime prompt registry. |

### Sidecars

Sidecars are integration points between Nebula and your organization.

Each implements a contract in [`contracts/openapi/`](contracts/openapi/), and any implementation of the contract can replace the bundled one by pointing `services.<name>.endpoint` in `config.yaml` at it.

The bundled implementations exist so the stack runs end to end out of the box — they are references, not organizational policy.

| Sidecar | Shipped `config.yaml` | Bundled implementation | Production-ready as shipped? |
|---|---|---|---|
| `iac` | **enabled** (mandatory) | Reference executor: runs OpenTofu 1.12.6 (default) or the bundled HashiCorp Terraform 1.16.0 as asynchronous jobs on the shared workspace volume. Terraform is BUSL-1.1 licensed; selecting it makes your use subject to its terms. | **No** — implement the contract for your requirements, or at minimum harden the bundled image. |
| `notifications` | disabled | Slack only: renders a Slack-format message and posts it to one incoming webhook. | **Yes, for Slack only** — point it at your production channel and supply that channel's webhook URL, which is itself the credential. For Teams, email, PagerDuty, or any other system, implement the contract. |
| `mapping` | disabled | Identity passthrough: the repository URL you enter is used as-is. While disabled, the core performs the same mapping itself. | **N/A** — leave disabled, or implement the contract against your catalogue. |
| `authz` | disabled | Permissive placeholder: answers "authorized" to every cloud-project check. | **No** — never enable it as your access policy; implement the contract against your policy source. |

A disabled sidecar is never contacted. Compose still builds and starts every sidecar container; a disabled `notifications` container that exits because it has no webhook URL is expected and harmless. Every *enabled* sidecar needs a bearer token that matches between the core and the sidecar.

The end-to-end flow, the core's layering, and the data model are described in [Architecture](docs/architecture.md).

## Choose your deployment model

Nebula supports **two deployment models**: Local/non-production and Production. 

**Decide which one you need before touching any configuration, because they differ in what you must configure, harden, and replace.**

Read the Production column as a checklist. Each cell starts with the action required:

- **Use bundled** — the shipped component works; you only supply credentials or configuration.
- **Harden** — the shipped component is the starting point, but needs production controls.
- **Implement** — the shipped component is a reference or placeholder; write your own against the contract.
- **Replace** — swap the shipped component for a managed or organizational equivalent.

| Area | Local/non-production | Production |
|---|---|---|
| Intended use | Evaluation, development, demos, testing on one trusted host | Shared organizational use |
| Platform | **Use bundled** Docker Compose stack, as shipped | **Replace** with a production platform such as Kubernetes. No manifests or Helm charts are shipped; Compose is the reference topology |
| `core`, `proxy`, web application | **Use bundled** as shipped; just set the two models to be used in `config.yaml` | **Use bundled** as shipped; configure every relevant `config.yaml` section and front them with TLS and a real ingress |
| `core-db`, `redis`, `object-storage`, Phoenix | **Use bundled** containers with their default credentials and single-host volumes | **Replace** with managed or hardened instances: real credentials, persistence, backups, and an authenticated Phoenix console |
| `iac` sidecar (mandatory) | **Use bundled** executor; give it the shared bearer token and cloud credentials | **Implement** the contract to your requirements (how the engine runs, where workspaces and state live, which identity it uses, what isolation and approval controls apply), or **harden** the bundled image: production cloud identity, isolation, resource limits, egress policy, and a shared workspace volume owned by the same unprivileged user as the core |
| `notifications` sidecar | **Use bundled**, optional: enable it and add any `SLACK_WEBHOOK_URL` to post to a test channel | **Configure** it for your notification system and credentials. On Slack, **use bundled** with your operational channel's production webhook URL; for Teams, email, PagerDuty, or anything else, **implement** the contract |
| `mapping` sidecar | Leave disabled; the core maps repository URLs itself | **Implement** the contract against your repository catalogue, or leave disabled |
| `authz` sidecar | Leave disabled; every cloud-project check answers "authorized" | **Implement** the contract against your policy source. The bundled placeholder must never be your access-control policy |
| Authentication | OIDC may stay disabled: every request runs as a built-in identity holding the `devops` operation role and the panel `admin` role | **Configure** OIDC — it must be enabled |
| Secrets | Local gitignored `.env` files with sample values | **Replace** with Kubernetes Secrets or an equivalent secret manager |
| Prompts and compliance rules | **Use bundled** seeds as shipped | **Curate** them in Phoenix so they encode your architecture, security, and networking standards |
| Operations | Single-host stack, no backups, no TLS | Production networking, persistence, backups, upgrades, and observability |

### QuickStart 

Quickstart targets the Local/non-production deployment mode. 

It runs on any system with Docker and Docker Compose and uses the bundled stack as shipped: core, web application, the four sidecars, PostgreSQL databases, Redis, RustFS object storage, Phoenix, and the nginx proxy.

What you must configure is small and listed here in full:

- `config.yaml` — the two model strings (`llm.model` and `llm.small_model`).
- `core/.env` — LLM credentials, Git credentials, and the IaC bearer token.
- `services/iac/.env` — the matching IaC bearer token and the cloud credentials your Terraform providers need.
- Optionally, to enable notifications: `services.notifications` in `config.yaml`, `services/notifications/.env` with a matching `NEBULA_NOTIFICATIONS_TOKEN`, and `SLACK_WEBHOOK_URL`.

Everything else runs as bundled. **Authentication may remain disabled only for trusted local development** — with OIDC disabled, every request runs as a privileged built-in identity holding the `devops` operation role and the panel `admin` role, so anyone who can reach the port has that access. Installation ends with a core build and `docker compose up --build`.

This model is **not suitable for shared or production environments**: it ships well-known default credentials, no TLS, an unauthenticated Phoenix console, and a single host with no backups.

**Start here:** [Getting started: local/non-production](docs/getting-started-local.md)

### Production

Production is **not** the local Compose stack with `environment: production` in `config.yaml`. That setting only changes how traces and prompts are tagged; it enables no security control.

In production, all four sidecars are integration boundaries between Nebula and your organization, and each must be reviewed, configured, hardened, or customized as the table above states. Where a bundled implementation is suitable as a starting point, customizing it means secure configuration and integration; where it is not, implement the contract yourself.

Beyond the sidecars, production requires you to configure all relevant `config.yaml` sections, the core's secrets, the environment variables or secrets of every enabled sidecar, OIDC, project-level authorization, LLM credentials, Git credentials, cloud credentials, persistence for PostgreSQL, Redis, object storage, and Phoenix, and the surrounding networking, TLS, secret management, backups, upgrades, and observability.

Production should run on an appropriate platform such as Kubernetes. **This repository does not include Kubernetes manifests or Helm charts.** The Compose file is the reference topology; the production guide explains what each component needs so that you can express it on your platform.

**Start here:** [Getting started: production](docs/getting-started-production.md)

## Documentation

**Start here**

| Guide | Read it when you need to |
|---|---|
| [Getting started: local/non-production](docs/getting-started-local.md) | Install the Compose stack on a workstation and run your first session. |
| [Getting started: production](docs/getting-started-production.md) | Plan and harden a shared deployment: sidecars, secrets, OIDC, persistence, networking. |

**Use Nebula** (for the people who make requests)

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
| [LiteLLM providers and models](docs/litellm.md) | Choose LLM providers and models, set their credentials, use router fallbacks. |
| [Architecture](docs/architecture.md) | See how the pieces fit: components, the core's layering, and the end-to-end flow from a request to an applied plan. |
| Sidecar OpenAPI contracts | [`contracts/openapi/`](contracts/openapi/) (specs), [`contracts/conformance/`](contracts/conformance/) (Schemathesis suites), and the READMEs of [`services/iac`](services/iac/README.md), [`services/mapping`](services/mapping/README.md), [`services/notifications`](services/notifications/README.md), [`services/authz`](services/authz/README.md). |

## Contributing

We welcome contributions! Please read [CONTRIBUTING.md](CONTRIBUTING.md) and follow the [Code of Conduct](CODE_OF_CONDUCT.md). Security issues are handled as described in [SECURITY.md](SECURITY.md). Planned work is tracked in the repository's issues.

## Acknowledgments

Nebula builds on [LiteLLM](https://docs.litellm.ai/) for model access, [Arize Phoenix](https://arize.com/docs/phoenix) for tracing and prompt management, [OpenTofu](https://opentofu.org/) as the default IaC engine, and [FastAPI](https://fastapi.tiangolo.com/) and [React](https://react.dev/) for the core and the web application.

## License

This project is licensed under the [Apache-2.0 License](LICENSE).

© 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)

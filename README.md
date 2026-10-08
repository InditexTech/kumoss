<!--
SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)

SPDX-License-Identifier: Apache-2.0
-->

![GitHub License](https://img.shields.io/github/license/InditexTech/kumoss)

# Kumoss

Kumoss turns natural-language requests into reviewed, compliant Infrastructure as Code (IaC). Platform engineers and application developers describe the infrastructure they need, and Kumoss's agents generate Terraform-compatible HCL in the right repository, guided by the organization's architecture, security, and networking standards. Every change is validated, planned, reported, and audited for compliance before Kumoss opens a pull request and applies it on request.

Kumoss is an orchestration platform: a FastAPI core, a React web application, and four replaceable sidecar services behind OpenAPI contracts for the IaC engine, repository mapping, notifications, and authorization.

https://github.com/user-attachments/assets/cb8d1b4b-7e10-45d6-ac05-acfebfb38b9b

## Key capabilities

**What Kumoss does for you**

- **Compliant infrastructure from plain language.** A developer-friendly assistant needs only your request and the project you are working on.
- **A validated plan, every time.** Kumoss reads your IaC code and the infrastructure actually deployed in the cloud, then proposes a change that fulfills the request. It treats what is deployed as the source of truth and transparently corrects existing and impacted drift, including day-2 changes. The result is a successful Terraform/OpenTofu plan that complies with the architecture, security, and governance rules your organization defines.
- **Human review where it matters.** Any request detected as high impact or non-compliant locks the session until your administrator team reviews it.
- **A report people can read.** Every session ends with a summary of the proposal, its impact, and a cost estimate.
- **Several modes of operation.** Generate new infrastructure, remediate drift, or import console created resources, for part of a project or all of it.

**Built to fit your organization**

- **Works with what you already have.** Use your existing IaC repositories, Terraform state, and Git provider (GitHub, Azure DevOps, or GitLab).
- **Multicloud.** AWS, Azure, Google Cloud, Oracle Cloud Infrastructure, and Kubernetes.
- **Your rules, your definition of critical.** You decide what is allowed, what is high risk, and which compliance checks apply. Critical can mean special projects, every production environment, changes above a cost threshold, or any rule you write.
- **Full traceability.** An admin panel shows users, sessions, and roles, all stored in a database.
- **Observability built in.** Every agent and every system prompt read at runtime is traced with OpenTelemetry and Arize Phoenix.

**Bring your own**

- **Model.** Any [LiteLLM](https://docs.litellm.ai/)-supported model.
- **Identity provider.** Any OIDC provider for sign-in.
- **Authorization logic.** You decide who may request infrastructure, and where, by implementing the authorization OpenAPI contract.
- **IaC executor.** Keep your own Terraform or OpenTofu runtime, version, and execution environment by implementing the IaC OpenAPI contract.
- **Notification system.** Send session outcomes and review requests to any channel, such as Slack, Microsoft Teams, email, Discord, or WhatsApp, by implementing the notifications OpenAPI contract.

Each integration point is a sidecar service behind an [OpenAPI contract](contracts/openapi/), so you can replace the bundled reference implementation with your own.

> [!NOTE]
> Kumoss exposes everything through a FastAPI API, so support for the Model Context Protocol (MCP) and the Agent2Agent (A2A) protocol is in progress, letting other agents consume Kumoss directly.

## How it works

1. **You ask.** Describe the infrastructure you need in plain language and pick the project.
2. **Kumoss checks who you are.** It authenticates you and confirms you are authorized to work on that project.
3. **Kumoss gathers context.** It reads the infrastructure deployed in your cloud, your existing IaC repository, your request, and the architecture, security, and governance standards your organization defined.
4. **Kumoss builds a plan that passes.** It generates the code and runs a Terraform/OpenTofu plan. If the plan fails, Kumoss fixes the code and tries again until it passes.
5. **Kumoss fixes drift along the way.** The infrastructure deployed in the cloud is the source of truth, not the repository. Any drift is fixed by updating the code to match what really runs in production.
6. **You get a clear report.** It summarizes the impact, the main changes, and the estimated cost.
7. **A compliance agent reviews the proposal.** It checks the change against your organization's policies and flags it as high impact when it matches the criteria your organization defined. Kumoss then opens a pull request.
8. **Risky changes wait for review.** If the proposal is not compliant or is high impact, apply is blocked and your administrator team is notified to accept or reject it.
9. **You apply.** Once the proposal is cleared, you approve and apply it, and Kumoss gives you a new report with the result.

## Documentation

The full documentation is published at **[inditextech.github.io/kumoss](https://inditextech.github.io/kumoss/stable/)**.

- [Quickstart](https://inditextech.github.io/kumoss/stable/main/quickstart/): run the full stack locally with Docker Compose.
- [Architecture](https://inditextech.github.io/kumoss/stable/main/architecture/): components, the core's layering, and the end-to-end flow from a request to an applied plan.

## Contributing

We welcome contributions! Please read [CONTRIBUTING.md](CONTRIBUTING.md) and follow the [Code of Conduct](CODE_OF_CONDUCT.md). Security issues are handled as described in [SECURITY.md](SECURITY.md).

## License

This project is licensed under the [Apache-2.0 License](LICENSE).

© 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)

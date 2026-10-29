<!--
SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)

SPDX-License-Identifier: Apache-2.0
-->

# OpenAPI specs

One hand-written OpenAPI 3.1 document per sidecar service, named
`<service>.v<major>.yaml`. These files are the source of truth for
every implementation of a Kumoss sidecar, bundled or third-party, and
of the core's HTTP clients for them (`core/src/infrastructure/external/`,
`core/src/infrastructure/terraform/iac.rs` and
`core/src/infrastructure/llm/sidecar.rs`). Kumoss bundles
implementations of the IaC, notifications and LLM contracts; mapping and
authorization are optional extension points you implement yourself.

| Spec | Service | Bundled implementation | Conformance suite |
|---|---|---|---|
| [`iac.v1.yaml`](iac.v1.yaml) | IaC engine executor: runs OpenTofu or Terraform commands as asynchronous jobs on a shared workspace | [`services/iac`](../../services/iac/README.md) | [`../conformance/iac/`](../conformance/iac/) |
| [`mapping.v1.yaml`](mapping.v1.yaml) | Resolves a business identifier to a repository URL, plus a best-effort terraform provider and cloud scope | None (optional, disabled by default) | [`../conformance/mapping/`](../conformance/mapping/) |
| [`notifications.v1.yaml`](notifications.v1.yaml) | Delivers notifications (compliance failures, high-impact detections, apply failures, user support requests) to a channel | [`services/notifications`](../../services/notifications/README.md) | [`../conformance/notifications/`](../conformance/notifications/) |
| [`llm.v1.yaml`](llm.v1.yaml) | LLM gateway: LiteLLM completions, web search and page reads, so the core holds no provider credentials | [`services/llm`](../../services/llm/README.md) | None |
| [`authz.v1.yaml`](authz.v1.yaml) | Cloud-project authorization checks | None (optional, disabled by default) | [`../conformance/authz/`](../conformance/authz/) |

## Updating the core clients

The core's clients are hand-written Rust. After changing a spec, update
the matching client and its tests in `core/` so requests, responses and
error handling still follow the document.

See [`../README.md`](../README.md) for error, authentication, and
versioning conventions.

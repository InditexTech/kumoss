<!--
SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)

SPDX-License-Identifier: Apache-2.0
-->

# OpenAPI specs

One hand-written OpenAPI 3.1 document per sidecar service, named
`<service>.v<major>.yaml`. These files are the source of truth for
every implementation of a Nebula sidecar, bundled or third-party, and
the core's HTTP clients under `core/src/clients/` are generated from
them.

| Spec | Service | Bundled reference implementation | Conformance suite |
|---|---|---|---|
| [`iac.v1.yaml`](iac.v1.yaml) | IaC engine executor: runs OpenTofu or Terraform commands as asynchronous jobs on a shared workspace | [`services/iac`](../../services/iac/README.md) | [`../conformance/iac/`](../conformance/iac/) |
| [`mapping.v1.yaml`](mapping.v1.yaml) | Resolves a business identifier to a repository URL and project name | [`services/mapping`](../../services/mapping/README.md) | [`../conformance/mapping/`](../conformance/mapping/) |
| [`notifications.v1.yaml`](notifications.v1.yaml) | Delivers notifications (compliance failures, high-impact detections, apply failures, user support requests) to a channel | [`services/notifications`](../../services/notifications/README.md) | [`../conformance/notifications/`](../conformance/notifications/) |
| [`authz.v1.yaml`](authz.v1.yaml) | Cloud-project authorization checks | [`services/authz`](../../services/authz/README.md) | [`../conformance/authz/`](../conformance/authz/) |

## Regenerating the core clients

After changing a spec, regenerate the matching client from `core/`
(the config forces a common package name so generated imports are
identical across services):

```bash
uv run openapi-python-client generate \
  --path ../contracts/openapi/<service>.v1.yaml \
  --config ../contracts/openapi-python-client.yaml \
  --meta none \
  --output-path src/clients/<service> \
  --overwrite
```

Do not hand-edit the generated clients.

See [`../README.md`](../README.md) for error, authentication, and
versioning conventions.

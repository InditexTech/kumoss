<!--
SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)

SPDX-License-Identifier: Apache-2.0
-->

# Kumoss Helm chart

Deploys Kumoss and its bundled services on Kubernetes, mirroring
`docker-compose.yml`.

```bash
helm upgrade --install kumoss charts/kumoss -n kumoss --create-namespace \
  --set core.existingSecret=<secret with LLM / git credentials>
```

`files/` holds symlinks to the repository's `config.yaml`,
`nginx/nginx.conf` and `services/searxng/settings.yml`; the chart
rewrites their Compose hostnames at render time.

Full guide, including a local kind walkthrough, workload identity on
AKS / EKS / GKE, and every value that matters:
https://inditextech.github.io/kumoss/stable/main/guides/deploy-with-helm/

<!--
SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)

SPDX-License-Identifier: Apache-2.0
-->

# Kumoss Helm chart

Deploys Kumoss and its bundled services on Kubernetes, mirroring
`docker-compose.yml`.

Each release publishes it to `oci://ghcr.io/inditextech/charts/kumoss`
with the release's version:

```bash
helm upgrade --install kumoss oci://ghcr.io/inditextech/charts/kumoss \
  --version <version> -n kumoss --create-namespace \
  --set core.existingSecret=<secret with LLM / git credentials>
```

From a checkout, use `charts/kumoss` instead of the OCI reference.
`charts/kind-up.sh` brings it up on a local kind cluster in one command.
Behind a TLS-inspecting proxy, set `caBundle.existingConfigMap` to a
ConfigMap of your corporate PEM roots.

`files/` holds symlinks to the repository's `config.yaml`,
`nginx/nginx.conf` and `services/searxng/settings.yml`; the chart
rewrites their Compose hostnames at render time.

Full guide, including a local kind walkthrough, workload identity on
AKS / EKS / GKE, and every value that matters:
https://inditextech.github.io/kumoss/stable/main/guides/deploy-with-helm/

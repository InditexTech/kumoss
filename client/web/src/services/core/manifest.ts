// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { apiFetch } from "@/services/api";
import type { ManifestProbeRequest, ManifestProbeResponse } from "@/types/api";

const MANIFEST_BASE = "/api/v1/manifest";

// The probe clones the repository and inspects the root module.
const PROBE_TIMEOUT_MS = 180_000;

/** POST /v1/manifest/probe — What the root module needs before a session runs on it */
export async function probeManifest(
  request: ManifestProbeRequest,
): Promise<ManifestProbeResponse> {
  return apiFetch<ManifestProbeResponse>(`${MANIFEST_BASE}/probe`, {
    method: "POST",
    body: JSON.stringify(request),
    timeout: PROBE_TIMEOUT_MS,
  });
}

// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import type { ResolveRequest, ResolveResponse } from "@/types/api_mapper";
import { apiFetch } from "@/services/api";

const BASE = "/api/v1/mapping";

export async function resolveProject(
  request: ResolveRequest,
): Promise<ResolveResponse> {
  return apiFetch<ResolveResponse>(`${BASE}/resolve`, {
    method: "POST",
    body: JSON.stringify(request),
  });
}

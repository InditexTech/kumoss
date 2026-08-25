// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { apiFetch } from "@/services/api";
import { AuthorizeRequest, AuthorizeResponse } from "@/types/api";

const BASE = "/api/v1/authorize";

/** POST /v1/authorize — Endpoint to manage if a user has permissions on a given project */
export async function authorizeUser(
  request: AuthorizeRequest,
): Promise<AuthorizeResponse> {
  return apiFetch<AuthorizeResponse>(BASE, {
    method: "POST",
    body: JSON.stringify(request),
  });
}

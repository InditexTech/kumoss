// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { apiFetch } from "@/services/api";
import type { SessionPayloadResponse, UserMeResponse } from "@/types/api";
import { getSessionData } from "@/services/core/events";

// NOTE: the admin session endpoints (/api/v1/admin/sessions*) were retired
// with the sessions API refactor. The admin view consumes the same
// /api/v1/sessions endpoints as the user view until dedicated admin
// endpoints (cross-user listing, block toggle) are rebuilt server-side.

/** GET /v1/events/get/{session_id} — Reload a session's full payload for the admin detail view */
export async function reloadSession(
  sessionId: string,
): Promise<SessionPayloadResponse> {
  return getSessionData(sessionId);
}

/** GET /v1/users/me — Check if the current user has the admin role */
export async function checkIsAdmin(): Promise<boolean> {
  try {
    const user = await apiFetch<UserMeResponse>("/api/v1/users/me");
    return user.roles.includes("admin");
  } catch {
    return false;
  }
}

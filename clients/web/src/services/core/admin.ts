import { apiFetch } from "@/services/api";
import {
  ApplyAllowedResponse,
  AdminSessionDetailResponse,
  SessionsListResponse,
  UserMeResponse,
  normalizeHistory,
} from "@/types/api";
import type { SessionPayloadResponse } from "@/types/api";
import { getSessionData } from "@/services/core/events";

import { SessionFilter } from "@/types/ui";

const BASE = "/api/v1/admin";

/** GET /v1/admin/sessions — List sessions with pagination and filters */
export async function listSessions(
  params: SessionFilter = {},
): Promise<SessionsListResponse> {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null) {
      query.set(key, String(value));
    }
  }
  const qs = query.toString();
  return apiFetch<SessionsListResponse>(
    `${BASE}/sessions${qs ? `?${qs}` : ""}`,
  );
}

/** GET /v1/admin/sessions/{session_id} — Get session detail with operations timeline */
export async function getSessionDetail(
  sessionId: string,
): Promise<AdminSessionDetailResponse> {
  const raw = await apiFetch<AdminSessionDetailResponse>(
    `${BASE}/sessions/${encodeURIComponent(sessionId)}`,
  );
  // TEMPORAL FIX: normalize {user, assistant} turn pairs from backend into {role, content} entries
  if (raw.full_history) {
    raw.full_history = normalizeHistory(raw.full_history);
  }
  return raw;
}

/** PATCH /v1/admin/sessions/{session_id}/apply_allowed — Toggle apply_allowed for a session (admin unlock/lock) */
export async function toggleApplyAllowed(
  sessionId: string,
  allowed: boolean,
): Promise<ApplyAllowedResponse> {
  return apiFetch<ApplyAllowedResponse>(
    `${BASE}/sessions/${encodeURIComponent(sessionId)}/apply_allowed`,
    {
      method: "PATCH",
      body: JSON.stringify({ allowed }),
    },
  );
}

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

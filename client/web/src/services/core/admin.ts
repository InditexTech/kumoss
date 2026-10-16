// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { apiFetch } from "@/services/api";
import type {
  AdminSessionDetail,
  AdminUserEntry,
  OperationType,
  PaginatedSessionSummary,
  PaginatedUsers,
  SessionLockResponse,
  SessionStatus,
  UpdateUserRolesRequest,
  UserMeResponse,
} from "@/types/api";

const BASE = "/api/v1/admin";

function buildQuery(params: Record<string, unknown>): string {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") {
      query.set(key, String(value));
    }
  }
  const qs = query.toString();
  return qs ? `?${qs}` : "";
}

/** GET /api/v1/users/me — The authenticated caller's identity and roles */
export async function getMe(): Promise<UserMeResponse> {
  return apiFetch<UserMeResponse>("/api/v1/users/me");
}

export interface ListAdminSessionsParams {
  page?: number;
  page_size?: number;
  search?: string;
  user_email?: string;
  status?: SessionStatus;
  operation?: OperationType;
}

/** GET /api/v1/admin/sessions/list — Cross-user session list (panel viewer+) */
export async function listAdminSessions(
  params: ListAdminSessionsParams = {},
): Promise<PaginatedSessionSummary> {
  return apiFetch<PaginatedSessionSummary>(
    `${BASE}/sessions/list${buildQuery({ ...params })}`,
  );
}

/**
 * GET /api/v1/admin/sessions?id={id} — Any session's full aggregate
 * (panel viewer+). `includeChatHistory` populates `chat_history`, the
 * same conversation the user sees; `includeHistory` populates `history`,
 * the internal record fed to the LLM, which is debugging material with
 * no contract. Either flag reads fresh (bypasses the finished-session
 * cache).
 */
export async function getAdminSessionDetail(
  sessionId: string,
  opts?: { includeChatHistory?: boolean; includeHistory?: boolean },
): Promise<AdminSessionDetail> {
  const query = new URLSearchParams({ id: sessionId });
  if (opts?.includeChatHistory) query.set("include_chat_history", "true");
  if (opts?.includeHistory) query.set("include_history", "true");
  return apiFetch<AdminSessionDetail>(`${BASE}/sessions?${query}`);
}

/** PATCH /api/v1/admin/sessions/{id}/toggle_lock — Lock/unlock apply (panel editor+) */
export async function setSessionLock(
  sessionId: string,
  locked: boolean,
): Promise<SessionLockResponse> {
  return apiFetch<SessionLockResponse>(
    `${BASE}/sessions/${encodeURIComponent(sessionId)}/toggle_lock`,
    {
      method: "PATCH",
      body: JSON.stringify({ locked }),
    },
  );
}

export interface ListUsersParams {
  page?: number;
  page_size?: number;
  search?: string;
}

/** GET /api/v1/admin/users — Internal users with their roles (panel admin) */
export async function listUsers(
  params: ListUsersParams = {},
): Promise<PaginatedUsers> {
  return apiFetch<PaginatedUsers>(`${BASE}/users${buildQuery({ ...params })}`);
}

/** PUT /api/v1/admin/users/{id}/roles — Full-state role assignment (panel admin) */
export async function setUserRoles(
  userId: number,
  roles: UpdateUserRolesRequest,
): Promise<AdminUserEntry> {
  return apiFetch<AdminUserEntry>(`${BASE}/users/${userId}/roles`, {
    method: "PUT",
    body: JSON.stringify(roles),
  });
}

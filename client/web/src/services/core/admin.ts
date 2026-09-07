// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { apiFetch } from "@/services/api";
import type {
  AdminUserEntry,
  OperationType,
  PaginatedSessionSummary,
  PaginatedUsers,
  SessionDetail,
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

/** GET /api/v1/admin/sessions — Cross-user session list (panel viewer+) */
export async function listAdminSessions(
  params: ListAdminSessionsParams = {},
): Promise<PaginatedSessionSummary> {
  return apiFetch<PaginatedSessionSummary>(
    `${BASE}/sessions${buildQuery({ ...params })}`,
  );
}

/** GET /api/v1/admin/sessions/{id} — Any session's full aggregate (panel viewer+) */
export async function getAdminSessionDetail(
  sessionId: string,
  opts?: { includeHistory?: boolean },
): Promise<SessionDetail> {
  const suffix = opts?.includeHistory ? "?include_history=true" : "";
  return apiFetch<SessionDetail>(
    `${BASE}/sessions/${encodeURIComponent(sessionId)}${suffix}`,
  );
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

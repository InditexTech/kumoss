// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { ApiError, apiFetch } from "@/services/api";
import type {
  OperationType,
  PaginatedSessionSummary,
  SessionDetail,
  SessionStatus,
} from "@/types/api";

const BASE = "/api/v1/sessions";

export interface ListSessionsParams {
  page?: number;
  page_size?: number;
  search?: string;
  status?: SessionStatus;
  operation?: OperationType;
}

/** GET /api/v1/sessions — List a user's sessions with pagination and filters */
export async function listUserSessions(
  userEmail: string,
  params: ListSessionsParams = {},
): Promise<PaginatedSessionSummary> {
  const query = new URLSearchParams();
  query.set("username", userEmail);
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") {
      query.set(key, String(value));
    }
  }
  try {
    return await apiFetch<PaginatedSessionSummary>(
      `${BASE}?${query.toString()}`,
    );
  } catch (err) {
    // A brand-new user has no User row server-side yet, so the list
    // endpoint answers 404 ("User not found"). For a collection, that
    // means "no sessions" — resolve with an empty page so callers render
    // their empty state instead of a failure toast.
    if (err instanceof ApiError && err.status === 404) {
      return {
        items: [],
        total: 0,
        page: params.page ?? 1,
        page_size: params.page_size ?? 0,
        total_pages: 0,
      };
    }
    throw err;
  }
}

/**
 * GET /api/v1/sessions/{sessionId} — Full session aggregate (facts,
 * timeline, rounds). `includeHistory` also populates `history` with the
 * raw conversation turns; it always reads fresh (bypasses the
 * finished-session cache), so leave it off in polling loops.
 */
export async function getSessionDetail(
  sessionId: string,
  opts?: { includeHistory?: boolean },
): Promise<SessionDetail> {
  const suffix = opts?.includeHistory ? "?include_history=true" : "";
  return apiFetch<SessionDetail>(
    `${BASE}/${encodeURIComponent(sessionId)}${suffix}`,
  );
}

/** Whether applying is currently allowed for a session (inverse of is_blocked). */
export async function checkApplyAllowed(sessionId: string): Promise<boolean> {
  const detail = await getSessionDetail(sessionId);
  return !detail.is_blocked;
}

/** Fetch artifact content directly from its (pre-signed) storage URL */
export async function fetchArtifactContent(url: string): Promise<string> {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`Failed to fetch artifact: ${response.status}`);
  }
  return response.text();
}

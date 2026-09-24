// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { apiFetch } from "@/services/api";
import type {
  OperationType,
  PaginatedSessionSummary,
  PlanType,
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

/** GET /api/v1/sessions — The caller's own sessions (always self-scoped) */
export async function listUserSessions(
  params: ListSessionsParams = {},
): Promise<PaginatedSessionSummary> {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") {
      query.set(key, String(value));
    }
  }
  const qs = query.toString();
  return apiFetch<PaginatedSessionSummary>(qs ? `${BASE}?${qs}` : BASE);
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

/**
 * One artifact read: the body, plus what the store said about it.
 *
 * Body and metadata arrive in the same response, so a caller that needs
 * both must not pay for two — hence one return value rather than a
 * second lookup keyed on the same URL.
 */
export interface ArtifactPayload {
  text: string;
  /**
   * The plan flavour, or null for an artifact that carries no `type`
   * metadata — every report and code change, and any plan stored before
   * the backend began writing it.
   */
  planType: PlanType | null;
}

/**
 * The `type` metadata the store returns alongside an object.
 *
 * Two spellings because two vendors: S3 and RustFS answer
 * `x-amz-meta-type`, Azure Blob answers `x-ms-meta-type`. The backend
 * writes one metadata key and each store renames it on the way out.
 *
 * Null when absent or unrecognised — the header is also null when a
 * proxy drops `Access-Control-Expose-Headers`, which is indistinguishable
 * from here and lands on the same neutral fallback either way.
 */
function readPlanType(response: Response): PlanType | null {
  const value =
    response.headers.get("x-amz-meta-type") ??
    response.headers.get("x-ms-meta-type");
  return value === "drift" || value === "plan" ? value : null;
}

/** Fetch an artifact's body and metadata from its (pre-signed) storage URL. */
export async function fetchArtifact(url: string): Promise<ArtifactPayload> {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`Failed to fetch artifact: ${response.status}`);
  }
  return { text: await response.text(), planType: readPlanType(response) };
}

/** Fetch artifact content directly from its (pre-signed) storage URL */
export async function fetchArtifactContent(url: string): Promise<string> {
  return (await fetchArtifact(url)).text;
}

/**
 * A plan's flavour alone, without downloading the plan.
 *
 * The object is the only place it lives: `terraform_plans` holds no
 * flavour column and the read model does not synthesise one, so asking
 * means fetching. Use `fetchArtifact` when the body is wanted too — it
 * returns both from one response. This exists for the case where it is
 * not: labelling timeline rows the user has not opened, where
 * downloading every plan to read one header would be absurd.
 *
 * `Range: bytes=0-0` keeps that to a single byte — the store answers 206
 * with the full metadata header set — and a simple byte range is
 * CORS-safelisted, so it costs no preflight. A HEAD would be cheaper
 * still and is not an option: the URL is presigned for GET and SigV4
 * covers the method, so HEAD returns 403.
 *
 * Returns null rather than throwing when the flavour is unreadable.
 * Callers fall back to the neutral label; a plan row is still openable
 * without knowing its flavour.
 */
export async function fetchPlanType(url: string): Promise<PlanType | null> {
  try {
    const response = await fetch(url, { headers: { Range: "bytes=0-0" } });
    if (!response.ok) return null;
    return readPlanType(response);
  } catch {
    return null;
  }
}

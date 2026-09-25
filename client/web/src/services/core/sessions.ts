// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { apiFetch } from "@/services/api";
import { metadataHeaderPrefix } from "@/services/auth";
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
 * One artifact read: the body, plus what the store said about it. Both
 * arrive in the same response, so a caller needing both must not pay twice.
 */
export interface ArtifactPayload {
  text: string;
  /**
   * The plan flavour, or null for an artifact that carries no `type`
   * metadata — every report and code change, and any plan stored before
   * the backend began writing it.
   */
  planType: PlanType | null;
  /** See `readIsNewFile`. Meaningless for reports and plans. */
  isNewFile: boolean;
}

/**
 * One user-metadata value the store returned alongside an object.
 *
 * The backend writes bare keys (`type`, `new_file`) and each store
 * renames them on the way out — S3 and RustFS to `x-amz-meta-`, Azure
 * Blob to `x-ms-meta-`. Nothing is guessed here: `GET /api/v1/auth/config`
 * tells the SPA which prefix the deployed store uses. `Headers.get` is
 * case-insensitive, so the prefix's casing costs nothing.
 *
 * Null when the key is absent — and also when the store's CORS rules do
 * not expose it: the reference proxy's `Access-Control-Expose-Headers`,
 * or `ExposeHeaders`/`ExposedHeaders` on an S3 bucket or Azure storage
 * account. Indistinguishable from here; see the networking guide.
 */
function readMeta(response: Response, key: string): string | null {
  return response.headers.get(`${metadataHeaderPrefix()}${key}`);
}

/** The plan flavour, or null when absent or unrecognised. */
function readPlanType(response: Response): PlanType | null {
  const value = readMeta(response, "type");
  return value === "drift" || value === "plan" ? value : null;
}

/**
 * Whether a code change's body is a whole file rather than `git diff`
 * output.
 *
 * The backend tags tracked-file diffs `new_file=false` — including newly
 * *added* tracked files, whose diff carries `new file mode` — and
 * untracked files `new_file=true`. So this is the artifact's SHAPE, not
 * its novelty, which is exactly what the viewer needs.
 *
 * Only an explicit `"false"` means diff. An unreadable tag then renders
 * the body verbatim, which is the legible failure: parsing raw content as
 * a diff yields an empty original *and* modified, i.e. a blank editor.
 */
function readIsNewFile(response: Response): boolean {
  return readMeta(response, "new_file") !== "false";
}

/** Fetch an artifact's body and metadata from its (pre-signed) storage URL. */
export async function fetchArtifact(url: string): Promise<ArtifactPayload> {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`Failed to fetch artifact: ${response.status}`);
  }
  return {
    text: await response.text(),
    planType: readPlanType(response),
    isNewFile: readIsNewFile(response),
  };
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
 * returns both from one response. This is for labelling timeline rows
 * nobody has opened yet.
 *
 * `Range: bytes=0-0` keeps that to a single byte, and a simple byte
 * range is CORS-safelisted, so it costs no preflight. RustFS answers 206
 * with the object's metadata headers intact; Azure answers 206 for the
 * same request.
 *
 * A HEAD would be cheaper still and is not portable: an Azure read-SAS
 * serves one, but an S3 or RustFS URL is presigned for GET and SigV4
 * covers the method, so HEAD is 403 there. The ranged GET is the one
 * shape both backends answer.
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

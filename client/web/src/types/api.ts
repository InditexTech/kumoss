// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

// ─── Shared Types ───────────────────────────────────────────

export const TERRAFORM_PROVIDERS = [
  "azure",
  "gcp",
  "aws",
  "oci",
  "kubernetes",
] as const;
export type TerraformProvider = (typeof TERRAFORM_PROVIDERS)[number];
export type HistoryRole = "user" | "assistant" | "validation";

export interface HistoryEntry {
  role: HistoryRole;
  content: string;
}

// Raw conversation turn as returned by the backend's History.serialize()
// (exposed via GET /sessions/{id}?include_history=true).
export interface RawHistoryTurn {
  user: string;
  assistant: string;
}

// Converts backend {user, assistant} turn pairs into the flat
// {role, content} HistoryEntry[] the UI consumes. Tolerates entries
// already in {role, content} form (mock data / future backend).
export function normalizeHistory(
  raw: unknown[] | null | undefined,
): HistoryEntry[] {
  if (!raw) return [];
  const result: HistoryEntry[] = [];
  for (const entry of raw) {
    const obj = entry as Record<string, unknown>;
    if ("role" in obj && "content" in obj) {
      result.push(obj as unknown as HistoryEntry);
    } else if ("user" in obj && "assistant" in obj) {
      result.push({ role: "user", content: String(obj.user) });
      result.push({ role: "assistant", content: String(obj.assistant) });
    }
  }
  return result;
}

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  total_pages?: number;
}

// ─── IaC Operations (/api/v1/iac/*) ─────────────────────────
// URI-driven, session-iterating model: first call provides repo_uri +
// terraform_providers (+ optional scope_id / iac_path); iteration calls
// provide session_id only.

export interface BaseIacRequest {
  repo_uri?: string | null;
  session_id?: string | null;
  scope_id?: string | null;
  terraform_providers?: TerraformProvider | null;
  user_id: string;
  q: string;
  iac_path?: string | null;
}

export type GenerateRequest = BaseIacRequest;

export interface DriftRequest extends BaseIacRequest {
  is_partial?: boolean;
}

/** Apply reuses the session's stored plan; it takes no query or targets. */
export interface ApplyRequest {
  user_id: string;
  session_id: string;
}

export interface IacSessionResponse {
  session_id: string;
}

// ─── Repository / PR (/api/v1/repository/*) ─────────────────

export interface CreatePrRequest {
  session_id: string;
}

export interface MergePrRequest {
  session_id: string;
}

/** Response of PUT /repository/pr. */
export interface PullRequestDTO {
  id: number;
  url: string;
  status: string;
}

// ─── Authorization (/api/v1/authorize) ──────────────────────

export interface AuthorizeRequest {
  cloud: string;
  project_name: string;
  environment: string;
  user_email: string;
}

export interface AuthorizeResponse {
  result: boolean;
  message: string;
  portalUrl?: string;
}

// ─── Sessions (/api/v1/sessions/*) ─────────────────────────

export type OperationType = "generate" | "drift" | "import";

export type SessionStatus =
  | "started"
  | "filtering"
  | "generating"
  | "validating"
  | "apply"
  | "report"
  | "completed"
  | "uncompleted"
  | "failed";

/**
 * Statuses a finished round rests on: `completed` (succeeded), `uncompleted`
 * (filter-rejected — no `completed` follows) and `failed` (exception).
 */
export const TERMINAL_STATUSES: SessionStatus[] = [
  "completed",
  "uncompleted",
  "failed",
];

export interface StatusEntry {
  status: SessionStatus;
  message: string | null;
  created_at: string;
}

/**
 * A client-fetchable artifact produced during a round. `id` is the pk of
 * the typed row (report / plan / code change), not the storage row.
 */
export interface ArtifactRef {
  id: number;
  url: string;
  content_type: string | null;
  file_size_bytes: number | null;
  created_at: string;
}

export interface TerraformPlanRef extends ArtifactRef {
  targets: string[];
}

export interface CodeChangeRef extends ArtifactRef {
  file_name: string;
}

/**
 * `provider` is the enum token (e.g. "GITHUB"), not the host name.
 * `number` is the pull request's id at the provider.
 */
export interface PullRequestRef {
  provider: string;
  url: string;
  number: number;
}

/** One generation iteration with its statuses and artifacts. */
export interface RoundDetail {
  id: number;
  number: number;
  statuses: StatusEntry[];
  report: ArtifactRef | null;
  plan: TerraformPlanRef | null;
  code_changes: CodeChangeRef[];
  pull_requests: PullRequestRef[];
  created_at: string;
}

export interface WorkspaceRef {
  uri: string;
  branch: string;
  root_path: string | null;
}

export interface SessionSummary {
  uuid: string;
  username: string | null;
  operation: OperationType;
  provider: TerraformProvider;
  first_query: string | null;
  workspace_uri: string;
  current_status: SessionStatus;
  in_flight: boolean;
  is_blocked: boolean;
  created_at: string;
  updated_at: string;
}

/**
 * Full session aggregate. `statuses` holds the session's full status
 * timeline; round-level statuses also live inside their round. Pull
 * requests live inside their round. `history` is populated only when
 * requested via `?include_history=true`.
 */
export interface SessionDetail extends SessionSummary {
  workspace: WorkspaceRef;
  scope_id: string;
  statuses: StatusEntry[];
  rounds: RoundDetail[];
  history?: RawHistoryTurn[] | null;
}

export type PaginatedSessionSummary = PaginatedResponse<SessionSummary>;

// ─── Events / SSE (/api/v1/events/subscribe/{id}) ───────────
// The stream re-emits the session's *last* status every ~5s (duplicates
// are normal) and closes server-side after COMPLETED, UNCOMPLETED, or
// FAILED. A rejected round rests on UNCOMPLETED (no COMPLETED follows);
// the client still closes on first terminal receipt.

/** SSE carries the UPPERCASE enum NAME; REST uses the lowercase value. */
export type SseStatus = Uppercase<SessionStatus>;

export interface SessionEventData {
  status_msg: SseStatus;
  detail: {
    message: string;
  };
}

// ─── Users (/api/v1/users/*) ────────────────────────────────
// DISABLED: GET /users/me has no backend route. Kept for when the
// admin-role enrichment returns server-side.

// export interface UserMeResponse {
//   id: string;
//   email?: string | null;
//   name?: string | null;
//   roles: string[];
// }

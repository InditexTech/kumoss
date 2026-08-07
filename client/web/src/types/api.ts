// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import type { TerraformReport } from "./index";

// ─── Shared Types ───────────────────────────────────────────

export const TERRAFORM_PROVIDERS = [
  "azure",
  "gcp",
  "aws",
  "oci",
  "kubernetes",
  "common",
] as const;
export type TerraformProvider = (typeof TERRAFORM_PROVIDERS)[number];
export type HistoryRole = "user" | "assistant" | "validation";

export interface HistoryEntry {
  role: HistoryRole;
  content: string;
}

// TEMPORAL FIX: Raw conversation turn as returned by the backend's
// History.serialize(). Remove this and normalizeHistory() once the
// backend returns HistoryEntry[] directly.
export interface RawHistoryTurn {
  user: string;
  assistant: string;
}

// TEMPORAL FIX: Converts backend {user, assistant} turn pairs into
// the flat {role, content} HistoryEntry[] the UI consumes. Tolerates
// entries already in {role, content} form (mock data / future backend).
export function normalizeHistory(
  raw: unknown[] | undefined,
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

export interface ApplyRequest extends BaseIacRequest {
  terraform_targets?: string[];
}

export interface IacSessionResponse {
  session_id: string;
}

// ─── Events / SSE (/api/v1/events/*) ────────────────────────

export interface SessionPayloadResponse {
  id: string;
  response: string;
  main_history: { user: string; assistant: string };
  full_history: HistoryEntry[];
  environment: string;
  cloud: string;
  project: string;
  validation: boolean;
  branch_name: string;
  terraform_plan: string | null;
  terraform_targets: string[] | null;
  terraform_report: TerraformReport | null;
  pipeline_url: string | null;
  apply_allowed: boolean;
}

// ─── Repository / PR (/api/v1/repository/*) ─────────────────

export interface CreatePrRequest {
  session_id: string;
  q: string;
}

export interface RepositoryPrStatusResponse {
  id: number;
  status: string;
}

export interface ApprovePrRequest {
  id: number;
}

// ─── Authorization (/api/v1/authorize/) ─────────────────────

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
  | "report"
  | "completed"
  | "uncompleted"
  | "failed";

/** Session-level statuses; anything else belongs to a round. */
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

/** One generation iteration with its statuses and artifacts. */
export interface RoundDetail {
  id: number;
  number: number;
  statuses: StatusEntry[];
  report: ArtifactRef | null;
  plan: TerraformPlanRef | null;
  code_changes: CodeChangeRef[];
  created_at: string;
}

export interface WorkspaceRef {
  uri: string;
  branch: string;
  root_path: string | null;
}

/** `provider` is the enum token (e.g. "GITHUB"), not the host name. */
export interface PullRequestRef {
  provider: string;
  url: string;
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
 * Full session aggregate. `statuses` holds session-level entries only;
 * round-level statuses live inside their round. `history` is populated
 * on admin surfaces only and arrives as raw backend turns.
 */
export interface SessionDetail extends SessionSummary {
  workspace: WorkspaceRef;
  scope_id: string;
  pull_request: PullRequestRef | null;
  statuses: StatusEntry[];
  rounds: RoundDetail[];
  history?: unknown[] | null;
}

export type PaginatedSessionSummary = PaginatedResponse<SessionSummary>;

// ─── Users (/api/v1/users/*) ────────────────────────────────

export interface UserMeResponse {
  id: string;
  email?: string | null;
  name?: string | null;
  roles: string[];
}

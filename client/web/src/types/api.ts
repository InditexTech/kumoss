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

export interface UserSessionInfo {
  session_id: string;
  user_id: string;
  repo_uri: string;
  cloud_provider: string;
  environment: string;
  branch_name: string;
  status: string;
  in_flight: boolean;
  created_at: string;
  updated_at: string;
  initial_query?: string | null;
  operation_type?: string | null;
  apply_allowed: boolean;
  iac_path?: string | null;
}

export type UserSessionsListResponse = PaginatedResponse<UserSessionInfo>;

// ─── Sessions & Admin Shared (/api/v1/sessions/* & /api/v1/admin/*) ─

export interface ApplyAllowedResponse {
  session_id: string;
  apply_allowed: boolean;
}

// ─── Users (/api/v1/users/*) ────────────────────────────────

export interface UserMeResponse {
  id: string;
  email?: string | null;
  name?: string | null;
  roles: string[];
}

// ─── Admin (/api/v1/admin/*) ────────────────────────────────

export interface AdminSessionInfo {
  // Persisted columns
  session_id: string;
  user_id: string;
  repo_uri: string;
  cloud_provider: string;
  environment: string;
  branch_name: string;
  status: string;
  in_flight: boolean;
  created_at: string;
  updated_at: string;
  // Observability columns
  operation_type: string;
  failure_reason: string | null;
  pull_request_url: string | null;
  apply_allowed: boolean;
  iac_path: string | null;
  // Computed fields
  is_active: boolean;
  current_status: string;
  final_status: string | null;
  initial_query: string | null;
  repository_id: string;
  completed_at: string | null;
  duration_seconds: number | null;
}

export type SessionsListResponse = PaginatedResponse<AdminSessionInfo>;

export interface AdminOperationItem {
  id: number;
  operation_number: number;
  operation_type: string;
  operation_phase: string | null;
  operation_subtype: string | null;
  success: boolean | null;
  duration_seconds: number | null;
  error_message: string | null;
  artifact_type: string | null;
  blob_url: string | null;
  file_size_bytes: number | null;
  content_type: string | null;
  terraform_targets: string[] | null;
  pipeline_run_id: string | null;
  created_at: string;
}

export interface AdminSessionDetailResponse {
  session: AdminSessionInfo;
  operations: AdminOperationItem[];
  full_history?: HistoryEntry[];
}

// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import type { OperationRole, PanelRole } from "./api";

/** The signed-in user as resolved by GET /api/v1/users/me. */
export interface UserInfo {
  id: number;
  email: string | null;
  displayName: string | null;
  operationRole: OperationRole;
  panelRole: PanelRole | null;
}

// ─── Terraform Report ───────────────────────────────────────

export interface TerraformChange {
  action: string;
  name?: string;
  user_friendly_header?: string;
  notes?: string;
  summary?: string;
  details?: string;
  [key: string]: unknown;
}

export interface BulletPoint {
  title: string;
  description: string;
}

export interface CostBreakdownItem {
  resource_type: string;
  pricing_model: "fixed" | "usage_based" | "free";
  fixed_monthly_cost: number;
  notes: string;
}

// Import reports: one entry per resource the round tried to import, plus
// the unmanaged resources the import exception list withheld (skipped on
// purpose, never attempted — not failures).
export interface ImportedResource {
  resource_address: string;
  resource_id: string;
  status: "imported" | "failed";
  details: string;
  error_message?: string | null;
}

export interface ExcludedResource {
  resource_id: string;
  details: string;
}

export interface DriftChange {
  attribute_modified: string;
  change_description: string;
  reason: string;
  details?: string[];
}

export interface DriftResource {
  resource_address: string;
  file_path: string;
  changes?: DriftChange[];
}

// Both blocks are drift the round left in place, and both are absent
// from a report whose round left nothing behind. `resource_address` is
// best-effort: a failed drift read names no resource, and an exception
// rule can cover a type or a naming pattern rather than one address.
export interface DriftUnreconciled {
  resource_address?: string;
  reason: string;
  details?: string[];
}

export interface DriftException {
  resource_address?: string;
  change: string;
  rule: string;
}

export interface ApplyResourceChange {
  resource_type: string;
  resource_name: string;
  action: string;
  status: string;
  details: string;
  error_message?: string;
}

export interface PlanSummary {
  create: number;
  update: number;
  delete: number;
  recreate: number;
}

export interface ApplySummary {
  total_resources?: number;
  created?: number;
  updated?: number;
  destroyed?: number;
  failed?: number;
}

export interface ImportSummary {
  selected: number;
  imported: number;
  failed: number;
}

export interface TerraformReport {
  status?: string;
  summary?: PlanSummary | ApplySummary | ImportSummary | string;
  potential_impact?: {
    banner?: { level: string; title: string; description: string };
    summary?: string;
    bullet_points?: BulletPoint[];
  };
  estimated_costs?: {
    currency?: string;
    total_fixed_monthly_cost?: number;
    introduction_paragraph?: string;
    breakdown?: CostBreakdownItem[];
  };
  detailed_changes?: TerraformChange[];
  remediated_resources?: DriftResource[];
  unreconciled_drift?: DriftUnreconciled[];
  whitelisted_exceptions?: DriftException[];
  execution_summary?: string;
  imported_resources?: ImportedResource[];
  excluded_resources?: ExcludedResource[];
  state_alignment?: string;
  recommendations?: string[];
  resource_changes?: ApplyResourceChange[];
  [key: string]: unknown;
}

// ─── Events ─────────────────────────────────────────────────

export interface EventMessage {
  status_msg?: string;
  detail?: { validation_id?: string; message?: string };
  [key: string]: unknown;
}

// ─── API ────────────────────────────────────────────────────

export interface ApiOptions extends RequestInit {
  headers?: Record<string, string>;
  timeout?: number;
}

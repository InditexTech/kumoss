// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

export interface UserInfo {
  username: string;
  name: string;
  homeAccountId: string;
  environment: string;
  tenantId: string;
  localAccountId: string;
  roles: string[];
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

export interface ImportResourceDetail {
  category: string;
  resource_identifier: string;
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

export interface TerraformReport {
  status?: string;
  summary?: PlanSummary | ApplySummary | string;
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
  execution_summary?: string;
  resource_details?: ImportResourceDetail[];
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

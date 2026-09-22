// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import type { TerraformChange, TerraformReport } from "@/types";

export type FilterId = "all" | "create" | "update" | "delete" | "recreate";
export type DetailView = "impact" | "costs" | "change" | null;

export const FILTERS: { id: FilterId; label: string }[] = [
  { id: "all", label: "All" },
  { id: "create", label: "Created" },
  { id: "update", label: "Updated" },
  { id: "delete", label: "Deleted" },
  { id: "recreate", label: "Recreated" },
];

export function getLevelLabel(level: string): string {
  const labels: Record<string, string> = {
    high: "High Impact",
    medium: "Medium Impact",
    low: "Low Impact",
  };
  return labels[level] || level;
}

export function formatResourceName(change: TerraformChange): string {
  return change.user_friendly_header || change.name || "Unknown Resource";
}

export function hasStructuredCosts(
  costs: TerraformReport["estimated_costs"],
): costs is NonNullable<TerraformReport["estimated_costs"]> {
  return typeof costs?.total_fixed_monthly_cost === "number";
}

// Drift rounds report "Succeeded" / "Partial" / "Failed", apply rounds
// "success" / "failed" — the badge knows "succeeded".
export function reportStatusVariant(status: unknown): string | null {
  if (typeof status !== "string" || status.trim() === "") return null;
  const key = status.trim().toLowerCase();
  return key === "success" ? "succeeded" : key;
}

const HOURS_PER_MONTH = 730;

export const PRICING_MODEL_LABELS: Record<string, string> = {
  usage_based: "Usage-based",
  free: "Free",
};

export function formatMonthlyCost(
  amount: number,
  currency: string = "USD",
): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(amount);
}

export function summaryCosts(
  monthly: number,
  currency: string = "USD",
): Array<{ amount: string; period: string }> {
  const hourly = monthly / HOURS_PER_MONTH;
  const digits = Math.abs(hourly) < 0.01 ? 4 : 3;
  const hourlyFmt = new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(hourly);
  return [
    { amount: formatMonthlyCost(monthly, currency), period: "MONTH" },
    { amount: hourlyFmt, period: "HOUR" },
  ];
}

export function extractCodeFiles(input: string): Record<string, string> {
  if (!input) return {};
  const fileRegex = /<([\w.-]+)>([\s\S]*?)<\/\1>/g;
  const files: Record<string, string> = {};
  let match;
  while ((match = fileRegex.exec(input)) !== null) {
    if (match[1] !== "Terraform_Plan") {
      files[match[1]] = match[2].trim() + "\n\n";
    }
  }
  return files;
}

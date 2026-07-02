import type { TerraformChange } from "@/types";

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

export function parseCostValue(cost: string): {
  value: string;
  unit: string | null;
} {
  const match = cost.match(/^(.+?)\s+per\s+(.+)$/i);
  if (match)
    return {
      value: match[1].trim(),
      unit: `PER ${match[2].trim().toUpperCase()}`,
    };
  return { value: cost, unit: null };
}

export function parseSummaryCosts(
  summary: string,
): Array<{ amount: string; period: string }> | null {
  const results: Array<{ amount: string; period: string }> = [];

  const re =
    /([~≈]?-?\$[\d,.]+|[~≈]?-?[\d,.]+\s?[€£¥])\s*(?:per\s+|\/)(month|hour|year|day|week)/gi;
  let m;
  while ((m = re.exec(summary)) !== null) {
    results.push({ amount: m[1].trim(), period: m[2].toUpperCase() });
  }

  if (results.length === 0) {
    const periodWord = summary.match(
      /\b(month(?:ly)?|hour(?:ly)?|year(?:ly)?)\b/i,
    );
    const value = summary.match(/([~≈]?-?\$[\d,.]+|[~≈]?-?[\d,.]+\s?[€£¥])/);
    if (periodWord && value) {
      const period = periodWord[1].replace(/ly$/i, "").toUpperCase();
      results.push({ amount: value[1].trim(), period });
    }
  }

  if (results.length === 0) return null;

  if (
    results.some((r) => r.period === "MONTH") &&
    !results.some((r) => r.period === "HOUR")
  ) {
    const monthly = results.find((r) => r.period === "MONTH")!;
    const num = monthly.amount.match(/-?[\d,.]+/);
    if (num) {
      const hourly = parseFloat(num[0].replace(",", ".")) / 730;
      const fmt = hourly < 0.01 ? hourly.toFixed(4) : hourly.toFixed(3);
      const pre = monthly.amount.includes("$") ? "$" : "";
      const suf = monthly.amount.includes("€") ? "€" : "";
      results.push({ amount: `${pre}${fmt}${suf}`, period: "HOUR" });
    }
  }

  return results;
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

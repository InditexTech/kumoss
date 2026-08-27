// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React, { useEffect } from "react";
import { useSession } from "@/contexts/SessionContext";
import { renderWithProviders } from "@/test/render";
import ResultPanel from "./ResultPanel";
import type { TerraformReport } from "@/types";

vi.mock("@/components/ui/CodeBlock/CodeBlock", () => ({
  default: ({ code, files }: { code?: string; files?: Record<string, string> }) => (
    <pre data-testid="code-block">{code ?? JSON.stringify(Object.keys(files ?? {}))}</pre>
  ),
}));

function SessionInjector({ patch, children }: { patch: Record<string, unknown>; children: React.ReactNode }) {
  const { updateSession } = useSession();
  useEffect(() => { updateSession(patch); }, []);
  return <>{children}</>;
}

const mockReport: TerraformReport = {
  execution_summary: "Plan: 2 to add, 1 to change",
  potential_impact: {
    banner: { level: "medium", title: "Medium Impact", description: "Some resources will change" },
    summary: "Impact summary here",
    bullet_points: [{ title: "DB changes", description: "Database will be modified" }],
  },
  estimated_costs: {
    banner: { summary: "$12.50/mo increase" },
    introduction_paragraph: "Cost impact",
    breakdown: [{ resource_type: "azurerm_vm", details: { estimated_cost: "$10.00", additional_details: "Standard B2s" } }],
  },
  detailed_changes: [
    { name: "azurerm_resource_group.main", action: "create", notes: "New RG", summary: "Create RG", details: "resource group main" },
    { name: "azurerm_vm.web", action: "update", notes: "Resize", summary: "Update VM", details: "vm resize" },
  ],
};

function renderResultPanel(
  props?: Partial<React.ComponentProps<typeof ResultPanel>>,
  sessionPatch?: Record<string, unknown>,
) {
  const ui = sessionPatch
    ? <SessionInjector patch={sessionPatch}><ResultPanel {...props} /></SessionInjector>
    : <ResultPanel {...props} />;

  return renderWithProviders(ui, { routerProps: { initialEntries: ["/home/results/test-id"] } });
}

describe("ResultPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders report tab by default with report data", () => {
    renderResultPanel(undefined, { terraform_report: mockReport });
    expect(screen.getByText("Execution Summary")).toBeInTheDocument();
    expect(screen.getByText("Plan: 2 to add, 1 to change")).toBeInTheDocument();
  });

  it("renders empty state when no report", () => {
    renderResultPanel();
    expect(screen.getByText("No report data available.")).toBeInTheDocument();
  });

  it("shows potential impact card", () => {
    renderResultPanel(undefined, { terraform_report: mockReport });
    expect(screen.getByText("Medium Impact")).toBeInTheDocument();
  });

  it("shows estimated costs card", () => {
    renderResultPanel(undefined, { terraform_report: mockReport });
    expect(screen.getByText("$12.50/mo increase")).toBeInTheDocument();
  });

  it("switches to plan tab", async () => {
    const user = userEvent.setup();
    renderResultPanel(undefined, { terraform_report: mockReport, code: "<Terraform_Plan>resource {}</Terraform_Plan>" });

    await user.click(screen.getByRole("button", { name: "Plan" }));
    expect(screen.getByTestId("code-block")).toBeInTheDocument();
  });

  it("shows empty plan state when no code", async () => {
    const user = userEvent.setup();
    renderResultPanel(undefined, { terraform_report: mockReport });

    await user.click(screen.getByRole("button", { name: "Plan" }));
    expect(screen.getByText("No terraform plan available to display.")).toBeInTheDocument();
  });

  it("code tab hidden in import mode", () => {
    // For import mode we'd need to set ModeContext, but by default it's "generate"
    renderResultPanel(undefined, { terraform_report: mockReport });
    expect(screen.getByRole("button", { name: "Code" })).toBeInTheDocument();
  });

  it("calls onTabChange when tab is controlled", async () => {
    const user = userEvent.setup();
    const onTabChange = vi.fn();
    renderResultPanel({ tab: "report", onTabChange }, { terraform_report: mockReport });

    await user.click(screen.getByRole("button", { name: "Plan" }));
    expect(onTabChange).toHaveBeenCalledWith("plan");
  });

  it("opens impact detail when impact card clicked", async () => {
    const user = userEvent.setup();
    renderResultPanel(undefined, { terraform_report: mockReport });

    await user.click(screen.getByText("Medium Impact"));
    // Bullet points only render in ImpactDetail, not PotentialImpactCard
    expect(screen.getByText("DB changes")).toBeInTheDocument();
    expect(screen.getByText("Database will be modified")).toBeInTheDocument();
  });

  it("closes detail on Escape key", async () => {
    const user = userEvent.setup();
    renderResultPanel(undefined, { terraform_report: mockReport });

    await user.click(screen.getByText("Medium Impact"));
    expect(screen.getByText("DB changes")).toBeInTheDocument();

    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByText("DB changes")).not.toBeInTheDocument();
  });

  it("renders changes in the changes table", () => {
    renderResultPanel(undefined, { terraform_report: mockReport });
    expect(screen.getByText("azurerm_resource_group.main")).toBeInTheDocument();
    expect(screen.getByText("azurerm_vm.web")).toBeInTheDocument();
  });

  describe("drift reports", () => {
    const driftReport: TerraformReport = {
      status: "Succeeded",
      summary: "All drift remediated: 2 resources deleted.",
      remediated_resources: [
        {
          resource_address: "azurerm_key_vault.app",
          file_path: "key_vault_app.tf",
          changes: [
            {
              attribute_modified: "resource",
              change_description: "Deleted the Key Vault resource.",
              reason: "Marked for deletion during drift remediation.",
              details: ["Removed: azurerm_key_vault.app"],
            },
          ],
        },
        {
          resource_address: "azurerm_redis_cache.main",
          file_path: "redis_cache.tf",
          changes: [
            {
              attribute_modified: "resource",
              change_description: "Deleted the Redis Cache resource.",
              reason: "Drifted resource.",
            },
          ],
        },
      ],
    };

    it("renders the drift summary and remediated resources", () => {
      renderResultPanel(undefined, { terraform_report: driftReport });

      expect(screen.getByText("Drift Summary")).toBeInTheDocument();
      expect(
        screen.getByText("All drift remediated: 2 resources deleted."),
      ).toBeInTheDocument();
      expect(screen.getByText("Remediated Resources")).toBeInTheDocument();
      expect(screen.getByText("azurerm_key_vault.app")).toBeInTheDocument();
      expect(screen.getByText("azurerm_redis_cache.main")).toBeInTheDocument();
      // The plan report's action filters make no sense for drift.
      expect(screen.queryByText("Recreated")).not.toBeInTheDocument();
    });

    it("opens the resource detail when a row is clicked", async () => {
      const user = userEvent.setup();
      renderResultPanel(undefined, { terraform_report: driftReport });

      await user.click(screen.getByText("azurerm_key_vault.app"));
      expect(
        screen.getByText("Marked for deletion during drift remediation."),
      ).toBeInTheDocument();
      expect(
        screen.getByText("Removed: azurerm_key_vault.app"),
      ).toBeInTheDocument();
    });
  });
});

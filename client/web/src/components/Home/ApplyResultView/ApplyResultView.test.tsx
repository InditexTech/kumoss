// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React, { useEffect } from "react";
import { useSession } from "@/contexts/SessionContext";
import { renderWithProviders } from "@/test/render";
import type { ApplyResultsData } from "@/types/ui";
import ApplyResultView from "./ApplyResultView";

function SessionInjector({ patch, children }: { patch: Record<string, unknown>; children: React.ReactNode }) {
  const { updateSession } = useSession();
  useEffect(() => { updateSession(patch); }, []);
  return <>{children}</>;
}

function renderApply(applyResults?: ApplyResultsData) {
  const ui = applyResults
    ? <SessionInjector patch={{ applyResults }}><ApplyResultView /></SessionInjector>
    : <ApplyResultView />;
  return renderWithProviders(ui);
}

const mockChanges = [
  { resource_type: "azurerm_resource_group", resource_name: "rg-main", action: "created", status: "success", details: "Created successfully" },
  { resource_type: "azurerm_virtual_network", resource_name: "vnet-prod", action: "updated", status: "success", details: "" },
  { resource_type: "azurerm_storage_account", resource_name: "stdelete", action: "destroyed", status: "success", details: "" },
  { resource_type: "azurerm_vm", resource_name: "vm-broken", action: "created", status: "failed", details: "", error_message: "quota exceeded" },
];

const mockResults: ApplyResultsData = {
  sessionId: "test-session",
  status: "Partial",
  message: "Apply partially completed",
  errorMessage: "",
  timestamp: "2026-06-25T12:00:00Z",
  applyReport: {
    status: "Partial",
    execution_summary: "3 of 4 resources applied successfully",
    resource_changes: mockChanges,
    recommendations: ["Review quota limits", "Check network rules"],
    summary: { total_resources: 4, created: 1, updated: 1, destroyed: 1, failed: 1 },
  },
};

describe("ApplyResultView", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders empty state when no applyResults", () => {
    renderApply();
    expect(screen.getByText("No apply results available.")).toBeInTheDocument();
  });

  it("renders execution summary with status", () => {
    renderApply(mockResults);
    expect(screen.getByText(/Execution Summary/)).toBeInTheDocument();
    expect(screen.getByText(/Partially Applied/)).toBeInTheDocument();
    expect(screen.getByText("3 of 4 resources applied successfully")).toBeInTheDocument();
  });

  it("renders resource names in the table", () => {
    renderApply(mockResults);
    expect(screen.getByText("rg-main")).toBeInTheDocument();
    expect(screen.getByText("vnet-prod")).toBeInTheDocument();
    expect(screen.getByText("stdelete")).toBeInTheDocument();
    expect(screen.getByText("vm-broken")).toBeInTheDocument();
  });

  it("renders recommendations when present", () => {
    renderApply(mockResults);
    expect(screen.getByText("Recommendations")).toBeInTheDocument();
    expect(screen.getByText("Review quota limits")).toBeInTheDocument();
    expect(screen.getByText("Check network rules")).toBeInTheDocument();
  });

  it("renders success status correctly", () => {
    const successResults: ApplyResultsData = {
      ...mockResults,
      status: "Success",
      applyReport: { ...mockResults.applyReport!, status: "Success" },
    };
    renderApply(successResults);
    expect(screen.getByText(/Succeeded/)).toBeInTheDocument();
  });

  it("filters by action when filter button clicked", async () => {
    const user = userEvent.setup();
    renderApply(mockResults);

    const createdBtn = screen.getByRole("button", { name: /Created/ });
    await user.click(createdBtn);

    expect(screen.getByText("rg-main")).toBeInTheDocument();
    expect(screen.queryByText("vnet-prod")).not.toBeInTheDocument();
    expect(screen.queryByText("stdelete")).not.toBeInTheDocument();
  });

  it("filters by failed status", async () => {
    const user = userEvent.setup();
    renderApply(mockResults);

    const failedBtn = screen.getByRole("button", { name: /Failed/ });
    await user.click(failedBtn);

    expect(screen.getByText("vm-broken")).toBeInTheDocument();
    expect(screen.queryByText("rg-main")).not.toBeInTheDocument();
  });

  it("opens side panel when clicking a row with details", async () => {
    const user = userEvent.setup();
    renderApply(mockResults);

    await user.click(screen.getByText("rg-main"));
    expect(screen.getByText("Created successfully")).toBeInTheDocument();
  });

  it("shows error message in detail panel for failed resources", async () => {
    const user = userEvent.setup();
    renderApply(mockResults);

    await user.click(screen.getByText("vm-broken"));
    expect(screen.getByText("quota exceeded")).toBeInTheDocument();
  });
});

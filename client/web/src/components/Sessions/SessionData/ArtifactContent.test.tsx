// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect } from "vitest";
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "@/mocks/server";
import { makeRound } from "@/mocks/state";
import { renderWithProviders } from "@/test/render";
import type {
  ComplianceCheckRef,
  OperationType,
  ReportRef,
} from "@/types/api";
import ArtifactContent from "./ArtifactContent";

const STORAGE = "https://storage.test";

const applyRef: ReportRef = {
  id: 1,
  url: `${STORAGE}/report.json`,
  content_type: "application/json",
  file_size_bytes: 10,
  created_at: "2026-01-01T00:00:00Z",
  type: "apply",
};

const applyReport = {
  status: "Partial",
  summary: { total_resources: 2, created: 1, updated: 0, destroyed: 0, failed: 1 },
  execution_summary: "1 of 2 resources applied successfully",
  resource_changes: [
    {
      resource_type: "azurerm_resource_group",
      resource_name: "rg-main",
      action: "created",
      status: "success",
      details: "Created successfully",
    },
    {
      resource_type: "azurerm_vm",
      resource_name: "vm-broken",
      action: "created",
      status: "failed",
      details: "",
      error_message: "quota exceeded",
    },
  ],
  recommendations: ["Review quota limits"],
};

function renderReport(
  payload: Record<string, unknown>,
  ref: ReportRef = applyRef,
  operation: OperationType = "generate",
) {
  server.use(
    http.get(`${STORAGE}/report.json`, () => HttpResponse.json(payload)),
  );
  renderWithProviders(
    <ArtifactContent
      kind="report"
      artifact={ref}
      round={makeRound({ report: ref })}
      operation={operation}
    />,
  );
}

describe("ArtifactContent apply reports", () => {
  it("renders the apply report's summary, status and resource changes", async () => {
    renderReport(applyReport);

    expect(
      await screen.findByText("1 of 2 resources applied successfully"),
    ).toBeInTheDocument();
    expect(screen.getByText("PARTIAL")).toBeInTheDocument();
    expect(screen.getByText("rg-main")).toBeInTheDocument();
    expect(screen.getByText("vm-broken")).toBeInTheDocument();
    expect(screen.getByText("Review quota limits")).toBeInTheDocument();
  });

  it("opens the resource detail overlay from a row", async () => {
    const user = userEvent.setup();
    renderReport(applyReport);

    await user.click(await screen.findByText("vm-broken"));
    expect(screen.getByText("quota exceeded")).toBeInTheDocument();
  });

  it("selects the renderer from the declared type, not the payload shape", async () => {
    renderReport({
      summary: "drift text",
      remediated_resources: [
        {
          resource_address: "azurerm_vm.legacy",
          file_path: "main.tf",
          changes: [],
        },
      ],
    });

    // type: "apply" wins: apply filter tabs render (even with no changes)
    // under the apply header, and the drift resource list does not.
    expect(await screen.findByText("Destroyed")).toBeInTheDocument();
    expect(screen.getByText("Execution Summary")).toBeInTheDocument();
    expect(screen.queryByText("azurerm_vm.legacy")).not.toBeInTheDocument();
  });

  it("renders the drift report for a ref typed drift", async () => {
    renderReport(
      {
        summary: "one resource remediated",
        remediated_resources: [
          {
            resource_address: "azurerm_vm.drifted",
            file_path: "main.tf",
            changes: [],
          },
        ],
      },
      { ...applyRef, type: "drift" },
      "drift",
    );

    expect(await screen.findByText("Drift Summary")).toBeInTheDocument();
    expect(screen.getByText("azurerm_vm.drifted")).toBeInTheDocument();
    expect(screen.queryByText("Drift Not Reconciled")).not.toBeInTheDocument();
    expect(
      screen.queryByText("Left Alone by Exception Rules"),
    ).not.toBeInTheDocument();
  });

  it("reports the drift a round left in place, unreconciled or whitelisted", async () => {
    renderReport(
      {
        summary: "one resource remediated, one left alone",
        status: "Partial",
        remediated_resources: [],
        unreconciled_drift: [
          { reason: "The plan could not be read." },
        ],
        whitelisted_exceptions: [
          {
            resource_address: "azurerm_storage_account.shared",
            change: "The resource is missing from the code.",
            rule: "The platform team manages it outside Terraform.",
          },
        ],
      },
      { ...applyRef, type: "drift" },
      "drift",
    );

    expect(await screen.findByText("Drift Not Reconciled")).toBeInTheDocument();
    expect(screen.getByText("PARTIAL")).toBeInTheDocument();
    expect(screen.getByText("The plan could not be read.")).toBeInTheDocument();
    expect(screen.getByText("Left Alone by Exception Rules")).toBeInTheDocument();
    expect(
      screen.getByText("azurerm_storage_account.shared"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("The platform team manages it outside Terraform."),
    ).toBeInTheDocument();
  });
});

describe("ArtifactContent import reports", () => {
  const importRef: ReportRef = { ...applyRef, type: "import" };
  const importReport = {
    status: "Succeeded",
    summary: { selected: 1, imported: 1, failed: 0 },
    execution_summary: "The storage account is now managed by Terraform.",
    imported_resources: [
      {
        resource_address: "azurerm_storage_account.sta_001",
        resource_id: "/subscriptions/sub-123/storageAccounts/sta001",
        status: "imported",
        details: "Storage account sta001 in rg.",
        error_message: null,
      },
    ],
    excluded_resources: [
      {
        resource_id: "/subscriptions/sub-123/storageAccounts/shared",
        details: "Shared platform storage account.",
      },
    ],
    state_alignment: "No changes: the configuration matches the imported state.",
    recommendations: ["Review the generated block."],
  };

  it("renders the import report for a ref typed import", async () => {
    renderReport(importReport, importRef, "import");

    expect(await screen.findByText("Import Summary")).toBeInTheDocument();
    expect(screen.getByText("SUCCEEDED")).toBeInTheDocument();
    expect(
      screen.getByText("The storage account is now managed by Terraform."),
    ).toBeInTheDocument();
    expect(screen.getByText("azurerm_storage_account.sta_001")).toBeInTheDocument();
    expect(screen.getByText("Excluded by Import Exceptions")).toBeInTheDocument();
    expect(
      screen.getByText("No changes: the configuration matches the imported state."),
    ).toBeInTheDocument();
    expect(screen.getByText("Review the generated block.")).toBeInTheDocument();
  });

  it("opens the imported resource detail from a row", async () => {
    renderReport(importReport, importRef, "import");

    await userEvent.click(
      await screen.findByText("azurerm_storage_account.sta_001"),
    );
    expect(screen.getByText("Storage account sta001 in rg.")).toBeInTheDocument();
  });
});

describe("ArtifactContent compliance checks", () => {
  const complianceRef: ComplianceCheckRef = {
    id: 2,
    url: `${STORAGE}/compliance.json`,
    content_type: "application/json",
    file_size_bytes: 10,
    created_at: "2026-01-01T00:00:00Z",
    passed: false,
  };

  function renderCompliance(payload: Record<string, unknown>) {
    server.use(
      http.get(`${STORAGE}/compliance.json`, () => HttpResponse.json(payload)),
    );
    renderWithProviders(
      <ArtifactContent
        kind="compliance"
        artifact={complianceRef}
        round={makeRound({ compliance: complianceRef })}
        operation="generate"
      />,
    );
  }

  it("renders the verdict, summary and violations", async () => {
    renderCompliance({
      passed: false,
      summary: "Public ingress is not allowed",
      checked_rules: ["NET-001", "TAG-002"],
      violations: [
        {
          rule_id: "TAG-002",
          severity: "warning",
          message: "Missing owner tag",
        },
        {
          rule_id: "NET-001",
          severity: "critical",
          resource: "azurerm_network_security_rule.ssh",
          message: "0.0.0.0/0 on port 22",
          suggested_fix: "Restrict the source address prefix",
        },
      ],
    });

    expect(
      await screen.findByText("Public ingress is not allowed"),
    ).toBeInTheDocument();
    expect(screen.getByText("FAILED")).toBeInTheDocument();
    expect(screen.getByText("2 violations · 2 rules checked")).toBeInTheDocument();
    expect(
      screen.getByText("azurerm_network_security_rule.ssh"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Suggested fix: Restrict the source address prefix"),
    ).toBeInTheDocument();

    // Severest first, whatever order the checker emitted them in.
    const violationsSection = screen.getByText("Violations").closest("section")!;
    const ruleIds = within(violationsSection)
      .getAllByText(/^(NET-001|TAG-002)$/)
      .map((el) => el.textContent);
    expect(ruleIds).toEqual(["NET-001", "TAG-002"]);
  });

  it("renders a passed check without a violations list", async () => {
    renderCompliance({
      passed: true,
      summary: "All rules satisfied",
      violations: [],
    });

    expect(await screen.findByText("PASSED")).toBeInTheDocument();
    expect(screen.getByText("0 violations")).toBeInTheDocument();
    expect(screen.queryByText("Violations")).not.toBeInTheDocument();
    expect(screen.queryByText("Rules checked")).not.toBeInTheDocument();
  });

  it("lists the checked rules, violated ones first", async () => {
    renderCompliance({
      passed: false,
      summary: "Standalone deletion",
      checked_rules: ["scope_exceeded", "critical_deletion", "scope_incomplete"],
      violations: [
        {
          rule_id: "critical_deletion",
          severity: "critical",
          resource: "azurerm_storage_account.sttestdev004",
          message: "Standalone destruction with no recreate",
        },
      ],
    });

    expect(await screen.findByText("Rules checked")).toBeInTheDocument();
    expect(screen.queryByText("Compliance Check")).not.toBeInTheDocument();
    const chips = screen.getAllByRole("listitem").filter((li) => li.title);
    expect(chips.map((li) => [li.textContent, li.title])).toEqual([
      ["✕critical_deletion", "Violated (critical)"],
      ["✓scope_exceeded", "Passed"],
      ["✓scope_incomplete", "Passed"],
    ]);
  });

  it("clamps a long summary behind a toggle", async () => {
    const summary = "Inventory entry. ".repeat(40).trim();
    renderCompliance({ passed: true, summary, violations: [] });

    const toggle = await screen.findByRole("button", { name: "Show more" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(toggle);
    expect(screen.getByRole("button", { name: "Show less" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
  });

  it("shows a short summary without a toggle", async () => {
    renderCompliance({ passed: true, summary: "All rules satisfied", violations: [] });

    expect(await screen.findByText("All rules satisfied")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Show more" })).not.toBeInTheDocument();
  });
});

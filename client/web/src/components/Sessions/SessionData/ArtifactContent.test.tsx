// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "@/mocks/server";
import { makeRound } from "@/mocks/state";
import { renderWithProviders } from "@/test/render";
import type {
  OperationType,
  ReportRef,
  TerraformPlanRef,
} from "@/types/api";
import ArtifactContent, { artifactLabel } from "./ArtifactContent";

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
      round={makeRound({ reports: [ref] })}
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
  });
});

describe("artifactLabel for plans", () => {
  const SIG = "X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Signature=abc123";

  function planRef(url: string): TerraformPlanRef {
    return {
      id: 7,
      url,
      content_type: "text/plain",
      file_size_bytes: 8633,
      created_at: "2026-01-01T00:00:00Z",
      targets: [],
    };
  }

  it("labels a drift-keyed plan as a drift operation", () => {
    const ref = planRef(
      `${STORAGE}/nebula-artifacts/sessions/s1/rounds/8/plans/drift-ee05fba7.txt?${SIG}`,
    );

    expect(artifactLabel("plan", ref)).toBe("Drift Operation");
  });

  it("labels a plan-keyed plan as a terraform plan", () => {
    const ref = planRef(
      `${STORAGE}/nebula-artifacts/sessions/s1/rounds/8/plans/plan-ee05fba7.txt?${SIG}`,
    );

    expect(artifactLabel("plan", ref)).toBe("Terraform Plan");
  });

  it("falls back to terraform plan for an unrecognized key", () => {
    // Pre-`is_drift` rows, or a future key format: the label degrades to
    // the generic one rather than mislabelling the artifact.
    const ref = planRef(`${STORAGE}/legacy/terraform_plan.txt?${SIG}`);

    expect(artifactLabel("plan", ref)).toBe("Terraform Plan");
  });

  it("ignores 'drift' appearing outside the key's file name", () => {
    // A substring search over the whole URL would trip on the signature
    // or on a path segment; only the file name carries the flavour.
    const ref = planRef(
      `${STORAGE}/nebula-artifacts/sessions/drift/rounds/8/plans/plan-ee05fba7.txt?${SIG}&x=drift`,
    );

    expect(artifactLabel("plan", ref)).toBe("Terraform Plan");
  });
});

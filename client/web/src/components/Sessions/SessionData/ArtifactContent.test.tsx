// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "@/test/server";
import { renderWithProviders } from "@/test/render";
import type {
  CodeChangeRef,
  ComplianceCheckRef,
  OperationType,
  PlanType,
  ReportRef,
  TerraformPlanRef,
} from "@/types/api";
import ArtifactContent, {
  artifactLabel,
  prettyPrintJson,
} from "./ArtifactContent";

// Monaco is lazy-loaded and unmocked in jsdom, so asserting on editor DOM
// would be slow and flaky. What this change actually decides is the pair of
// props handed to the viewer, so record those and render nothing. The
// factory returns null rather than JSX: vi.mock is hoisted above the
// automatic JSX runtime import.
const viewer = vi.hoisted(() => ({
  code: undefined as string | undefined,
  language: undefined as string | undefined,
  files: undefined as Record<string, string> | undefined,
  newFiles: undefined as ReadonlySet<string> | undefined,
}));

vi.mock("@/components/ui", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/components/ui")>()),
  CodeBlock: ({
    code,
    language,
    files,
    newFiles,
  }: {
    code?: string;
    language?: string;
    files?: Record<string, string>;
    newFiles?: ReadonlySet<string>;
  }) => {
    viewer.code = code;
    viewer.language = language;
    viewer.files = files;
    viewer.newFiles = newFiles;
    return null;
  },
}));

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

describe("ArtifactContent plan metadata", () => {
  it("reports the flavour that came back with the plan body", async () => {
    // The point of the merged read: one request yields the plan and the
    // `type` metadata the timeline needed, so opening a plan costs no
    // extra round trip to learn what it is.
    let requests = 0;
    const ref: TerraformPlanRef = {
      id: 42,
      url: `${STORAGE}/plan.txt`,
      content_type: "text/plain",
      file_size_bytes: 10,
      created_at: "2026-01-01T00:00:00Z",
      targets: [],
    };
    server.use(
      http.get(`${STORAGE}/plan.txt`, () => {
        requests += 1;
        return HttpResponse.text("# drift diff", {
          headers: { "x-amz-meta-type": "drift" },
        });
      }),
    );
    const onPlanType = vi.fn();

    renderWithProviders(
      <ArtifactContent
        kind="plan"
        artifact={ref}
        operation="drift"
        onPlanType={onPlanType}
      />,
    );

    await waitFor(() => expect(onPlanType).toHaveBeenCalledWith(42, "drift"));
    expect(requests).toBe(1);
  });
});

describe("ArtifactContent plan targets", () => {
  const TARGETS = [
    "aws_s3_bucket.s3-003",
    "aws_s3_bucket_versioning.s3-003",
    "aws_s3_bucket_server_side_encryption_configuration.s3-003",
  ];

  function renderPlan(targets: string[]) {
    const ref: TerraformPlanRef = {
      id: 7,
      url: `${STORAGE}/plan.txt`,
      content_type: "text/plain",
      file_size_bytes: 10,
      created_at: "2026-01-01T00:00:00Z",
      targets,
    };
    server.use(
      http.get(`${STORAGE}/plan.txt`, () => HttpResponse.text("# plan")),
    );
    renderWithProviders(
      <ArtifactContent
        kind="plan"
        artifact={ref}
        operation="generate"
      />,
    );
  }

  it("lists every target, open by default", async () => {
    // The timeline row only had room for a count, so nothing may be
    // elided here — this is where the addresses become readable.
    renderPlan(TARGETS);

    expect(await screen.findByText("Targets (3)")).toBeInTheDocument();
    for (const target of TARGETS) {
      expect(screen.getByText(target)).toBeInTheDocument();
    }
  });

  it("collapses the list on toggle", async () => {
    const user = userEvent.setup();
    renderPlan(TARGETS);

    const toggle = await screen.findByRole("button", { name: /Targets \(3\)/ });
    expect(toggle).toHaveAttribute("aria-expanded", "true");

    await user.click(toggle);

    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText(TARGETS[0])).toBeNull();
  });

  it("renders no targets block for a plan that carries none", async () => {
    renderPlan([]);

    await waitFor(() => expect(screen.queryByText(/Loading/)).toBeNull());
    expect(screen.queryByText(/^Targets/)).toBeNull();
  });
});

describe("artifactLabel for plans", () => {
  const SIG = "X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Signature=abc123";
  const KEYED = (flavour: string) =>
    `${STORAGE}/kumoss-artifacts/sessions/s1/rounds/8/plans/${flavour}-ee05fba7.txt?${SIG}`;

  function planRef(url = KEYED("plan")): TerraformPlanRef {
    return {
      id: 7,
      url,
      content_type: "text/plain",
      file_size_bytes: 8633,
      created_at: "2026-01-01T00:00:00Z",
      targets: [],
    };
  }

  it("labels a drift plan as a drift operation", () => {
    expect(artifactLabel("plan", planRef(), "drift")).toBe("Drift Operation");
  });

  it("labels a plain plan as a terraform plan", () => {
    expect(artifactLabel("plan", planRef(), "plan")).toBe("Terraform Plan");
  });

  it("reads the flavour from the resolved metadata, not the signed URL", () => {
    // The object's `type` metadata is the source, so a URL whose key
    // disagrees (a renamed key, a proxied download) must not win.
    expect(artifactLabel("plan", planRef(KEYED("plan")), "drift")).toBe(
      "Drift Operation",
    );
    expect(artifactLabel("plan", planRef(KEYED("drift")), "plan")).toBe(
      "Terraform Plan",
    );
  });

  it.each([undefined, null] as const)(
    "falls back to the neutral label when the flavour is %s",
    (flavour: PlanType | null | undefined) => {
      // An unreadable object must not be announced as drift: an unlabelled
      // diff is a smaller lie than a plan presented as one.
      expect(artifactLabel("plan", planRef(KEYED("drift")), flavour)).toBe(
        "Terraform Plan",
      );
    },
  );
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

describe("prettyPrintJson", () => {
  it("indents the single-line resource-action array from a plan artifact", () => {
    const body =
      '[{"address": "aws_s3_bucket.s3-003", "action": "delete resource"}, ' +
      '{"address": "aws_s3_bucket_versioning.s3-003", "action": "delete resource"}]';

    expect(prettyPrintJson(body)).toBe(
      `[
  {
    "address": "aws_s3_bucket.s3-003",
    "action": "delete resource"
  },
  {
    "address": "aws_s3_bucket_versioning.s3-003",
    "action": "delete resource"
  }
]`,
    );
  });

  it("indents a top-level object", () => {
    expect(prettyPrintJson('{"status":"Succeeded","imported":1}')).toBe(
      `{
  "status": "Succeeded",
  "imported": 1
}`,
    );
  });

  it("leaves an already-indented body readable", () => {
    // Review Focus 1: a producer that already pretty-printed must not be
    // skipped (it would then be at the mercy of getLanguage saying "hcl"),
    // and must not come back mangled.
    const body = '{\n  "action": "delete resource"\n}';
    expect(prettyPrintJson(body)).toBe('{\n  "action": "delete resource"\n}');
  });

  it("tolerates leading whitespace before the opening brace", () => {
    expect(prettyPrintJson('\n  {"a":1}')).toBe('{\n  "a": 1\n}');
  });

  it.each([
    ["HCL plan output", 'resource "aws_s3_bucket" "b" {\n  bucket = "x"\n}'],
    ["a bare number", "42"],
    ["a bare boolean", "true"],
    ["a quoted string", '"delete resource"'],
    ["the JSON literal null", "null"],
  ])("returns null for %s", (_label: string, body: string) => {
    // All of these are rejected by the opening-character gate, before the
    // parse. Scalars are left alone deliberately: re-quoting a bare number
    // gains nothing, and a body that is literally `null` must fall back
    // rather than print the word in the viewer.
    expect(prettyPrintJson(body)).toBeNull();
  });

  it.each([
    ["an empty body", ""],
    ["a whitespace-only body", "   \n\t "],
  ])("returns null for %s", (_label: string, body: string) => {
    expect(prettyPrintJson(body)).toBeNull();
  });

  it("returns null for malformed JSON that starts like an object", () => {
    // Review Focus 4: the gate lets this reach JSON.parse, so the catch is
    // what keeps a truncated upload rendering as raw text.
    expect(prettyPrintJson('{"address": "aws_s3_bucket.s3-003"')).toBeNull();
  });

  it("returns null past the size cap rather than tripling the string", () => {
    const huge = `[${'{"a":1},'.repeat(80_000)}{"a":1}]`;
    expect(huge.length).toBeGreaterThan(512 * 1024);
    expect(prettyPrintJson(huge)).toBeNull();
  });
});

describe("ArtifactContent JSON bodies in the raw viewer", () => {
  // Named apart from the `planRef` helper in the `artifactLabel for plans`
  // suite above — sibling scopes, but two different things under one name
  // in one file is a trap for the next reader.
  const jsonPlanRef: TerraformPlanRef = {
    id: 9,
    url: `${STORAGE}/plan.txt`,
    content_type: "text/plain",
    file_size_bytes: 160,
    created_at: "2026-01-01T00:00:00Z",
    targets: [],
  };

  const ONE_LINE =
    '[{"address": "aws_s3_bucket.s3-003", "action": "delete resource"}]';

  function renderPlan(body: string, ref: TerraformPlanRef = jsonPlanRef) {
    server.use(http.get(`${STORAGE}/plan.txt`, () => HttpResponse.text(body)));
    renderWithProviders(
      <ArtifactContent
        kind="plan"
        artifact={ref}
        operation="generate"
      />,
    );
  }

  beforeEach(() => {
    viewer.code = undefined;
    viewer.language = undefined;
  });

  it("indents a JSON plan body and hands Monaco the json language", async () => {
    renderPlan(ONE_LINE);

    await waitFor(() => expect(viewer.code).toBeDefined());
    expect(viewer.code).toBe(
      `[
  {
    "address": "aws_s3_bucket.s3-003",
    "action": "delete resource"
  }
]`,
    );
    expect(viewer.language).toBe("json");
  });

  it("indents a body already declared as json", async () => {
    // Review Focus 2: getLanguage already returned "json" for this ref, so
    // highlighting was never the missing piece — the body still needs
    // re-serializing or the artifact stays on one line.
    renderPlan(ONE_LINE, { ...jsonPlanRef, content_type: "application/json" });

    await waitFor(() => expect(viewer.code).toBeDefined());
    expect(viewer.code).toContain("\n");
    expect(viewer.language).toBe("json");
  });

  it("leaves an HCL plan body and its language untouched", async () => {
    const hcl = 'resource "aws_s3_bucket" "b" {\n  bucket = "x"\n}';
    renderPlan(hcl);

    await waitFor(() => expect(viewer.code).toBeDefined());
    expect(viewer.code).toBe(hcl);
    expect(viewer.language).toBe("hcl");
  });

  it("falls back to the raw body when the JSON is malformed", async () => {
    // Review Focus 4: a truncated upload must still be inspectable.
    const broken = '{"address": "aws_s3_bucket.s3-003"';
    renderPlan(broken);

    await waitFor(() => expect(viewer.code).toBeDefined());
    expect(viewer.code).toBe(broken);
    expect(viewer.language).toBe("hcl");
  });

  it("does not divert a report body away from the report renderer", async () => {
    // Review Focus 3: applyReport parses as JSON, so an ungated memo would
    // parse it a second time — and if the viewer ever won, the tables would
    // vanish. Assert the tables still render and the viewer was never used.
    renderReport(applyReport);

    expect(await screen.findByText("rg-main")).toBeInTheDocument();
    expect(viewer.code).toBeUndefined();
  });
});

describe("ArtifactContent code changes", () => {
  const MAIN_DIFF = [
    "diff --git main.tf main.tf",
    "--- main.tf",
    "+++ main.tf",
    "@@ -1,1 +1,1 @@",
    '-resource "a" {}',
    '+resource "b" {}',
  ].join("\n");

  function changeRef(id: number, fileName: string): CodeChangeRef {
    return {
      id,
      url: `${STORAGE}/${fileName}`,
      content_type: "text/plain",
      file_size_bytes: 20,
      created_at: "2026-01-01T00:00:00Z",
      file_name: fileName,
    };
  }

  /** Serve a code-change object with its `new_file` metadata tag. */
  function serveChange(fileName: string, isNewFile: boolean, body: string) {
    return http.get(`${STORAGE}/${fileName}`, () =>
      HttpResponse.text(body, {
        headers: { "x-amz-meta-new_file": String(isNewFile) },
      }),
    );
  }

  function renderChange(ref: CodeChangeRef) {
    renderWithProviders(
      <ArtifactContent kind="change" artifact={ref} operation="generate" />,
    );
  }

  beforeEach(() => {
    viewer.files = undefined;
    viewer.newFiles = undefined;
  });

  it("tells the viewer when the file is raw rather than a diff", async () => {
    server.use(serveChange("vars.tf", true, 'variable "a" {}'));
    renderChange(changeRef(1, "vars.tf"));

    await waitFor(() => expect(viewer.files).toBeDefined());
    expect(viewer.files).toEqual({ "vars.tf": 'variable "a" {}' });
    expect([...viewer.newFiles!]).toEqual(["vars.tf"]);
  });

  it("shows the clicked revision as stored, not composed", async () => {
    server.use(serveChange("main.tf", false, MAIN_DIFF));
    renderChange(changeRef(1, "main.tf"));

    await waitFor(() => expect(viewer.files).toBeDefined());
    expect(viewer.files).toEqual({ "main.tf": MAIN_DIFF });
    expect([...viewer.newFiles!]).toEqual([]);
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

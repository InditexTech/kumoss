// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect, beforeEach } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "@/mocks/server";
import { mockState, makeSessionDetail, makeRound, makeStatus } from "@/mocks/state";
import type { ReportRef } from "@/types/api";
import {
  resolveSessionOutcome,
  buildSessionPatch,
  buildAssistantMessage,
  buildApplyResults,
  appendAssistantMessage,
  isApplyRound,
  waitForNewRound,
} from "./session_outcome";

const STORAGE = "https://storage.test";

function artifactRef(id: number, path: string) {
  return {
    id,
    url: `${STORAGE}/${path}`,
    content_type: "text/plain",
    file_size_bytes: 10,
    created_at: "2026-01-01T00:00:00Z",
  };
}

function reportRef(id: number, path: string): ReportRef {
  return { ...artifactRef(id, path), type: "generate" };
}

beforeEach(() => {
  mockState.clear();
});

describe("resolveSessionOutcome", () => {
  it("rebuilds report, plan and code blob for a completed round", async () => {
    const report = { status: "ok", potential_impact: { summary: "Low risk" } };
    mockState.addSession(
      makeSessionDetail({
        rounds: [
          makeRound({
            statuses: [makeStatus("started"), makeStatus("completed")],
            reports: [reportRef(1, "report.json")],
            plans: [{ ...artifactRef(2, "plan.txt"), targets: ["a.b"] }],
            code_changes: [
              { ...artifactRef(3, "main.tf"), file_name: "main.tf" },
              { ...artifactRef(4, "vars.tf"), file_name: "vars.tf" },
            ],
          }),
        ],
      }),
    );
    server.use(
      http.get(`${STORAGE}/report.json`, () => HttpResponse.json(report)),
      http.get(`${STORAGE}/plan.txt`, () => HttpResponse.text("plan output")),
      http.get(`${STORAGE}/main.tf`, () => HttpResponse.text("resource {}")),
      http.get(`${STORAGE}/vars.tf`, () => HttpResponse.text("variable {}")),
    );

    const outcome = await resolveSessionOutcome("sess-1");

    expect(outcome.kind).toBe("results");
    if (outcome.kind !== "results") throw new Error("unreachable");
    expect(outcome.report).toEqual(report);
    expect(outcome.targets).toEqual(["a.b"]);
    expect(outcome.code).toContain("<Terraform_Plan>\nplan output\n</Terraform_Plan>");
    expect(outcome.code).toContain("<main.tf>\nresource {}\n</main.tf>");
    expect(outcome.code).toContain("<vars.tf>\nvariable {}\n</vars.tf>");
  });

  it("uses the newest plan when a drift round stored several", async () => {
    mockState.addSession(
      makeSessionDetail({
        uuid: "sess-multi",
        operation: "drift",
        rounds: [
          makeRound({
            statuses: [makeStatus("started"), makeStatus("completed")],
            reports: [reportRef(10, "report.json")],
            plans: [
              { ...artifactRef(11, "drift.txt"), targets: ["a.b"] },
              { ...artifactRef(12, "final.txt"), targets: ["c.d"] },
            ],
          }),
        ],
      }),
    );
    server.use(
      http.get(`${STORAGE}/report.json`, () =>
        HttpResponse.json({ status: "ok" }),
      ),
      http.get(`${STORAGE}/drift.txt`, () => HttpResponse.text("drift diff")),
      http.get(`${STORAGE}/final.txt`, () => HttpResponse.text("final plan")),
    );

    const outcome = await resolveSessionOutcome("sess-multi");

    expect(outcome.kind).toBe("results");
    if (outcome.kind !== "results") throw new Error("unreachable");
    expect(outcome.code).toContain("final plan");
    expect(outcome.code).not.toContain("drift diff");
    expect(outcome.targets).toEqual(["c.d"]);
  });

  it("merges code changes across rounds, with later rounds winning", async () => {
    mockState.addSession(
      makeSessionDetail({
        rounds: [
          makeRound({
            number: 1,
            code_changes: [
              { ...artifactRef(3, "storage.tf"), file_name: "storage.tf" },
              { ...artifactRef(4, "outputs-r1.tf"), file_name: "outputs.tf" },
            ],
          }),
          makeRound({
            number: 2,
            statuses: [makeStatus("started"), makeStatus("completed")],
            plans: [{ ...artifactRef(5, "plan.txt"), targets: [] }],
            code_changes: [
              { ...artifactRef(6, "outputs-r2.tf"), file_name: "outputs.tf" },
              { ...artifactRef(7, "vault.tf"), file_name: "vault.tf" },
            ],
          }),
        ],
      }),
    );
    server.use(
      http.get(`${STORAGE}/plan.txt`, () => HttpResponse.text("plan output")),
      http.get(`${STORAGE}/storage.tf`, () => HttpResponse.text("storage v1")),
      http.get(`${STORAGE}/outputs-r1.tf`, () => HttpResponse.text("outputs v1")),
      http.get(`${STORAGE}/outputs-r2.tf`, () => HttpResponse.text("outputs v2")),
      http.get(`${STORAGE}/vault.tf`, () => HttpResponse.text("vault v1")),
    );

    const outcome = await resolveSessionOutcome("sess-1");

    expect(outcome.kind).toBe("results");
    if (outcome.kind !== "results") throw new Error("unreachable");
    expect(outcome.code).toContain("<storage.tf>\nstorage v1\n</storage.tf>");
    expect(outcome.code).toContain("<vault.tf>\nvault v1\n</vault.tf>");
    expect(outcome.code).toContain("<outputs.tf>\noutputs v2\n</outputs.tf>");
    expect(outcome.code).not.toContain("outputs v1");
  });

  it("chains a drift round's sequential diffs of one file into a cumulative diff", async () => {
    // Drift remediation edits the same file several times; each artifact
    // diffs against the previous one, so only chaining them shows the
    // round's full change (not just the last incremental step).
    const diff1 = [
      "diff --git outputs.tf outputs.tf",
      "--- outputs.tf",
      "+++ outputs.tf",
      "@@ -1,3 +1,2 @@",
      ' output "a" {}',
      '-output "b" {}',
      ' output "c" {}',
    ].join("\n");
    const diff2 = [
      "diff --git outputs.tf outputs.tf",
      "--- outputs.tf",
      "+++ outputs.tf",
      "@@ -1,2 +1,1 @@",
      ' output "a" {}',
      '-output "c" {}',
    ].join("\n");
    mockState.addSession(
      makeSessionDetail({
        operation: "drift",
        rounds: [
          makeRound({
            statuses: [makeStatus("started"), makeStatus("completed")],
            code_changes: [
              { ...artifactRef(3, "diff1"), file_name: "outputs.tf" },
              { ...artifactRef(4, "diff2"), file_name: "outputs.tf" },
            ],
          }),
        ],
      }),
    );
    server.use(
      http.get(`${STORAGE}/diff1`, () => HttpResponse.text(diff1)),
      http.get(`${STORAGE}/diff2`, () => HttpResponse.text(diff2)),
    );

    const outcome = await resolveSessionOutcome("sess-1");

    expect(outcome.kind).toBe("results");
    if (outcome.kind !== "results") throw new Error("unreachable");
    // One file entry whose diff spans first-original → last-modified.
    expect(outcome.code.match(/<outputs\.tf>/g)).toHaveLength(1);
    expect(outcome.code).toContain('-output "b" {}');
    expect(outcome.code).toContain('-output "c" {}');
    expect(outcome.code).toContain('+output "a" {}');
  });

  it("requests the conversation history when given a session id", async () => {
    let sawIncludeHistory = false;
    mockState.addSession(makeSessionDetail({ rounds: [makeRound()] }));
    server.use(
      http.get("/api/v1/sessions/:sessionId", ({ request, params }) => {
        sawIncludeHistory =
          new URL(request.url).searchParams.get("include_history") === "true";
        return HttpResponse.json(
          mockState.getSession(params.sessionId as string),
        );
      }),
    );

    await resolveSessionOutcome("sess-1");
    expect(sawIncludeHistory).toBe(true);
  });

  it("maps a filter-rejected round (uncompleted) to a rejected outcome", async () => {
    mockState.addSession(
      makeSessionDetail({
        current_status: "uncompleted",
        rounds: [
          makeRound({
            statuses: [
              makeStatus("started"),
              makeStatus("filtering"),
              makeStatus("uncompleted", "Query is off-topic"),
            ],
          }),
        ],
      }),
    );

    const outcome = await resolveSessionOutcome("sess-1");

    expect(outcome).toMatchObject({
      kind: "rejected",
      rationale: "Query is off-topic",
    });
    if (outcome.kind !== "rejected") throw new Error("unreachable");
    expect(outcome.prior).toBeUndefined();
  });

  it("hydrates the prior round's artifacts for a rejected iteration", async () => {
    mockState.addSession(
      makeSessionDetail({
        current_status: "uncompleted",
        rounds: [
          makeRound({
            statuses: [makeStatus("started"), makeStatus("completed")],
            reports: [reportRef(1, "report.json")],
            code_changes: [
              { ...artifactRef(2, "main.tf"), file_name: "main.tf" },
            ],
          }),
          makeRound({
            statuses: [
              makeStatus("started"),
              makeStatus("uncompleted", "Query is off-topic"),
            ],
          }),
        ],
      }),
    );
    server.use(
      http.get(`${STORAGE}/report.json`, () =>
        HttpResponse.json({ status: "ok" }),
      ),
      http.get(`${STORAGE}/main.tf`, () => HttpResponse.text("resource {}")),
    );

    const outcome = await resolveSessionOutcome("sess-1");

    expect(outcome.kind).toBe("rejected");
    if (outcome.kind !== "rejected") throw new Error("unreachable");
    expect(outcome.rationale).toBe("Query is off-topic");
    expect(outcome.prior?.report).toEqual({ status: "ok" });
    expect(outcome.prior?.code).toContain("<main.tf>\nresource {}\n</main.tf>");
  });

  it("degrades a rejected iteration to chat-only when artifacts can't load", async () => {
    mockState.addSession(
      makeSessionDetail({
        current_status: "uncompleted",
        rounds: [
          makeRound({
            statuses: [makeStatus("started"), makeStatus("completed")],
            reports: [reportRef(1, "report.json")],
          }),
          makeRound({
            statuses: [makeStatus("uncompleted", "Query is off-topic")],
          }),
        ],
      }),
    );
    server.use(
      http.get(`${STORAGE}/report.json`, () =>
        new HttpResponse(null, { status: 403 }),
      ),
    );

    const outcome = await resolveSessionOutcome("sess-1");

    expect(outcome).toMatchObject({
      kind: "rejected",
      rationale: "Query is off-topic",
    });
    if (outcome.kind !== "rejected") throw new Error("unreachable");
    expect(outcome.prior).toBeUndefined();
  });

  it("retries with a fresh detail to hydrate a rejected iteration's prior round", async () => {
    let reportCalls = 0;
    mockState.addSession(
      makeSessionDetail({
        current_status: "uncompleted",
        rounds: [
          makeRound({
            statuses: [makeStatus("started"), makeStatus("completed")],
            reports: [reportRef(1, "report.json")],
            code_changes: [
              { ...artifactRef(2, "main.tf"), file_name: "main.tf" },
            ],
          }),
          makeRound({
            statuses: [makeStatus("uncompleted", "Query is off-topic")],
          }),
        ],
      }),
    );
    server.use(
      http.get(`${STORAGE}/report.json`, () => {
        reportCalls++;
        if (reportCalls === 1) {
          return new HttpResponse(null, { status: 403 });
        }
        return HttpResponse.json({ status: "ok" });
      }),
      http.get(`${STORAGE}/main.tf`, () => HttpResponse.text("resource {}")),
    );

    const outcome = await resolveSessionOutcome("sess-1");

    // The stale first fetch (403) must fall through to the fresh-detail
    // retry, which needs the refetched round set to merge code changes —
    // otherwise it throws and the prior round degrades to chat-only.
    expect(reportCalls).toBe(2);
    expect(outcome.kind).toBe("rejected");
    if (outcome.kind !== "rejected") throw new Error("unreachable");
    expect(outcome.prior?.report).toEqual({ status: "ok" });
    expect(outcome.prior?.code).toContain("<main.tf>\nresource {}\n</main.tf>");
  });

  it("maps a failed round to a failed outcome with the status message", async () => {
    mockState.addSession(
      makeSessionDetail({
        current_status: "failed",
        rounds: [
          makeRound({
            statuses: [
              makeStatus("started"),
              makeStatus("failed", "runner failed: boom"),
            ],
          }),
        ],
      }),
    );

    const outcome = await resolveSessionOutcome("sess-1");

    expect(outcome).toMatchObject({
      kind: "failed",
      message: "runner failed: boom",
    });
  });

  it("detects apply rounds by their apply status", async () => {
    const applyReport = { status: "Success", execution_summary: "Applied" };
    mockState.addSession(
      makeSessionDetail({
        rounds: [
          makeRound({
            statuses: [
              makeStatus("started"),
              makeStatus("apply"),
              makeStatus("completed"),
            ],
            reports: [reportRef(9, "apply-report.json")],
          }),
        ],
      }),
    );
    server.use(
      http.get(`${STORAGE}/apply-report.json`, () =>
        HttpResponse.json(applyReport),
      ),
    );

    const outcome = await resolveSessionOutcome("sess-1");

    expect(outcome.kind).toBe("apply-results");
    if (outcome.kind !== "apply-results") throw new Error("unreachable");
    expect(outcome.report).toEqual(applyReport);
  });

  it("retries once with a fresh detail when an artifact URL is stale", async () => {
    let artifactCalls = 0;
    mockState.addSession(
      makeSessionDetail({
        rounds: [
          makeRound({
            statuses: [makeStatus("completed")],
            reports: [reportRef(1, "report.json")],
          }),
        ],
      }),
    );
    server.use(
      http.get(`${STORAGE}/report.json`, () => {
        artifactCalls++;
        if (artifactCalls === 1) {
          return new HttpResponse(null, { status: 403 });
        }
        return HttpResponse.json({ status: "ok" });
      }),
    );

    const outcome = await resolveSessionOutcome("sess-1");

    expect(artifactCalls).toBe(2);
    expect(outcome.kind).toBe("results");
    if (outcome.kind !== "results") throw new Error("unreachable");
    expect(outcome.report).toEqual({ status: "ok" });
  });
});

describe("waitForNewRound", () => {
  it("returns immediately once the new round has a status", async () => {
    mockState.addSession(
      makeSessionDetail({
        rounds: [makeRound(), makeRound({ statuses: [makeStatus("started")] })],
      }),
    );

    await expect(waitForNewRound("sess-1", 1)).resolves.toBeUndefined();
  });
});

describe("isApplyRound", () => {
  it("isApplyRound is false for plain generate rounds", () => {
    expect(isApplyRound(makeRound())).toBe(false);
    expect(
      isApplyRound(makeRound({ statuses: [makeStatus("apply")] })),
    ).toBe(true);
  });
});

describe("buildSessionPatch", () => {
  it("maps a results outcome onto the UI session shape", () => {
    const detail = makeSessionDetail({ is_blocked: true });
    const patch = buildSessionPatch({
      kind: "results",
      detail,
      round: detail.rounds[0],
      report: null,
      code: "<main.tf>\nx\n</main.tf>",
      targets: ["a.b"],
    });

    expect(patch).toMatchObject({
      uuid: "sess-1",
      operation: "generate",
      provider: "azure",
      scope_id: "sub-123",
      first_query: "deploy a VM",
      workspace: {
        uri: "https://dev.azure.com/org/project/_git/repo",
        branch: "nebula/sess-1",
        root_path: "environments/dev",
      },
      is_blocked: true,
      current_status: "completed",
      code: "<main.tf>\nx\n</main.tf>",
    });
    expect(patch).not.toHaveProperty("terraform_targets");
    expect(patch.history).toEqual([
      { role: "user", content: "deploy a VM" },
      { role: "assistant", content: "Here is your VM" },
    ]);
  });

  it("marks failed outcomes with current_status failed only", () => {
    expect(
      buildSessionPatch({ kind: "failed", detail: null, message: "boom" }),
    ).toEqual({ current_status: "failed" });
  });

  it("keeps the prior round's artifacts for rejected iterations", () => {
    const patch = buildSessionPatch({
      kind: "rejected",
      detail: makeSessionDetail({ current_status: "uncompleted" }),
      rationale: "Off-topic",
      prior: {
        report: { status: "ok" },
        code: "<main.tf>\nx\n</main.tf>",
        targets: ["a.b"],
      },
    });

    expect(patch).toMatchObject({
      current_status: "uncompleted",
      code: "<main.tf>\nx\n</main.tf>",
      terraform_report: { status: "ok" },
    });
  });
});

describe("appendAssistantMessage", () => {
  it("appends when the history does not already end with the message", () => {
    expect(
      appendAssistantMessage([{ role: "user", content: "q" }], "summary"),
    ).toEqual([
      { role: "user", content: "q" },
      { role: "assistant", content: "summary" },
    ]);
  });

  it("does not duplicate a rationale the backend already persisted", () => {
    const history = [
      { role: "user" as const, content: "off-topic query" },
      { role: "assistant" as const, content: "Query is off-topic" },
    ];
    expect(appendAssistantMessage(history, "Query is off-topic")).toEqual(
      history,
    );
  });
});

describe("buildAssistantMessage", () => {
  const detail = makeSessionDetail();

  it("prefers the potential impact summary for generate results", () => {
    expect(
      buildAssistantMessage({
        kind: "results",
        detail,
        round: detail.rounds[0],
        report: { potential_impact: { summary: "Adds one VM" } },
        code: "",
        targets: undefined,
      }),
    ).toBe("Adds one VM");
  });

  it("falls back to plan counts", () => {
    expect(
      buildAssistantMessage({
        kind: "results",
        detail,
        round: detail.rounds[0],
        report: { summary: { create: 2, update: 1, delete: 0, recreate: 0 } },
        code: "",
        targets: undefined,
      }),
    ).toContain("2 to create");
  });

  it("uses the drift report summary for drift sessions", () => {
    expect(
      buildAssistantMessage({
        kind: "results",
        detail: makeSessionDetail({ operation: "drift" }),
        round: detail.rounds[0],
        report: { summary: "One resource drifted" },
        code: "",
        targets: undefined,
      }),
    ).toBe("One resource drifted");
  });

  it("uses execution_summary for apply results and rationale for rejections", () => {
    expect(
      buildAssistantMessage({
        kind: "apply-results",
        detail,
        round: detail.rounds[0],
        report: { execution_summary: "Applied 3 resources" },
      }),
    ).toBe("Applied 3 resources");
    expect(
      buildAssistantMessage({
        kind: "rejected",
        detail,
        rationale: "Off-topic",
      }),
    ).toBe("Off-topic");
  });
});

describe("buildApplyResults", () => {
  it("projects the apply report onto ApplyResultsData", () => {
    const detail = makeSessionDetail();
    const results = buildApplyResults({
      kind: "apply-results",
      detail,
      round: detail.rounds[0],
      report: { status: "Success", execution_summary: "Done" },
    });

    expect(results).toMatchObject({
      sessionId: "sess-1",
      status: "Success",
      message: "Done",
      timestamp: detail.updated_at,
    });
  });
});

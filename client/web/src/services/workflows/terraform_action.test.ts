// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "@/test/server";
import { MODE } from "@/types/ui";
import type { Mode } from "@/types/ui";
import { runTerraformActionWorkflow } from "./terraform_action";

/** Capture the path and JSON body of every IaC POST. */
function captureIacCalls() {
  const calls: { path: string; body: unknown }[] = [];
  server.use(
    http.post("/api/v1/iac/:action", async ({ request, params }) => {
      calls.push({ path: String(params.action), body: await request.json() });
      return HttpResponse.json({ session_id: "sess-1" }, { status: 202 });
    }),
  );
  return calls;
}

const firstCall = {
  query: "import the storage account staweu1001",
  repoUri: "https://github.com/org/repo",
  terraformProviders: "azure" as const,
  scopeId: "sub-123",
  iacPath: "environments/dev",
};

describe("runTerraformActionWorkflow", () => {
  const cases: Array<[Mode, string, boolean | undefined]> = [
    [MODE.GENERATE, "generate", undefined],
    [MODE.DRIFT, "drift", false],
    [MODE.PARTIAL_DRIFT, "drift", true],
    [MODE.IMPORT, "import", false],
    [MODE.PARTIAL_IMPORT, "import", true],
  ];

  it.each(cases)("mode %s → POST /iac/%s (is_partial %s)", async (mode, path, isPartial) => {
    const calls = captureIacCalls();

    const result = await runTerraformActionWorkflow({ ...firstCall, mode });

    expect(result).toEqual({ sessionId: "sess-1" });
    expect(calls).toHaveLength(1);
    expect(calls[0].path).toBe(path);
    expect(calls[0].body).toEqual({
      repo_uri: firstCall.repoUri,
      q: firstCall.query,
      terraform_providers: "azure",
      scope_id: "sub-123",
      iac_path: "environments/dev",
      ...(isPartial === undefined ? {} : { is_partial: isPartial }),
    });
  });

  it("iterates an import session with only the session id and query", async () => {
    const calls = captureIacCalls();

    await runTerraformActionWorkflow({
      sessionId: "sess-1",
      query: "also import the key vault",
      mode: MODE.PARTIAL_IMPORT,
    });

    expect(calls).toEqual([
      {
        path: "import",
        body: { session_id: "sess-1", q: "also import the key vault", is_partial: true },
      },
    ]);
  });

  it("an apply action hits /iac/apply with only the session id", async () => {
    const calls = captureIacCalls();

    await runTerraformActionWorkflow({ kind: "apply", sessionId: "sess-1" });

    expect(calls).toEqual([{ path: "apply", body: { session_id: "sess-1" } }]);
  });
});

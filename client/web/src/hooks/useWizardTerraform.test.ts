// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { SessionProvider, useSession } from "@/contexts/SessionContext";
import { useWizardTerraform } from "./useWizardTerraform";
import { invalidateSessionsCache } from "@/services/core/sessionsCache";
import type { SessionPayloadResponse } from "@/types/api";

vi.mock("@/services/core/sessionsCache", () => ({
  invalidateSessionsCache: vi.fn(),
}));

function Wrapper({ children }: { children: React.ReactNode }) {
  return React.createElement(
    MemoryRouter,
    { initialEntries: ["/home"] },
    React.createElement(SessionProvider, null, children),
  );
}

function makePayload(
  overrides?: Partial<SessionPayloadResponse>,
): SessionPayloadResponse {
  return {
    id: "session-123",
    response: "Generated terraform code here",
    main_history: { user: "create a vm", assistant: "Here is your VM" },
    full_history: [{ role: "user", content: "create a vm" }],
    environment: "dev",
    cloud: "azure",
    project: "my-project",
    validation: true,
    branch_name: "nebula/session-123",
    terraform_plan: "plan output",
    terraform_targets: ["azurerm_resource_group.main"],
    terraform_report: null,
    pipeline_url: null,
    apply_allowed: true,
    ...overrides,
  };
}

describe("useWizardTerraform", () => {
  beforeEach(() => {
    vi.mocked(invalidateSessionsCache).mockClear();
  });

  it("handleCompleted updates code in session", () => {
    const { result } = renderHook(
      () => ({
        terraform: useWizardTerraform(),
        session: useSession(),
      }),
      { wrapper: Wrapper },
    );

    const payload = makePayload({ response: "resource block here" });

    act(() => result.current.terraform.handleCompleted(payload));

    expect(result.current.session.session.code).toBe("resource block here");
  });

  it("handleApplyCompleted sets applyResults in session", () => {
    const { result } = renderHook(
      () => ({
        terraform: useWizardTerraform(),
        session: useSession(),
      }),
      { wrapper: Wrapper },
    );

    const payload = makePayload({
      id: "apply-session",
      response: "Apply output",
      pipeline_url: "https://pipeline.example.com/run/42",
    });

    act(() => result.current.terraform.handleApplyCompleted(payload));

    const applyResults = result.current.session.session.applyResults;
    expect(applyResults).toBeDefined();
    expect(applyResults!.sessionId).toBe("apply-session");
    expect(applyResults!.status).toBe("Unknown");
    expect(applyResults!.message).toBe("Apply output");
    expect(applyResults!.resultsUrl).toBe(
      "https://pipeline.example.com/run/42",
    );
  });

  it("handleApplyCompleted uses terraform_report.status when available", () => {
    const { result } = renderHook(
      () => ({
        terraform: useWizardTerraform(),
        session: useSession(),
      }),
      { wrapper: Wrapper },
    );

    const payload = makePayload({
      terraform_report: {
        status: "Success",
        summary: {
          total_resources: 1,
          created: 1,
          updated: 0,
          destroyed: 0,
          failed: 0,
        },
        execution_summary: "Applied successfully",
        resource_changes: [],
        recommendations: [],
      } as never,
    });

    act(() => result.current.terraform.handleApplyCompleted(payload));

    expect(result.current.session.session.applyResults!.status).toBe(
      "Success",
    );
  });

  it("handleCompleted invalidates the sessions cache", () => {
    const { result } = renderHook(
      () => ({ terraform: useWizardTerraform() }),
      { wrapper: Wrapper },
    );

    act(() => result.current.terraform.handleCompleted(makePayload()));

    expect(invalidateSessionsCache).toHaveBeenCalledOnce();
  });

  it("handleApplyCompleted invalidates the sessions cache", () => {
    const { result } = renderHook(
      () => ({ terraform: useWizardTerraform() }),
      { wrapper: Wrapper },
    );

    act(() => result.current.terraform.handleApplyCompleted(makePayload()));

    expect(invalidateSessionsCache).toHaveBeenCalledOnce();
  });
});

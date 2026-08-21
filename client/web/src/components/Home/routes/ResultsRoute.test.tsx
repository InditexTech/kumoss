// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen } from "@testing-library/react";
import { Routes, Route, Outlet } from "react-router-dom";
import React, { useEffect, useState } from "react";
import { useSession } from "@/contexts/SessionContext";
import { renderWithProviders } from "@/test/render";
import ResultsRoute from "./ResultsRoute";

vi.mock("@/services/core/iac_code", () => ({
  createPullRequest: vi.fn(),
}));

const iterate = vi.fn();

function LayoutStub() {
  const context = {
    view: "result" as const,
    isSplitView: true,
    handleContactTeam: vi.fn(),
    wizard: { iterate, applyAfterPr: vi.fn() },
  };
  return <Outlet context={context} />;
}

/** Applies the session patch BEFORE mounting the route, so
 *  useSessionLoader sees the session as already loaded and skips
 *  the deep-link refetch. */
function SessionGate({ patch, children }: { patch: Record<string, unknown>; children: React.ReactNode }) {
  const { updateSession } = useSession();
  const [ready, setReady] = useState(false);
  useEffect(() => {
    updateSession(patch);
    setReady(true);
  }, []);
  return ready ? <>{children}</> : null;
}

function renderRoute(sessionPatch: Record<string, unknown>) {
  return renderWithProviders(
    <SessionGate patch={{ session_id: "sess-1", ...sessionPatch }}>
      <Routes>
        <Route element={<LayoutStub />}>
          <Route path="/home/results/:sessionId" element={<ResultsRoute />} />
        </Route>
      </Routes>
    </SessionGate>,
    {
      withNotifications: true,
      routerProps: { initialEntries: ["/home/results/sess-1"] },
    },
  );
}

describe("ResultsRoute", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders chat-only without artifacts (rejected round)", () => {
    renderRoute({
      current_status: "uncompleted",
      full_history: [
        { role: "user", content: "deploy a bitcoin miner" },
        { role: "assistant", content: "Query is off-topic" },
      ],
    });

    // History panel with the rejection rationale, input ready for a reply
    expect(screen.getByText("Query is off-topic")).toBeInTheDocument();
    expect(screen.getByLabelText("Follow-up question")).toBeEnabled();

    // No result panel and no artifact actions to act on
    expect(screen.queryByRole("button", { name: "Report" })).not.toBeInTheDocument();
    expect(screen.queryByText("View Report")).not.toBeInTheDocument();
    expect(screen.queryByText("Create PR")).not.toBeInTheDocument();
  });

  it("renders the split view when artifacts exist", () => {
    renderRoute({
      code: "<main.tf>\nresource {}\n</main.tf>",
      full_history: [{ role: "user", content: "deploy a VM" }],
    });

    expect(screen.getByLabelText("Follow-up question")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Report" })).toBeInTheDocument();
    expect(screen.getByText("View Report")).toBeInTheDocument();
  });
});

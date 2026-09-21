// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Routes, Route, Outlet, useLocation } from "react-router-dom";
import React, { useEffect, useState } from "react";
import { useSession } from "@/contexts/SessionContext";
import { renderWithProviders } from "@/test/render";
import { mergePullRequest } from "@/services/core/iac_code";
import ResultsRoute from "./ResultsRoute";

vi.mock("@/services/core/iac_code", () => ({
  createPullRequest: vi.fn(),
  mergePullRequest: vi.fn(),
}));

const mockMergePr = vi.mocked(mergePullRequest);
const iterate = vi.fn();
const applyAfterPr = vi.fn();

function LayoutStub() {
  const context = {
    view: "result" as const,
    isSplitView: true,
    handleContactTeam: vi.fn(),
    wizard: { iterate, applyAfterPr },
  };
  return <Outlet context={context} />;
}

/** Surfaces the live URL so tests can assert on navigation side effects. */
function LocationProbe() {
  const { pathname, search } = useLocation();
  return <div data-testid="location">{`${pathname}${search}`}</div>;
}

/** Applies the session patch BEFORE mounting the route, so
 *  useSessionLoader sees the session as already loaded and skips
 *  the deep-link refetch. */
function SessionGate({ patch, pr, children }: {
  patch: Record<string, unknown>;
  pr?: Record<string, unknown>;
  children: React.ReactNode;
}) {
  const { updateSession, updatePrDetails } = useSession();
  const [ready, setReady] = useState(false);
  useEffect(() => {
    updateSession(patch);
    if (pr) updatePrDetails(pr);
    setReady(true);
  }, []);
  return ready ? <>{children}</> : null;
}

function renderRoute(
  sessionPatch: Record<string, unknown>,
  options?: { pr?: Record<string, unknown>; entry?: string },
) {
  return renderWithProviders(
    <SessionGate patch={{ uuid: "sess-1", ...sessionPatch }} pr={options?.pr}>
      <LocationProbe />
      <Routes>
        <Route element={<LayoutStub />}>
          <Route path="/home/results/:sessionId" element={<ResultsRoute />} />
        </Route>
      </Routes>
    </SessionGate>,
    {
      withNotifications: true,
      routerProps: {
        initialEntries: [options?.entry ?? "/home/results/sess-1"],
      },
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
      history: [
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

  it("keeps the split view for a rejected iteration with prior artifacts", () => {
    renderRoute({
      current_status: "uncompleted",
      code: "<main.tf>\nresource {}\n</main.tf>",
      history: [
        { role: "user", content: "deploy a VM" },
        { role: "assistant", content: "Query is off-topic" },
      ],
    });

    expect(screen.getByText("Query is off-topic")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Report" })).toBeInTheDocument();
    expect(screen.getByText("View Report")).toBeInTheDocument();
  });

  it("renders the split view when artifacts exist", () => {
    renderRoute({
      code: "<main.tf>\nresource {}\n</main.tf>",
      history: [{ role: "user", content: "deploy a VM" }],
    });

    expect(screen.getByLabelText("Follow-up question")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Report" })).toBeInTheDocument();
    expect(screen.getByText("View Report")).toBeInTheDocument();
  });

  describe("PR approval", () => {
    const CONFIRMING = "/home/results/sess-1?view=pr-confirming";

    function renderPrFlow(operation: string) {
      return renderRoute(
        { operation, code: "<main.tf>\nresource {}\n</main.tf>" },
        { pr: { number: 42, url: "https://dev.azure.com/pr/42" }, entry: CONFIRMING },
      );
    }

    // The defect: merging a drift PR *is* the remediation, so firing the apply
    // afterwards re-runs work the merge just completed.
    it("does not trigger an apply after merging a drift PR", async () => {
      const user = userEvent.setup();
      mockMergePr.mockResolvedValue(undefined);
      renderPrFlow("drift");

      await user.click(screen.getByText("Confirm and Merge"));

      await waitFor(() => expect(mockMergePr).toHaveBeenCalledWith({ session_id: "sess-1" }));
      expect(applyAfterPr).not.toHaveBeenCalled();
    });

    it("returns to the report view after merging a drift PR", async () => {
      const user = userEvent.setup();
      mockMergePr.mockResolvedValue(undefined);
      renderPrFlow("drift");

      await user.click(screen.getByText("Confirm and Merge"));

      await waitFor(() =>
        expect(screen.getByTestId("location")).toHaveTextContent("/home/results/sess-1"),
      );
      expect(screen.getByTestId("location")).not.toHaveTextContent("view=pr");
    });

    // A hand-edited ?view= must not resurrect the approval screen for a PR
    // that is already merged — the second merge would fail against a real
    // git provider.
    it("ignores a ?view deep link for an already merged drift session", () => {
      renderRoute(
        { operation: "drift", code: "<main.tf>\nresource {}\n</main.tf>" },
        {
          pr: { number: 42, url: "https://dev.azure.com/pr/42", merged: true },
          entry: CONFIRMING,
        },
      );

      expect(screen.queryByText("Confirm and Merge")).not.toBeInTheDocument();
      expect(screen.getByText("View Report")).toBeInTheDocument();
    });

    it("still triggers the apply after merging a generate PR", async () => {
      const user = userEvent.setup();
      mockMergePr.mockResolvedValue(undefined);
      renderPrFlow("generate");

      await user.click(screen.getByText("Confirm and Apply"));

      await waitFor(() => expect(applyAfterPr).toHaveBeenCalled());
    });
  });
});

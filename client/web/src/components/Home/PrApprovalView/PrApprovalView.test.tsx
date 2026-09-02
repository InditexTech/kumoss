// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect, vi, beforeEach } from "vitest";
import { act, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React, { useEffect } from "react";
import { useSession } from "@/contexts/SessionContext";
import { renderWithProviders } from "@/test/render";
import { mergePullRequest } from "@/services/core/iac_code";
import { isPullRequestMerged } from "@/services/pullRequestState";
import type { PrApprovalStep } from "@/types/ui";
import PrApprovalView from "./PrApprovalView";

vi.mock("@/services/core/iac_code", () => ({
  mergePullRequest: vi.fn(),
  createPullRequest: vi.fn(),
}));

const mockMergePr = vi.mocked(mergePullRequest);

function SessionInjector({ session, pr, children }: {
  session?: Record<string, unknown>;
  pr?: Record<string, unknown>;
  children: React.ReactNode;
}) {
  const { updateSession, updatePrDetails } = useSession();
  useEffect(() => {
    if (session) updateSession(session);
    if (pr) updatePrDetails(pr);
  }, []);
  return <>{children}</>;
}

function PrStateProbe() {
  const { prDetails } = useSession();
  return <output data-testid="pr-merged">{String(prDetails.merged)}</output>;
}

function renderPr(
  step: PrApprovalStep = "initial",
  overrides?: {
    sessionPatch?: Record<string, unknown>;
    prPatch?: Record<string, unknown>;
    props?: Partial<React.ComponentProps<typeof PrApprovalView>>;
  },
) {
  const defaultProps = {
    step,
    onStepChange: vi.fn(),
    onApprove: vi.fn(),
    onBackToReport: vi.fn(),
    onContactTeam: vi.fn(),
    ...overrides?.props,
  };

  const needsInjection = overrides?.sessionPatch || overrides?.prPatch;
  const component = (
    <>
      <PrApprovalView {...defaultProps} />
      <PrStateProbe />
    </>
  );
  const ui = needsInjection
    ? <SessionInjector session={overrides?.sessionPatch} pr={overrides?.prPatch}>{component}</SessionInjector>
    : component;

  return { ...renderWithProviders(ui, { withNotifications: true }), props: defaultProps };
}

describe("PrApprovalView", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
  });

  it("renders initial step with PR ready message", () => {
    renderPr("initial", { prPatch: { id: 42, prUrl: "https://dev.azure.com/pr/42" } });

    expect(screen.getByText("Here is your Pull Request.")).toBeInTheDocument();
    expect(screen.getByText("Approve PR and Apply")).toBeInTheDocument();
  });

  it("shows View PR link when prUrl is set and allowed", () => {
    renderPr("initial", { prPatch: { id: 42, prUrl: "https://dev.azure.com/pr/42" } });
    expect(screen.getByText("View Pull Request")).toBeInTheDocument();
  });

  it("renders blocked state when apply_allowed is false", () => {
    renderPr("initial", {
      sessionPatch: { apply_allowed: false },
      prPatch: { id: 42 },
    });

    expect(screen.getByText("Resource Deletion Detected")).toBeInTheDocument();
    expect(screen.getByText("Back to Report")).toBeInTheDocument();
    expect(screen.getByText("Contact Team")).toBeInTheDocument();
  });

  it("calls onBackToReport when Back to Report clicked in blocked state", async () => {
    const user = userEvent.setup();
    const { props } = renderPr("initial", {
      sessionPatch: { apply_allowed: false },
      prPatch: { id: 42 },
    });

    await user.click(screen.getByText("Back to Report"));
    expect(props.onBackToReport).toHaveBeenCalled();
  });

  it("clicking Approve PR and Apply advances to confirming step", async () => {
    const user = userEvent.setup();
    const { props } = renderPr("initial", { prPatch: { id: 42 } });

    await user.click(screen.getByText("Approve PR and Apply"));
    expect(props.onStepChange).toHaveBeenCalledWith("confirming");
  });

  it("merges drift pull requests directly without starting the apply flow", async () => {
    const user = userEvent.setup();
    mockMergePr.mockResolvedValue(undefined);
    const { props } = renderPr("confirming", {
      sessionPatch: { session_id: "sess-1", operation: "drift" },
      prPatch: { sessionId: "sess-1", id: 42 },
    });

    expect(screen.getByText("Merge Pull Request")).toBeInTheDocument();
    expect(screen.queryByText("Confirm and Apply")).not.toBeInTheDocument();

    await user.click(screen.getByText("Merge Pull Request"));

    expect(mockMergePr).toHaveBeenCalledWith({ session_id: "sess-1" });
    expect(props.onBackToReport).toHaveBeenCalled();
    expect(props.onApprove).not.toHaveBeenCalled();
    expect(props.onStepChange).not.toHaveBeenCalled();
    expect(screen.getByTestId("pr-merged")).toHaveTextContent("true");
    expect(isPullRequestMerged("sess-1", 42)).toBe(true);
  });

  it("does not offer to merge an already merged drift pull request", () => {
    renderPr("initial", {
      sessionPatch: { session_id: "sess-1", operation: "drift" },
      prPatch: { id: 42, merged: true },
    });

    expect(screen.getByText("Pull Request Merged")).toBeInTheDocument();
    expect(screen.queryByText("Merge Pull Request")).not.toBeInTheDocument();
  });

  it("blocks back navigation and ignores stale callbacks while merging", async () => {
    const user = userEvent.setup();
    let resolveMerge: () => void;
    mockMergePr.mockReturnValue(
      new Promise<void>((resolve) => {
        resolveMerge = resolve;
      }),
    );
    const { props, unmount } = renderPr("initial", {
      sessionPatch: { session_id: "sess-1", operation: "drift" },
      prPatch: { sessionId: "sess-1", id: 42 },
    });

    await user.click(screen.getByText("Merge Pull Request"));
    expect(screen.getByText("Back to Report")).toBeDisabled();

    unmount();
    await act(async () => resolveMerge!());

    expect(props.onBackToReport).not.toHaveBeenCalled();
  });

  it("renders confirming step with confirm and request review buttons", () => {
    renderPr("confirming", { prPatch: { id: 42 } });

    expect(screen.getByText("Confirmation")).toBeInTheDocument();
    expect(screen.getByText("Confirm and Apply")).toBeInTheDocument();
    expect(screen.getByText("Request Review")).toBeInTheDocument();
  });

  it("confirm in confirming step with high impact shows warning", async () => {
    const user = userEvent.setup();
    const { props } = renderPr("confirming", {
      sessionPatch: {
        terraform_report: {
          potential_impact: { banner: { level: "high", title: "Major", description: "Destroys resources" } },
        },
      },
      prPatch: { id: 42 },
    });

    await user.click(screen.getByText("Confirm and Apply"));
    expect(props.onStepChange).toHaveBeenCalledWith("high_impact_warning");
  });

  it("confirm in confirming step without high impact calls mergePullRequest", async () => {
    const user = userEvent.setup();
    mockMergePr.mockResolvedValue(undefined);
    const { props } = renderPr("confirming", {
      sessionPatch: { session_id: "sess-1" },
      prPatch: { id: 42 },
    });

    await user.click(screen.getByText("Confirm and Apply"));
    expect(mockMergePr).toHaveBeenCalledWith({ session_id: "sess-1" });
    expect(props.onApprove).toHaveBeenCalled();
  });

  it("renders high_impact_warning step with warning banner", () => {
    renderPr("high_impact_warning", {
      sessionPatch: {
        terraform_report: {
          potential_impact: { banner: { level: "high", title: "Major", description: "Destroys production resources" } },
        },
      },
      prPatch: { id: 42 },
    });

    expect(screen.getByText("High Impact Deployment")).toBeInTheDocument();
    expect(screen.getByText("Destroys production resources")).toBeInTheDocument();
    expect(screen.getByText("I understand, Apply")).toBeInTheDocument();
  });

  it("API error shows notification and resets to initial", async () => {
    const user = userEvent.setup();
    mockMergePr.mockRejectedValue(new Error("Server error"));
    const { props } = renderPr("confirming", {
      sessionPatch: { session_id: "sess-1" },
      prPatch: { id: 42 },
    });

    await user.click(screen.getByText("Confirm and Apply"));
    expect(mockMergePr).toHaveBeenCalled();
    expect(props.onStepChange).toHaveBeenCalledWith("initial");
  });

  it("Approve button is disabled without prDetails.id", () => {
    renderPr("initial");
    expect(screen.getByText("Approve PR and Apply")).toBeDisabled();
  });

  it("Request Review calls onContactTeam", async () => {
    const user = userEvent.setup();
    const { props } = renderPr("confirming", { prPatch: { id: 42 } });

    await user.click(screen.getByText("Request Review"));
    expect(props.onContactTeam).toHaveBeenCalled();
  });
});

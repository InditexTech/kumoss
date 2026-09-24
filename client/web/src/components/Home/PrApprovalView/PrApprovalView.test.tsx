// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React, { useEffect } from "react";
import { useSession } from "@/contexts/SessionContext";
import { renderWithProviders } from "@/test/render";
import { mergePullRequest } from "@/services/core/iac_code";
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
  const component = <PrApprovalView {...defaultProps} />;
  const ui = needsInjection
    ? <SessionInjector session={overrides?.sessionPatch} pr={overrides?.prPatch}>{component}</SessionInjector>
    : component;

  return { ...renderWithProviders(ui, { withNotifications: true }), props: defaultProps };
}

describe("PrApprovalView", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders initial step with PR ready message", () => {
    renderPr("initial", { prPatch: { number: 42, url: "https://dev.azure.com/pr/42" } });

    expect(screen.getByText("Here is your Pull Request.")).toBeInTheDocument();
    expect(screen.getByText("Approve PR and Apply")).toBeInTheDocument();
  });

  it("shows View PR link when url is set and allowed", () => {
    renderPr("initial", { prPatch: { number: 42, url: "https://dev.azure.com/pr/42" } });
    expect(screen.getByText("View Pull Request")).toBeInTheDocument();
  });

  it("renders blocked state when is_blocked is true", () => {
    renderPr("initial", {
      sessionPatch: { is_blocked: true },
      prPatch: { number: 42 },
    });

    expect(screen.getByText("Deployment Blocked")).toBeInTheDocument();
    expect(screen.queryByText("Why")).not.toBeInTheDocument();
    expect(screen.getByText("Back to Report")).toBeInTheDocument();
    expect(screen.getByText("Contact Team")).toBeInTheDocument();
    expect(screen.queryByText("Approve PR and Apply")).not.toBeInTheDocument();
    expect(screen.queryByText("Confirm and Apply")).not.toBeInTheDocument();
  });

  it("blocked state lists the high impact reason", () => {
    renderPr("confirming", {
      sessionPatch: {
        is_blocked: true,
        terraform_report: {
          potential_impact: { banner: { level: "high", title: "Major", description: "Destroys production resources" } },
        },
      },
      prPatch: { number: 42 },
    });

    expect(screen.getByText("High impact")).toBeInTheDocument();
    expect(screen.getByText("Destroys production resources")).toBeInTheDocument();
    expect(screen.queryByText("Compliance")).not.toBeInTheDocument();
    expect(screen.queryByText("Confirm and Apply")).not.toBeInTheDocument();
  });

  it("blocked state lists only the blocking violations until expanded", async () => {
    const user = userEvent.setup();
    renderPr("initial", {
      sessionPatch: {
        is_blocked: true,
        compliance_report: {
          passed: false,
          summary: "Public ingress is not allowed",
          violations: [
            { rule_id: "TAG-002", severity: "warning", message: "Missing owner tag" },
            {
              rule_id: "NET-001",
              severity: "critical",
              resource: "azurerm_network_security_rule.ssh",
              message: "0.0.0.0/0 on port 22",
              suggested_fix: "Restrict the source address prefix",
            },
          ],
        },
      },
      prPatch: { number: 42 },
    });

    expect(screen.getByText("Compliance")).toBeInTheDocument();
    expect(screen.queryByText("High impact")).not.toBeInTheDocument();
    expect(screen.getByText("1 blocking violation")).toBeInTheDocument();
    expect(screen.getByText("NET-001")).toBeInTheDocument();
    expect(screen.getByText("azurerm_network_security_rule.ssh")).toBeInTheDocument();
    expect(screen.getByText("0.0.0.0/0 on port 22")).toBeInTheDocument();
    expect(screen.queryByText("TAG-002")).not.toBeInTheDocument();
    expect(
      screen.queryByText("Suggested fix: Restrict the source address prefix"),
    ).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Show all findings (2)" }));

    expect(screen.getByText("TAG-002")).toBeInTheDocument();
    expect(
      screen.getByText("Suggested fix: Restrict the source address prefix"),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Hide findings" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
  });

  it("blocked state omits the toggle when every finding is already shown", () => {
    renderPr("initial", {
      sessionPatch: {
        is_blocked: true,
        compliance_report: {
          passed: false,
          violations: [
            { rule_id: "NET-001", severity: "critical", message: "0.0.0.0/0 on port 22" },
          ],
        },
      },
      prPatch: { number: 42 },
    });

    expect(screen.getByText("NET-001")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Show all findings/ })).not.toBeInTheDocument();
  });

  it("blocked state lists both reasons when the plan is high impact and compliance failed", () => {
    renderPr("initial", {
      sessionPatch: {
        is_blocked: true,
        terraform_report: {
          potential_impact: { banner: { level: "high", title: "Major", description: "Destroys production resources" } },
        },
        compliance_report: {
          passed: false,
          summary: "Public ingress is not allowed",
          violations: [
            { rule_id: "NET-001", severity: "critical", message: "0.0.0.0/0 on port 22" },
          ],
        },
      },
      prPatch: { number: 42 },
    });

    expect(screen.getByText("Deployment Blocked")).toBeInTheDocument();
    expect(screen.getByText("Destroys production resources")).toBeInTheDocument();
    expect(screen.getByText("NET-001")).toBeInTheDocument();
  });

  it("blocked state hides a passed compliance check", () => {
    renderPr("initial", {
      sessionPatch: {
        is_blocked: true,
        compliance_report: { passed: true, summary: "All rules satisfied", violations: [] },
      },
      prPatch: { number: 42 },
    });

    expect(screen.getByText("Deployment Blocked")).toBeInTheDocument();
    expect(screen.queryByText("Compliance")).not.toBeInTheDocument();
    expect(screen.queryByText("All rules satisfied")).not.toBeInTheDocument();
  });

  it("calls onBackToReport when Back to Report clicked in blocked state", async () => {
    const user = userEvent.setup();
    const { props } = renderPr("initial", {
      sessionPatch: { is_blocked: true },
      prPatch: { number: 42 },
    });

    await user.click(screen.getByText("Back to Report"));
    expect(props.onBackToReport).toHaveBeenCalled();
  });

  it("clicking Approve PR and Apply advances to confirming step", async () => {
    const user = userEvent.setup();
    const { props } = renderPr("initial", { prPatch: { number: 42 } });

    await user.click(screen.getByText("Approve PR and Apply"));
    expect(props.onStepChange).toHaveBeenCalledWith("confirming");
  });

  it("renders confirming step with confirm and request review buttons", () => {
    renderPr("confirming", { prPatch: { number: 42 } });

    expect(screen.getByText("Confirmation")).toBeInTheDocument();
    expect(screen.getByText("Confirm and Apply")).toBeInTheDocument();
    expect(screen.getByText("Request Review")).toBeInTheDocument();
  });

  it("confirm in confirming step with an unblocked high impact report still merges", async () => {
    const user = userEvent.setup();
    mockMergePr.mockResolvedValue(undefined);
    const { props } = renderPr("confirming", {
      sessionPatch: {
        uuid: "sess-1",
        is_blocked: false,
        terraform_report: {
          potential_impact: { banner: { level: "high", title: "Major", description: "Destroys resources" } },
        },
      },
      prPatch: { number: 42 },
    });

    await user.click(screen.getByText("Confirm and Apply"));
    expect(mockMergePr).toHaveBeenCalledWith({ session_id: "sess-1" });
    expect(props.onApprove).toHaveBeenCalled();
  });

  it("confirm in confirming step without high impact calls mergePullRequest", async () => {
    const user = userEvent.setup();
    mockMergePr.mockResolvedValue(undefined);
    const { props } = renderPr("confirming", {
      sessionPatch: { uuid: "sess-1" },
      prPatch: { number: 42 },
    });

    await user.click(screen.getByText("Confirm and Apply"));
    expect(mockMergePr).toHaveBeenCalledWith({ session_id: "sess-1" });
    expect(props.onApprove).toHaveBeenCalled();
  });

  it("API error shows notification and resets to initial", async () => {
    const user = userEvent.setup();
    mockMergePr.mockRejectedValue(new Error("Server error"));
    const { props } = renderPr("confirming", {
      sessionPatch: { uuid: "sess-1" },
      prPatch: { number: 42 },
    });

    await user.click(screen.getByText("Confirm and Apply"));
    expect(mockMergePr).toHaveBeenCalled();
    expect(props.onStepChange).toHaveBeenCalledWith("initial");
  });

  it("Approve button is disabled without prDetails.number", () => {
    renderPr("initial");
    expect(screen.getByText("Approve PR and Apply")).toBeDisabled();
  });

  it("Request Review calls onContactTeam", async () => {
    const user = userEvent.setup();
    const { props } = renderPr("confirming", { prPatch: { number: 42 } });

    await user.click(screen.getByText("Request Review"));
    expect(props.onContactTeam).toHaveBeenCalled();
  });

  // For a drift session the merge IS the deliverable — no apply follows it — so
  // the wording must not promise one. Gated on session.operation, not useMode().
  it("labels the initial step for merging in a drift session", () => {
    renderPr("initial", {
      sessionPatch: { uuid: "sess-1", operation: "drift" },
      prPatch: { number: 42 },
    });

    expect(screen.getByText("Approve and Merge PR")).toBeInTheDocument();
    expect(screen.queryByText("Approve PR and Apply")).not.toBeInTheDocument();
  });

  it("labels the confirming step for merging in a drift session", () => {
    renderPr("confirming", {
      sessionPatch: { uuid: "sess-1", operation: "drift" },
      prPatch: { number: 42 },
    });

    expect(screen.getByText("Confirm and Merge")).toBeInTheDocument();
    expect(screen.queryByText("Confirm and Apply")).not.toBeInTheDocument();
  });

  it("still merges and notifies the caller in a drift session", async () => {
    const user = userEvent.setup();
    mockMergePr.mockResolvedValue(undefined);
    const { props } = renderPr("confirming", {
      sessionPatch: { uuid: "sess-1", operation: "drift" },
      prPatch: { number: 42 },
    });

    await user.click(screen.getByText("Confirm and Merge"));
    expect(mockMergePr).toHaveBeenCalledWith({ session_id: "sess-1" });
    expect(props.onApprove).toHaveBeenCalled();
  });
});

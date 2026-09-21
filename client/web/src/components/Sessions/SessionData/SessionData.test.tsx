// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect, vi } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { makeSessionDetail, makeRound, makeStatus } from "@/mocks/state";
import { renderWithProviders } from "@/test/render";
import SessionData from "./SessionData";

function at(second: number): string {
  return new Date(Date.UTC(2026, 0, 1, 12, 0, second)).toISOString();
}

/** True when `a` precedes `b` in document order. */
function isBefore(a: Element, b: Element): boolean {
  return !!(
    a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING
  );
}

/**
 * A round mid-report: two artifact-bearing stages already behind it, so the
 * timeline has to interleave. Left non-terminal on purpose — a `completed`
 * round would render "Completed" both as its own event and as the session's
 * terminal entry.
 */
function interleavedSession() {
  return makeSessionDetail({
    current_status: "report",
    in_flight: true,
    operation: "drift",
    rounds: [
      makeRound({
        statuses: [
          makeStatus("filtering", null, at(0)),
          makeStatus("generating", null, at(10)),
          makeStatus("validating", null, at(30)),
          makeStatus("report", null, at(50)),
        ],
        code_changes: [
          {
            id: 1,
            file_name: "main.tf",
            url: "https://storage.example.com/main.tf",
            content_type: "text/plain",
            file_size_bytes: 10,
            created_at: at(15),
          },
        ],
        plans: [
          {
            id: 2,
            targets: [],
            url: "https://storage.example.com/plan",
            content_type: "text/plain",
            file_size_bytes: 10,
            created_at: at(35),
          },
        ],
        reports: [
          {
            id: 3,
            type: "drift",
            url: "https://storage.example.com/report",
            content_type: "application/json",
            file_size_bytes: 10,
            created_at: at(55),
          },
        ],
      }),
    ],
  });
}

describe("SessionData additional info", () => {
  it("shows the full session id", () => {
    const uuid = "9b2e4c1a-7d3f-4e55-a1b2-c3d4e5f60789";
    renderWithProviders(<SessionData session={makeSessionDetail({ uuid })} />);

    expect(screen.getByText("Session ID")).toBeInTheDocument();
    expect(screen.getByText(uuid)).toBeInTheDocument();
  });
});

describe("SessionData timeline", () => {
  it("nests each artifact under the status that produced it", () => {
    renderWithProviders(<SessionData session={interleavedSession()} />);

    const rows = [
      "Filtering",
      "Generating",
      "main.tf",
      "Validating",
      "Terraform Plan",
      "Report",
      "Drift Report",
    ].map((label) => screen.getByText(label));

    for (let i = 0; i < rows.length - 1; i++) {
      expect(isBefore(rows[i], rows[i + 1])).toBe(true);
    }
  });

  it("no longer splits a round into status and artifact groups", () => {
    renderWithProviders(<SessionData session={interleavedSession()} />);

    expect(screen.queryByText("Statuses")).toBeNull();
    expect(screen.queryByText("Artifacts")).toBeNull();
  });

  it("renders a reconciling pass with its plan", () => {
    const session = makeSessionDetail({
      current_status: "reconciling",
      in_flight: true,
      operation: "drift",
      rounds: [
        makeRound({
          statuses: [
            makeStatus("validating", null, at(0)),
            makeStatus("reconciling", null, at(20)),
          ],
          plans: [
            {
              id: 7,
              targets: [],
              url: "https://storage.example.com/drift",
              content_type: "text/plain",
              file_size_bytes: 10,
              created_at: at(25),
            },
          ],
        }),
      ],
    });
    renderWithProviders(<SessionData session={session} />);

    const phase = screen.getByText("Reconciling");
    const plan = screen.getByText("Terraform Plan");
    expect(phase).toBeInTheDocument();
    expect(isBefore(phase, plan)).toBe(true);
  });
});

/**
 * A drift round whose plan is scoped to named resources. Partial drift is
 * the flow that actually populates `targets`; a validation-loop plan
 * carries the validator's `terraform_targets`, which are usually empty.
 */
function targetedSession(targets: string[]) {
  return makeSessionDetail({
    current_status: "validating",
    in_flight: true,
    operation: "drift",
    rounds: [
      makeRound({
        statuses: [makeStatus("validating", null, at(0))],
        plans: [
          {
            id: 11,
            targets,
            url: "https://storage.example.com/plans/plan-abc.txt",
            content_type: "text/plain",
            file_size_bytes: 10,
            created_at: at(5),
          },
        ],
      }),
    ],
  });
}

describe("SessionData plan targets", () => {
  it("lists a plan's targets beneath its label", () => {
    const session = targetedSession([
      "azurerm_storage_account.main",
      "azurerm_resource_group.rg",
    ]);
    renderWithProviders(<SessionData session={session} />);

    const label = screen.getByText("Terraform Plan");
    const targets = screen.getByText(
      "Targets: azurerm_storage_account.main, azurerm_resource_group.rg",
    );
    expect(isBefore(label, targets)).toBe(true);
  });

  it("keeps the full list reachable when the line is clamped", () => {
    const session = targetedSession(["a.one", "b.two"]);
    renderWithProviders(<SessionData session={session} />);

    expect(screen.getByText("Targets: a.one, b.two")).toHaveAttribute(
      "title",
      "a.one, b.two",
    );
  });

  it("renders no targets line for a plan that carries none", () => {
    renderWithProviders(<SessionData session={interleavedSession()} />);

    expect(screen.getByText("Terraform Plan")).toBeInTheDocument();
    expect(screen.queryByText(/^Targets:/)).toBeNull();
  });
});

describe("SessionData apply lock", () => {
  it("renders a read-only label when no lock handler is given", () => {
    renderWithProviders(
      <SessionData session={makeSessionDetail({ is_blocked: false })} />,
    );

    expect(screen.getByText("Apply Open")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /apply open/i })).toBeNull();
  });

  it("renders a button that calls the lock handler", async () => {
    const onToggleLock = vi.fn();
    renderWithProviders(
      <SessionData
        session={makeSessionDetail({ is_blocked: true })}
        onToggleLock={onToggleLock}
      />,
    );

    const button = screen.getByRole("button", { name: /apply locked/i });
    expect(button).toHaveAttribute("title", "Unlock apply");
    await userEvent.click(button);
    expect(onToggleLock).toHaveBeenCalledTimes(1);
  });
});

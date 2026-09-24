// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect, vi } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { makeRound, makeSessionDetail } from "@/mocks/state";
import { renderWithProviders } from "@/test/render";
import SessionData from "./SessionData";

describe("SessionData additional info", () => {
  it("shows the full session id", () => {
    const uuid = "9b2e4c1a-7d3f-4e55-a1b2-c3d4e5f60789";
    renderWithProviders(<SessionData session={makeSessionDetail({ uuid })} />);

    expect(screen.getByText("Session ID")).toBeInTheDocument();
    expect(screen.getByText(uuid)).toBeInTheDocument();
  });
});

describe("SessionData artifacts", () => {
  it("lists the round's compliance check alongside the other artifacts", () => {
    const session = makeSessionDetail({
      rounds: [
        makeRound({
          compliance: {
            id: 7,
            url: "https://storage.test/compliance.json",
            content_type: "application/json",
            file_size_bytes: 10,
            created_at: "2026-01-01T00:00:00Z",
            passed: false,
          },
        }),
      ],
    });
    renderWithProviders(<SessionData session={session} />);

    expect(screen.getByText("Compliance Check")).toBeInTheDocument();
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

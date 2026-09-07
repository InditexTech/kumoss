// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect, vi } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { makeSessionDetail } from "@/mocks/state";
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

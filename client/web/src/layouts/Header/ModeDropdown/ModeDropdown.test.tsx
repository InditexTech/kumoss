// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect, vi } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "@/test/render";
import type { OperationRole } from "@/types/api";
import ModeDropdown from "./ModeDropdown";

const auth = vi.hoisted(() => ({
  operationRole: null as OperationRole | null,
}));
vi.mock("@/contexts/AuthContext", () => ({ useAuth: () => auth }));

async function openDropdown() {
  renderWithProviders(<ModeDropdown />);
  await userEvent.click(screen.getByRole("combobox"));
  return screen.findAllByRole("option");
}

function option(name: RegExp) {
  return screen.getByRole("option", { name });
}

describe("ModeDropdown role gating", () => {
  it("disables import and drift modes for developers", async () => {
    auth.operationRole = "developer";
    await openDropdown();

    expect(option(/generate infrastructure/i)).not.toHaveAttribute(
      "aria-disabled",
      "true",
    );
    for (const name of [
      /import infrastructure/i,
      /full drift remediation/i,
      /partial drift remediation/i,
    ]) {
      const item = option(name);
      expect(item).toHaveAttribute("aria-disabled", "true");
      expect(item).toHaveTextContent("Requires the devops operation role.");
    }
  });

  it("enables every mode for devops", async () => {
    auth.operationRole = "devops";
    const options = await openDropdown();

    expect(options).toHaveLength(4);
    for (const item of options) {
      expect(item).not.toHaveAttribute("aria-disabled", "true");
    }
    expect(option(/import infrastructure/i)).toHaveTextContent(
      "Adds existing resources to manage them from the tool.",
    );
  });
});

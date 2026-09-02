// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import type { ReactNode } from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  MemoryRouter,
  Route,
  Routes,
  useLocation,
} from "react-router-dom";
import Header from "@/layouts/Header/Header";
import HomeLayout from "./HomeLayout";

const { mockReset } = vi.hoisted(() => ({
  mockReset: vi.fn(),
}));

vi.mock("./useHomeWizard", () => ({
  useHomeWizard: () => ({ reset: mockReset }),
}));

vi.mock("@/contexts/AuthContext", () => ({
  Authenticated: ({ children }: { children: ReactNode }) => children,
}));

vi.mock("@/components/ui", () => ({
  ErrorBoundary: ({ children }: { children: ReactNode }) => children,
  SupportButton: () => null,
}));

vi.mock("@/components/ConfigurationModal/ConfigurationModal", () => ({
  default: () => null,
}));

vi.mock("@/layouts/Header/ModeDropdown/ModeDropdown", () => ({
  default: () => null,
}));

function LocationProbe() {
  return <div data-testid="pathname">{useLocation().pathname}</div>;
}

describe("HomeLayout", () => {
  it("resets the wizard when the main logo returns home", async () => {
    const user = userEvent.setup();

    render(
      <MemoryRouter initialEntries={["/home/planning"]}>
        <Header />
        <LocationProbe />
        <Routes>
          <Route path="/home" element={<HomeLayout />}>
            <Route path="planning" element={<div>Planning</div>} />
            <Route index element={<div>Wizard</div>} />
          </Route>
        </Routes>
      </MemoryRouter>,
    );

    await user.click(screen.getByRole("link", { name: "NEBULA.AI" }));

    await waitFor(() => {
      expect(screen.getByTestId("pathname")).toHaveTextContent("/home");
      expect(mockReset).toHaveBeenCalledOnce();
    });
  });
});

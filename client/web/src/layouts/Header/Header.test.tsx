// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect, vi } from "vitest";
import { screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useSession } from "@/contexts/SessionContext";
import { renderWithProviders } from "@/test/render";
import Header from "./Header";

// The logo sits outside <Authenticated>, so leaving the auth-gated icons
// unrendered keeps the modals and the mode dropdown out of this test.
vi.mock("@/contexts/AuthContext", () => ({
  useAuth: () => ({ user: null, operationRole: null }),
  Authenticated: () => null,
}));

/** Renders the session's first query, and seeds it on demand. */
function SessionProbe() {
  const { session, updateSession } = useSession();
  return (
    <button onClick={() => updateSession({ first_query: "deploy a VM" })}>
      query:{session.first_query ?? "none"}
    </button>
  );
}

function renderHeader() {
  return renderWithProviders(
    <>
      <Header />
      <SessionProbe />
    </>,
  );
}

function logo() {
  return screen.getByRole("link", { name: /nebula/i });
}

describe("Header logo", () => {
  it("clears the collected information on click", async () => {
    renderHeader();

    await userEvent.click(screen.getByRole("button", { name: /query:/ }));
    expect(screen.getByRole("button", { name: "query:deploy a VM" })).toBeTruthy();

    await userEvent.click(logo());

    expect(screen.getByRole("button", { name: "query:none" })).toBeTruthy();
  });

  // A modifier click opens a new tab; the current tab must keep its state.
  it("keeps the collected information on a modifier click", async () => {
    renderHeader();

    await userEvent.click(screen.getByRole("button", { name: /query:/ }));

    fireEvent.click(logo(), { button: 0, ctrlKey: true });

    expect(screen.getByRole("button", { name: "query:deploy a VM" })).toBeTruthy();
  });
});

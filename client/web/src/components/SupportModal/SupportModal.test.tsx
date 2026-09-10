// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "@/mocks/server";
import { renderWithProviders } from "@/test/render";
import type { UserInfo } from "@/types";
import { STRINGS } from "@/constants/strings";
import SupportModal from "./SupportModal";

const auth = vi.hoisted(() => ({
  user: {
    id: 1,
    email: "someone@example.com",
    displayName: "Someone",
    operationRole: "developer",
    panelRole: null,
  } as UserInfo | null,
}));
vi.mock("@/contexts/AuthContext", () => ({ useAuth: () => auth }));

function renderModal(onClose = vi.fn()) {
  renderWithProviders(<SupportModal onClose={onClose} />, { withNotifications: true });
  return onClose;
}

describe("SupportModal", () => {
  it("keeps Send disabled until a question is typed", async () => {
    renderModal();
    const send = screen.getByRole("button", { name: STRINGS.supportModal.send });
    expect(send).toBeDisabled();

    await userEvent.type(screen.getByPlaceholderText(STRINGS.supportModal.placeholder), "help");
    expect(send).toBeEnabled();
  });

  it("rejects HTML without calling the backend", async () => {
    const onClose = renderModal();
    await userEvent.type(
      screen.getByPlaceholderText(STRINGS.supportModal.placeholder),
      "<script>alert(1)</script>",
    );
    await userEvent.click(screen.getByRole("button", { name: STRINGS.supportModal.send }));

    expect(await screen.findByText(STRINGS.supportModal.htmlError)).toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
  });

  it("sends a support.user_question notification and closes on success", async () => {
    let received: Record<string, unknown> | null = null;
    server.use(
      http.post("/api/v1/notifications", async ({ request }) => {
        received = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({ delivery_id: "d-1" }, { status: 202 });
      }),
    );
    const onClose = renderModal();

    await userEvent.type(
      screen.getByPlaceholderText(STRINGS.supportModal.placeholder),
      "How do I import an existing resource group?",
    );
    await userEvent.click(screen.getByRole("button", { name: STRINGS.supportModal.send }));

    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    expect(received).toMatchObject({
      kind: "support.user_question",
      severity: "info",
      subject: "Support question from someone@example.com",
      body: "How do I import an existing resource group?",
      context: { user_email: "someone@example.com", user_name: "Someone" },
    });
    // Recipients are derived by the core from the signed-in user.
    expect(received).not.toHaveProperty("audience");
    expect(await screen.findByText(STRINGS.supportModal.success)).toBeInTheDocument();
  });

  it("shows the backend detail and stays open when delivery fails", async () => {
    server.use(
      http.post("/api/v1/notifications", () =>
        HttpResponse.json(
          { detail: "Notification was not delivered." },
          { status: 502 },
        ),
      ),
    );
    const onClose = renderModal();

    await userEvent.type(screen.getByPlaceholderText(STRINGS.supportModal.placeholder), "help");
    await userEvent.click(screen.getByRole("button", { name: STRINGS.supportModal.send }));

    expect(await screen.findByText(/was not delivered/)).toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
  });
});

// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useSession } from "@/contexts/SessionContext";
import { renderWithProviders } from "@/test/render";
import ChatHistory from "./ChatHistory";
import React, { useEffect } from "react";

vi.mock("@/services/core/iac_code", () => ({
  createPullRequest: vi.fn(),
}));

function SessionInjector({ patch, children }: { patch: Record<string, unknown>; children: React.ReactNode }) {
  const { updateSession } = useSession();
  useEffect(() => { updateSession(patch); }, []);
  return <>{children}</>;
}

function renderChat(
  props?: Partial<React.ComponentProps<typeof ChatHistory>>,
  sessionPatch?: Record<string, unknown>,
) {
  const defaultProps = {
    onIterate: vi.fn(),
    onResetToReport: vi.fn(),
    ...props,
  };

  const ui = sessionPatch
    ? <SessionInjector patch={sessionPatch}><ChatHistory {...defaultProps} /></SessionInjector>
    : <ChatHistory {...defaultProps} />;

  return { ...renderWithProviders(ui, { withNotifications: true }), props: defaultProps };
}

describe("ChatHistory", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders without crash with no history", () => {
    renderChat();
    expect(screen.getByLabelText("Follow-up question")).toBeInTheDocument();
    expect(screen.getByLabelText("Send message")).toBeInTheDocument();
  });

  it("renders messages from session.full_history", () => {
    renderChat(undefined, {
      full_history: [
        { role: "user", content: "deploy a VM" },
        { role: "assistant", content: "I'll create the terraform for that." },
      ],
    });

    expect(screen.getByText("deploy a VM")).toBeInTheDocument();
    expect(screen.getByText("I'll create the terraform for that.")).toBeInTheDocument();
  });

  it("filters out validation messages", () => {
    renderChat(undefined, {
      full_history: [
        { role: "user", content: "deploy a VM" },
        { role: "validation", content: "internal validation note" },
        { role: "assistant", content: "Done!" },
      ],
    });

    expect(screen.getByText("deploy a VM")).toBeInTheDocument();
    expect(screen.getByText("Done!")).toBeInTheDocument();
    expect(screen.queryByText("internal validation note")).not.toBeInTheDocument();
  });

  it("submits on Enter key and clears input", async () => {
    const user = userEvent.setup();
    const { props } = renderChat();

    const input = screen.getByLabelText("Follow-up question");
    await user.type(input, "add a database");
    await user.keyboard("{Enter}");

    expect(props.onIterate).toHaveBeenCalledWith("add a database");
    expect(input).toHaveValue("");
  });

  it("submits on send button click and clears input", async () => {
    const user = userEvent.setup();
    const { props } = renderChat();

    const input = screen.getByLabelText("Follow-up question");
    await user.type(input, "add a database");

    const sendBtn = screen.getByLabelText("Send message");
    await user.click(sendBtn);

    expect(props.onIterate).toHaveBeenCalledWith("add a database");
    expect(input).toHaveValue("");
  });

  it("does not submit empty input", async () => {
    const user = userEvent.setup();
    const { props } = renderChat();

    await user.keyboard("{Enter}");
    expect(props.onIterate).not.toHaveBeenCalled();
  });

  it("send button is disabled when input is empty", () => {
    renderChat();
    expect(screen.getByLabelText("Send message")).toBeDisabled();
  });

  it("send button enables after typing", async () => {
    const user = userEvent.setup();
    renderChat();

    const input = screen.getByLabelText("Follow-up question");
    await user.type(input, "hello");

    expect(screen.getByLabelText("Send message")).toBeEnabled();
  });

  it("input and send button are disabled when disabled prop is true", () => {
    renderChat({ disabled: true });

    expect(screen.getByLabelText("Follow-up question")).toBeDisabled();
    expect(screen.getByLabelText("Send message")).toBeDisabled();
  });

  it("input has maxLength of 500", () => {
    renderChat();
    expect(screen.getByLabelText("Follow-up question")).toHaveAttribute("maxLength", "500");
  });

  it("hideActions removes the action bar but keeps the input usable", async () => {
    const user = userEvent.setup();
    const { props } = renderChat({ hideActions: true }, { current_status: "uncompleted" });

    expect(screen.queryByText("View Report")).not.toBeInTheDocument();
    expect(screen.queryByText("Create PR")).not.toBeInTheDocument();

    // An uncompleted (rejected) session must still accept a reply
    const input = screen.getByLabelText("Follow-up question");
    expect(input).toBeEnabled();
    await user.type(input, "make it on-topic");
    await user.keyboard("{Enter}");
    expect(props.onIterate).toHaveBeenCalledWith("make it on-topic");
  });

  it("shows the action bar by default", () => {
    renderChat();
    expect(screen.getByText("View Report")).toBeInTheDocument();
  });
});

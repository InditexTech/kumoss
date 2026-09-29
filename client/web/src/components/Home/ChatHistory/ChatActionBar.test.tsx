// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { server } from "@/test/server";
import userEvent from "@testing-library/user-event";
import React, { useEffect, useState } from "react";
import { useSession } from "@/contexts/SessionContext";
import { renderWithProviders } from "@/test/render";
import { createPullRequest } from "@/services/core/iac_code";
import ChatActionBar from "./ChatActionBar";

vi.mock("@/services/core/iac_code", () => ({
  createPullRequest: vi.fn(),
  mergePullRequest: vi.fn(),
}));

const mockCreatePr = vi.mocked(createPullRequest);

function Injector({ pr, children }: {
  pr?: Record<string, unknown>;
  children: React.ReactNode;
}) {
  const { updateSession, updatePrDetails } = useSession();
  const [ready, setReady] = useState(false);
  useEffect(() => {
    updateSession({ uuid: "sess-1" });
    if (pr) updatePrDetails(pr);
    setReady(true);
  }, []);
  return ready ? <>{children}</> : null;
}

function renderBar(
  pr?: Record<string, unknown>,
  props?: Partial<React.ComponentProps<typeof ChatActionBar>>,
) {
  const onResetToReport = vi.fn();
  renderWithProviders(
    <Injector pr={pr}>
      <ChatActionBar onResetToReport={onResetToReport} {...props} />
    </Injector>,
    { withNotifications: true },
  );
  return { onResetToReport };
}

describe("ChatActionBar", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("offers PR creation when no PR exists yet", () => {
    renderBar();

    expect(screen.getByText("Create PR")).toBeInTheDocument();
    expect(screen.queryByText("Continue with Pull Request")).not.toBeInTheDocument();
  });

  it("offers to continue once a PR exists", () => {
    renderBar({ number: 42, url: "https://dev.azure.com/pr/42" });

    expect(screen.getByText("Continue with Pull Request")).toBeInTheDocument();
    expect(screen.queryByText("Create PR")).not.toBeInTheDocument();
  });

  // Re-entering the approval flow on a merged PR issues a second merge, which a
  // real git provider rejects — the user gets a failure toast for something
  // that already succeeded. Invisible locally: the MSW mock always returns 204.
  it("stops offering to continue once the PR is merged", () => {
    renderBar({ number: 42, url: "https://dev.azure.com/pr/42", merged: true });

    expect(screen.queryByText("Continue with Pull Request")).not.toBeInTheDocument();
    expect(screen.queryByText("Create PR")).not.toBeInTheDocument();
    expect(screen.getByText("View Report")).toBeInTheDocument();
  });

  it("records the created PR so the flow can be resumed", async () => {
    const user = userEvent.setup();
    mockCreatePr.mockResolvedValue({
      id: 42,
      url: "https://dev.azure.com/pr/42",
      status: "active",
    });
    renderBar();

    await user.click(screen.getByText("Create PR"));

    await waitFor(() => expect(mockCreatePr).toHaveBeenCalledWith({ session_id: "sess-1" }));
    expect(await screen.findByText("Continue with Pull Request")).toBeInTheDocument();
  });

  it("re-reads the lock before continuing with the PR", async () => {
    const user = userEvent.setup();
    let reads = 0;
    server.use(
      http.get("/api/v1/sessions", () => {
        reads += 1;
        return HttpResponse.json({ is_blocked: false });
      }),
    );
    renderBar({ number: 42, url: "https://dev.azure.com/pr/42" });

    await user.click(screen.getByText("Continue with Pull Request"));

    await waitFor(() => expect(reads).toBe(1));
  });

  it("re-reads the lock after creating the PR", async () => {
    const user = userEvent.setup();
    let reads = 0;
    server.use(
      http.get("/api/v1/sessions", () => {
        reads += 1;
        return HttpResponse.json({ is_blocked: true });
      }),
    );
    mockCreatePr.mockResolvedValue({
      id: 42,
      url: "https://dev.azure.com/pr/42",
      status: "active",
    });
    renderBar();

    await user.click(screen.getByText("Create PR"));

    await waitFor(() => expect(reads).toBe(1));
  });

  it("renders nothing on the apply result view", () => {
    renderBar({ number: 42 }, { isApplyResult: true });

    expect(screen.queryByText("View Report")).not.toBeInTheDocument();
  });
});

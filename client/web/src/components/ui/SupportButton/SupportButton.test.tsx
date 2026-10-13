// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { useEffect } from "react";
import { server } from "@/test/server";
import { mockState, makeSessionDetail } from "@/test/factories";
import { renderWithProviders } from "@/test/render";
import { useSession } from "@/contexts/SessionContext";
import type { UserInfo } from "@/types";
import type { Session, PrDetails } from "@/types/ui";
import { STRINGS } from "@/constants/strings";
import SupportButton from "./SupportButton";

const SESSION_ID = "21434e55-fa1f-43c5-ab4a-ecafb4d3729e";

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

/** Seeds the session context before rendering the button under test. */
interface SeededProps {
  session: Partial<Session>;
  pr?: Partial<PrDetails>;
  autoTrigger?: boolean;
}

function Seeded({ session, pr, autoTrigger = false }: SeededProps) {
  const { updateSession, updatePrDetails } = useSession();
  useEffect(() => {
    updateSession(session);
    if (pr) updatePrDetails(pr);
  }, [updateSession, updatePrDetails, session, pr]);
  return <SupportButton autoTrigger={autoTrigger} />;
}

function renderButton(session: Partial<Session>, pr?: Partial<PrDetails>, autoTrigger = false) {
  renderWithProviders(<Seeded session={session} pr={pr} autoTrigger={autoTrigger} />, {
    withNotifications: true,
  });
}

/** Captures the next POST /api/v1/notifications body. */
function captureNotification(): { current: Record<string, unknown> | null } {
  const box: { current: Record<string, unknown> | null } = { current: null };
  server.use(
    http.post("/api/v1/notifications", async ({ request }) => {
      box.current = (await request.json()) as Record<string, unknown>;
      return HttpResponse.json({ delivery_id: "d-1" }, { status: 202 });
    }),
  );
  return box;
}

beforeEach(() => {
  mockState.clear();
  sessionStorage.clear();
});

describe("SupportButton", () => {
  it("sends a support.contact_team notification carrying the session metadata", async () => {
    mockState.addSession(makeSessionDetail({ uuid: SESSION_ID, is_blocked: false }));
    let received: Record<string, unknown> | null = null;
    server.use(
      http.post("/api/v1/notifications", async ({ request }) => {
        received = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({ delivery_id: "d-1" }, { status: 202 });
      }),
    );

    renderButton(
      {
        uuid: SESSION_ID,
        provider: "azure",
        workspace: { uri: "https://github.com/org/demo", root_path: "dev" },
        first_query: "Create a storage account in west europe",
      },
      { url: "https://github.com/org/infra/pull/7" },
    );

    await userEvent.click(screen.getByRole("button", { name: STRINGS.support.buttonText }));

    await waitFor(() => expect(received).not.toBeNull());
    expect(received).toMatchObject({
      kind: "support.contact_team",
      severity: "info",
      subject: `Support request from someone@example.com – session ${SESSION_ID}`,
      links: [
        { label: "Open session", url: `${window.location.origin}/home/results/${SESSION_ID}` },
        { label: "Pull request", url: "https://github.com/org/infra/pull/7" },
      ],
      context: {
        user_email: "someone@example.com",
        session_id: SESSION_ID,
        cloud: "azure",
        project: "demo",
        environment: "dev",
        repository: "https://github.com/org/demo",
        request: "Create a storage account in west europe",
        pull_request: "https://github.com/org/infra/pull/7",
        has_deletes_or_recreates: false,
        trigger: "manual",
      },
    });
    // Recipients are derived by the core from the signed-in user.
    expect(received).not.toHaveProperty("audience");
    expect(await screen.findByText(STRINGS.support.groupCreated)).toBeInTheDocument();
  });

  it("tags an auto-triggered notification as automatic", async () => {
    mockState.addSession(makeSessionDetail({ uuid: SESSION_ID, is_blocked: false }));
    const received = captureNotification();

    renderButton({ uuid: SESSION_ID }, undefined, true);

    await waitFor(() => expect(received.current).not.toBeNull());
    expect(received.current).toMatchObject({
      kind: "support.contact_team",
      context: { trigger: "automatic" },
    });
  });

  it("escalates to warning severity when the session is blocked", async () => {
    mockState.addSession(makeSessionDetail({ uuid: SESSION_ID, is_blocked: true }));
    let received: Record<string, unknown> | null = null;
    server.use(
      http.post("/api/v1/notifications", async ({ request }) => {
        received = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({ delivery_id: "d-2" }, { status: 202 });
      }),
    );

    renderButton({ uuid: SESSION_ID });
    await userEvent.click(screen.getByRole("button", { name: STRINGS.support.buttonText }));

    await waitFor(() => expect(received).not.toBeNull());
    expect(received).toMatchObject({
      severity: "warning",
      context: { has_deletes_or_recreates: true },
    });
  });

  it("reports a failure toast instead of a fake success when the backend rejects", async () => {
    server.use(
      http.post("/api/v1/notifications", () =>
        HttpResponse.json({ detail: "Notification was not delivered." }, { status: 502 }),
      ),
    );

    renderButton({});
    await userEvent.click(screen.getByRole("button", { name: STRINGS.support.buttonText }));

    expect(await screen.findByText(/was not delivered/)).toBeInTheDocument();
    expect(screen.queryByText(STRINGS.support.groupCreated)).not.toBeInTheDocument();
  });
});

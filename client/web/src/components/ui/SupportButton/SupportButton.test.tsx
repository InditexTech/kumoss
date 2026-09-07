// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { useEffect } from "react";
import { server } from "@/mocks/server";
import { mockState, makeSessionDetail } from "@/mocks/state";
import { renderWithProviders } from "@/test/render";
import { AuthProvider } from "@/contexts/AuthContext";
import { useSession } from "@/contexts/SessionContext";
import { storeUser, clearUser } from "@/services/auth";
import type { Session, PrDetails } from "@/types/ui";
import { STRINGS } from "@/constants/strings";
import SupportButton from "./SupportButton";

const SESSION_ID = "21434e55-fa1f-43c5-ab4a-ecafb4d3729e";

/** Seeds the session context before rendering the button under test. */
function Seeded({ session, pr }: { session: Partial<Session>; pr?: Partial<PrDetails> }) {
  const { updateSession, updatePrDetails } = useSession();
  useEffect(() => {
    updateSession(session);
    if (pr) updatePrDetails(pr);
  }, [updateSession, updatePrDetails, session, pr]);
  return <SupportButton />;
}

function renderButton(session: Partial<Session>, pr?: Partial<PrDetails>) {
  renderWithProviders(
    <AuthProvider>
      <Seeded session={session} pr={pr} />
    </AuthProvider>,
    { withNotifications: true },
  );
}

beforeEach(() => {
  mockState.clear();
  clearUser();
  storeUser({
    username: "someone@example.com",
    name: "Someone",
    homeAccountId: "",
    environment: "",
    tenantId: "",
    localAccountId: "",
    roles: [],
  });
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
        session_id: SESSION_ID,
        cloud: "azure",
        project: "demo",
        environment: "dev",
        firstQuery: "Create a storage account in west europe",
      },
      { prUrl: "https://github.com/org/infra/pull/7" },
    );

    await userEvent.click(screen.getByRole("button", { name: STRINGS.support.buttonText }));

    await waitFor(() => expect(received).not.toBeNull());
    expect(received).toMatchObject({
      kind: "support.contact_team",
      severity: "info",
      subject: `Support request from someone@example.com – session ${SESSION_ID}`,
      audience: ["someone@example.com"],
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
        request: "Create a storage account in west europe",
        pull_request: "https://github.com/org/infra/pull/7",
        has_deletes_or_recreates: false,
        trigger: "manual",
      },
    });
    expect(await screen.findByText(STRINGS.support.groupCreated)).toBeInTheDocument();
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

    renderButton({ session_id: SESSION_ID });
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
        HttpResponse.json({ detail: "notifications service rejected: Invalid bearer token." }, { status: 502 }),
      ),
    );

    renderButton({});
    await userEvent.click(screen.getByRole("button", { name: STRINGS.support.buttonText }));

    expect(await screen.findByText(/Invalid bearer token/)).toBeInTheDocument();
    expect(screen.queryByText(STRINGS.support.groupCreated)).not.toBeInTheDocument();
  });
});

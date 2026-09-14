// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect, beforeEach } from "vitest";
import { waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { server } from "@/mocks/server";
import { renderHookWithProviders } from "@/test/render";
import { useSession } from "@/contexts/SessionContext";
import {
  mockState,
  makeSessionDetail,
  makeRound,
  makeStatus,
} from "@/mocks/state";
import { useSessionLoader } from "./useSessionLoader";

/** The loader plus the context it writes into, so tests can assert on both. */
function useLoaderWithSession(sessionId: string | undefined) {
  const loader = useSessionLoader(sessionId);
  const { session } = useSession();
  return { loader, session };
}

function codeChangeRef(fileName: string) {
  return {
    id: 1,
    url: `https://storage.test/${fileName}`,
    content_type: "text/plain",
    file_size_bytes: 10,
    created_at: "2026-01-01T00:00:00Z",
    file_name: fileName,
  };
}

beforeEach(() => {
  mockState.clear();
});

describe("useSessionLoader", () => {
  it("reports a still-running session as in progress instead of ready", async () => {
    mockState.addSession(
      makeSessionDetail({
        current_status: "generating",
        in_flight: true,
        rounds: [
          makeRound({
            statuses: [makeStatus("started"), makeStatus("generating")],
          }),
        ],
      }),
    );

    const { result } = renderHookWithProviders(() =>
      useLoaderWithSession("sess-1"),
    );

    await waitFor(() =>
      expect(result.current.loader.inProgress).toEqual({
        sessionId: "sess-1",
        isApply: false,
      }),
    );
    expect(result.current.loader.ready).toBe(false);
    expect(result.current.loader.error).toBeNull();
    // Facts are rehydrated, but nothing is presented as a result.
    expect(result.current.session.operation).toBe("generate");
    expect(result.current.session.code).toBeUndefined();
    expect(result.current.session.terraform_report).toBeUndefined();
  });

  it("flags a running apply round so the resumed view uses apply phases", async () => {
    mockState.addSession(
      makeSessionDetail({
        current_status: "apply",
        in_flight: true,
        rounds: [
          makeRound({ statuses: [makeStatus("started"), makeStatus("apply")] }),
        ],
      }),
    );

    const { result } = renderHookWithProviders(() =>
      useLoaderWithSession("sess-1"),
    );

    await waitFor(() =>
      expect(result.current.loader.inProgress).toEqual({
        sessionId: "sess-1",
        isApply: true,
      }),
    );
  });

  it("re-resolves a session the context already holds as running", async () => {
    // The sessions-table "Reload Session" path patches the session before
    // navigating; short-circuiting on the uuid alone would strand a running
    // session on an empty results view.
    mockState.addSession(
      makeSessionDetail({
        current_status: "generating",
        in_flight: true,
        rounds: [
          makeRound({
            statuses: [makeStatus("started"), makeStatus("generating")],
          }),
        ],
      }),
    );

    const { result } = renderHookWithProviders(() =>
      useLoaderWithSession("sess-1"),
    );

    // First pass writes the uuid into the context; the resume must survive it.
    await waitFor(() => expect(result.current.session.uuid).toBe("sess-1"));
    await waitFor(() =>
      expect(result.current.loader.inProgress).toEqual({
        sessionId: "sess-1",
        isApply: false,
      }),
    );
    expect(result.current.loader.ready).toBe(false);
  });

  it("loads a finished session's artifacts and reports no resume", async () => {
    mockState.addSession(
      makeSessionDetail({
        rounds: [
          makeRound({
            statuses: [makeStatus("started"), makeStatus("completed")],
            code_changes: [codeChangeRef("main.tf")],
          }),
        ],
      }),
    );
    server.use(
      http.get("https://storage.test/main.tf", () =>
        HttpResponse.text("resource {}"),
      ),
    );

    const { result } = renderHookWithProviders(() =>
      useLoaderWithSession("sess-1"),
    );

    await waitFor(() => expect(result.current.loader.ready).toBe(true));
    expect(result.current.loader.inProgress).toBeNull();
    expect(result.current.session.code).toContain("<main.tf>");
  });

  it("surfaces a failed session as an error, not as a resume", async () => {
    mockState.addSession(
      makeSessionDetail({
        current_status: "failed",
        rounds: [
          makeRound({
            statuses: [makeStatus("started"), makeStatus("failed", "boom")],
          }),
        ],
      }),
    );

    const { result } = renderHookWithProviders(() =>
      useLoaderWithSession("sess-1"),
    );

    await waitFor(() => expect(result.current.loader.error).toBe("boom"));
    expect(result.current.loader.inProgress).toBeNull();
  });
});

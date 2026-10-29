// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import React, { useEffect, useState } from "react";
import { describe, it, expect, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { server } from "@/test/server";
import {
  mockState,
  makeSessionDetail,
  makeRound,
  makeStatus,
} from "@/test/factories";
import { createWrapper } from "@/test/render";
import { useSession } from "@/contexts/SessionContext";
import { SessionProvider } from "@/contexts/SessionContext";
import { useSessionLoader } from "./useSessionLoader";
import type { ReportRef, HistoryEntry } from "@/types/api";
import { MemoryRouter } from "react-router-dom";
import { NotificationProvider } from "@/contexts/NotificationContext";
import { ShellProvider } from "@/contexts/ShellContext";
import { ModeProvider } from "@/contexts/ModeContext";

const STORAGE = "https://storage.test";

function artifactRef(id: number, path: string) {
  return {
    id,
    url: `${STORAGE}/${path}`,
    content_type: "text/plain",
    file_size_bytes: 10,
    created_at: "2026-01-01T00:00:00Z",
  };
}

function reportRef(id: number, path: string): ReportRef {
  return { ...artifactRef(id, path), type: "generate" };
}

const wrapper = createWrapper({ withNotifications: true });

beforeEach(() => {
  mockState.clear();
});

describe("useSessionLoader — uncompleted sessions", () => {
  it("loads chat history for an uncompleted first-round session", async () => {
    mockState.addSession(
      makeSessionDetail({
        uuid: "sess-unc-1",
        current_status: "uncompleted",
        chat_history: [
          {
            user: "deploy a bitcoin miner",
            assistant: "Query is off-topic",
          },
        ],
        rounds: [
          makeRound({
            statuses: [
              makeStatus("started"),
              makeStatus("filtering"),
              makeStatus("uncompleted", "Query is off-topic"),
            ],
          }),
        ],
      }),
    );

    const { result } = renderHook(
      () => ({
        loader: useSessionLoader("sess-unc-1"),
        session: useSession(),
      }),
      { wrapper },
    );

    await waitFor(() => expect(result.current.loader.ready).toBe(true));

    const session = result.current.session.session;
    expect(session.uuid).toBe("sess-unc-1");
    expect(session.current_status).toBe("uncompleted");

    // Chat history is populated from the backend's chat_history
    expect(session.history).toEqual([
      { role: "user", content: "deploy a bitcoin miner" },
      { role: "assistant", content: "Query is off-topic" },
    ]);

    // No artifacts — ResultsRoute will render chat-only
    expect(session.code).toBeUndefined();
    expect(session.terraform_report).toBeUndefined();
    expect(session.compliance_report).toBeUndefined();
    expect(session.planTargets).toBeUndefined();
    expect(session.newFiles).toBeUndefined();
  });

  it("clears stale artifacts when loading an uncompleted session over a completed one", async () => {
    // First session: completed with artifacts
    mockState.addSession(
      makeSessionDetail({
        uuid: "sess-completed",
        current_status: "completed",
        rounds: [
          makeRound({
            statuses: [makeStatus("started"), makeStatus("completed")],
            reports: [reportRef(1, "report.json")],
            code_changes: [
              { ...artifactRef(2, "main.tf"), file_name: "main.tf" },
            ],
          }),
        ],
      }),
    );
    server.use(
      http.get(`${STORAGE}/report.json`, () =>
        HttpResponse.json({ status: "ok" }),
      ),
      http.get(`${STORAGE}/main.tf`, () => HttpResponse.text("resource {}")),
    );

    const { result, rerender } = renderHook(
      ({ sessionId }: { sessionId: string }) => ({
        loader: useSessionLoader(sessionId),
        session: useSession(),
      }),
      { wrapper, initialProps: { sessionId: "sess-completed" } },
    );

    // Wait for the first session to load
    await waitFor(() => expect(result.current.loader.ready).toBe(true));
    expect(result.current.session.session.code).toContain("resource {}");
    expect(result.current.session.session.terraform_report).toEqual({
      status: "ok",
    });

    // Second session: uncompleted with no prior artifacts
    mockState.addSession(
      makeSessionDetail({
        uuid: "sess-uncompleted",
        current_status: "uncompleted",
        chat_history: [
          { user: "deploy a bitcoin miner", assistant: "Off-topic request" },
        ],
        rounds: [
          makeRound({
            statuses: [
              makeStatus("started"),
              makeStatus("uncompleted", "Off-topic request"),
            ],
          }),
        ],
      }),
    );

    // Navigate to the uncompleted session
    rerender({ sessionId: "sess-uncompleted" });

    await waitFor(() =>
      expect(result.current.session.session.uuid).toBe("sess-uncompleted"),
    );

    const session = result.current.session.session;
    expect(session.current_status).toBe("uncompleted");

    // Chat history is present
    expect(session.history).toEqual([
      { role: "user", content: "deploy a bitcoin miner" },
      { role: "assistant", content: "Off-topic request" },
    ]);

    // Stale artifacts from the completed session are cleared
    expect(session.code).toBeUndefined();
    expect(session.terraform_report).toBeUndefined();
    expect(session.compliance_report).toBeUndefined();
    expect(session.planTargets).toBeUndefined();
    expect(session.newFiles).toBeUndefined();
    expect(session.applyResults).toBeUndefined();
  });

  it("preserves prior-round artifacts for an uncompleted iteration", async () => {
    mockState.addSession(
      makeSessionDetail({
        uuid: "sess-iter",
        current_status: "uncompleted",
        chat_history: [
          { user: "deploy a VM", assistant: "Done." },
          { user: "deploy a miner", assistant: "Query is off-topic" },
        ],
        rounds: [
          makeRound({
            number: 1,
            statuses: [makeStatus("started"), makeStatus("completed")],
            reports: [reportRef(1, "report.json")],
            code_changes: [
              { ...artifactRef(2, "main.tf"), file_name: "main.tf" },
            ],
          }),
          makeRound({
            number: 2,
            statuses: [
              makeStatus("started"),
              makeStatus("uncompleted", "Query is off-topic"),
            ],
          }),
        ],
      }),
    );
    server.use(
      http.get(`${STORAGE}/report.json`, () =>
        HttpResponse.json({ status: "ok", potential_impact: { summary: "Low" } }),
      ),
      http.get(`${STORAGE}/main.tf`, () => HttpResponse.text("resource {}")),
    );

    const { result } = renderHook(
      () => ({
        loader: useSessionLoader("sess-iter"),
        session: useSession(),
      }),
      { wrapper },
    );

    await waitFor(() => expect(result.current.loader.ready).toBe(true));

    const session = result.current.session.session;
    expect(session.uuid).toBe("sess-iter");
    expect(session.current_status).toBe("uncompleted");

    // Chat history includes both rounds
    expect(session.history).toEqual([
      { role: "user", content: "deploy a VM" },
      { role: "assistant", content: "Done." },
      { role: "user", content: "deploy a miner" },
      { role: "assistant", content: "Query is off-topic" },
    ]);

    // Prior round's artifacts are hydrated via the `prior` field
    expect(session.code).toContain("<main.tf>\nresource {}\n</main.tf>");
    expect(session.terraform_report).toEqual({
      status: "ok",
      potential_impact: { summary: "Low" },
    });
  });

  it("degrades to chat-only when prior-round artifacts cannot be fetched", async () => {
    mockState.addSession(
      makeSessionDetail({
        uuid: "sess-degraded",
        current_status: "uncompleted",
        chat_history: [
          { user: "deploy a VM", assistant: "Done." },
          { user: "now break it", assistant: "Query is off-topic" },
        ],
        rounds: [
          makeRound({
            number: 1,
            statuses: [makeStatus("started"), makeStatus("completed")],
            reports: [reportRef(1, "report.json")],
          }),
          makeRound({
            number: 2,
            statuses: [
              makeStatus("started"),
              makeStatus("uncompleted", "Query is off-topic"),
            ],
          }),
        ],
      }),
    );
    // Both fetches fail — forces the degraded path
    server.use(
      http.get(`${STORAGE}/report.json`, () =>
        new HttpResponse(null, { status: 403 }),
      ),
    );

    const { result } = renderHook(
      () => ({
        loader: useSessionLoader("sess-degraded"),
        session: useSession(),
      }),
      { wrapper },
    );

    await waitFor(() => expect(result.current.loader.ready).toBe(true));

    const session = result.current.session.session;
    expect(session.current_status).toBe("uncompleted");

    // Chat survives degradation
    expect(session.history).toHaveLength(4);
    expect(session.history?.[3]).toEqual({
      role: "assistant",
      content: "Query is off-topic",
    });

    // Artifacts cleared — chat-only view
    expect(session.code).toBeUndefined();
    expect(session.terraform_report).toBeUndefined();
  });

  it("skips fetching when the session is already loaded in context", async () => {
    let fetchCount = 0;
    server.use(
      http.get("/api/v1/sessions", () => {
        fetchCount++;
        return HttpResponse.json(
          { detail: "Should not be called" },
          { status: 500 },
        );
      }),
    );

    // Pre-populate the session BEFORE the hook mounts, so
    // useSessionLoader sees alreadyLoaded=true on its first render.
    function PreloadedWrapper({ children }: { children: React.ReactNode }) {
      const { updateSession } = useSession();
      const [ready, setReady] = useState(false);
      useEffect(() => {
        updateSession({
          uuid: "sess-already",
          current_status: "uncompleted",
          history: [
            { role: "user", content: "hello" },
            { role: "assistant", content: "rejected" },
          ] as HistoryEntry[],
        });
        setReady(true);
        // eslint-disable-next-line react-hooks/exhaustive-deps
      }, []);
      return ready ? React.createElement(React.Fragment, null, children) : null;
    }

    function FullWrapper({ children }: { children: React.ReactNode }) {
      return React.createElement(
        MemoryRouter,
        { initialEntries: ["/home"] },
        React.createElement(
          ShellProvider,
          null,
          React.createElement(
            SessionProvider,
            null,
            React.createElement(
              ModeProvider,
              null,
              React.createElement(
                NotificationProvider,
                null,
                React.createElement(PreloadedWrapper, null, children),
              ),
            ),
          ),
        ),
      );
    }

    const { result } = renderHook(
      () => ({
        loader: useSessionLoader("sess-already"),
        session: useSession(),
      }),
      { wrapper: FullWrapper },
    );

    await waitFor(() => expect(result.current.loader.ready).toBe(true));

    // The session was already in context — no API call
    expect(fetchCount).toBe(0);
  });

  it("populates PR details when the session has a pull request", async () => {
    mockState.addSession(
      makeSessionDetail({
        uuid: "sess-pr",
        current_status: "completed",
        rounds: [
          makeRound({
            statuses: [makeStatus("started"), makeStatus("completed")],
            reports: [reportRef(1, "report-pr.json")],
            code_changes: [
              { ...artifactRef(2, "main-pr.tf"), file_name: "main.tf" },
            ],
            pull_requests: [
              { provider: "github", number: 99, url: "https://git.example.com/pr/99" },
            ],
          }),
        ],
      }),
    );
    server.use(
      http.get(`${STORAGE}/report-pr.json`, () =>
        HttpResponse.json({ status: "ok" }),
      ),
      http.get(`${STORAGE}/main-pr.tf`, () => HttpResponse.text("resource {}")),
    );

    const { result } = renderHook(
      () => ({
        loader: useSessionLoader("sess-pr"),
        session: useSession(),
      }),
      { wrapper },
    );

    await waitFor(() => expect(result.current.loader.ready).toBe(true));

    const { prDetails } = result.current.session;
    expect(prDetails.number).toBe(99);
    expect(prDetails.url).toBe("https://git.example.com/pr/99");
  });

  it("sets error state when the session is not found", async () => {
    // No session in mockState → 404

    const { result } = renderHook(
      () => ({
        loader: useSessionLoader("sess-missing"),
        session: useSession(),
      }),
      { wrapper },
    );

    await waitFor(() => expect(result.current.loader.loading).toBe(false));

    expect(result.current.loader.error).toBeTruthy();
    expect(result.current.loader.ready).toBe(false);
  });
});

// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import type { Mock } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { createWrapper } from "@/test/render";
import { useAssistantMsg } from "@/contexts/AssistantMsgContext";
import { PHASE } from "@/types/ui";
import type { SseConnection } from "@/services/core/events";
import type { TerraformActionParams } from "@/services/workflows/terraform_action";
import type { SessionOutcome } from "@/services/workflows/session_outcome";

// ─── Mock controls ────────────────────────────────────────────
const mockRunWorkflow = vi.fn<
  (params: TerraformActionParams, signal: AbortSignal) => Promise<{ sessionId: string }>
>().mockResolvedValue({ sessionId: "sess-abc" });

let mockSseConnection: SseConnection & { close: Mock<() => void> };

function createMockSse(): typeof mockSseConnection {
  return { onmessage: null, onerror: null, close: vi.fn<() => void>() };
}

const mockSubscribe = vi.fn((_sessionId: string) => {
  mockSseConnection = createMockSse();
  return mockSseConnection;
});

function makeResultsOutcome(overrides?: Partial<Record<string, unknown>>): SessionOutcome {
  return {
    kind: "results",
    detail: { uuid: "sess-abc", operation: "generate", rounds: [{}] },
    round: {},
    report: null,
    code: "<main.tf>\nresource {}\n</main.tf>",
    targets: undefined,
    ...overrides,
  } as unknown as SessionOutcome;
}

const mockResolveOutcome = vi.fn<(id: string) => Promise<SessionOutcome>>();
const mockWaitForNewRound = vi.fn<
  (id: string, baseline: number, signal?: AbortSignal) => Promise<void>
>().mockResolvedValue(undefined);
const mockCheckSessionStatus = vi.fn<(id: string) => Promise<{ status: string }>>();
const mockGetSessionDetail = vi.fn<(id: string) => Promise<{ rounds: unknown[] }>>()
  .mockResolvedValue({ rounds: [{}] });
const mockNotifyIfHidden = vi.fn();

vi.mock("@/services/workflows/terraform_action", () => ({
  runTerraformActionWorkflow: (...args: unknown[]) => mockRunWorkflow(...(args as [TerraformActionParams, AbortSignal])),
}));

vi.mock("@/services/core/events", () => ({
  subscribeToSession: (...args: unknown[]) => mockSubscribe(...(args as [string])),
  checkSessionStatus: (...args: unknown[]) => mockCheckSessionStatus(...(args as [string])),
}));

vi.mock("@/services/workflows/session_outcome", () => ({
  resolveSessionOutcome: (...args: unknown[]) => mockResolveOutcome(...(args as [string])),
  waitForNewRound: (...args: unknown[]) => mockWaitForNewRound(...(args as [string, number, AbortSignal])),
}));

vi.mock("@/services/core/sessions", () => ({
  getSessionDetail: (...args: unknown[]) => mockGetSessionDetail(...(args as [string])),
}));

vi.mock("@/hooks/useBrowserNotification", () => ({
  useBrowserNotification: () => ({
    notifyIfHidden: mockNotifyIfHidden,
  }),
}));

// ─── Helpers ──────────────────────────────────────────────────

const defaultParams: TerraformActionParams = {
  repoUri: "https://dev.azure.com/org/repo",
  query: "deploy a VM",
  terraformProviders: "azure",
  scopeId: "sub-123",
  iacPath: "environments/dev",
  mode: "generate",
};

function sseEvent(status_msg: string, message = "") {
  return {
    data: JSON.stringify({
      status_msg,
      detail: { message },
    }),
  };
}

describe("useTerraformActions", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockRunWorkflow.mockResolvedValue({ sessionId: "sess-abc" });
    mockResolveOutcome.mockResolvedValue(makeResultsOutcome());
    mockWaitForNewRound.mockResolvedValue(undefined);
    mockGetSessionDetail.mockResolvedValue({ rounds: [{}] });
  });

  // Need dynamic import because vi.mock hoists above imports
  async function importHook() {
    const { useTerraformActions } = await import("@/hooks/use_terraform_actions");
    return useTerraformActions;
  }

  it("initializes with idle state", async () => {
    const useTerraformActions = await importHook();
    const wrapper = createWrapper({ withAssistantMsg: true });
    const { result } = renderHook(() => useTerraformActions(), { wrapper });

    expect(result.current.state).toEqual({ status: "idle" });
  });

  it("run transitions idle → loading → streaming", async () => {
    const useTerraformActions = await importHook();
    const wrapper = createWrapper({ withAssistantMsg: true });
    const { result } = renderHook(() => useTerraformActions(), { wrapper });

    await act(async () => {
      result.current.run(defaultParams);
    });

    expect(result.current.state).toEqual({ status: "streaming", sessionId: "sess-abc" });
    expect(mockRunWorkflow).toHaveBeenCalledWith(defaultParams, expect.any(AbortSignal));
    expect(mockSubscribe).toHaveBeenCalledWith("sess-abc");
    // First calls subscribe directly: no baseline fetch, no round wait
    expect(mockGetSessionDetail).not.toHaveBeenCalled();
    expect(mockWaitForNewRound).not.toHaveBeenCalled();
  });

  it("iteration waits for the new round before subscribing", async () => {
    mockGetSessionDetail.mockResolvedValue({ rounds: [{}, {}] });

    const useTerraformActions = await importHook();
    const wrapper = createWrapper({ withAssistantMsg: true });
    const { result } = renderHook(() => useTerraformActions(), { wrapper });

    await act(async () => {
      result.current.run({ ...defaultParams, sessionId: "sess-abc" });
    });

    // Baseline captured from the existing session before the POST
    expect(mockGetSessionDetail).toHaveBeenCalledWith("sess-abc");
    expect(mockWaitForNewRound).toHaveBeenCalledWith(
      "sess-abc",
      2,
      expect.any(AbortSignal),
    );
    expect(mockSubscribe).toHaveBeenCalledWith("sess-abc");
    expect(mockWaitForNewRound.mock.invocationCallOrder[0]).toBeLessThan(
      mockSubscribe.mock.invocationCallOrder[0],
    );
  });

  it("COMPLETED event resolves the outcome and calls onOutcome", async () => {
    const useTerraformActions = await importHook();
    const wrapper = createWrapper({ withAssistantMsg: true });
    const onOutcome = vi.fn();
    const { result } = renderHook(() => useTerraformActions(), { wrapper });

    await act(async () => {
      result.current.run(defaultParams, onOutcome);
    });

    await act(async () => {
      mockSseConnection.onmessage?.(sseEvent("COMPLETED", "Done."));
    });

    expect(mockSseConnection.close).toHaveBeenCalled();

    await act(async () => {
      await vi.waitFor(() => {
        expect(mockResolveOutcome).toHaveBeenCalledWith("sess-abc");
        expect(onOutcome).toHaveBeenCalledWith(
          expect.objectContaining({ kind: "results" }),
        );
      });
    });

    expect(result.current.state).toEqual({ status: "success", sessionId: "sess-abc" });
    expect(mockNotifyIfHidden).toHaveBeenCalledWith("Pipeline completed", expect.anything());
  });

  it("outcome resolution failure surfaces a failed outcome, never a silent error", async () => {
    mockResolveOutcome.mockRejectedValue(new Error("fetch failed"));

    const useTerraformActions = await importHook();
    const wrapper = createWrapper({ withAssistantMsg: true });
    const onOutcome = vi.fn();
    const { result } = renderHook(() => useTerraformActions(), { wrapper });

    await act(async () => {
      result.current.run(defaultParams, onOutcome);
    });

    await act(async () => {
      mockSseConnection.onmessage?.(sseEvent("COMPLETED", "Done."));
    });

    await act(async () => {
      await vi.waitFor(() => {
        expect(onOutcome).toHaveBeenCalledWith(
          expect.objectContaining({
            kind: "failed",
            message: "Completed, but results could not be loaded",
          }),
        );
      });
    });

    expect(result.current.state.status).toBe("error");
  });

  it("UNCOMPLETED closes the stream client-side and reports a rejected iteration", async () => {
    // Two rounds: this is an iteration rejection, handed to onOutcome
    mockResolveOutcome.mockResolvedValue({
      kind: "rejected",
      detail: { uuid: "sess-abc", rounds: [{}, {}] },
      rationale: "Query is off-topic",
    } as unknown as SessionOutcome);

    const useTerraformActions = await importHook();
    const wrapper = createWrapper({ withAssistantMsg: true });
    const onOutcome = vi.fn();
    const { result } = renderHook(() => useTerraformActions(), { wrapper });

    await act(async () => {
      result.current.run(defaultParams, onOutcome);
    });

    await act(async () => {
      mockSseConnection.onmessage?.(sseEvent("UNCOMPLETED", "Query is off-topic"));
    });

    expect(mockSseConnection.close).toHaveBeenCalled();

    await act(async () => {
      await vi.waitFor(() => {
        expect(onOutcome).toHaveBeenCalledWith(
          expect.objectContaining({ kind: "rejected" }),
        );
      });
    });

    expect(result.current.state).toEqual({ status: "success", sessionId: "sess-abc" });
  });

  it("UNCOMPLETED on the first round hands the rejected outcome over too", async () => {
    mockResolveOutcome.mockResolvedValue({
      kind: "rejected",
      detail: { uuid: "sess-abc", rounds: [{}] },
      rationale: "Query is off-topic",
    } as unknown as SessionOutcome);

    const useTerraformActions = await importHook();
    const wrapper = createWrapper({ withAssistantMsg: true });
    const onOutcome = vi.fn();
    const { result } = renderHook(() => useTerraformActions(), { wrapper });

    await act(async () => {
      result.current.run(defaultParams, onOutcome);
    });

    await act(async () => {
      mockSseConnection.onmessage?.(sseEvent("UNCOMPLETED", "Query is off-topic"));
    });

    expect(mockSseConnection.close).toHaveBeenCalled();

    await act(async () => {
      await vi.waitFor(() => {
        expect(onOutcome).toHaveBeenCalledWith(
          expect.objectContaining({ kind: "rejected", rationale: "Query is off-topic" }),
        );
      });
    });

    expect(result.current.state).toEqual({ status: "success", sessionId: "sess-abc" });
    expect(mockNotifyIfHidden).toHaveBeenCalledWith(
      "Request rejected",
      expect.objectContaining({ body: "Query is off-topic" }),
    );
  });

  it("a blocked session triggers the browser notification", async () => {
    mockResolveOutcome.mockResolvedValue(
      makeResultsOutcome({
        detail: {
          uuid: "sess-abc",
          operation: "generate",
          rounds: [{}],
          is_blocked: true,
        },
      }),
    );

    const useTerraformActions = await importHook();
    const wrapper = createWrapper({ withAssistantMsg: true });
    const { result } = renderHook(() => useTerraformActions(), { wrapper });

    await act(async () => {
      result.current.run(defaultParams);
    });

    await act(async () => {
      mockSseConnection.onmessage?.(sseEvent("COMPLETED", "Done."));
    });

    await act(async () => {
      await vi.waitFor(() => {
        expect(mockNotifyIfHidden).toHaveBeenCalledWith(
          "Session blocked",
          expect.objectContaining({ tag: "nebula-session-blocked" }),
        );
      });
    });
  });

  it("an unblocked session does not trigger the blocked notification", async () => {
    const useTerraformActions = await importHook();
    const wrapper = createWrapper({ withAssistantMsg: true });
    const { result } = renderHook(() => useTerraformActions(), { wrapper });

    await act(async () => {
      result.current.run(defaultParams);
    });

    await act(async () => {
      mockSseConnection.onmessage?.(sseEvent("COMPLETED", "Done."));
    });

    await act(async () => {
      await vi.waitFor(() => {
        expect(mockNotifyIfHidden).toHaveBeenCalledWith(
          "Pipeline completed",
          expect.anything(),
        );
      });
    });

    expect(mockNotifyIfHidden).not.toHaveBeenCalledWith(
      "Session blocked",
      expect.anything(),
    );
  });

  it("FAILED event transitions to error and hands a failed outcome over", async () => {
    const useTerraformActions = await importHook();
    const wrapper = createWrapper({ withAssistantMsg: true });
    const onOutcome = vi.fn();
    const { result } = renderHook(() => useTerraformActions(), { wrapper });

    await act(async () => {
      result.current.run(defaultParams, onOutcome);
    });

    await act(async () => {
      mockSseConnection.onmessage?.(sseEvent("FAILED", "Generation failed"));
    });

    expect(result.current.state).toEqual({ status: "error", message: "Generation failed" });
    expect(mockSseConnection.close).toHaveBeenCalled();
    expect(onOutcome).toHaveBeenCalledWith(
      expect.objectContaining({ kind: "failed", message: "Generation failed" }),
    );
    expect(mockNotifyIfHidden).toHaveBeenCalledWith("Pipeline failed", expect.objectContaining({ body: "Generation failed" }));
  });

  it("SSE error + not_found = error state", async () => {
    mockCheckSessionStatus.mockResolvedValueOnce({ status: "not_found" });

    const useTerraformActions = await importHook();
    const wrapper = createWrapper({ withAssistantMsg: true });
    const { result } = renderHook(() => useTerraformActions(), { wrapper });

    await act(async () => {
      result.current.run(defaultParams);
    });

    await act(async () => {
      mockSseConnection.onerror?.();
    });

    await act(async () => {
      await vi.waitFor(() => {
        expect(result.current.state).toEqual({ status: "error", message: "Connection to server lost" });
      });
    });

    expect(mockSseConnection.close).toHaveBeenCalled();
  });

  it("SSE error + completed = success recovery via outcome resolution", async () => {
    mockCheckSessionStatus.mockResolvedValueOnce({ status: "completed" });

    const useTerraformActions = await importHook();
    const wrapper = createWrapper({ withAssistantMsg: true });
    const onOutcome = vi.fn();
    const { result } = renderHook(() => useTerraformActions(), { wrapper });

    await act(async () => {
      result.current.run(defaultParams, onOutcome);
    });

    await act(async () => {
      mockSseConnection.onerror?.();
    });

    await act(async () => {
      await vi.waitFor(() => {
        expect(result.current.state).toEqual({ status: "success", sessionId: "sess-abc" });
        expect(onOutcome).toHaveBeenCalledWith(
          expect.objectContaining({ kind: "results" }),
        );
      });
    });

    expect(mockNotifyIfHidden).toHaveBeenCalledWith(
      "Pipeline completed",
      expect.objectContaining({ body: "Your infrastructure changes are ready for review." }),
    );
  });

  it("SSE error + uncompleted = rejected outcome recovery", async () => {
    mockCheckSessionStatus.mockResolvedValueOnce({ status: "uncompleted" });
    mockResolveOutcome.mockResolvedValue({
      kind: "rejected",
      detail: { uuid: "sess-abc", rounds: [{}, {}] },
      rationale: "Rejected",
    } as unknown as SessionOutcome);

    const useTerraformActions = await importHook();
    const wrapper = createWrapper({ withAssistantMsg: true });
    const onOutcome = vi.fn();
    const { result } = renderHook(() => useTerraformActions(), { wrapper });

    await act(async () => {
      result.current.run(defaultParams, onOutcome);
    });

    await act(async () => {
      mockSseConnection.onerror?.();
    });

    await act(async () => {
      await vi.waitFor(() => {
        expect(onOutcome).toHaveBeenCalledWith(
          expect.objectContaining({ kind: "rejected" }),
        );
      });
    });

    expect(result.current.state).toEqual({ status: "success", sessionId: "sess-abc" });
  });

  it("SSE error + in_progress = reconnect", async () => {
    mockCheckSessionStatus.mockResolvedValueOnce({ status: "in_progress" });

    const useTerraformActions = await importHook();
    const wrapper = createWrapper({ withAssistantMsg: true });
    const { result } = renderHook(() => useTerraformActions(), { wrapper });

    await act(async () => {
      result.current.run(defaultParams);
    });

    const firstConnection = mockSseConnection;

    await act(async () => {
      firstConnection.onerror?.();
    });

    await act(async () => {
      await vi.waitFor(() => {
        expect(mockSubscribe).toHaveBeenCalledTimes(2);
      });
    });

    // Still streaming after reconnect
    expect(result.current.state.status).toBe("streaming");

    // Second connection should work normally
    const secondConnection = mockSseConnection;
    await act(async () => {
      secondConnection.onmessage?.(sseEvent("COMPLETED", "Done."));
    });

    await act(async () => {
      await vi.waitFor(() => {
        expect(result.current.state).toEqual({ status: "success", sessionId: "sess-abc" });
      });
    });
    // COMPLETED must close the reconnected connection, not the stale one
    expect(secondConnection.close).toHaveBeenCalled();
  });

  it("SSE error + failed = error state with failure notification", async () => {
    mockCheckSessionStatus.mockResolvedValueOnce({ status: "failed" });
    mockResolveOutcome.mockResolvedValue({
      kind: "failed",
      detail: { uuid: "sess-abc", rounds: [{}] },
      message: "Process failed",
    } as unknown as SessionOutcome);

    const useTerraformActions = await importHook();
    const wrapper = createWrapper({ withAssistantMsg: true });
    const { result } = renderHook(() => useTerraformActions(), { wrapper });

    await act(async () => {
      result.current.run(defaultParams);
    });

    await act(async () => {
      mockSseConnection.onerror?.();
    });

    await act(async () => {
      await vi.waitFor(() => {
        expect(result.current.state).toEqual({ status: "error", message: "Process failed" });
      });
    });

    // No reconnect attempt for a terminal failed session
    expect(mockSubscribe).toHaveBeenCalledTimes(1);
    expect(mockNotifyIfHidden).toHaveBeenCalledWith(
      "Pipeline failed",
      expect.objectContaining({ body: "Process failed" }),
    );
  });

  it("SSE error + recovery failure = error state", async () => {
    mockCheckSessionStatus.mockRejectedValueOnce(new Error("Network error"));

    const useTerraformActions = await importHook();
    const wrapper = createWrapper({ withAssistantMsg: true });
    const { result } = renderHook(() => useTerraformActions(), { wrapper });

    await act(async () => {
      result.current.run(defaultParams);
    });

    await act(async () => {
      mockSseConnection.onerror?.();
    });

    await act(async () => {
      await vi.waitFor(() => {
        expect(result.current.state).toEqual({ status: "error", message: "Connection to server lost" });
      });
    });
  });

  it("workflow error (runTerraformActionWorkflow throws) sets error state", async () => {
    const { ApiError: RealApiError } = await import("@/services/api");
    mockRunWorkflow.mockRejectedValueOnce(new RealApiError(403, { detail: "Forbidden" }));

    const useTerraformActions = await importHook();
    const wrapper = createWrapper({ withAssistantMsg: true });
    const { result } = renderHook(() => useTerraformActions(), { wrapper });

    await act(async () => {
      result.current.run(defaultParams);
    });

    expect(result.current.state).toEqual({ status: "error", message: "Forbidden" });
    expect(mockSubscribe).not.toHaveBeenCalled();
  });

  it("reset closes connection and returns to idle", async () => {
    const useTerraformActions = await importHook();
    const wrapper = createWrapper({ withAssistantMsg: true });
    const { result } = renderHook(() => useTerraformActions(), { wrapper });

    await act(async () => {
      result.current.run(defaultParams);
    });
    expect(result.current.state.status).toBe("streaming");

    act(() => { result.current.reset(); });

    expect(result.current.state).toEqual({ status: "idle" });
    expect(mockSseConnection.close).toHaveBeenCalled();
  });

  it("SSE events update phases correctly", async () => {
    const useTerraformActions = await importHook();
    const wrapper = createWrapper({ withAssistantMsg: true });
    const { result } = renderHook(() => useTerraformActions(), { wrapper });

    await act(async () => {
      result.current.run(defaultParams);
    });

    // Each event should be processed without errors, including APPLY
    await act(async () => {
      mockSseConnection.onmessage?.(sseEvent("STARTED", "Analyzing..."));
    });
    await act(async () => {
      mockSseConnection.onmessage?.(sseEvent("GENERATING", "Generating code..."));
    });
    await act(async () => {
      mockSseConnection.onmessage?.(sseEvent("VALIDATING", "Running terraform validate..."));
    });
    await act(async () => {
      mockSseConnection.onmessage?.(sseEvent("APPLY", "Applying..."));
    });
    await act(async () => {
      mockSseConnection.onmessage?.(sseEvent("REPORT", "Preparing report..."));
    });

    // Still streaming (not completed/failed)
    expect(result.current.state.status).toBe("streaming");
  });

  it("RECONCILING drives the running phase", async () => {
    // The smoke test above cannot catch a missing `case "RECONCILING"`:
    // an unmapped status returns null, the hook skips the state write,
    // and `state` stays "streaming" either way while the assistant sits
    // on the previous step. The context is where that difference shows.
    const useTerraformActions = await importHook();
    const wrapper = createWrapper({ withAssistantMsg: true });
    const { result } = renderHook(
      () => ({ actions: useTerraformActions(), assistant: useAssistantMsg() }),
      { wrapper },
    );

    await act(async () => {
      result.current.actions.run(defaultParams);
    });
    await act(async () => {
      mockSseConnection.onmessage?.(
        sseEvent("RECONCILING", "Reconciling drift state"),
      );
    });

    expect(result.current.assistant.assistantMsgState).toMatchObject({
      pipelineStep: PHASE.RUNNING,
      sseStatus: "RECONCILING",
      msg: "Reconciling drift state",
    });
    expect(result.current.actions.state.status).toBe("streaming");
  });
});

describe("useTerraformActions — inactivity timeout", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
    mockRunWorkflow.mockResolvedValue({ sessionId: "sess-abc" });
    mockResolveOutcome.mockResolvedValue(makeResultsOutcome());
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("90s inactivity triggers timeout error", async () => {
    const { useTerraformActions } = await import("@/hooks/use_terraform_actions");
    const wrapper = createWrapper({ withAssistantMsg: true });
    const { result } = renderHook(() => useTerraformActions(), { wrapper });

    await act(async () => {
      result.current.run(defaultParams);
    });

    act(() => {
      vi.advanceTimersByTime(90_000);
    });

    expect(result.current.state).toEqual({
      status: "error",
      message: "Connection timed out — no response from server",
    });
    expect(mockSseConnection.close).toHaveBeenCalled();
  });

  it("SSE event resets the inactivity timer", async () => {
    const { useTerraformActions } = await import("@/hooks/use_terraform_actions");
    const wrapper = createWrapper({ withAssistantMsg: true });
    const { result } = renderHook(() => useTerraformActions(), { wrapper });

    await act(async () => {
      result.current.run(defaultParams);
    });

    // Advance 80s (below 90s threshold)
    act(() => { vi.advanceTimersByTime(80_000); });

    // SSE event arrives — should reset the timer
    await act(async () => {
      mockSseConnection.onmessage?.(sseEvent("GENERATING", "Working..."));
    });

    // Advance another 80s (below 90s from last event)
    act(() => { vi.advanceTimersByTime(80_000); });

    // Should still be streaming, not timed out
    expect(result.current.state.status).toBe("streaming");

    // Now advance past the 90s mark from last event
    act(() => { vi.advanceTimersByTime(11_000); });

    expect(result.current.state).toEqual({
      status: "error",
      message: "Connection timed out — no response from server",
    });
  });
});

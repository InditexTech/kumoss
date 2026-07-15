// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { createWrapper } from "@/test/render";
import type { SseConnection } from "@/services/core/events";
import type { TerraformActionParams } from "@/services/workflows/terraform_action";

// ─── Mock controls ────────────────────────────────────────────
const mockRunWorkflow = vi.fn<[TerraformActionParams, AbortSignal], Promise<{ sessionId: string }>>()
  .mockResolvedValue({ sessionId: "sess-abc" });

let mockSseConnection: SseConnection & { close: ReturnType<typeof vi.fn> };

function createMockSse(): typeof mockSseConnection {
  return { onmessage: null, onerror: null, close: vi.fn() };
}

const mockSubscribe = vi.fn(() => {
  mockSseConnection = createMockSse();
  return mockSseConnection;
});

const mockGetSessionData = vi.fn().mockResolvedValue({
  id: "sess-abc",
  response: "resource {} code",
  main_history: { user: "deploy", assistant: "done" },
  full_history: [],
  environment: "dev",
  cloud: "azure",
  project: "myproj",
  validation: true,
  branch_name: "feat/test",
  terraform_report: null,
  apply_allowed: true,
});

const mockNotifyIfHidden = vi.fn();

vi.mock("@/services/workflows/terraform_action", () => ({
  runTerraformActionWorkflow: (...args: unknown[]) => mockRunWorkflow(...(args as [TerraformActionParams, AbortSignal])),
}));

vi.mock("@/services/core/events", () => ({
  subscribeToSession: (...args: unknown[]) => mockSubscribe(...(args as [string])),
  getSessionData: (...args: unknown[]) => mockGetSessionData(...(args as [string])),
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
  cloud: "azure",
  environment: "dev",
  userId: "user@test.com",
  mode: "generate",
};

function sseEvent(status_msg: string, message = "") {
  return {
    data: JSON.stringify({
      status_msg,
      detail: { validation_id: null, message },
    }),
  };
}

describe("useTerraformActions", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockRunWorkflow.mockResolvedValue({ sessionId: "sess-abc" });
    mockGetSessionData.mockResolvedValue({
      id: "sess-abc",
      response: "code",
      main_history: { user: "q", assistant: "a" },
      full_history: [],
      environment: "dev",
      cloud: "azure",
      project: "myproj",
      validation: true,
      branch_name: "feat/test",
      terraform_report: null,
      apply_allowed: true,
    });
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
  });

  it("COMPLETED event transitions to success and calls onCompleted", async () => {
    const useTerraformActions = await importHook();
    const wrapper = createWrapper({ withAssistantMsg: true });
    const onCompleted = vi.fn();
    const { result } = renderHook(() => useTerraformActions(), { wrapper });

    await act(async () => {
      result.current.run(defaultParams, onCompleted);
    });

    await act(async () => {
      mockSseConnection.onmessage?.(sseEvent("COMPLETED", "Done."));
    });

    expect(result.current.state).toEqual({ status: "success", sessionId: "sess-abc" });
    expect(mockSseConnection.close).toHaveBeenCalled();

    // Wait for getSessionData promise
    await act(async () => {
      await vi.waitFor(() => {
        expect(mockGetSessionData).toHaveBeenCalledWith("sess-abc");
      });
    });

    await act(async () => {
      await vi.waitFor(() => {
        expect(onCompleted).toHaveBeenCalled();
      });
    });
  });

  it("FAILED event transitions to error", async () => {
    const useTerraformActions = await importHook();
    const wrapper = createWrapper({ withAssistantMsg: true });
    const { result } = renderHook(() => useTerraformActions(), { wrapper });

    await act(async () => {
      result.current.run(defaultParams);
    });

    await act(async () => {
      mockSseConnection.onmessage?.(sseEvent("FAILED", "Generation failed"));
    });

    expect(result.current.state).toEqual({ status: "error", message: "Generation failed" });
    expect(mockSseConnection.close).toHaveBeenCalled();
    expect(mockNotifyIfHidden).toHaveBeenCalledWith("Pipeline failed", expect.objectContaining({ body: "Generation failed" }));
  });

  it("SSE connection error sets error state", async () => {
    const useTerraformActions = await importHook();
    const wrapper = createWrapper({ withAssistantMsg: true });
    const { result } = renderHook(() => useTerraformActions(), { wrapper });

    await act(async () => {
      result.current.run(defaultParams);
    });

    await act(async () => {
      mockSseConnection.onerror?.();
    });

    expect(result.current.state).toEqual({ status: "error", message: "Connection to server lost" });
    expect(mockSseConnection.close).toHaveBeenCalled();
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

    // Each event should be processed without errors
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
      mockSseConnection.onmessage?.(sseEvent("REPORT", "Preparing report..."));
    });

    // Still streaming (not completed/failed)
    expect(result.current.state.status).toBe("streaming");
  });

  it("COMPLETED notifies browser", async () => {
    const useTerraformActions = await importHook();
    const wrapper = createWrapper({ withAssistantMsg: true });
    const { result } = renderHook(() => useTerraformActions(), { wrapper });

    await act(async () => {
      result.current.run(defaultParams);
    });

    await act(async () => {
      mockSseConnection.onmessage?.(sseEvent("COMPLETED", "Done."));
    });

    expect(mockNotifyIfHidden).toHaveBeenCalledWith("Pipeline completed", expect.objectContaining({
      body: "Your infrastructure changes are ready for review.",
    }));
  });
});

describe("useTerraformActions — inactivity timeout", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
    mockRunWorkflow.mockResolvedValue({ sessionId: "sess-abc" });
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

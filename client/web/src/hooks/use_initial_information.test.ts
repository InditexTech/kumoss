// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";
import type {
  InitialInfoParams,
  InitialInfoResult,
} from "@/services/workflows/initial_information";
import { useInitialInformation } from "./use_initial_information";

const { mockRunWorkflow } = vi.hoisted(() => ({
  mockRunWorkflow: vi.fn<
    (
      params: InitialInfoParams,
      signal: AbortSignal,
    ) => Promise<InitialInfoResult>
  >(),
}));

vi.mock("@/services/workflows/initial_information", () => ({
  runInitialInfoWorkflow: (
    params: InitialInfoParams,
    signal: AbortSignal,
  ) => mockRunWorkflow(params, signal),
}));

describe("useInitialInformation", () => {
  it("reset aborts and ignores a pending authorization", async () => {
    let resolveRequest: (result: InitialInfoResult) => void = () => {};
    mockRunWorkflow.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveRequest = resolve;
        }),
    );
    const { result } = renderHook(() => useInitialInformation());
    const params: InitialInfoParams = {
      repositoryUrl: "https://example.com/repo",
      query: "create a vm",
      userEmail: "user@example.com",
    };
    let request: ReturnType<typeof result.current.run>;

    act(() => {
      request = result.current.run(params);
    });
    expect(result.current.state.status).toBe("loading");
    const signal = mockRunWorkflow.mock.calls[0][1];

    act(() => result.current.reset());

    expect(signal.aborted).toBe(true);
    expect(result.current.state.status).toBe("idle");

    await act(async () => {
      resolveRequest({
        ok: true,
        authorization: { result: true, message: "Authorized" },
      });
      await request;
    });

    expect(result.current.state.status).toBe("idle");
  });
});

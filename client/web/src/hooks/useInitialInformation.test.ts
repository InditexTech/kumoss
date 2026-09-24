// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import { http, HttpResponse, delay } from "msw";
import { server } from "@/mocks/server";
import { useInitialInformation } from "./use_initial_information";

const PARAMS = { repositoryUrl: "https://github.com/org/repo", query: "q" };

describe("useInitialInformation", () => {
  it("succeeds when the user is authorized", async () => {
    server.use(
      http.post("/api/v1/auth/authorize", () =>
        HttpResponse.json({ result: true, message: "ok" }),
      ),
    );
    const { result } = renderHook(() => useInitialInformation());

    await act(async () => { await result.current.run(PARAMS); });

    expect(result.current.state.status).toBe("success");
  });

  it("reset drops an authorization still in flight", async () => {
    let answered = false;
    server.use(
      http.post("/api/v1/auth/authorize", async () => {
        await delay(20);
        answered = true;
        return HttpResponse.json({ result: true, message: "ok" });
      }),
    );
    const { result } = renderHook(() => useInitialInformation());

    let pending!: Promise<void>;
    act(() => { pending = result.current.run(PARAMS); });
    act(() => { result.current.reset(); });
    await act(async () => { await pending; });

    await waitFor(() => expect(answered).toBe(true));
    expect(result.current.state.status).toBe("idle");
  });
});

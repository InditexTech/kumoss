// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import React from "react";
import { describe, it, expect } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { SessionProvider, useSession } from "./SessionContext";

function wrapper({ children }: { children: React.ReactNode }) {
  return <SessionProvider>{children}</SessionProvider>;
}

describe("SessionContext", () => {
  it("starts with a zero reset nonce", () => {
    const { result } = renderHook(() => useSession(), { wrapper });

    expect(result.current.resetNonce).toBe(0);
  });

  // The nonce is how consumers that own state outside this provider (the home
  // wizard) learn that a clear was requested somewhere else in the tree.
  it("clears session and PR details and bumps the reset nonce", () => {
    const { result } = renderHook(() => useSession(), { wrapper });

    act(() => {
      result.current.updateSession({
        uuid: "abc-123",
        first_query: "deploy a VM",
      });
      result.current.updatePrDetails({ url: "https://example.com/pr/1" });
    });

    expect(result.current.session.uuid).toBe("abc-123");
    expect(result.current.prDetails.url).toBe("https://example.com/pr/1");

    act(() => result.current.resetSession());

    expect(result.current.session).toEqual({});
    expect(result.current.prDetails).toEqual({});
    expect(result.current.resetNonce).toBe(1);
  });

  it("bumps the nonce once per reset call", () => {
    const { result } = renderHook(() => useSession(), { wrapper });

    act(() => result.current.resetSession());
    act(() => result.current.resetSession());

    expect(result.current.resetNonce).toBe(2);
  });
});

// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { server } from "@/test/server";
import { useRepositoryScan } from "./useRepositoryScan";

describe("useRepositoryScan", () => {
  it("initializes with empty state", () => {
    const { result } = renderHook(() => useRepositoryScan());

    expect(result.current.scanPaths).toEqual([]);
    expect(result.current.scanLoading).toBe(false);
    expect(result.current.scanError).toBeNull();
  });

  it("scan parses the typed URL directly, without the mapping service", async () => {
    const requested: string[] = [];
    let mapped = false;
    server.use(
      http.post("/api/v1/mapping/resolve", () => {
        mapped = true;
        return HttpResponse.json({});
      }),
      http.post("/api/v1/repository/parse", async ({ request }) => {
        const body = (await request.json()) as { repo_uri: string };
        requested.push(body.repo_uri);
        return HttpResponse.json({ roots: ["environments/dev", "environments/pro"] });
      }),
    );

    const { result } = renderHook(() => useRepositoryScan());

    let paths: string[] = [];
    await act(async () => {
      paths = await result.current.scan("https://dev.azure.com/org/project/_git/repo");
    });

    expect(requested).toEqual(["https://dev.azure.com/org/project/_git/repo"]);
    expect(mapped).toBe(false);
    expect(paths).toEqual(["environments/dev", "environments/pro"]);
    expect(result.current.scanPaths).toEqual(["environments/dev", "environments/pro"]);
    expect(result.current.scanLoading).toBe(false);
  });

  it("scan returns empty paths when the repo has no IaC", async () => {
    server.use(
      http.post("/api/v1/repository/parse", () => HttpResponse.json({ roots: [] })),
    );

    const { result } = renderHook(() => useRepositoryScan());

    let paths: string[] = ["x"];
    await act(async () => {
      paths = await result.current.scan("https://example.com/repo");
    });

    expect(paths).toEqual([]);
    expect(result.current.scanPaths).toEqual([]);
  });

  it("scan throws on a failed request", async () => {
    server.use(
      http.post("/api/v1/repository/parse", () =>
        HttpResponse.json({ detail: "Not found" }, { status: 404 }),
      ),
    );

    const { result } = renderHook(() => useRepositoryScan());

    await expect(
      act(async () => {
        await result.current.scan("https://example.com/bad");
      }),
    ).rejects.toThrow();

    await waitFor(() => expect(result.current.scanLoading).toBe(false));
  });

  it("sets scanLoading during the scan", async () => {
    server.use(
      http.post("/api/v1/repository/parse", () => HttpResponse.json({ roots: ["dev"] })),
    );

    const { result } = renderHook(() => useRepositoryScan());

    let pending: Promise<unknown>;
    act(() => {
      pending = result.current.scan("https://example.com/repo");
    });
    expect(result.current.scanLoading).toBe(true);

    await act(async () => {
      await pending;
    });
    expect(result.current.scanLoading).toBe(false);
  });

  it("resetScan clears all state", async () => {
    server.use(
      http.post("/api/v1/repository/parse", () => HttpResponse.json({ roots: ["dev", "pro"] })),
    );

    const { result } = renderHook(() => useRepositoryScan());

    await act(async () => {
      await result.current.scan("https://example.com/repo");
    });
    act(() => result.current.setScanError("err"));

    expect(result.current.scanPaths.length).toBeGreaterThan(0);
    expect(result.current.scanError).toBe("err");

    act(() => result.current.resetScan());

    expect(result.current.scanPaths).toEqual([]);
    expect(result.current.scanLoading).toBe(false);
    expect(result.current.scanError).toBeNull();
  });
});

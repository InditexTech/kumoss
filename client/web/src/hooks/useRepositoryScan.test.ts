// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { server } from "@/test/server";
import { useRepositoryScan } from "./useRepositoryScan";
import type { RepositoryScan } from "./useRepositoryScan";

describe("useRepositoryScan", () => {
  it("initializes with empty state", () => {
    const { result } = renderHook(() => useRepositoryScan());

    expect(result.current.scanPaths).toEqual([]);
    expect(result.current.scanLoading).toBe(false);
    expect(result.current.scanError).toBeNull();
  });

  it("scan parses the typed URL directly", async () => {
    const requested: string[] = [];
    server.use(
      http.post("/api/v1/repository/parse", async ({ request }) => {
        const body = (await request.json()) as { repo_uri: string };
        requested.push(body.repo_uri);
        return HttpResponse.json({
          repo_url: body.repo_uri,
          project_identifier: body.repo_uri,
          roots: ["environments/dev", "environments/pro"],
        });
      }),
    );

    const { result } = renderHook(() => useRepositoryScan());

    let scanned: RepositoryScan = { repoUrl: "", projectIdentifier: "", roots: [] };
    await act(async () => {
      scanned = await result.current.scan("https://dev.azure.com/org/project/_git/repo");
    });

    expect(requested).toEqual(["https://dev.azure.com/org/project/_git/repo"]);
    expect(scanned).toEqual({
      repoUrl: "https://dev.azure.com/org/project/_git/repo",
      projectIdentifier: "https://dev.azure.com/org/project/_git/repo",
      roots: ["environments/dev", "environments/pro"],
    });
    expect(result.current.scanPaths).toEqual(["environments/dev", "environments/pro"]);
    expect(result.current.scanLoading).toBe(false);
  });

  it("scan answers the URL the core resolved a name to", async () => {
    const requested: string[] = [];
    server.use(
      http.post("/api/v1/repository/parse", async ({ request }) => {
        const body = (await request.json()) as { repo_uri: string };
        requested.push(body.repo_uri);
        return HttpResponse.json({
          repo_url: "https://github.com/MySuperOrg/foo.git",
          project_identifier: "foo",
          roots: ["infra"],
        });
      }),
    );

    const { result } = renderHook(() => useRepositoryScan());

    let scanned: RepositoryScan = { repoUrl: "", projectIdentifier: "", roots: [] };
    await act(async () => {
      scanned = await result.current.scan("foo");
    });

    expect(requested).toEqual(["foo"]);
    expect(scanned).toEqual({
      repoUrl: "https://github.com/MySuperOrg/foo.git",
      projectIdentifier: "foo",
      roots: ["infra"],
    });
  });

  it("scan returns empty paths when the repo has no IaC", async () => {
    server.use(
      http.post("/api/v1/repository/parse", () =>
        HttpResponse.json({
          repo_url: "https://example.com/repo",
          project_identifier: "https://example.com/repo",
          roots: [],
        }),
      ),
    );

    const { result } = renderHook(() => useRepositoryScan());

    let scanned: RepositoryScan = { repoUrl: "", projectIdentifier: "", roots: ["x"] };
    await act(async () => {
      scanned = await result.current.scan("https://example.com/repo");
    });

    expect(scanned.roots).toEqual([]);
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
      http.post("/api/v1/repository/parse", () => HttpResponse.json({ repo_url: "https://example.com/repo", roots: ["dev"] })),
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
      http.post("/api/v1/repository/parse", () => HttpResponse.json({ repo_url: "https://example.com/repo", roots: ["dev", "pro"] })),
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

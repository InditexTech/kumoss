// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { server } from "@/test/server";
import { useMapperResolution } from "./useMapperResolution";

describe("useMapperResolution", () => {
  it("initializes with empty state", () => {
    const { result } = renderHook(() => useMapperResolution());

    expect(result.current.scanPaths).toEqual([]);
    expect(result.current.mapperLoading).toBe(false);
    expect(result.current.mapperError).toBeNull();
  });

  it("resolveAndScan returns repoUrl, identifier, and paths on success", async () => {
    server.use(
      http.post("/api/v1/mapping/resolve", () =>
        HttpResponse.json({
          repo_url: "https://dev.azure.com/org/project/_git/repo",
          identifier: "my-repo-identifier",
        }),
      ),
      http.post("/api/v1/repository/parse", () =>
        HttpResponse.json({ roots: ["environments/dev", "environments/pro"] }),
      ),
    );

    const { result } = renderHook(() => useMapperResolution());

    let resolved: Awaited<
      ReturnType<typeof result.current.resolveAndScan>
    >;
    await act(async () => {
      resolved = await result.current.resolveAndScan("my-repo-identifier");
    });

    expect(resolved!.repoUrl).toBe(
      "https://dev.azure.com/org/project/_git/repo",
    );
    expect(resolved!.identifier).toBe("my-repo-identifier");
    // The mapper answered neither, so the wizard must still ask.
    expect(resolved!.provider).toBeNull();
    expect(resolved!.scopeId).toBeNull();
    expect(resolved!.paths).toEqual([
      "environments/dev",
      "environments/pro",
    ]);
    expect(result.current.scanPaths).toEqual([
      "environments/dev",
      "environments/pro",
    ]);
    expect(result.current.mapperLoading).toBe(false);
  });

  it("resolveAndScan surfaces a provider and scope the mapper answered", async () => {
    server.use(
      http.post("/api/v1/mapping/resolve", () =>
        HttpResponse.json({
          repo_url: "https://git.example/iac.git",
          identifier: "my-project",
          terraform_provider: "oci",
          // Not validated against the typed-scope pattern: an OCID
          // contains dots, which that human-typo guard rejects.
          scope_id: "ocid1.compartment.oc1..aaaaexample",
        }),
      ),
      http.post("/api/v1/repository/parse", () =>
        HttpResponse.json({ roots: ["infra"] }),
      ),
    );

    const { result } = renderHook(() => useMapperResolution());

    let resolved: Awaited<ReturnType<typeof result.current.resolveAndScan>>;
    await act(async () => {
      resolved = await result.current.resolveAndScan("my-project");
    });

    expect(resolved!.provider).toBe("oci");
    expect(resolved!.scopeId).toBe("ocid1.compartment.oc1..aaaaexample");
  });

  it("resolveAndScan returns empty paths when repo has no IaC", async () => {
    server.use(
      http.post("/api/v1/mapping/resolve", () =>
        HttpResponse.json({
          repo_url: "https://example.com/repo",
          identifier: "empty-repo",
        }),
      ),
      http.post("/api/v1/repository/parse", () =>
        HttpResponse.json({ roots: [] }),
      ),
    );

    const { result } = renderHook(() => useMapperResolution());

    let resolved: Awaited<
      ReturnType<typeof result.current.resolveAndScan>
    >;
    await act(async () => {
      resolved = await result.current.resolveAndScan("empty-repo");
    });

    expect(resolved!.paths).toEqual([]);
    expect(result.current.scanPaths).toEqual([]);
  });

  it("resolveAndScan throws on network error", async () => {
    server.use(
      http.post("/api/v1/mapping/resolve", () =>
        HttpResponse.json({ detail: "Not found" }, { status: 404 }),
      ),
    );

    const { result } = renderHook(() => useMapperResolution());

    await expect(
      act(async () => {
        await result.current.resolveAndScan("bad-identifier");
      }),
    ).rejects.toThrow();

    await waitFor(() => {
      expect(result.current.mapperLoading).toBe(false);
    });
  });

  it("sets mapperLoading during resolution", async () => {
    server.use(
      http.post("/api/v1/mapping/resolve", () =>
        HttpResponse.json({ repo_url: "url", identifier: "i" }),
      ),
      http.post("/api/v1/repository/parse", () =>
        HttpResponse.json({ roots: ["dev"] }),
      ),
    );

    const { result } = renderHook(() => useMapperResolution());

    expect(result.current.mapperLoading).toBe(false);

    let resolvePromise: Promise<unknown>;
    act(() => {
      resolvePromise = result.current.resolveAndScan("test-repo");
    });
    expect(result.current.mapperLoading).toBe(true);

    await act(async () => {
      await resolvePromise;
    });
    expect(result.current.mapperLoading).toBe(false);
  });

  it("setMapperError sets the error message", () => {
    const { result } = renderHook(() => useMapperResolution());

    act(() => result.current.setMapperError("Something went wrong"));
    expect(result.current.mapperError).toBe("Something went wrong");
  });

  it("resetMapper clears all state", async () => {
    server.use(
      http.post("/api/v1/mapping/resolve", () =>
        HttpResponse.json({ repo_url: "url", identifier: "i" }),
      ),
      http.post("/api/v1/repository/parse", () =>
        HttpResponse.json({ roots: ["dev", "pro"] }),
      ),
    );

    const { result } = renderHook(() => useMapperResolution());

    await act(async () => {
      await result.current.resolveAndScan("repo");
    });
    act(() => result.current.setMapperError("err"));

    expect(result.current.scanPaths.length).toBeGreaterThan(0);
    expect(result.current.mapperError).toBe("err");

    act(() => result.current.resetMapper());

    expect(result.current.scanPaths).toEqual([]);
    expect(result.current.mapperLoading).toBe(false);
    expect(result.current.mapperError).toBeNull();
  });
});

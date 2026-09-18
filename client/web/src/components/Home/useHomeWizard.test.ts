// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { SessionProvider, useSession } from "@/contexts/SessionContext";
import { ModeProvider } from "@/contexts/ModeContext";
import { useHomeWizard } from "./useHomeWizard";

// ─── Dynamic mock controls ────────────────────────────────────
const mockAuthState = vi.fn<() => { status: string; message?: string; data?: unknown }>(() => ({ status: "idle" }));
const mockAuthRun = vi.fn();
const mockAuthReset = vi.fn();

const mockTerraformState = vi.fn<() => { status: string; message?: string }>(() => ({ status: "idle" }));
const mockTerraformRun = vi.fn();
const mockTerraformReset = vi.fn();

const mockResolveAndScan = vi.fn<
  (identifier: string) => Promise<{ repoUrl: string; project: string | null; paths: string[] }>
>();
const mockScanPathsValue = vi.fn<() => string[]>(() => []);
const mockMapperLoadingValue = vi.fn(() => false);
const mockMapperErrorValue = vi.fn<() => string | null>(() => null);
const mockSetMapperError = vi.fn();
const mockResetMapper = vi.fn();

const mockHandleOutcome = vi.fn();
vi.mock("@/hooks/useWizardTerraform", () => ({
  useWizardTerraform: () => ({
    handleOutcome: mockHandleOutcome,
  }),
}));

vi.mock("@/hooks/use_initial_information", () => ({
  useInitialInformation: () => ({
    state: mockAuthState(),
    run: mockAuthRun,
    reset: mockAuthReset,
  }),
}));

vi.mock("@/hooks/use_terraform_actions", () => ({
  useTerraformActions: () => ({
    state: mockTerraformState(),
    run: mockTerraformRun,
    reset: mockTerraformReset,
  }),
}));

vi.mock("@/hooks/useMapperResolution", () => ({
  useMapperResolution: () => ({
    scanPaths: mockScanPathsValue(),
    mapperLoading: mockMapperLoadingValue(),
    mapperError: mockMapperErrorValue(),
    setMapperError: mockSetMapperError,
    resolveAndScan: mockResolveAndScan,
    resetMapper: mockResetMapper,
  }),
}));

function Wrapper({ children }: { children: React.ReactNode }) {
  return React.createElement(
    MemoryRouter,
    { initialEntries: ["/home"] },
    React.createElement(
      SessionProvider,
      null,
      React.createElement(ModeProvider, null, children),
    ),
  );
}

describe("useHomeWizard orchestrator", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockAuthState.mockReturnValue({ status: "idle" });
    mockTerraformState.mockReturnValue({ status: "idle" });
    mockScanPathsValue.mockReturnValue([]);
    mockMapperLoadingValue.mockReturnValue(false);
    mockMapperErrorValue.mockReturnValue(null);
  });

  it("initializes with query step and wizard homeView", () => {
    const { result } = renderHook(() => useHomeWizard(), {
      wrapper: Wrapper,
    });

    expect(result.current.step).toBe("query");
    expect(result.current.homeView).toBe("wizard");
    expect(result.current.isLoading).toBe(false);
    expect(result.current.error).toBeNull();
    expect(result.current.scanPaths).toEqual([]);
  });

  it("handleInput with query advances to repository_url step", async () => {
    const { result } = renderHook(
      () => ({
        wizard: useHomeWizard(),
        session: useSession(),
      }),
      { wrapper: Wrapper },
    );

    await act(async () => {
      await result.current.wizard.handleInput("deploy a VM");
    });

    expect(result.current.wizard.step).toBe("repository_url");
    expect(result.current.wizard.data.query).toBe("deploy a VM");
    expect(result.current.session.session.first_query).toBe("deploy a VM");
  });

  it("handleInput rejects empty query", async () => {
    const { result } = renderHook(() => useHomeWizard(), {
      wrapper: Wrapper,
    });

    await act(async () => {
      await result.current.handleInput("   ");
    });

    expect(result.current.step).toBe("query");
  });

  it("handleInput rejects query longer than 500 chars", async () => {
    const { result } = renderHook(() => useHomeWizard(), {
      wrapper: Wrapper,
    });

    const longQuery = "a".repeat(501);
    await act(async () => {
      await result.current.handleInput(longQuery);
    });

    expect(result.current.step).toBe("query");
  });

  it("handlePath sets iacPath and advances to provider", () => {
    const { result } = renderHook(
      () => ({
        wizard: useHomeWizard(),
        session: useSession(),
      }),
      { wrapper: Wrapper },
    );

    act(() => {
      result.current.wizard.handlePath("environments/dev");
    });

    expect(result.current.wizard.step).toBe("provider");
    expect(result.current.wizard.data.iacPath).toBe("environments/dev");
    expect(result.current.session.session.workspace?.root_path).toBe(
      "environments/dev",
    );
  });

  it("handleProvider sets provider and advances to cloud_scope", () => {
    const { result } = renderHook(
      () => ({
        wizard: useHomeWizard(),
        session: useSession(),
      }),
      { wrapper: Wrapper },
    );

    act(() => {
      result.current.wizard.handleProvider("azure");
    });

    expect(result.current.wizard.step).toBe("cloud_scope");
    expect(result.current.wizard.data.provider).toBe("azure");
    expect(result.current.session.session.provider).toBe("azure");
  });

  it("reset restores wizard state to initial", async () => {
    const { result } = renderHook(() => useHomeWizard(), {
      wrapper: Wrapper,
    });

    await act(async () => {
      await result.current.handleInput("create something");
    });
    expect(result.current.step).toBe("repository_url");

    act(() => result.current.reset());

    expect(result.current.step).toBe("query");
    expect(result.current.data).toEqual({
      query: "",
      repositoryUrl: "",
      provider: "",
      cloudScope: "",
      iacPath: "",
    });
    expect(result.current.scanPaths).toEqual([]);
    expect(result.current.isLoading).toBe(false);
    expect(result.current.error).toBeNull();
  });

  it("promptMessage and placeholder return correct values per step", async () => {
    const { result } = renderHook(() => useHomeWizard(), {
      wrapper: Wrapper,
    });

    expect(result.current.promptMessage()).toContain("need");
    expect(result.current.placeholder()).toContain("Type");

    await act(async () => {
      await result.current.handleInput("create a vm");
    });

    expect(result.current.promptMessage()).toContain("repository");
  });

  it("isLoading is false when all sub-states are idle", () => {
    const { result } = renderHook(() => useHomeWizard(), {
      wrapper: Wrapper,
    });

    expect(result.current.isLoading).toBe(false);
  });

  it("error is null when no sub-state has errors", () => {
    const { result } = renderHook(() => useHomeWizard(), {
      wrapper: Wrapper,
    });

    expect(result.current.error).toBeNull();
  });
});

describe("useHomeWizard — repository resolution", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockAuthState.mockReturnValue({ status: "idle" });
    mockTerraformState.mockReturnValue({ status: "idle" });
    mockScanPathsValue.mockReturnValue([]);
    mockMapperLoadingValue.mockReturnValue(false);
    mockMapperErrorValue.mockReturnValue(null);
  });

  it("single IaC path auto-advances to provider", async () => {
    mockResolveAndScan.mockResolvedValueOnce({
      repoUrl: "https://dev.azure.com/org/repo",
      project: "myproj",
      paths: ["environments/dev"],
    });

    const { result } = renderHook(
      () => ({ wizard: useHomeWizard(), session: useSession() }),
      { wrapper: Wrapper },
    );

    await act(async () => { await result.current.wizard.handleInput("deploy a VM"); });
    await act(async () => { await result.current.wizard.handleInput("https://dev.azure.com/org/repo"); });

    expect(result.current.wizard.step).toBe("provider");
    expect(result.current.wizard.data.repositoryUrl).toBe("https://dev.azure.com/org/repo");
    expect(result.current.wizard.data.iacPath).toBe("environments/dev");
    expect(result.current.session.session.workspace).toEqual({
      uri: "https://dev.azure.com/org/repo",
      root_path: "environments/dev",
    });
  });

  it("multiple IaC paths go to iac_path step", async () => {
    mockResolveAndScan.mockResolvedValueOnce({
      repoUrl: "https://dev.azure.com/org/repo",
      project: "myproj",
      paths: ["environments/dev", "environments/pro"],
    });

    const { result } = renderHook(() => useHomeWizard(), { wrapper: Wrapper });

    await act(async () => { await result.current.handleInput("deploy a VM"); });
    await act(async () => { await result.current.handleInput("https://dev.azure.com/org/repo"); });

    expect(result.current.step).toBe("iac_path");
  });

  it("zero IaC paths sets mapper error", async () => {
    mockResolveAndScan.mockResolvedValueOnce({
      repoUrl: "https://dev.azure.com/org/repo",
      project: "myproj",
      paths: [],
    });

    const { result } = renderHook(() => useHomeWizard(), { wrapper: Wrapper });

    await act(async () => { await result.current.handleInput("deploy a VM"); });
    await act(async () => { await result.current.handleInput("https://dev.azure.com/org/repo"); });

    expect(mockSetMapperError).toHaveBeenCalled();
  });

  it("resolve failure sets mapper error", async () => {
    mockResolveAndScan.mockRejectedValueOnce(new Error("Network error"));

    const { result } = renderHook(() => useHomeWizard(), { wrapper: Wrapper });

    await act(async () => { await result.current.handleInput("deploy a VM"); });
    await act(async () => { await result.current.handleInput("https://bad-url.com/repo"); });

    expect(mockSetMapperError).toHaveBeenCalled();
  });
});

describe("useHomeWizard — auth & terraform orchestration", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockAuthState.mockReturnValue({ status: "idle" });
    mockTerraformState.mockReturnValue({ status: "idle" });
    mockScanPathsValue.mockReturnValue([]);
    mockMapperLoadingValue.mockReturnValue(false);
    mockMapperErrorValue.mockReturnValue(null);
  });

  it("cloud_scope input stores the scope and calls auth.run with correct params", async () => {
    mockResolveAndScan.mockResolvedValueOnce({
      repoUrl: "https://dev.azure.com/org/repo",
      project: "myproj",
      paths: ["environments/dev"],
    });

    const { result } = renderHook(
      () => ({ wizard: useHomeWizard(), session: useSession() }),
      { wrapper: Wrapper },
    );

    await act(async () => { await result.current.wizard.handleInput("deploy a VM"); });
    await act(async () => { await result.current.wizard.handleInput("https://dev.azure.com/org/repo"); });
    act(() => { result.current.wizard.handleProvider("azure"); });
    await act(async () => { await result.current.wizard.handleInput("sub-123"); });

    expect(result.current.session.session.scope_id).toBe("sub-123");
    expect(mockAuthRun).toHaveBeenCalledWith({
      repositoryUrl: "https://dev.azure.com/org/repo",
      query: "deploy a VM",
      cloud: "azure",
      environment: "environments/dev",
    });
  });

  it("auth success triggers terraform.run", async () => {
    mockResolveAndScan.mockResolvedValueOnce({
      repoUrl: "https://dev.azure.com/org/repo",
      project: "myproj",
      paths: ["environments/dev"],
    });

    const { result, rerender } = renderHook(() => useHomeWizard(), { wrapper: Wrapper });

    await act(async () => { await result.current.handleInput("deploy a VM"); });
    await act(async () => { await result.current.handleInput("https://dev.azure.com/org/repo"); });
    act(() => { result.current.handleProvider("azure"); });
    await act(async () => { await result.current.handleInput("sub-123"); });

    mockAuthState.mockReturnValue({ status: "success" });
    await act(async () => { rerender(); });

    expect(mockTerraformRun).toHaveBeenCalled();
    expect(mockTerraformRun.mock.calls[0][0]).toMatchObject({
      repoUri: "https://dev.azure.com/org/repo",
      query: "deploy a VM",
      terraformProviders: "azure",
      scopeId: "sub-123",
      iacPath: "environments/dev",
      mode: "generate",
    });
  });

  it("auth success triggers terraform only once (ref guard)", async () => {
    mockResolveAndScan.mockResolvedValueOnce({
      repoUrl: "https://dev.azure.com/org/repo",
      project: null,
      paths: ["environments/dev"],
    });

    const { result, rerender } = renderHook(() => useHomeWizard(), { wrapper: Wrapper });

    await act(async () => { await result.current.handleInput("deploy a VM"); });
    await act(async () => { await result.current.handleInput("https://dev.azure.com/org/repo"); });
    act(() => { result.current.handleProvider("azure"); });
    await act(async () => { await result.current.handleInput("sub-123"); });

    mockAuthState.mockReturnValue({ status: "success" });
    await act(async () => { rerender(); });
    await act(async () => { rerender(); });

    expect(mockTerraformRun).toHaveBeenCalledTimes(1);
  });

  it("cloud_scope rejects invalid scope (special chars)", async () => {
    mockResolveAndScan.mockResolvedValueOnce({
      repoUrl: "https://dev.azure.com/org/repo",
      project: null,
      paths: ["environments/dev"],
    });

    const { result } = renderHook(() => useHomeWizard(), { wrapper: Wrapper });

    await act(async () => { await result.current.handleInput("deploy a VM"); });
    await act(async () => { await result.current.handleInput("https://dev.azure.com/org/repo"); });
    act(() => { result.current.handleProvider("azure"); });
    await act(async () => { await result.current.handleInput("azure!@#"); });

    expect(mockAuthRun).not.toHaveBeenCalled();
  });
});

describe("useHomeWizard — iterate & applyAfterPr", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockAuthState.mockReturnValue({ status: "idle" });
    mockTerraformState.mockReturnValue({ status: "idle" });
    mockScanPathsValue.mockReturnValue([]);
    mockMapperLoadingValue.mockReturnValue(false);
    mockMapperErrorValue.mockReturnValue(null);
  });

  it("iterate does nothing without a session uuid", () => {
    const { result } = renderHook(() => useHomeWizard(), { wrapper: Wrapper });

    act(() => { result.current.iterate("add a database"); });

    expect(mockTerraformRun).not.toHaveBeenCalled();
  });

  it("iterate calls terraform.run with the session uuid", async () => {
    const { result } = renderHook(
      () => ({ wizard: useHomeWizard(), session: useSession() }),
      { wrapper: Wrapper },
    );

    act(() => {
      result.current.session.updateSession({ uuid: "abc-123" });
    });

    mockResolveAndScan.mockResolvedValueOnce({
      repoUrl: "https://dev.azure.com/org/repo",
      project: null,
      paths: ["environments/dev"],
    });

    await act(async () => { await result.current.wizard.handleInput("deploy a VM"); });
    await act(async () => { await result.current.wizard.handleInput("https://dev.azure.com/org/repo"); });
    act(() => { result.current.wizard.handleProvider("azure"); });
    await act(async () => { await result.current.wizard.handleInput("sub-123"); });

    act(() => { result.current.wizard.iterate("add a database"); });

    expect(mockTerraformRun).toHaveBeenCalled();
    expect(mockTerraformRun.mock.calls[0][0]).toMatchObject({
      sessionId: "abc-123",
      query: "add a database",
    });
  });

  it("applyAfterPr does nothing without a session uuid", () => {
    const { result } = renderHook(() => useHomeWizard(), { wrapper: Wrapper });

    act(() => { result.current.applyAfterPr(); });

    expect(mockTerraformRun).not.toHaveBeenCalled();
  });

  it("applyAfterPr calls terraform in import mode", async () => {
    const { result } = renderHook(
      () => ({ wizard: useHomeWizard(), session: useSession() }),
      { wrapper: Wrapper },
    );

    act(() => {
      result.current.session.updateSession({
        uuid: "abc-123",
        first_query: "deploy a VM",
      });
    });

    mockResolveAndScan.mockResolvedValueOnce({
      repoUrl: "https://dev.azure.com/org/repo",
      project: null,
      paths: ["environments/dev"],
    });

    await act(async () => { await result.current.wizard.handleInput("deploy a VM"); });
    await act(async () => { await result.current.wizard.handleInput("https://dev.azure.com/org/repo"); });
    act(() => { result.current.wizard.handleProvider("azure"); });
    await act(async () => { await result.current.wizard.handleInput("sub-123"); });

    act(() => { result.current.wizard.applyAfterPr(); });

    expect(mockTerraformRun).toHaveBeenCalled();
    expect(mockTerraformRun.mock.calls[0][0]).toMatchObject({
      sessionId: "abc-123",
      mode: "import",
    });
  });

  // Defence in depth: the route already declines to call this for a drift
  // session, but applyAfterPr is exposed through the outlet context and any
  // future route could reach it.
  it("applyAfterPr refuses to apply a drift session", () => {
    const { result } = renderHook(
      () => ({ wizard: useHomeWizard(), session: useSession() }),
      { wrapper: Wrapper },
    );

    act(() => {
      result.current.session.updateSession({
        uuid: "abc-123",
        operation: "drift",
      });
    });

    act(() => { result.current.wizard.applyAfterPr(); });

    expect(mockTerraformRun).not.toHaveBeenCalled();
  });
});

describe("useHomeWizard — retry", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockAuthState.mockReturnValue({ status: "idle" });
    mockTerraformState.mockReturnValue({ status: "idle" });
    mockScanPathsValue.mockReturnValue([]);
    mockMapperLoadingValue.mockReturnValue(false);
    mockMapperErrorValue.mockReturnValue(null);
  });

  it("retry with mapper error resets to repository_url", async () => {
    mockMapperErrorValue.mockReturnValue("No IaC paths found");

    const { result } = renderHook(() => useHomeWizard(), { wrapper: Wrapper });

    await act(async () => { await result.current.handleInput("deploy a VM"); });

    act(() => { result.current.retry(); });

    expect(result.current.step).toBe("repository_url");
    expect(mockResetMapper).toHaveBeenCalled();
    expect(mockAuthReset).toHaveBeenCalled();
    expect(mockTerraformReset).toHaveBeenCalled();
  });

  it("retry with auth error resets to cloud_scope", async () => {
    mockAuthState.mockReturnValue({ status: "error", message: "Forbidden" });

    const { result } = renderHook(() => useHomeWizard(), { wrapper: Wrapper });

    act(() => { result.current.retry(); });

    expect(result.current.step).toBe("cloud_scope");
    expect(mockAuthReset).toHaveBeenCalled();
    expect(mockTerraformReset).toHaveBeenCalled();
  });

  it("retry with terraform error resets terraform state", () => {
    mockTerraformState.mockReturnValue({ status: "error", message: "Plan failed" });

    const { result } = renderHook(() => useHomeWizard(), { wrapper: Wrapper });

    act(() => { result.current.retry(); });

    expect(mockTerraformReset).toHaveBeenCalled();
  });
});

describe("useHomeWizard — aggregated isLoading & error", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockAuthState.mockReturnValue({ status: "idle" });
    mockTerraformState.mockReturnValue({ status: "idle" });
    mockScanPathsValue.mockReturnValue([]);
    mockMapperLoadingValue.mockReturnValue(false);
    mockMapperErrorValue.mockReturnValue(null);
  });

  it("isLoading is true when mapper is loading", () => {
    mockMapperLoadingValue.mockReturnValue(true);
    const { result } = renderHook(() => useHomeWizard(), { wrapper: Wrapper });
    expect(result.current.isLoading).toBe(true);
  });

  it("isLoading is true when auth is loading", () => {
    mockAuthState.mockReturnValue({ status: "loading" });
    const { result } = renderHook(() => useHomeWizard(), { wrapper: Wrapper });
    expect(result.current.isLoading).toBe(true);
  });

  it("isLoading is true when terraform is loading", () => {
    mockTerraformState.mockReturnValue({ status: "loading" });
    const { result } = renderHook(() => useHomeWizard(), { wrapper: Wrapper });
    expect(result.current.isLoading).toBe(true);
  });

  it("error reflects mapper error first", () => {
    mockMapperErrorValue.mockReturnValue("Repository not found");
    const { result } = renderHook(() => useHomeWizard(), { wrapper: Wrapper });
    expect(result.current.error).toBe("Repository not found");
  });

  it("error reflects auth error when mapper has none", () => {
    mockAuthState.mockReturnValue({ status: "error", message: "Unauthorized" });
    const { result } = renderHook(() => useHomeWizard(), { wrapper: Wrapper });
    expect(result.current.error).toBe("Unauthorized");
  });

  it("error reflects terraform error when mapper and auth have none", () => {
    mockTerraformState.mockReturnValue({ status: "error", message: "Plan failed" });
    const { result } = renderHook(() => useHomeWizard(), { wrapper: Wrapper });
    expect(result.current.error).toBe("Plan failed");
  });

  it("mapper error takes precedence over auth error", () => {
    mockMapperErrorValue.mockReturnValue("Mapper error");
    mockAuthState.mockReturnValue({ status: "error", message: "Auth error" });
    const { result } = renderHook(() => useHomeWizard(), { wrapper: Wrapper });
    expect(result.current.error).toBe("Mapper error");
  });
});

// The header logo is rendered above the router and cannot reach the wizard's
// state directly, so it clears through SessionContext's reset nonce.
describe("useHomeWizard — clear requested from outside", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockAuthState.mockReturnValue({ status: "idle" });
    mockTerraformState.mockReturnValue({ status: "idle" });
    mockScanPathsValue.mockReturnValue([]);
    mockMapperLoadingValue.mockReturnValue(false);
    mockMapperErrorValue.mockReturnValue(null);
  });

  it("discards the collected information when the nonce is bumped", async () => {
    const { result } = renderHook(
      () => ({ wizard: useHomeWizard(), session: useSession() }),
      { wrapper: Wrapper },
    );

    await act(async () => {
      await result.current.wizard.handleInput("deploy a VM");
    });
    expect(result.current.wizard.step).toBe("repository_url");
    expect(result.current.wizard.data.query).toBe("deploy a VM");

    await act(async () => {
      result.current.session.resetSession();
    });

    expect(result.current.wizard.step).toBe("query");
    expect(result.current.wizard.data).toEqual({
      query: "",
      repositoryUrl: "",
      provider: "",
      cloudScope: "",
      iacPath: "",
    });
    // In-flight authorization / terraform work is aborted, not just hidden.
    expect(mockResetMapper).toHaveBeenCalled();
    expect(mockAuthReset).toHaveBeenCalled();
    expect(mockTerraformReset).toHaveBeenCalled();
  });

  // Mounting is not a clear request: a deep link into /home/results/:id would
  // otherwise be bounced straight back to the wizard on load.
  it("does not clear on mount", () => {
    renderHook(() => useHomeWizard(), { wrapper: Wrapper });

    expect(mockResetMapper).not.toHaveBeenCalled();
    expect(mockAuthReset).not.toHaveBeenCalled();
    expect(mockTerraformReset).not.toHaveBeenCalled();
  });
});

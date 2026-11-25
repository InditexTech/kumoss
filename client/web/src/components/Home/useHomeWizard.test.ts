// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { SessionProvider, useSession } from "@/contexts/SessionContext";
import { ModeProvider, useMode } from "@/contexts/ModeContext";
import { MODE } from "@/types/ui";
import { STRINGS } from "@/constants/strings";
import { useHomeWizard } from "./useHomeWizard";
import { ApiError } from "@/services/api";
import type { RepositoryScan } from "@/hooks/useRepositoryScan";
import type { ManifestProbeRequest, ManifestProbeResponse } from "@/types/api";

// ─── Dynamic mock controls ────────────────────────────────────
const mockTerraformState = vi.fn<() => { status: string; message?: string }>(() => ({ status: "idle" }));
const mockTerraformRun = vi.fn();
const mockTerraformReset = vi.fn();

const mockScan = vi.fn<(input: string) => Promise<RepositoryScan>>();
const mockScanPathsValue = vi.fn<() => string[]>(() => []);
const mockScanLoadingValue = vi.fn(() => false);
const mockScanErrorValue = vi.fn<() => string | null>(() => null);
const mockSetScanError = vi.fn();
const mockResetScan = vi.fn();

const NOTHING_NEEDED: ManifestProbeResponse = {
  status: "up_to_date",
  needs_input: false,
  missing_variables: [],
  selectable_var_files: [],
  selected_var_files: [],
  missing_var_files: [],
  provider_changes: [],
  missing_scopes: [],
};
const mockProbeManifest = vi.fn(
  async (_request: ManifestProbeRequest): Promise<ManifestProbeResponse> => NOTHING_NEEDED,
);
vi.mock("@/services/core/manifest", () => ({
  probeManifest: (request: ManifestProbeRequest) => mockProbeManifest(request),
}));

const mockHandleOutcome = vi.fn();
vi.mock("@/hooks/useWizardTerraform", () => ({
  useWizardTerraform: () => ({
    handleOutcome: mockHandleOutcome,
  }),
}));

vi.mock("@/hooks/use_terraform_actions", () => ({
  useTerraformActions: () => ({
    state: mockTerraformState(),
    run: mockTerraformRun,
    reset: mockTerraformReset,
  }),
}));

vi.mock("@/hooks/useRepositoryScan", () => ({
  useRepositoryScan: () => ({
    scanPaths: mockScanPathsValue(),
    scanLoading: mockScanLoadingValue(),
    scanError: mockScanErrorValue(),
    setScanError: mockSetScanError,
    scan: mockScan,
    resetScan: mockResetScan,
  }),
}));

const REPO = "https://dev.azure.com/org/repo";

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
    mockTerraformState.mockReturnValue({ status: "idle" });
    mockScanPathsValue.mockReturnValue([]);
    mockScanLoadingValue.mockReturnValue(false);
    mockScanErrorValue.mockReturnValue(null);
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

  it("handlePath sets rootModulePath and advances to inputs", async () => {
    mockScan.mockResolvedValueOnce({ repoUrl: REPO, roots: ["environments/dev", "environments/pro"] });

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
    await act(async () => {
      await result.current.wizard.handleInput(REPO);
    });

    act(() => {
      result.current.wizard.handlePath("environments/dev");
    });

    expect(result.current.wizard.step).toBe("inputs");
    expect(result.current.wizard.data.rootModulePath).toBe("environments/dev");
    expect(result.current.session.session.workspace?.root_path).toBe(
      "environments/dev",
    );
    await waitFor(() => expect(mockTerraformRun).toHaveBeenCalled());
  });

  it("no longer exposes a provider handler", () => {
    const { result } = renderHook(() => useHomeWizard(), { wrapper: Wrapper });
    expect(result.current).not.toHaveProperty("handleProvider");
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
      rootModulePath: "",
      inputsChecked: false,
      inputs: null,
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

describe("useHomeWizard — repository scan", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockTerraformState.mockReturnValue({ status: "idle" });
    mockScanPathsValue.mockReturnValue([]);
    mockScanLoadingValue.mockReturnValue(false);
    mockScanErrorValue.mockReturnValue(null);
  });

  it("scans the trimmed input", async () => {
    mockScan.mockResolvedValueOnce({ repoUrl: REPO, roots: ["environments/dev", "environments/pro"] });
    const { result } = renderHook(() => useHomeWizard(), { wrapper: Wrapper });

    await act(async () => { await result.current.handleInput("deploy a VM"); });
    await act(async () => { await result.current.handleInput(`  ${REPO}  `); });

    expect(mockScan).toHaveBeenCalledWith(REPO);
    expect(result.current.data.repositoryUrl).toBe(REPO);
  });

  it("keeps the URL a repository name resolved to, not the name", async () => {
    const resolvedUrl = "https://github.com/MySuperOrg/foo.git";
    mockScan.mockResolvedValueOnce({ repoUrl: resolvedUrl, roots: ["environments/dev", "environments/pro"] });
    const { result } = renderHook(
      () => ({ wizard: useHomeWizard(), session: useSession() }),
      { wrapper: Wrapper },
    );

    await act(async () => { await result.current.wizard.handleInput("deploy a VM"); });
    await act(async () => { await result.current.wizard.handleInput("foo"); });

    expect(mockScan).toHaveBeenCalledWith("foo");
    expect(result.current.wizard.data.repositoryUrl).toBe(resolvedUrl);
    expect(result.current.session.session.workspace).toEqual({ uri: resolvedUrl });

    act(() => { result.current.wizard.handlePath("environments/pro"); });
    await waitFor(() => expect(mockTerraformRun).toHaveBeenCalled());
    expect(mockTerraformRun.mock.calls[0][0]).toMatchObject({ repoUri: resolvedUrl });
  });

  it("shows the core's reason when a name cannot be resolved", async () => {
    mockScan.mockRejectedValueOnce(
      new ApiError(404, { detail: "Set MAPPING_PREFIX_IDENTIFIER or type the full URL." }),
    );
    const { result } = renderHook(() => useHomeWizard(), { wrapper: Wrapper });

    await act(async () => { await result.current.handleInput("deploy a VM"); });
    await act(async () => { await result.current.handleInput("foo"); });

    expect(mockSetScanError).toHaveBeenCalledWith(
      "Set MAPPING_PREFIX_IDENTIFIER or type the full URL.",
    );
  });

  it("single root module path skips provider/scope and goes straight to inputs", async () => {
    mockScan.mockResolvedValueOnce({ repoUrl: REPO, roots: ["environments/dev"] });
    let answer: (r: ManifestProbeResponse) => void = () => {};
    mockProbeManifest.mockImplementationOnce(
      () => new Promise<ManifestProbeResponse>((resolve) => { answer = resolve; }),
    );

    const { result } = renderHook(
      () => ({ wizard: useHomeWizard(), session: useSession() }),
      { wrapper: Wrapper },
    );

    await act(async () => { await result.current.wizard.handleInput("deploy a VM"); });
    await act(async () => { await result.current.wizard.handleInput(REPO); });

    expect(result.current.wizard.step).toBe("inputs");
    expect(result.current.wizard.isLoading).toBe(true);
    expect(result.current.wizard.loadingMessage).toBe(STRINGS.wizard.loadingInputs);
    expect(result.current.wizard.data.repositoryUrl).toBe(REPO);
    expect(result.current.wizard.data.rootModulePath).toBe("environments/dev");
    expect(result.current.session.session.workspace).toEqual({
      uri: REPO,
      root_path: "environments/dev",
    });

    await act(async () => { answer(NOTHING_NEEDED); });
    await waitFor(() => expect(mockTerraformRun).toHaveBeenCalled());
  });

  it("multiple root module paths go to root_module_path, then to inputs", async () => {
    mockScan.mockResolvedValueOnce({ repoUrl: REPO, roots: ["environments/dev", "environments/pro"] });

    const { result } = renderHook(() => useHomeWizard(), { wrapper: Wrapper });

    await act(async () => { await result.current.handleInput("deploy a VM"); });
    await act(async () => { await result.current.handleInput(REPO); });

    expect(result.current.step).toBe("root_module_path");
    expect(mockProbeManifest).not.toHaveBeenCalled();
    expect(mockTerraformRun).not.toHaveBeenCalled();

    act(() => { result.current.handlePath("environments/pro"); });

    expect(result.current.step).toBe("inputs");
    await waitFor(() => expect(mockTerraformRun).toHaveBeenCalled());
    expect(mockTerraformRun).toHaveBeenCalledWith(
      {
        repoUri: REPO,
        query: "deploy a VM",
        mode: "generate",
        rootModulePath: "environments/pro",
      },
      mockHandleOutcome,
    );
  });

  it("zero root module paths reports that none were found", async () => {
    mockScan.mockResolvedValueOnce({ repoUrl: REPO, roots: [] });

    const { result } = renderHook(() => useHomeWizard(), { wrapper: Wrapper });

    await act(async () => { await result.current.handleInput("deploy a VM"); });
    await act(async () => { await result.current.handleInput(REPO); });

    expect(mockSetScanError).toHaveBeenCalledWith(STRINGS.wizard.noRootModulePaths);
    expect(mockProbeManifest).not.toHaveBeenCalled();
  });

  it("a failed scan sets the scan error", async () => {
    mockScan.mockRejectedValueOnce(new Error("Network error"));

    const { result } = renderHook(() => useHomeWizard(), { wrapper: Wrapper });

    await act(async () => { await result.current.handleInput("deploy a VM"); });
    await act(async () => { await result.current.handleInput("https://bad-url.com/repo"); });

    expect(mockSetScanError).toHaveBeenCalledWith(STRINGS.wizard.scanError);
  });
});

describe("useHomeWizard — first call", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockTerraformState.mockReturnValue({ status: "idle" });
    mockScanPathsValue.mockReturnValue([]);
    mockScanLoadingValue.mockReturnValue(false);
    mockScanErrorValue.mockReturnValue(null);
  });

  it("probes with the repository and root module only: no provider", async () => {
    mockScan.mockResolvedValueOnce({ repoUrl: REPO, roots: ["environments/dev"] });
    const { result } = renderHook(() => useHomeWizard(), { wrapper: Wrapper });

    await act(async () => { await result.current.handleInput("deploy a VM"); });
    await act(async () => { await result.current.handleInput(REPO); });

    await waitFor(() => expect(mockProbeManifest).toHaveBeenCalled());
    const request = mockProbeManifest.mock.calls[0][0];
    expect(request).toEqual({ repo_uri: REPO, root_module_path: "environments/dev" });
    expect(request).not.toHaveProperty("terraform_provider");
  });

  it("starts the session with repo, query and root module, and no provider or scope", async () => {
    mockScan.mockResolvedValueOnce({ repoUrl: REPO, roots: ["environments/dev"] });
    const { result } = renderHook(
      () => ({ wizard: useHomeWizard(), session: useSession() }),
      { wrapper: Wrapper },
    );

    await act(async () => { await result.current.wizard.handleInput("deploy a VM"); });
    await act(async () => { await result.current.wizard.handleInput(REPO); });

    await waitFor(() => expect(mockTerraformRun).toHaveBeenCalled());
    const params = mockTerraformRun.mock.calls[0][0];
    expect(params).toEqual({
      repoUri: REPO,
      query: "deploy a VM",
      mode: "generate",
      rootModulePath: "environments/dev",
    });
    expect(params).not.toHaveProperty("terraformProviders");
    expect(params).not.toHaveProperty("scopeId");
    expect(result.current.session.session).not.toHaveProperty("providers");
  });
});

describe("useHomeWizard — full modes skip the query", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockTerraformState.mockReturnValue({ status: "idle" });
    mockScanPathsValue.mockReturnValue([]);
    mockScanLoadingValue.mockReturnValue(false);
    mockScanErrorValue.mockReturnValue(null);
  });

  function renderWizard() {
    return renderHook(
      () => ({ wizard: useHomeWizard(), mode: useMode(), session: useSession() }),
      { wrapper: Wrapper },
    );
  }

  it.each([
    [MODE.IMPORT, "Import all the infrastructure"],
    [MODE.DRIFT, "Reconcile all the drift"],
  ])("%s starts at the repository with a fixed query", (mode, query) => {
    const { result } = renderWizard();

    act(() => { result.current.mode.setMode(mode); });

    expect(result.current.wizard.step).toBe("repository_url");
    expect(result.current.wizard.data.query).toBe(query);
    expect(result.current.session.session.first_query).toBe(query);
  });

  it("a full mode overrides a query typed in a partial mode", async () => {
    const { result } = renderWizard();

    act(() => { result.current.mode.setMode(MODE.PARTIAL_IMPORT); });
    await act(async () => { await result.current.wizard.handleInput("import the vault"); });
    act(() => { result.current.mode.setMode(MODE.IMPORT); });

    expect(result.current.wizard.step).toBe("repository_url");
    expect(result.current.wizard.data.query).toBe("Import all the infrastructure");
  });

  it("switching between full modes swaps the fixed query", () => {
    const { result } = renderWizard();

    act(() => { result.current.mode.setMode(MODE.DRIFT); });
    act(() => { result.current.mode.setMode(MODE.IMPORT); });

    expect(result.current.wizard.data.query).toBe("Import all the infrastructure");
  });

  it("leaving a full mode for a partial one asks for the query again", () => {
    const { result } = renderWizard();

    act(() => { result.current.mode.setMode(MODE.IMPORT); });
    act(() => { result.current.mode.setMode(MODE.PARTIAL_IMPORT); });

    expect(result.current.wizard.step).toBe("query");
    expect(result.current.wizard.data.query).toBe("");
  });

  it("sends the fixed query to the API", async () => {
    mockScan.mockResolvedValueOnce({ repoUrl: REPO, roots: ["environments/dev"] });
    const { result } = renderWizard();

    act(() => { result.current.mode.setMode(MODE.IMPORT); });
    await act(async () => {
      await result.current.wizard.handleInput("https://dev.azure.com/org/repo");
    });

    await waitFor(() => expect(mockTerraformRun).toHaveBeenCalled());
    expect(mockTerraformRun.mock.calls[0][0]).toMatchObject({
      query: "Import all the infrastructure",
      mode: "import",
    });
  });
});

describe("useHomeWizard — iterate & applyAfterPr", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockTerraformState.mockReturnValue({ status: "idle" });
    mockScanPathsValue.mockReturnValue([]);
    mockScanLoadingValue.mockReturnValue(false);
    mockScanErrorValue.mockReturnValue(null);
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

    mockScan.mockResolvedValueOnce({ repoUrl: REPO, roots: ["environments/dev"] });

    await act(async () => { await result.current.wizard.handleInput("deploy a VM"); });
    await act(async () => { await result.current.wizard.handleInput("https://dev.azure.com/org/repo"); });
    await waitFor(() => expect(mockTerraformRun).toHaveBeenCalled());

    act(() => { result.current.wizard.iterate("add a database"); });

    expect(mockTerraformRun).toHaveBeenCalled();
    expect(mockTerraformRun.mock.calls[1][0]).toMatchObject({
      sessionId: "abc-123",
      query: "add a database",
    });
  });

  it("applyAfterPr does nothing without a session uuid", () => {
    const { result } = renderHook(() => useHomeWizard(), { wrapper: Wrapper });

    act(() => { result.current.applyAfterPr(); });

    expect(mockTerraformRun).not.toHaveBeenCalled();
  });

  it("applyAfterPr runs an apply action, not a mode", async () => {
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

    mockScan.mockResolvedValueOnce({ repoUrl: REPO, roots: ["environments/dev"] });

    await act(async () => { await result.current.wizard.handleInput("deploy a VM"); });
    await act(async () => { await result.current.wizard.handleInput("https://dev.azure.com/org/repo"); });
    await waitFor(() => expect(mockTerraformRun).toHaveBeenCalled());

    act(() => { result.current.wizard.applyAfterPr(); });

    expect(mockTerraformRun).toHaveBeenCalled();
    const lastCall = mockTerraformRun.mock.calls[mockTerraformRun.mock.calls.length - 1];
    expect(lastCall[0]).toEqual({
      kind: "apply",
      sessionId: "abc-123",
    });
  });

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

  it("applyAfterPr refuses to apply an import session", () => {
    const { result } = renderHook(
      () => ({ wizard: useHomeWizard(), session: useSession() }),
      { wrapper: Wrapper },
    );

    act(() => {
      result.current.session.updateSession({
        uuid: "abc-123",
        operation: "import",
      });
    });

    act(() => { result.current.wizard.applyAfterPr(); });

    expect(mockTerraformRun).not.toHaveBeenCalled();
  });
});

describe("useHomeWizard — retry", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockTerraformState.mockReturnValue({ status: "idle" });
    mockScanPathsValue.mockReturnValue([]);
    mockScanLoadingValue.mockReturnValue(false);
    mockScanErrorValue.mockReturnValue(null);
  });

  it("retry with scan error resets to repository_url", async () => {
    mockScanErrorValue.mockReturnValue("No root modules found");

    const { result } = renderHook(() => useHomeWizard(), { wrapper: Wrapper });

    await act(async () => { await result.current.handleInput("deploy a VM"); });

    act(() => { result.current.retry(); });

    expect(result.current.step).toBe("repository_url");
    expect(mockResetScan).toHaveBeenCalled();
    expect(mockTerraformReset).toHaveBeenCalled();
  });

  it("retry with terraform error resets terraform state", () => {
    mockTerraformState.mockReturnValue({ status: "error", message: "Plan failed" });

    const { result } = renderHook(() => useHomeWizard(), { wrapper: Wrapper });

    act(() => { result.current.retry(); });

    expect(mockTerraformReset).toHaveBeenCalled();
  });
});

describe("useHomeWizard — restart", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockTerraformState.mockReturnValue({ status: "idle" });
    mockScanPathsValue.mockReturnValue([]);
    mockScanLoadingValue.mockReturnValue(false);
    mockScanErrorValue.mockReturnValue(null);
  });

  it("restart after full wizard completion clears all fields except query", async () => {
    mockScan.mockResolvedValueOnce({ repoUrl: REPO, roots: ["environments/dev"] });

    const { result } = renderHook(() => useHomeWizard(), { wrapper: Wrapper });

    await act(async () => { await result.current.handleInput("deploy a VM"); });
    await act(async () => { await result.current.handleInput("https://dev.azure.com/org/repo"); });

    await waitFor(() => expect(mockTerraformRun).toHaveBeenCalled());
    expect(result.current.data.repositoryUrl).toBe("https://dev.azure.com/org/repo");
    expect(result.current.data.rootModulePath).toBe("environments/dev");

    act(() => { result.current.restart(); });

    expect(result.current.step).toBe("query");
    expect(result.current.data.query).toBe("deploy a VM");
    expect(result.current.data.repositoryUrl).toBe("");
    expect(result.current.data.rootModulePath).toBe("");
    expect(mockResetScan).toHaveBeenCalled();
    expect(mockTerraformReset).toHaveBeenCalled();
  });

  it("restart with no prior query resets to empty query step", () => {
    const { result } = renderHook(() => useHomeWizard(), { wrapper: Wrapper });

    act(() => { result.current.restart(); });

    expect(result.current.step).toBe("query");
    expect(result.current.data.query).toBe("");
  });
});

describe("useHomeWizard — aggregated isLoading & error", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockTerraformState.mockReturnValue({ status: "idle" });
    mockScanPathsValue.mockReturnValue([]);
    mockScanLoadingValue.mockReturnValue(false);
    mockScanErrorValue.mockReturnValue(null);
  });

  it("isLoading is true when the scan is loading", () => {
    mockScanLoadingValue.mockReturnValue(true);
    const { result } = renderHook(() => useHomeWizard(), { wrapper: Wrapper });
    expect(result.current.isLoading).toBe(true);
  });

  it("isLoading is true when terraform is loading", () => {
    mockTerraformState.mockReturnValue({ status: "loading" });
    const { result } = renderHook(() => useHomeWizard(), { wrapper: Wrapper });
    expect(result.current.isLoading).toBe(true);
  });

  it("error reflects scan error first", () => {
    mockScanErrorValue.mockReturnValue("Repository not found");
    const { result } = renderHook(() => useHomeWizard(), { wrapper: Wrapper });
    expect(result.current.error).toBe("Repository not found");
  });

  it("error reflects terraform error when the scan has none", () => {
    mockTerraformState.mockReturnValue({ status: "error", message: "Plan failed" });
    const { result } = renderHook(() => useHomeWizard(), { wrapper: Wrapper });
    expect(result.current.error).toBe("Plan failed");
  });

  it("scan error takes precedence over terraform error", () => {
    mockScanErrorValue.mockReturnValue("Scan error");
    mockTerraformState.mockReturnValue({ status: "error", message: "TF error" });
    const { result } = renderHook(() => useHomeWizard(), { wrapper: Wrapper });
    expect(result.current.error).toBe("Scan error");
  });
});

describe("useHomeWizard — clear requested from outside", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockTerraformState.mockReturnValue({ status: "idle" });
    mockScanPathsValue.mockReturnValue([]);
    mockScanLoadingValue.mockReturnValue(false);
    mockScanErrorValue.mockReturnValue(null);
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
      rootModulePath: "",
      inputsChecked: false,
      inputs: null,
    });
    expect(mockResetScan).toHaveBeenCalled();
    expect(mockTerraformReset).toHaveBeenCalled();
  });

  it("does not clear on mount", () => {
    renderHook(() => useHomeWizard(), { wrapper: Wrapper });

    expect(mockResetScan).not.toHaveBeenCalled();
    expect(mockTerraformReset).not.toHaveBeenCalled();
  });
});

describe("useHomeWizard — root module inputs", () => {
  const NEEDS_REGION: ManifestProbeResponse = {
    status: "not_found",
    needs_input: true,
    missing_variables: [
      { name: "region", type: "string", description: "", required: true, sensitive: false },
    ],
    selectable_var_files: [],
    selected_var_files: [],
    missing_var_files: [],
    provider_changes: [],
    missing_scopes: [],
  };

  const NEEDS_SCOPES: ManifestProbeResponse = {
    ...NOTHING_NEEDED,
    status: "not_found",
    needs_input: true,
    missing_scopes: [
      { provider: "azurerm", source: "hashicorp/azurerm" },
      { provider: "google", source: "hashicorp/google" },
    ],
  };

  beforeEach(() => {
    vi.clearAllMocks();
    mockTerraformState.mockReturnValue({ status: "idle" });
    mockScanPathsValue.mockReturnValue([]);
    mockScanLoadingValue.mockReturnValue(false);
    mockScanErrorValue.mockReturnValue(null);
  });

  async function reachInputs() {
    mockScan.mockResolvedValueOnce({ repoUrl: REPO, roots: ["environments/dev"] });
    const rendered = renderHook(() => useHomeWizard(), { wrapper: Wrapper });
    await act(async () => { await rendered.result.current.handleInput("deploy a VM"); });
    await act(async () => { await rendered.result.current.handleInput("https://dev.azure.com/org/repo"); });
    return rendered;
  }

  it("shows the form when the probe needs input, and starts nothing", async () => {
    mockProbeManifest.mockResolvedValueOnce(NEEDS_REGION);
    const { result } = await reachInputs();

    await waitFor(() => expect(result.current.probe).toEqual(NEEDS_REGION));
    expect(result.current.step).toBe("inputs");
    expect(result.current.isLoading).toBe(false);
    expect(mockTerraformRun).not.toHaveBeenCalled();
  });

  it("starts the session with the answers once submitted", async () => {
    mockProbeManifest.mockResolvedValueOnce(NEEDS_REGION);
    const { result } = await reachInputs();
    await waitFor(() => expect(result.current.probe).not.toBeNull());

    act(() => {
      result.current.handleInputs({ variables: [{ name: "region", value: "westeurope" }] });
    });

    expect(mockTerraformRun).toHaveBeenCalledWith(
      {
        repoUri: "https://dev.azure.com/org/repo",
        query: "deploy a VM",
        mode: "generate",
        rootModulePath: "environments/dev",
        manifest: { variables: [{ name: "region", value: "westeurope" }] },
      },
      mockHandleOutcome,
    );
  });

  it("missing scopes show the form, and the answered scopes ride in the manifest", async () => {
    mockProbeManifest.mockResolvedValueOnce(NEEDS_SCOPES);
    const { result } = await reachInputs();
    await waitFor(() => expect(result.current.probe).toEqual(NEEDS_SCOPES));
    expect(mockTerraformRun).not.toHaveBeenCalled();

    const answers = {
      variables: [],
      scopes: { azurerm: "sub-123", google: "my-project" },
    };
    act(() => { result.current.handleInputs(answers); });

    expect(mockTerraformRun).toHaveBeenCalledTimes(1);
    const params = mockTerraformRun.mock.calls[0][0];
    expect(params).toEqual({
      repoUri: "https://dev.azure.com/org/repo",
      query: "deploy a VM",
      mode: "generate",
      rootModulePath: "environments/dev",
      manifest: answers,
    });
    expect(params).not.toHaveProperty("terraformProviders");
    expect(params).not.toHaveProperty("scopeId");
  });

  it("starts without answers when nothing is needed", async () => {
    const { result } = await reachInputs();
    await waitFor(() => expect(mockTerraformRun).toHaveBeenCalled());
    expect(mockTerraformRun.mock.calls[0][0]).not.toHaveProperty("manifest");
    expect(result.current.data.inputsChecked).toBe(true);
  });

  it("a failed probe is reported and can be retried", async () => {
    mockProbeManifest.mockRejectedValueOnce(new Error("boom"));
    const { result } = await reachInputs();
    await waitFor(() => expect(result.current.error).toBe(STRINGS.wizard.probeError));
    expect(mockTerraformRun).not.toHaveBeenCalled();

    act(() => { result.current.retry(); });

    await waitFor(() => expect(mockTerraformRun).toHaveBeenCalled());
    expect(mockProbeManifest).toHaveBeenCalledTimes(2);
    expect(result.current.error).toBeNull();
  });

  it("a probe answering after a restart is ignored", async () => {
    let answer: (r: ManifestProbeResponse) => void = () => {};
    mockProbeManifest.mockImplementationOnce(
      () => new Promise<ManifestProbeResponse>((resolve) => { answer = resolve; }),
    );
    const { result } = await reachInputs();

    act(() => { result.current.restart(); });
    await act(async () => { answer(NOTHING_NEEDED); });

    expect(mockTerraformRun).not.toHaveBeenCalled();
    expect(result.current.step).toBe("query");
  });
});

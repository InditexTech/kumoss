import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { SessionProvider, useSession } from "@/contexts/SessionContext";
import { ModeProvider } from "@/contexts/ModeContext";
import { useHomeWizard } from "./useHomeWizard";

// ─── Dynamic mock controls ────────────────────────────────────
const mockAuthState = vi.fn<[], { status: string; message?: string; data?: unknown }>(() => ({ status: "idle" }));
const mockAuthRun = vi.fn();
const mockAuthReset = vi.fn();

const mockTerraformState = vi.fn<[], { status: string; message?: string }>(() => ({ status: "idle" }));
const mockTerraformRun = vi.fn();
const mockTerraformReset = vi.fn();

const mockResolveAndScan = vi.fn();
const mockScanPathsValue = vi.fn<[], string[]>(() => []);
const mockMapperLoadingValue = vi.fn(() => false);
const mockMapperErrorValue = vi.fn<[], string | null>(() => null);
const mockSetMapperError = vi.fn();
const mockResetMapper = vi.fn();

vi.mock("@/contexts/AuthContext", () => ({
  useAuth: () => ({
    user: { username: "test@example.com", name: "Test User" } as never,
    isAuthenticated: true,
    login: vi.fn(),
    logout: vi.fn(),
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
    expect(result.current.session.session.firstQuery).toBe("deploy a VM");
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

  it("handlePath sets environment and advances to cloud_scope", () => {
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

    expect(result.current.wizard.step).toBe("cloud_scope");
    expect(result.current.wizard.data.environment).toBe("environments/dev");
    expect(result.current.session.session.environment).toBe(
      "environments/dev",
    );
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
      cloudScope: "",
      environment: "",
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

  it("single IaC path auto-advances to cloud_scope", async () => {
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

    expect(result.current.wizard.step).toBe("cloud_scope");
    expect(result.current.wizard.data.repositoryUrl).toBe("https://dev.azure.com/org/repo");
    expect(result.current.wizard.data.environment).toBe("environments/dev");
    expect(result.current.session.session.repositoryUrl).toBe("https://dev.azure.com/org/repo");
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

  it("cloud_scope input calls auth.run with correct params", async () => {
    mockResolveAndScan.mockResolvedValueOnce({
      repoUrl: "https://dev.azure.com/org/repo",
      project: "myproj",
      paths: ["environments/dev"],
    });

    const { result } = renderHook(() => useHomeWizard(), { wrapper: Wrapper });

    await act(async () => { await result.current.handleInput("deploy a VM"); });
    await act(async () => { await result.current.handleInput("https://dev.azure.com/org/repo"); });
    await act(async () => { await result.current.handleInput("azure"); });

    expect(mockAuthRun).toHaveBeenCalledWith({
      repositoryUrl: "https://dev.azure.com/org/repo",
      query: "deploy a VM",
      userEmail: "test@example.com",
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
    await act(async () => { await result.current.handleInput("azure"); });

    mockAuthState.mockReturnValue({ status: "success" });
    await act(async () => { rerender(); });

    expect(mockTerraformRun).toHaveBeenCalled();
    expect(mockTerraformRun.mock.calls[0][0]).toMatchObject({
      repoUri: "https://dev.azure.com/org/repo",
      query: "deploy a VM",
      cloud: "azure",
      environment: "environments/dev",
      userId: "test@example.com",
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
    await act(async () => { await result.current.handleInput("azure"); });

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

  it("iterate does nothing without session_id", () => {
    const { result } = renderHook(() => useHomeWizard(), { wrapper: Wrapper });

    act(() => { result.current.iterate("add a database"); });

    expect(mockTerraformRun).not.toHaveBeenCalled();
  });

  it("iterate calls terraform.run with session_id", async () => {
    const { result } = renderHook(
      () => ({ wizard: useHomeWizard(), session: useSession() }),
      { wrapper: Wrapper },
    );

    act(() => {
      result.current.session.updateSession({ session_id: "abc-123" });
    });

    mockResolveAndScan.mockResolvedValueOnce({
      repoUrl: "https://dev.azure.com/org/repo",
      project: null,
      paths: ["environments/dev"],
    });

    await act(async () => { await result.current.wizard.handleInput("deploy a VM"); });
    await act(async () => { await result.current.wizard.handleInput("https://dev.azure.com/org/repo"); });
    await act(async () => { await result.current.wizard.handleInput("azure"); });

    act(() => { result.current.wizard.iterate("add a database"); });

    expect(mockTerraformRun).toHaveBeenCalled();
    expect(mockTerraformRun.mock.calls[0][0]).toMatchObject({
      sessionId: "abc-123",
      query: "add a database",
    });
  });

  it("applyAfterPr does nothing without session_id", () => {
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
        session_id: "abc-123",
        firstQuery: "deploy a VM",
      });
    });

    mockResolveAndScan.mockResolvedValueOnce({
      repoUrl: "https://dev.azure.com/org/repo",
      project: null,
      paths: ["environments/dev"],
    });

    await act(async () => { await result.current.wizard.handleInput("deploy a VM"); });
    await act(async () => { await result.current.wizard.handleInput("https://dev.azure.com/org/repo"); });
    await act(async () => { await result.current.wizard.handleInput("azure"); });

    act(() => { result.current.wizard.applyAfterPr(); });

    expect(mockTerraformRun).toHaveBeenCalled();
    expect(mockTerraformRun.mock.calls[0][0]).toMatchObject({
      sessionId: "abc-123",
      mode: "import",
    });
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

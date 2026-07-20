// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useWizardNavigation } from "./useWizardNavigation";
import { STRINGS } from "@/constants/strings";

describe("useWizardNavigation", () => {
  it("initializes with step=query and empty data", () => {
    const { result } = renderHook(() => useWizardNavigation());

    expect(result.current.step).toBe("query");
    expect(result.current.data).toEqual({
      query: "",
      repositoryUrl: "",
      provider: "",
      cloudScope: "",
      iacPath: "",
    });
  });

  it("setStep updates the current step", () => {
    const { result } = renderHook(() => useWizardNavigation());

    act(() => result.current.setStep("repository_url"));
    expect(result.current.step).toBe("repository_url");

    act(() => result.current.setStep("cloud_scope"));
    expect(result.current.step).toBe("cloud_scope");
  });

  it("setData merges partial updates", () => {
    const { result } = renderHook(() => useWizardNavigation());

    act(() =>
      result.current.setData((prev) => ({ ...prev, query: "deploy a vm" })),
    );
    expect(result.current.data.query).toBe("deploy a vm");
    expect(result.current.data.repositoryUrl).toBe("");

    act(() =>
      result.current.setData((prev) => ({
        ...prev,
        repositoryUrl: "https://repo.example.com",
      })),
    );
    expect(result.current.data.query).toBe("deploy a vm");
    expect(result.current.data.repositoryUrl).toBe(
      "https://repo.example.com",
    );
  });

  describe("promptMessage", () => {
    it("returns query prompt for query step", () => {
      const { result } = renderHook(() => useWizardNavigation());
      expect(result.current.promptMessage("idle")).toBe(
        STRINGS.wizard.promptQuery,
      );
    });

    it("returns repository prompt for repository_url step", () => {
      const { result } = renderHook(() => useWizardNavigation());
      act(() => result.current.setStep("repository_url"));
      expect(result.current.promptMessage("idle")).toBe(
        STRINGS.wizard.promptRepository,
      );
    });

    it("returns iac_path prompt for iac_path step", () => {
      const { result } = renderHook(() => useWizardNavigation());
      act(() => result.current.setStep("iac_path"));
      expect(result.current.promptMessage("idle")).toBe(
        STRINGS.wizard.promptIacPath,
      );
    });

    it("returns provider prompt for provider step", () => {
      const { result } = renderHook(() => useWizardNavigation());
      act(() => result.current.setStep("provider"));
      expect(result.current.promptMessage("idle")).toBe(
        STRINGS.wizard.promptProvider,
      );
    });

    it("returns cloud scope prompt for cloud_scope step", () => {
      const { result } = renderHook(() => useWizardNavigation());
      act(() => result.current.setStep("cloud_scope"));
      expect(result.current.promptMessage("idle")).toBe(
        STRINGS.wizard.promptCloudScope,
      );
    });

    it("returns auth-checking message when auth is loading", () => {
      const { result } = renderHook(() => useWizardNavigation());
      act(() =>
        result.current.setData((prev) => ({
          ...prev,
          cloudScope: "my-subscription",
        })),
      );
      expect(result.current.promptMessage("loading")).toBe(
        `${STRINGS.wizard.checkingPermissions} my-subscription`,
      );
    });
  });

  describe("placeholder", () => {
    it("returns query placeholder for query step", () => {
      const { result } = renderHook(() => useWizardNavigation());
      expect(result.current.placeholder()).toBe(
        STRINGS.wizard.placeholderQuery,
      );
    });

    it("returns repository placeholder for repository_url step", () => {
      const { result } = renderHook(() => useWizardNavigation());
      act(() => result.current.setStep("repository_url"));
      expect(result.current.placeholder()).toBe(
        STRINGS.wizard.placeholderRepository,
      );
    });

    it("returns empty string for iac_path step", () => {
      const { result } = renderHook(() => useWizardNavigation());
      act(() => result.current.setStep("iac_path"));
      expect(result.current.placeholder()).toBe("");
    });

    it("returns empty string for provider step", () => {
      const { result } = renderHook(() => useWizardNavigation());
      act(() => result.current.setStep("provider"));
      expect(result.current.placeholder()).toBe("");
    });

    it("returns cloud scope placeholder for cloud_scope step", () => {
      const { result } = renderHook(() => useWizardNavigation());
      act(() => result.current.setStep("cloud_scope"));
      expect(result.current.placeholder()).toBe(
        STRINGS.wizard.placeholderCloudScope,
      );
    });
  });

  it("resetNavigation restores initial state", () => {
    const { result } = renderHook(() => useWizardNavigation());

    act(() => {
      result.current.setStep("cloud_scope");
      result.current.setData((prev) => ({
        ...prev,
        query: "create vm",
        repositoryUrl: "https://repo.example.com",
        provider: "azure",
        cloudScope: "sub-123",
        iacPath: "environments/dev",
      }));
    });

    expect(result.current.step).toBe("cloud_scope");
    expect(result.current.data.query).toBe("create vm");

    act(() => result.current.resetNavigation());

    expect(result.current.step).toBe("query");
    expect(result.current.data).toEqual({
      query: "",
      repositoryUrl: "",
      provider: "",
      cloudScope: "",
      iacPath: "",
    });
  });
});

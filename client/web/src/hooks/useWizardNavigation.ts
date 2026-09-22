// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { useState, useCallback } from "react";
import { STRINGS } from "@/constants/strings";
import type { WizardStep } from "@/types/ui";
import type { TerraformProvider } from "@/types/api";

export interface WizardData {
  query: string;
  repositoryUrl: string;
  provider: TerraformProvider | "";
  cloudScope: string;
  iacPath: string;
}

const INITIAL_DATA: WizardData = {
  query: "",
  repositoryUrl: "",
  provider: "",
  cloudScope: "",
  iacPath: "",
};

export function useWizardNavigation() {
  const [step, setStep] = useState<WizardStep>("query");
  const [data, setData] = useState<WizardData>(INITIAL_DATA);

  const promptMessage = useCallback(
    (authStatus: string): string => {
      if (authStatus === "loading") {
        return `${STRINGS.wizard.checkingPermissions} ${data.cloudScope}`;
      }
      switch (step) {
        case "query":
          return STRINGS.wizard.promptQuery;
        case "repository_url":
          return STRINGS.wizard.promptRepository;
        case "iac_path":
          return STRINGS.wizard.promptIacPath;
        case "provider":
          return STRINGS.wizard.promptProvider;
        case "cloud_scope":
          return data.provider
            ? STRINGS.wizard.scopeByProvider[data.provider].prompt
            : STRINGS.wizard.promptCloudScope;
        default:
          return "";
      }
    },
    [step, data.cloudScope, data.provider],
  );

  const placeholder = useCallback((): string => {
    switch (step) {
      case "query":
        return STRINGS.wizard.placeholderQuery;
      case "repository_url":
        return STRINGS.wizard.placeholderRepository;
      case "iac_path":
        return "";
      case "provider":
        return "";
      case "cloud_scope":
        return data.provider
          ? STRINGS.wizard.scopeByProvider[data.provider].placeholder
          : STRINGS.wizard.placeholderCloudScope;
      default:
        return "";
    }
  }, [step, data.provider]);

  /**
   * Merge `patch` into the collected data and hand the result back.
   *
   * The return value is required, not a convenience: when the mapper
   * supplies a provider and a scope, both are written and consumed in
   * the same tick, so `data` still holds the pre-merge value for the
   * rest of this render. Reading `data` straight after `setData` is
   * safe elsewhere only because each step is a separate interaction in
   * a separate render.
   */
  const applyResolution = useCallback(
    (patch: Partial<WizardData>): WizardData => {
      const merged = { ...data, ...patch };
      setData(merged);
      return merged;
    },
    [data],
  );

  const resetNavigation = useCallback(() => {
    setStep("query");
    setData(INITIAL_DATA);
  }, []);

  return {
    step,
    setStep,
    data,
    setData,
    applyResolution,
    promptMessage,
    placeholder,
    resetNavigation,
  } as const;
}

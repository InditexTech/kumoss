// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { useState, useCallback } from "react";
import { STRINGS } from "@/constants/strings";
import type { WizardStep } from "@/types/ui";
import type { ManifestAnswers } from "@/types/api";

export interface WizardData {
  query: string;
  repositoryUrl: string;
  rootModulePath: string;
  /** The root module's inputs were probed and, if needed, answered. */
  inputsChecked: boolean;
  /**
   * Answers for the inputs the probe reported missing (variables, var
   * files and provider scopes); null when none were needed.
   */
  inputs: ManifestAnswers | null;
}

export const INITIAL_WIZARD_DATA: WizardData = {
  query: "",
  repositoryUrl: "",
  rootModulePath: "",
  inputsChecked: false,
  inputs: null,
};

export function useWizardNavigation() {
  const [step, setStep] = useState<WizardStep>("query");
  const [data, setData] = useState<WizardData>(INITIAL_WIZARD_DATA);

  const promptMessage = useCallback((): string => {
    switch (step) {
      case "query":
        return STRINGS.wizard.promptQuery;
      case "repository_url":
        return STRINGS.wizard.promptRepository;
      case "root_module_path":
        return STRINGS.wizard.promptRootModulePath;
      case "inputs":
        return STRINGS.wizard.promptInputs;
      default:
        return "";
    }
  }, [step]);

  const placeholder = useCallback((): string => {
    switch (step) {
      case "query":
        return STRINGS.wizard.placeholderQuery;
      case "repository_url":
        return STRINGS.wizard.placeholderRepository;
      default:
        return "";
    }
  }, [step]);

  /**
   * Merge `patch` into the collected data and hand the result back.
   *
   * The return value is required, not a convenience: when a repository
   * has a single root module, its URL and path are written and consumed
   * in the same tick, so `data` still holds the pre-merge value for the
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
    setData(INITIAL_WIZARD_DATA);
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

import { useState, useCallback } from "react";
import { STRINGS } from "@/constants/strings";
import type { WizardStep } from "@/types/ui";

export interface WizardData {
  query: string;
  repositoryUrl: string;
  cloudScope: string;
  environment: string;
}

const INITIAL_DATA: WizardData = {
  query: "",
  repositoryUrl: "",
  cloudScope: "",
  environment: "",
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
        case "cloud_scope":
          return STRINGS.wizard.promptCloudScope;
        default:
          return "";
      }
    },
    [step, data.cloudScope],
  );

  const placeholder = useCallback((): string => {
    switch (step) {
      case "query":
        return STRINGS.wizard.placeholderQuery;
      case "repository_url":
        return STRINGS.wizard.placeholderRepository;
      case "iac_path":
        return "";
      case "cloud_scope":
        return STRINGS.wizard.placeholderCloudScope;
      default:
        return "";
    }
  }, [step]);

  const resetNavigation = useCallback(() => {
    setStep("query");
    setData(INITIAL_DATA);
  }, []);

  return {
    step,
    setStep,
    data,
    setData,
    promptMessage,
    placeholder,
    resetNavigation,
  } as const;
}

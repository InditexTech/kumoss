// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import type { WizardStep } from "@/types/ui";
import type { WizardData } from "./useWizardNavigation";

/**
 * Which step to show next, given everything collected so far.
 *
 * "First input still missing, else complete." Skipping a step is not a
 * special case: a step is skipped precisely because its slot is already
 * filled (a repository with a single root module fills the path itself).
 * That is why the whole decision fits here, as a pure function over the
 * collected data, and why the wizard can become complete at more than
 * one moment.
 *
 * Providers and their scopes are not asked here: they come from the root
 * module's manifest, and the `inputs` step asks for any missing scope.
 */
export function nextStep(data: WizardData): WizardStep | "complete" {
  if (!data.query) return "query";
  if (!data.repositoryUrl) return "repository_url";
  if (!data.rootModulePath) return "root_module_path";
  // Last, as the probe needs the repository and root module.
  if (!data.inputsChecked) return "inputs";
  return "complete";
}

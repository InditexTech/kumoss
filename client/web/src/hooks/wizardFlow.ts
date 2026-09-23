// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import type { WizardStep } from "@/types/ui";
import type { WizardData } from "./useWizardNavigation";

/**
 * Which step to show next, given everything collected so far.
 *
 * "First input still missing, else complete." Skipping a step is not a
 * special case: a step is skipped precisely because the mapper already
 * filled its slot. That is why the whole decision fits here, as a pure
 * function over the collected data, and why the wizard can become
 * complete at more than one moment.
 */
export function nextStep(data: WizardData): WizardStep | "complete" {
  if (!data.query) return "query";
  if (!data.repositoryUrl) return "repository_url";
  if (!data.iacPath) return "iac_path";
  if (!data.provider) return "provider";
  if (!data.cloudScope) return "cloud_scope";
  return "complete";
}

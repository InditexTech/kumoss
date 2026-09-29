// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { MODE } from "@/types/ui";
import type { Mode } from "@/types/ui";

export interface ModeOption {
  value: Mode;
  label: string;
  description?: string;
}

export const MODE_OPTIONS: ModeOption[] = [
  {
    value: MODE.GENERATE,
    label: "Generate Infrastructure",
    description: "Creates new infrastructure from the defined configuration.",
  },
  {
    value: MODE.PARTIAL_DRIFT,
    label: "Partial Drift Remediation",
    description: "Corrects only the selected changes.",
  },
  {
    value: MODE.DRIFT,
    label: "Full Drift Remediation",
    description: "Restores all infrastructure to the expected state.",
  },
  {
    value: MODE.PARTIAL_IMPORT,
    label: "Partial Import",
    description: "Imports only the unmanaged resources your request names.",
  },
  {
    value: MODE.IMPORT,
    label: "Full Import",
    description: "Brings every unmanaged resource in the scope under management.",
  },
];

/**
 * Full modes act on the whole scope, so the wizard asks no query and sends
 * these fixed ones instead. Partial modes need the user's query to know
 * what to act on.
 */
export const FIXED_MODE_QUERIES: Partial<Record<Mode, string>> = {
  [MODE.DRIFT]: "Reconcile all the drift",
  [MODE.IMPORT]: "Import all the infrastructure",
};

export function isFixedModeQuery(query: string): boolean {
  return Object.values(FIXED_MODE_QUERIES).includes(query);
}

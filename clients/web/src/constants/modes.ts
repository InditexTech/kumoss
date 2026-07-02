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
    value: MODE.IMPORT,
    label: "Import Infrastructure",
    description: "Adds existing resources to manage them from the tool.",
  },
];

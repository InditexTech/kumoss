// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import type { TerraformProvider } from "@/types/api";

/** Display names for the backend's lowercase provider tokens. */
export const PROVIDER_LABELS: Record<TerraformProvider, string> = {
  azure: "Microsoft Azure",
  gcp: "Google Cloud",
  aws: "Amazon Web Services",
  oci: "Oracle Cloud Infrastructure",
  kubernetes: "Kubernetes",
};

/** Display name for a provider token; capitalizes unknown values. */
export function providerLabel(
  provider: string | null | undefined,
): string {
  if (!provider) return "-";
  return (
    PROVIDER_LABELS[provider as TerraformProvider] ??
    provider.charAt(0).toUpperCase() + provider.slice(1)
  );
}

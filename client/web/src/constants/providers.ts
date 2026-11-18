// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { STRINGS } from "@/constants/strings";

/**
 * Display names for well-known Terraform provider type names. Any other
 * provider (`random`, `null`, `helm`…) is shown by its type name.
 */
export const PROVIDER_LABELS: Record<string, string> = {
  azurerm: "Microsoft Azure",
  google: "Google Cloud",
  aws: "Amazon Web Services",
  oci: "Oracle Cloud Infrastructure",
  kubernetes: "Kubernetes",
  vsphere: "VMware vSphere",
};

/**
 * Helper providers that manage no infrastructure of their own (random ids,
 * rendered templates, local files…). Compact views leave them out.
 */
export const UTILITY_PROVIDERS: ReadonlySet<string> = new Set([
  "archive",
  "cloudinit",
  "external",
  "http",
  "local",
  "null",
  "random",
  "template",
  "terraform",
  "time",
  "tls",
]);

/** Whether `provider` is a helper provider rather than an infrastructure one. */
export function isUtilityProvider(provider: string): boolean {
  return UTILITY_PROVIDERS.has(provider.toLowerCase());
}

/** Display name for a provider type name; unknown names are returned as is. */
export function providerLabel(provider: string | null | undefined): string {
  if (!provider) return "-";
  return PROVIDER_LABELS[provider.toLowerCase()] ?? provider;
}

/** What a provider calls its scope id (`Subscription ID` for azurerm…). */
export function scopeLabel(provider: string): string {
  return (
    STRINGS.wizard.scopeByProvider[provider.toLowerCase()]?.label ??
    STRINGS.wizard.scopeFallbackLabel
  );
}

/** An example scope id for `provider`, to show as a placeholder. */
export function scopePlaceholder(provider: string): string {
  return STRINGS.wizard.scopeByProvider[provider.toLowerCase()]?.placeholder ?? "";
}

// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it } from "vitest";

import { PROVIDER_LABELS, providerLabel, scopeLabel, scopePlaceholder } from "./providers";

describe("provider constants", () => {
  it.each(["azurerm", "google", "aws", "oci", "kubernetes", "vsphere"])(
    "%s has a label",
    (provider) => {
      expect(PROVIDER_LABELS[provider]).toBeTruthy();
    },
  );

  it("labels known Terraform providers and shows any other by its type name", () => {
    expect(providerLabel("vsphere")).toBe("VMware vSphere");
    expect(providerLabel("azurerm")).toBe("Microsoft Azure");
    expect(providerLabel("random")).toBe("random");
    expect(providerLabel(null)).toBe("-");
  });

  it.each([
    ["azurerm", "Subscription ID"],
    ["google", "Project ID"],
    ["aws", "Account ID"],
    ["oci", "Compartment OCID"],
    ["kubernetes", "Scope"],
    ["random", "Scope"],
  ])("%s scope is called %s", (provider, label) => {
    expect(scopeLabel(provider)).toBe(label);
  });

  it("has a scope placeholder for scoped providers only", () => {
    expect(scopePlaceholder("aws")).toBe("123456789012");
    expect(scopePlaceholder("random")).toBe("");
  });
});

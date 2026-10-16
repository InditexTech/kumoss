// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it } from "vitest";

import { TERRAFORM_PROVIDERS } from "@/types/api";
import { PROVIDER_LABELS, providerLabel } from "./providers";
import { STRINGS } from "./strings";

describe("provider constants", () => {
  it.each(TERRAFORM_PROVIDERS)("%s has a label and scope jargon", (provider) => {
    expect(PROVIDER_LABELS[provider]).toBeTruthy();
    const scope = STRINGS.wizard.scopeByProvider[provider];
    expect(scope.label).toBeTruthy();
    expect(scope.prompt).toBeTruthy();
    expect(scope.placeholder).toBeTruthy();
  });

  it("offers VMware vSphere, scoped by datacenter", () => {
    expect(TERRAFORM_PROVIDERS).toContain("vmware");
    expect(providerLabel("vmware")).toBe("VMware vSphere");
    expect(STRINGS.wizard.scopeByProvider.vmware).toEqual({
      label: "Datacenter",
      prompt: "Which vSphere datacenter?",
      placeholder: "dc-01",
    });
  });
});

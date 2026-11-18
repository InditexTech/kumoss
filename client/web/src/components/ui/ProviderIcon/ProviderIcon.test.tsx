// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import ProviderIcon from "./ProviderIcon";

describe("ProviderIcon", () => {
  it.each(["azurerm", "google", "aws", "oci", "kubernetes", "vsphere"])(
    "renders a logo for %s",
    (provider) => {
      render(<ProviderIcon provider={provider} data-testid="icon" />);
      const icon = screen.getByTestId("icon");
      expect(icon.querySelector("path")).not.toBeNull();
      expect(screen.queryByTestId("ExtensionOutlinedIcon")).toBeNull();
    },
  );

  it("falls back to a generic icon for any other provider", () => {
    render(<ProviderIcon provider="random" />);
    expect(screen.getByTestId("ExtensionOutlinedIcon")).toBeInTheDocument();
  });

  it.each(["azure", "gcp", "vmware"])("treats the old token %s as unknown", (provider) => {
    render(<ProviderIcon provider={provider} />);
    expect(screen.getByTestId("ExtensionOutlinedIcon")).toBeInTheDocument();
  });

  it("matches providers case-insensitively", () => {
    render(<ProviderIcon provider="AWS" data-testid="icon" />);
    const icon = screen.getByTestId("icon");
    expect(icon.querySelector("path")).not.toBeNull();
    expect(screen.queryByTestId("ExtensionOutlinedIcon")).toBeNull();
  });
});

// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import ProviderIcon from "./ProviderIcon";

describe("ProviderIcon", () => {
  it("renders an SVG icon for a known provider", () => {
    render(<ProviderIcon provider="azure" data-testid="icon" />);
    const icon = screen.getByTestId("icon");
    expect(icon.querySelector("path")).not.toBeNull();
  });

  it("falls back to a cloud icon for an unknown provider", () => {
    render(<ProviderIcon provider="unknown" />);
    expect(screen.getByTestId("CloudOutlinedIcon")).toBeInTheDocument();
  });

  it("matches providers case-insensitively", () => {
    render(<ProviderIcon provider="AWS" data-testid="icon" />);
    const icon = screen.getByTestId("icon");
    expect(icon.querySelector("path")).not.toBeNull();
    expect(screen.queryByTestId("CloudOutlinedIcon")).toBeNull();
  });
});

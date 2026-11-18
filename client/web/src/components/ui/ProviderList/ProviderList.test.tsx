// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect } from "vitest";
import { render, screen, within } from "@testing-library/react";
import ProviderList from "./ProviderList";

describe("ProviderList", () => {
  it("renders every provider by its type name", () => {
    render(<ProviderList providers={["azurerm", "google", "random"]} />);
    const items = within(screen.getByRole("list", { name: "Providers" })).getAllByRole("listitem");
    expect(items.map((li) => li.textContent)).toEqual(["azurerm", "google", "random"]);
  });

  it("uses the generic icon for unknown providers only", () => {
    render(<ProviderList providers={["aws", "random"]} />);
    expect(screen.getAllByTestId("ExtensionOutlinedIcon")).toHaveLength(1);
  });

  it("shows a dash for an empty list, or nothing when asked", () => {
    const { rerender, container } = render(<ProviderList providers={[]} />);
    expect(screen.getByText("—")).toBeInTheDocument();

    rerender(<ProviderList providers={[]} empty={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("leaves out utility providers when asked", () => {
    render(<ProviderList providers={["azurerm", "random", "template", "helm"]} hideUtilities />);
    const items = within(screen.getByRole("list", { name: "Providers" })).getAllByRole("listitem");
    expect(items.map((li) => li.textContent)).toEqual(["azurerm", "helm"]);
  });

  it("keeps utility providers when they are all there is", () => {
    render(<ProviderList providers={["random", "null"]} hideUtilities />);
    const items = within(screen.getByRole("list", { name: "Providers" })).getAllByRole("listitem");
    expect(items.map((li) => li.textContent)).toEqual(["random", "null"]);
  });

  it("icons variant names each provider for assistive tech", () => {
    render(<ProviderList providers={["vsphere", "kubernetes"]} variant="icons" />);
    expect(screen.getByLabelText("vsphere")).toBeInTheDocument();
    expect(screen.getByLabelText("kubernetes")).toBeInTheDocument();
    expect(screen.queryByText("vsphere")).toBeNull();
  });
});

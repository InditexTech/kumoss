// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import InputsForm from "./InputsForm";
import { STRINGS } from "@/constants/strings";
import type { ManifestProbeResponse } from "@/types/api";

const S = STRINGS.wizard.inputs;

const PROBE: ManifestProbeResponse = {
  status: "not_found",
  needs_input: true,
  missing_variables: [
    { name: "region", type: "map(string)", description: "Where it runs.", required: true, sensitive: false },
    { name: "db_password", type: "string", description: "", required: true, sensitive: true },
  ],
  selectable_var_files: [
    { path: "envs/dev.tfvars", selected: false, sets: ["region"] },
    { path: "envs/pro.tfvars", selected: false, sets: [] },
  ],
  missing_var_files: [],
  provider_changes: [],
};

function renderForm(props: Partial<React.ComponentProps<typeof InputsForm>> = {}) {
  const onSubmit = vi.fn();
  const onCancel = vi.fn();
  render(
    <InputsForm
      probe={PROBE}
      project="kumossdemo"
      rootModulePath="azure-pre"
      onSubmit={onSubmit}
      onCancel={onCancel}
      {...props}
    />,
  );
  return { onSubmit, onCancel };
}

describe("InputsForm", () => {
  it("is a dialog titled with the project and root module", () => {
    renderForm();
    expect(screen.getByRole("dialog", { name: "kumossdemo/azure-pre" })).toBeInTheDocument();
    expect(screen.getByText(S.progress.replace("{done}", "0").replace("{total}", "2"))).toBeInTheDocument();
  });

  it("lists every asked variable with its type, description and an example", () => {
    renderForm();
    const region = screen.getByLabelText("region");
    expect(region).toHaveAttribute("placeholder", '{"key": "…"}');
    expect(screen.getByText("map(string)")).toBeInTheDocument();
    expect(screen.getByText("Where it runs.")).toBeInTheDocument();
    // Declared sensitive: masked, badged, and its secret switch locked on.
    expect(screen.getByLabelText("db_password")).toHaveAttribute("type", "password");
    expect(screen.getByText(S.sensitiveBadge)).toBeInTheDocument();
    const locked = screen.getByRole("switch", { name: S.secretLocked });
    expect(locked).toBeChecked();
    expect(locked).toBeDisabled();
  });

  it("starts on the first field", () => {
    renderForm();
    expect(screen.getByLabelText("region")).toHaveFocus();
  });

  it("shows errors instead of submitting invalid values, and focuses the first", async () => {
    const { onSubmit } = renderForm();

    await userEvent.type(screen.getByLabelText("region"), "westeurope");
    await userEvent.click(screen.getByRole("button", { name: new RegExp(S.submit) }));

    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByText(S.invalidJson)).toBeInTheDocument();
    expect(screen.getByText(S.required)).toBeInTheDocument();
    expect(screen.getByLabelText("region")).toHaveFocus();
  });

  it("lets a picked var file answer a variable", async () => {
    const { onSubmit } = renderForm();

    await userEvent.click(screen.getByRole("checkbox", { name: /envs\/dev\.tfvars/ }));
    expect(screen.getByText(S.setByVarFile.replace("{file}", "envs/dev.tfvars"))).toBeInTheDocument();
    expect(screen.getByLabelText("region")).toHaveAttribute(
      "placeholder",
      S.setByVarFilePlaceholder.replace("{file}", "envs/dev.tfvars"),
    );
    await userEvent.type(screen.getByLabelText("db_password"), "s3cr3t");
    await userEvent.click(screen.getByRole("button", { name: new RegExp(S.submit) }));

    expect(onSubmit).toHaveBeenCalledWith({
      variables: [{ name: "db_password", value: "s3cr3t" }],
      var_files: ["envs/dev.tfvars"],
    });
  });

  it("submits typed answers, chosen secrets and the var files in the order picked", async () => {
    const { onSubmit } = renderForm();

    await userEvent.type(screen.getByLabelText("region"), '{{"location": "westeurope"}');
    await userEvent.click(screen.getByRole("switch", { name: `${S.secretLabel}: region` }));
    await userEvent.type(screen.getByLabelText("db_password"), "s3cr3t");
    await userEvent.click(screen.getByRole("checkbox", { name: /envs\/pro\.tfvars/ }));
    await userEvent.click(screen.getByRole("checkbox", { name: /envs\/dev\.tfvars/ }));
    await userEvent.keyboard("{Control>}{Enter}{/Control}");

    expect(onSubmit).toHaveBeenCalledWith({
      variables: [
        { name: "region", value: { location: "westeurope" }, sensitive: true },
        { name: "db_password", value: "s3cr3t" },
      ],
      var_files: ["envs/pro.tfvars", "envs/dev.tfvars"],
    });
  });

  it("cancels with Escape, the close button and Cancel", async () => {
    const { onCancel } = renderForm();
    await userEvent.keyboard("{Escape}");
    await userEvent.click(screen.getByRole("button", { name: S.close }));
    await userEvent.click(screen.getByRole("button", { name: S.cancel }));
    expect(onCancel).toHaveBeenCalledTimes(3);
  });
});

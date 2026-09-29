// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import StatusBadge from "./StatusBadge";
import styles from "./StatusBadge.module.css";

describe("StatusBadge reconciling", () => {
  it("styles reconciling as an in-progress phase, not the grey default", () => {
    render(<StatusBadge variant="reconciling" />);

    const badge = screen.getByText("RECONCILING");
    expect(badge.className).toContain(styles.generating);
    expect(badge.className).not.toContain(styles.default);
  });
});

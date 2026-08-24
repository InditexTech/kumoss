// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect } from "vitest";
import { isGitDiff, parseGitDiff } from "./diffUtils";

// Mirrors the backend's `git diff --no-prefix --unified=1000` output for
// an updated (tracked) file.
const UPDATED_FILE_DIFF = [
  "diff --git main.tf main.tf",
  "index 1234567..89abcde 100644",
  "--- main.tf",
  "+++ main.tf",
  "@@ -1,4 +1,5 @@",
  ' resource "azurerm_resource_group" "rg" {',
  '-  name     = "old-rg"',
  '+  name     = "new-rg"',
  '+  tags     = { env = "dev" }',
  '   location = "westeurope"',
  " }",
].join("\n");

const NEW_FILE_MODE_DIFF = [
  "diff --git vars.tf vars.tf",
  "new file mode 100644",
  "index 0000000..1234567",
  "--- /dev/null",
  "+++ vars.tf",
  "@@ -0,0 +1,2 @@",
  '+variable "location" {',
  "+}",
  "\\ No newline at end of file",
].join("\n");

describe("isGitDiff", () => {
  it("detects unified git diff output", () => {
    expect(isGitDiff(UPDATED_FILE_DIFF)).toBe(true);
    expect(isGitDiff(NEW_FILE_MODE_DIFF)).toBe(true);
  });

  it("rejects raw file content (new_file=true artifacts)", () => {
    expect(isGitDiff('resource "aws_s3_bucket" "b" {}\n')).toBe(false);
    expect(isGitDiff("")).toBe(false);
    // mentions of diffs inside a file aren't headers
    expect(isGitDiff('# run: git diff --git main.tf\n@@ -1 +1 @@')).toBe(false);
  });
});

describe("parseGitDiff", () => {
  it("rebuilds original and modified sides from an update diff", () => {
    const { original, modified } = parseGitDiff(UPDATED_FILE_DIFF);
    expect(original).toBe(
      [
        'resource "azurerm_resource_group" "rg" {',
        '  name     = "old-rg"',
        '  location = "westeurope"',
        "}",
      ].join("\n"),
    );
    expect(modified).toBe(
      [
        'resource "azurerm_resource_group" "rg" {',
        '  name     = "new-rg"',
        '  tags     = { env = "dev" }',
        '  location = "westeurope"',
        "}",
      ].join("\n"),
    );
  });

  it("handles new-file-mode diffs and no-newline markers", () => {
    const { original, modified } = parseGitDiff(NEW_FILE_MODE_DIFF);
    expect(original).toBe("");
    expect(modified).toBe('variable "location" {\n}');
  });
});

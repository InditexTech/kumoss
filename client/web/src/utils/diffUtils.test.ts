// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect } from "vitest";
import {
  isGitDiff,
  parseGitDiff,
  buildUnifiedDiff,
  composeFileArtifacts,
} from "./diffUtils";

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

describe("buildUnifiedDiff", () => {
  it("round-trips through isGitDiff/parseGitDiff", () => {
    const original = "a\n\nb";
    const modified = "a\nc";
    const diff = buildUnifiedDiff("main.tf", original, modified);

    expect(isGitDiff(diff)).toBe(true);
    expect(parseGitDiff(diff)).toEqual({ original, modified });
  });
});

// Sequential diffs of the same file: v1 → v2 → v3, mirroring a drift
// round that edits outputs.tf several times.
const DIFF_V1_V2 = [
  "diff --git outputs.tf outputs.tf",
  "--- outputs.tf",
  "+++ outputs.tf",
  "@@ -1,3 +1,2 @@",
  ' output "a" {}',
  '-output "b" {}',
  ' output "c" {}',
].join("\n");

const DIFF_V2_V3 = [
  "diff --git outputs.tf outputs.tf",
  "--- outputs.tf",
  "+++ outputs.tf",
  "@@ -1,2 +1,1 @@",
  ' output "a" {}',
  '-output "c" {}',
].join("\n");

describe("composeFileArtifacts", () => {
  it("keeps a single artifact untouched", () => {
    expect(composeFileArtifacts("outputs.tf", [DIFF_V1_V2])).toBe(DIFF_V1_V2);
    expect(composeFileArtifacts("main.tf", ["resource {}"])).toBe(
      "resource {}",
    );
  });

  it("chains sequential diffs into first-original → last-modified", () => {
    const combined = composeFileArtifacts("outputs.tf", [
      DIFF_V1_V2,
      DIFF_V2_V3,
    ]);

    expect(isGitDiff(combined)).toBe(true);
    expect(parseGitDiff(combined)).toEqual({
      original: 'output "a" {}\noutput "b" {}\noutput "c" {}',
      modified: 'output "a" {}',
    });
  });

  it("lets the newest raw snapshot supersede earlier artifacts", () => {
    expect(
      composeFileArtifacts("main.tf", [DIFF_V1_V2, "regenerated {}"]),
    ).toBe("regenerated {}");
  });

  it("keeps a file created in-session raw when diffs follow it", () => {
    // Raw artifact = new file; later diffs evolve it, but relative to the
    // session base the whole result is still an addition.
    const combined = composeFileArtifacts("vars.tf", [
      'variable "a" {}\nvariable "b" {}',
      [
        "diff --git vars.tf vars.tf",
        "--- vars.tf",
        "+++ vars.tf",
        "@@ -1,2 +1,1 @@",
        ' variable "a" {}',
        '-variable "b" {}',
      ].join("\n"),
    ]);

    expect(isGitDiff(combined)).toBe(false);
    expect(combined).toBe('variable "a" {}');
  });
});

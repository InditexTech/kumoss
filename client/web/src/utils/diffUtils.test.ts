// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect } from "vitest";
import {
  parseGitDiff,
  buildUnifiedDiff,
  composeFileArtifacts,
} from "./diffUtils";

/** A stored artifact whose body is a diff (`new_file=false`). */
const diff = (text: string) => ({ text, isNewFile: false });
/** A stored artifact whose body is whole-file content (`new_file=true`). */
const raw = (text: string) => ({ text, isNewFile: true });

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
  it("round-trips through parseGitDiff", () => {
    const original = "a\n\nb";
    const modified = "a\nc";

    expect(parseGitDiff(buildUnifiedDiff("main.tf", original, modified))).toEqual(
      { original, modified },
    );
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
  it("keeps a single artifact untouched, shape included", () => {
    expect(composeFileArtifacts("outputs.tf", [diff(DIFF_V1_V2)])).toEqual(
      diff(DIFF_V1_V2),
    );
    expect(composeFileArtifacts("main.tf", [raw("resource {}")])).toEqual(
      raw("resource {}"),
    );
  });

  it("returns an empty diff artifact for no artifacts at all", () => {
    expect(composeFileArtifacts("main.tf", [])).toEqual(diff(""));
  });

  it("chains sequential diffs into first-original → last-modified", () => {
    const combined = composeFileArtifacts("outputs.tf", [
      diff(DIFF_V1_V2),
      diff(DIFF_V2_V3),
    ]);

    expect(combined.isNewFile).toBe(false);
    expect(parseGitDiff(combined.text)).toEqual({
      original: 'output "a" {}\noutput "b" {}\noutput "c" {}',
      modified: 'output "a" {}',
    });
  });

  it("lets the newest raw snapshot supersede earlier artifacts", () => {
    expect(
      composeFileArtifacts("main.tf", [
        diff(DIFF_V1_V2),
        raw("regenerated {}"),
      ]),
    ).toEqual(raw("regenerated {}"));
  });

  it("keeps a file created in-session raw when diffs follow it", () => {
    // Raw artifact = new file; later diffs evolve it, but relative to the
    // session base the whole result is still an addition — so the composed
    // artifact reports itself as a new file too.
    const combined = composeFileArtifacts("vars.tf", [
      raw('variable "a" {}\nvariable "b" {}'),
      diff(
        [
          "diff --git vars.tf vars.tf",
          "--- vars.tf",
          "+++ vars.tf",
          "@@ -1,2 +1,1 @@",
          ' variable "a" {}',
          '-variable "b" {}',
        ].join("\n"),
      ),
    ]);

    expect(combined).toEqual(raw('variable "a" {}'));
  });

  it("chains only from the newest raw snapshot, ignoring older artifacts", () => {
    // v1→v2 diff, then the file is recreated, then edited again: the
    // pre-recreation diff must not contribute to the result.
    const combined = composeFileArtifacts("vars.tf", [
      diff(DIFF_V1_V2),
      raw('variable "a" {}\nvariable "b" {}'),
      diff(
        [
          "diff --git vars.tf vars.tf",
          "--- vars.tf",
          "+++ vars.tf",
          "@@ -1,2 +1,1 @@",
          ' variable "a" {}',
          '-variable "b" {}',
        ].join("\n"),
      ),
    ]);

    expect(combined).toEqual(raw('variable "a" {}'));
  });

  it("treats a new-file-mode diff as a diff, not as a raw file", () => {
    // A tracked file added this session: `new file mode` in the body, but
    // the store tagged it new_file=false, and metadata is what counts.
    const combined = composeFileArtifacts("vars.tf", [
      diff(NEW_FILE_MODE_DIFF),
      diff(UPDATED_FILE_DIFF),
    ]);

    expect(combined.isNewFile).toBe(false);
    expect(parseGitDiff(combined.text).original).toBe("");
  });
});

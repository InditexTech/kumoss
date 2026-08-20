// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

// Code-change artifacts come in two shapes (tagged new_file=true/false on
// the backend): updated files carry unified `git diff` output, new files
// carry the raw file content with no diff at all. The metadata tag isn't
// exposed through the presigned URL, so the shape is detected from the
// content itself.

export interface ParsedGitDiff {
  original: string;
  modified: string;
}

/** True when `content` is unified git-diff output rather than raw file content. */
export function isGitDiff(content: string): boolean {
  return (
    content.startsWith("diff --git ") &&
    /^@@ -\d+(,\d+)? \+\d+(,\d+)? @@/m.test(content)
  );
}

/**
 * Rebuild the before/after texts of a single-file unified diff. Hunks are
 * concatenated as-is: the backend produces diffs with --unified=1000, so
 * in practice they cover the whole file.
 */
export function parseGitDiff(content: string): ParsedGitDiff {
  const original: string[] = [];
  const modified: string[] = [];
  let inHunk = false;

  for (const line of content.split("\n")) {
    if (line.startsWith("diff --git ")) {
      inHunk = false;
      continue;
    }
    if (line.startsWith("@@")) {
      inHunk = true;
      continue;
    }
    if (!inHunk) continue; // header lines: index, ---/+++, mode changes
    if (line.startsWith("\\")) continue; // "\ No newline at end of file"

    if (line.startsWith("-")) {
      original.push(line.slice(1));
    } else if (line.startsWith("+")) {
      modified.push(line.slice(1));
    } else {
      // context line (leading space, or empty when trailing space is trimmed)
      original.push(line.slice(1));
      modified.push(line.slice(1));
    }
  }

  return { original: original.join("\n"), modified: modified.join("\n") };
}

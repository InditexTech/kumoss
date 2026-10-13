// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

// Code-change artifacts come in two shapes: updated files carry unified
// `git diff` output, new files carry the raw file content with no diff at
// all. The backend tags each with `new_file=true/false` metadata and the
// store serves that back as a response header (see `readIsNewFile` in
// services/core/sessions.ts), so the shape is read rather than inferred —
// but only when the store's CORS rules expose that header. `isGitDiff`
// covers the case where they do not.

export interface ParsedGitDiff {
  original: string;
  modified: string;
}

/** One stored code-change artifact: its body, and the shape the store declared. */
export interface CodeChangeArtifact {
  text: string;
  isNewFile: boolean;
}

/**
 * True when `content` is unified git-diff output rather than raw file content.
 *
 * A fallback, never the primary: `new_file` metadata wins whenever the
 * store exposes it. Sniffing cannot distinguish a file created in-session
 * from a tracked file that was added — both bodies open `diff --git` with
 * `new file mode` — which is precisely the ambiguity the metadata removed.
 * It is still far better than a fixed guess, so it carries deployments
 * whose bucket CORS rules predate the `new_file` header.
 */
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

/**
 * Wrap full before/after texts as a single-hunk unified diff. Only ever
 * read back through parseGitDiff (which rebuilds the two sides for Monaco
 * to re-diff), so hunk granularity doesn't matter.
 */
export function buildUnifiedDiff(
  fileName: string,
  original: string,
  modified: string,
): string {
  const originalLines = original.split("\n");
  const modifiedLines = modified.split("\n");
  return [
    `diff --git ${fileName} ${fileName}`,
    `--- ${fileName}`,
    `+++ ${fileName}`,
    `@@ -1,${originalLines.length} +1,${modifiedLines.length} @@`,
    ...originalLines.map((line) => `-${line}`),
    ...modifiedLines.map((line) => `+${line}`),
  ].join("\n");
}

/**
 * Collapse the artifacts uploaded for one file (oldest first) into a
 * single displayable artifact. A session can touch the same file several
 * times; each updated-file artifact diffs against the PREVIOUS artifact's
 * result, so keeping only the newest would show just the last incremental
 * step. The cumulative change is first-original → last-modified. A raw
 * artifact is a full snapshot of a file created in-session: it supersedes
 * anything before it, and diffs chained onto it stay "new file" (raw), as
 * the whole result is an addition relative to the session base.
 *
 * The result carries its own shape: a composed diff is synthesised by
 * buildUnifiedDiff, so nothing downstream could recover it otherwise.
 */
export function composeFileArtifacts(
  fileName: string,
  artifacts: readonly CodeChangeArtifact[],
): CodeChangeArtifact {
  const last = artifacts[artifacts.length - 1];
  if (artifacts.length <= 1) return last ?? { text: "", isNewFile: false };
  if (last.isNewFile) return last;

  // First artifact of the unbroken diff chain that ends at `last`.
  let start = artifacts.length - 1;
  while (start > 0 && !artifacts[start - 1].isNewFile) start--;

  const { modified } = parseGitDiff(last.text);
  // Chain grows out of a raw snapshot: the whole result is an addition
  // relative to the session base, so it stays raw.
  if (start > 0) return { text: modified, isNewFile: true };
  return {
    text: buildUnifiedDiff(
      fileName,
      parseGitDiff(artifacts[start].text).original,
      modified,
    ),
    isNewFile: false,
  };
}

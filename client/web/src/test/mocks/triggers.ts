// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

export const REPO_TRIGGER = {
  INACCESSIBLE: "error://inaccessible",
  SCAN_FAILED: "error://scan-failed",
  NO_IAC: "error://no-iac",
} as const;

export const CLOUD_TRIGGER = {
  UNAUTHORIZED: "error-unauthorized",
} as const;

export const QUERY_TRIGGER = {
  NOT_IAC: "error:not-iac",
  GENERATION_FAILED: "error:generation-failed",
  DRIFT_FAILED: "error:drift-failed",
  IMPORT_FAILED: "error:import-failed",
  APPLY_FAILED: "error:apply-failed",
  PR_CREATE_FAILED: "error:pr-create-failed",
  PR_MERGE_FAILED: "error:pr-merge-failed",
  NOTIFY_FAILED: "error:notify-failed",
} as const;

type RepoTriggerValue = (typeof REPO_TRIGGER)[keyof typeof REPO_TRIGGER];
type CloudTriggerValue = (typeof CLOUD_TRIGGER)[keyof typeof CLOUD_TRIGGER];
type QueryTriggerValue = (typeof QUERY_TRIGGER)[keyof typeof QUERY_TRIGGER];

export function matchRepoTrigger(
  identifier: string,
): RepoTriggerValue | null {
  const lower = identifier.trim().toLowerCase();
  for (const val of Object.values(REPO_TRIGGER)) {
    if (lower === val) return val;
  }
  return null;
}

export function matchCloudTrigger(cloud: string): CloudTriggerValue | null {
  const lower = cloud.trim().toLowerCase();
  for (const val of Object.values(CLOUD_TRIGGER)) {
    if (lower === val) return val;
  }
  return null;
}

/**
 * `mock:<content-type>` picks which fixture bundle a run should produce
 * (e.g. `mock:destructive add a bucket`). Anything else falls back to
 * the bundle implied by the operation.
 */
export const SCENARIO_PREFIX = "mock:";

export function matchScenarioTrigger(query: string): string | null {
  const trimmed = query.trim().toLowerCase();
  if (!trimmed.startsWith(SCENARIO_PREFIX)) return null;
  const name = trimmed.slice(SCENARIO_PREFIX.length).split(/\s+/)[0];
  return name || null;
}

export function matchQueryTrigger(query: string): QueryTriggerValue | null {
  const lower = query.trim().toLowerCase();
  for (const val of Object.values(QUERY_TRIGGER)) {
    if (lower.startsWith(val)) return val;
  }
  return null;
}

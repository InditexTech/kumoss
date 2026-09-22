// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

/**
 * The mock artifact store.
 *
 * The backend never inlines round output in the session JSON: every
 * report, plan and code change is an object in blob storage, exposed as
 * a short-lived presigned URL on the `*Ref` DTOs. `fetchArtifactContent`
 * then GETs that URL with a bare `fetch` (no auth headers), so the mock
 * mirrors it with same-origin URLs under `/mock-artifacts/` served by
 * their own handler — the client code path stays byte-for-byte the one
 * that runs against a real bucket.
 */

import type {
  CodeChangeRef,
  ReportRef,
  ReportType,
  TerraformPlanRef,
} from "@/types/api";
import type { TerraformReport } from "@/types/index";

/** Same-origin stand-in for the storage account host. */
export const ARTIFACT_BASE = "/mock-artifacts";

interface StoredArtifact {
  content: string;
  contentType: string;
}

const store = new Map<string, StoredArtifact>();
let nextArtifactId = 1;

/** UTF-8 byte length, as the backend records it. */
function byteSize(content: string): number {
  return new TextEncoder().encode(content).length;
}

/** A fake SAS-style query string, so URLs look (and expire) like the real ones. */
function signature(): string {
  return `se=${encodeURIComponent(
    new Date(Date.now() + 24 * 3600_000).toISOString(),
  )}&sp=r&sig=${Math.random().toString(36).slice(2, 18)}`;
}

interface Registered {
  id: number;
  url: string;
  content_type: string;
  file_size_bytes: number;
  created_at: string;
}

function register(
  key: string,
  content: string,
  contentType: string,
  createdAt: string,
): Registered {
  store.set(key, { content, contentType });
  return {
    id: nextArtifactId++,
    url: `${ARTIFACT_BASE}/${key}?${signature()}`,
    content_type: contentType,
    file_size_bytes: byteSize(content),
    created_at: createdAt,
  };
}

/** Storage key for a round's artifact, mirroring the backend's layout. */
function keyFor(sessionId: string, round: number, name: string): string {
  return `${sessionId}/round-${round}/${name}`;
}

export function makeReportRef(
  sessionId: string,
  round: number,
  type: ReportType,
  report: TerraformReport,
  createdAt: string,
): ReportRef {
  const key = keyFor(sessionId, round, `${type}_report.json`);
  const content = JSON.stringify(report, null, 2);
  return { ...register(key, content, "application/json", createdAt), type };
}

/**
 * `isDrift` drives both the payload's `type` and the key's file-name
 * prefix, exactly as `store_terraform_plan` does on the backend: a drift
 * round's diff lands under `plans/drift-*`, a plain plan under
 * `plans/plan-*`. Only `type` is read by the app — `artifactLabel` uses it
 * to say "Drift Operation" rather than "Terraform Plan" — but the key keeps
 * mirroring production so the fixtures stay a faithful stand-in.
 */
export function makePlanRef(
  sessionId: string,
  round: number,
  plan: string,
  targets: string[],
  createdAt: string,
  isDrift = false,
): TerraformPlanRef {
  const flavour = isDrift ? "drift" : "plan";
  const key = keyFor(sessionId, round, `plans/${flavour}-terraform_plan.txt`);
  return {
    ...register(key, plan, "text/plain", createdAt),
    type: flavour,
    targets,
  };
}

export function makeCodeChangeRef(
  sessionId: string,
  round: number,
  fileName: string,
  content: string,
  createdAt: string,
): CodeChangeRef {
  const key = keyFor(sessionId, round, `code/${fileName}`);
  return {
    ...register(key, content, "text/plain", createdAt),
    file_name: fileName,
  };
}

/** Look an artifact up by the path the handler received (no leading base). */
export function resolveArtifact(key: string): StoredArtifact | undefined {
  return store.get(key);
}

export function clearArtifacts(): void {
  store.clear();
  nextArtifactId = 1;
}

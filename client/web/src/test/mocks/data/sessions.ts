// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

/**
 * Seed sessions, assembled the way the backend assembles them.
 *
 * A session is an aggregate: facts + a status timeline + N rounds, each
 * round owning its own statuses and artifact refs. Nothing here inlines
 * content — `buildSession` pushes every file/plan/report into the mock
 * artifact store and keeps only the presigned ref, so the UI has to walk
 * the same round → ref → fetch path it walks in production.
 */

import {
  makeCodeChangeRef,
  makePlanRef,
  makeReportRef,
} from "./artifacts";
import { getScenario, type MockContentType } from "./content";
import type {
  AdminUserEntry,
  AuthorizeResponse,
  OperationType,
  PullRequestDTO,
  PullRequestRef,
  RawHistoryTurn,
  RoundDetail,
  SessionDetail,
  SessionStatus,
  SessionSummary,
  StatusEntry,
  TerraformProvider,
} from "@/types/api";

// ─── Time helpers ─────────────────────────────────────────────
// Seeds are relative to load time so the sessions table always shows
// plausible "x minutes ago" values instead of a frozen date.

const LOADED_AT = Date.now();

function hoursAgo(hours: number): number {
  return LOADED_AT - hours * 3_600_000;
}

function iso(millis: number): string {
  return new Date(millis).toISOString();
}

// ─── Round assembly ───────────────────────────────────────────

/** How a round ended. `running` leaves it mid-flight (no terminal status). */
type RoundOutcome = "completed" | "failed" | "uncompleted" | "running";

export interface RoundSpec {
  content: MockContentType;
  query: string;
  outcome: RoundOutcome;
  /** Failure reason or rejection rationale, carried on the terminal status. */
  message?: string;
  /** Where a `running` round stopped, as an index into its status sequence. */
  stoppedAt?: number;
  pullRequest?: Omit<PullRequestRef, "provider"> & { provider?: string };
}

/**
 * The status sequence a round walks. Apply rounds skip the generation
 * stages — and their `apply` entry is what `isApplyRound` keys on to
 * route the UI to the apply-results panel instead of the code view.
 */
function statusSequence(content: MockContentType): SessionStatus[] {
  if (content.startsWith("apply")) {
    return ["started", "apply", "report"];
  }
  // A drift pass records its assessment before the drift read and its
  // conclusion after the remediation loop — one `reconciling` entry on
  // each side of `generating`/`validating`.
  if (content.startsWith("drift") || content.startsWith("partial_drift")) {
    return [
      "started",
      "filtering",
      "reconciling",
      "generating",
      "validating",
      "reconciling",
      "report",
    ];
  }
  return ["started", "filtering", "generating", "validating", "report"];
}

const STAGE_MESSAGES: Partial<Record<SessionStatus, string>> = {
  started: "Analyzing your request...",
  filtering: "Identifying relevant resources...",
  generating: "Generating Terraform code...",
  validating: "Validating generated code with terraform...",
  reconciling: "Reconciling infrastructure drift...",
  apply: "Applying the stored plan...",
  report: "Preparing report...",
  completed: "Infrastructure code ready.",
};

/** ~40s of wall clock per stage, so timelines render with real gaps. */
const STAGE_MS = 40_000;

function buildStatuses(
  spec: RoundSpec,
  startedAt: number,
): StatusEntry[] {
  const sequence = statusSequence(spec.content);
  const entries: StatusEntry[] = [];

  const stop =
    spec.outcome === "running"
      ? Math.min(spec.stoppedAt ?? 3, sequence.length)
      : spec.outcome === "uncompleted"
        ? 2 // rejected during filtering — nothing is ever generated
        : spec.outcome === "failed"
          ? Math.min(spec.stoppedAt ?? sequence.length - 1, sequence.length)
          : sequence.length;

  for (let i = 0; i < stop; i++) {
    entries.push({
      status: sequence[i],
      message: STAGE_MESSAGES[sequence[i]] ?? null,
      created_at: iso(startedAt + i * STAGE_MS),
    });
  }

  const terminalAt = startedAt + stop * STAGE_MS;
  if (spec.outcome === "completed") {
    entries.push({
      status: "completed",
      message: STAGE_MESSAGES.completed ?? null,
      created_at: iso(terminalAt),
    });
  } else if (spec.outcome === "failed") {
    entries.push({
      status: "failed",
      message: spec.message ?? "Process failed",
      created_at: iso(terminalAt),
    });
  } else if (spec.outcome === "uncompleted") {
    entries.push({
      status: "uncompleted",
      message: spec.message ?? "The request was rejected",
      created_at: iso(terminalAt),
    });
  }

  return entries;
}

/**
 * When the artifacts of a stage were written.
 *
 * Production persists the stage's status first and the artifact moments
 * later, and the session detail panel derives "which status produced this
 * artifact" from exactly that ordering. Stamping everything at the round's
 * end instead would pile every artifact onto the terminal event, so each one
 * lands just inside its own stage window (stages are STAGE_MS apart).
 */
function stageArtifactTime(
  statuses: StatusEntry[],
  stage: SessionStatus,
  fallback: string,
  offsetSeconds = 0,
): string {
  const entry = statuses.find((s) => s.status === stage);
  if (!entry) return fallback;
  return iso(Date.parse(entry.created_at) + (5 + offsetSeconds) * 1000);
}

function buildRound(
  sessionId: string,
  index: number,
  spec: RoundSpec,
  startedAt: number,
): { round: RoundDetail; history: RawHistoryTurn[] } {
  const number = index + 1;
  const createdAt = iso(startedAt);
  const statuses = buildStatuses(spec, startedAt);
  const scenario = getScenario(spec.content);

  // Rejected and still-running rounds have produced nothing yet; a
  // failed round dies before the report is written.
  const hasArtifacts = spec.outcome === "completed";
  // `stoppedAt: 0` models the window between a round's INSERT and its
  // first status write, so the sequence can legitimately be empty.
  const finishedAt = statuses[statuses.length - 1]?.created_at ?? createdAt;

  const round: RoundDetail = {
    id: index + 1,
    number,
    query: spec.query,
    statuses,
    reports: hasArtifacts
      ? [
          makeReportRef(
            sessionId,
            number,
            scenario.reportType,
            scenario.report,
            stageArtifactTime(statuses, "report", finishedAt),
          ),
        ]
      : [],
    plans:
      hasArtifacts && !spec.content.startsWith("apply")
        ? [
            makePlanRef(
              sessionId,
              number,
              scenario.plan,
              scenario.targets,
              stageArtifactTime(statuses, "validating", finishedAt),
              scenario.reportType === "drift",
            ),
          ]
        : [],
    code_changes: hasArtifacts
      ? scenario.files.map((file, fileIndex) =>
          makeCodeChangeRef(
            sessionId,
            number,
            file.name,
            file.content,
            // One second apart, so the write order the panel shows as
            // revision order is unambiguous.
            stageArtifactTime(statuses, "generating", finishedAt, fileIndex),
          ),
        )
      : [],
    pull_requests: spec.pullRequest
      ? [
          {
            provider: spec.pullRequest.provider ?? "GITHUB",
            url: spec.pullRequest.url,
            number: spec.pullRequest.number,
          },
        ]
      : [],
    created_at: createdAt,
  };

  // A rejected round persists its rationale as the assistant turn — the
  // reason `appendAssistantMessage` guards against a double entry.
  const history: RawHistoryTurn[] =
    spec.outcome === "uncompleted"
      ? [{ user: spec.query, assistant: spec.message ?? "Request rejected." }]
      : spec.outcome === "running"
        ? []
        : scenario.history.map((turn) => ({
            user: spec.query,
            assistant: turn.assistant,
          }));

  return { round, history };
}

// ─── Session assembly ─────────────────────────────────────────

export interface SessionSpec {
  uuid: string;
  username: string;
  operation: OperationType;
  provider: TerraformProvider;
  workspace_uri: string;
  branch: string;
  root_path?: string | null;
  scope_id: string;
  is_blocked?: boolean;
  /** Age of the session's first round, in hours. */
  age: number;
  rounds: RoundSpec[];
  /**
   * Override the derived run lock. The backend derives nothing: it sets
   * the flag in `acquire_in_flight` and clears it in the runner's
   * `finally`, so a killed process leaves it stuck `true` over a
   * non-terminal status — a combination the default derivation
   * (`!terminal`) cannot express.
   */
  in_flight?: boolean;
}

export function buildSession(spec: SessionSpec): SessionDetail {
  const startedAt = hoursAgo(spec.age);
  const statuses: StatusEntry[] = [];
  const rounds: RoundDetail[] = [];
  const history: RawHistoryTurn[] = [];

  spec.rounds.forEach((roundSpec, index) => {
    // Rounds run back to back; each starts where the previous ended.
    const roundStart = startedAt + index * 6 * STAGE_MS;
    const built = buildRound(spec.uuid, index, roundSpec, roundStart);
    rounds.push(built.round);
    statuses.push(...built.round.statuses);
    history.push(...built.history);
  });

  const last = statuses[statuses.length - 1];
  const terminal =
    last.status === "completed" ||
    last.status === "failed" ||
    last.status === "uncompleted";

  return {
    uuid: spec.uuid,
    username: spec.username,
    operation: spec.operation,
    provider: spec.provider,
    first_query: spec.rounds[0].query,
    workspace_uri: spec.workspace_uri,
    current_status: last.status,
    in_flight: spec.in_flight ?? !terminal,
    is_blocked: spec.is_blocked ?? false,
    created_at: iso(startedAt),
    updated_at: last.created_at,
    workspace: {
      uri: spec.workspace_uri,
      branch: spec.branch,
      root_path: spec.root_path ?? null,
    },
    scope_id: spec.scope_id,
    rounds,
    history,
  };
}

/** The list projection. `history` and `rounds` are detail-only. */
export function toSummary(detail: SessionDetail): SessionSummary {
  return {
    uuid: detail.uuid,
    username: detail.username,
    operation: detail.operation,
    provider: detail.provider,
    first_query: detail.first_query,
    workspace_uri: detail.workspace_uri,
    current_status: detail.current_status,
    in_flight: detail.in_flight,
    is_blocked: detail.is_blocked,
    created_at: detail.created_at,
    updated_at: detail.updated_at,
  };
}

// ─── Seed data ────────────────────────────────────────────────
// One set feeds both /sessions (self-scoped to MOCK_USER) and
// /admin/sessions (unscoped) — same DTO, different filter, exactly as
// the backend's `user_pk=None` switch does it.

export const MOCK_USER_EMAIL = "mock-user@example.com";

const REPO_INFRA = "https://github.com/contoso/infra-platform";
const REPO_LEGACY = "https://github.com/contoso/legacy-infra";
const REPO_GCP = "https://github.com/contoso/gcp-data-platform";

export const SESSION_SPECS: SessionSpec[] = [
  {
    uuid: "5f2c1a80-0001-4b7e-9c31-a1b2c3d4e001",
    username: MOCK_USER_EMAIL,
    operation: "generate",
    provider: "azure",
    workspace_uri: REPO_INFRA,
    branch: "nebula/add-storage-dev",
    root_path: "environments/dev",
    scope_id: "sub-dev-0001",
    age: 2,
    rounds: [
      {
        content: "generate",
        query:
          "Create a storage account in Azure with a resource group in West Europe",
        outcome: "completed",
      },
    ],
  },
  {
    uuid: "5f2c1a80-0002-4b7e-9c31-a1b2c3d4e002",
    username: MOCK_USER_EMAIL,
    operation: "drift",
    provider: "azure",
    workspace_uri: REPO_INFRA,
    branch: "nebula/drift-fix-networking",
    root_path: "environments/dev",
    scope_id: "sub-dev-0001",
    age: 5,
    rounds: [
      {
        content: "drift",
        query:
          "Detect and remediate drift in my Azure networking configuration",
        outcome: "completed",
      },
    ],
  },
  {
    uuid: "5f2c1a80-0003-4b7e-9c31-a1b2c3d4e003",
    username: "alice@example.com",
    operation: "import",
    provider: "azure",
    workspace_uri: REPO_LEGACY,
    branch: "nebula/import-legacy-prod",
    root_path: "environments/pro",
    scope_id: "sub-pro-0009",
    is_blocked: true,
    age: 9,
    rounds: [
      {
        content: "import",
        query:
          "Import existing Azure resources from resource group rg-legacy-prod into Terraform",
        outcome: "completed",
      },
    ],
  },
  {
    // Two rounds: the follow-up refines the first result, so the UI has
    // to merge code changes across rounds to show the full file set.
    uuid: "5f2c1a80-0004-4b7e-9c31-a1b2c3d4e004",
    username: "bob@example.com",
    operation: "generate",
    provider: "azure",
    workspace_uri: REPO_INFRA,
    branch: "nebula/migrate-to-containers",
    root_path: "environments/dev",
    scope_id: "sub-dev-0001",
    is_blocked: true,
    age: 12,
    rounds: [
      {
        content: "generate",
        query:
          "Migrate the backend from Virtual Machines to Azure Container Instances",
        outcome: "completed",
      },
      {
        content: "generate_multi",
        query: "Add a container registry and wire the app to pull from it",
        outcome: "completed",
        pullRequest: {
          url: "https://github.com/contoso/infra-platform/pull/312",
          number: 312,
        },
      },
    ],
  },
  {
    uuid: "5f2c1a80-0005-4b7e-9c31-a1b2c3d4e005",
    username: MOCK_USER_EMAIL,
    operation: "generate",
    provider: "gcp",
    workspace_uri: REPO_GCP,
    branch: "nebula/bigquery-dataset",
    root_path: "envs/dev",
    scope_id: "gcp-project-analytics",
    age: 0.05,
    rounds: [
      {
        content: "generate",
        query:
          "Create a BigQuery dataset with IAM bindings for the analytics team",
        outcome: "running",
        stoppedAt: 3,
      },
    ],
  },
  {
    // Generate then apply: the apply round is detected by its `apply`
    // status, while `operation` stays "generate".
    uuid: "5f2c1a80-0006-4b7e-9c31-a1b2c3d4e006",
    username: "alice@example.com",
    operation: "generate",
    provider: "azure",
    workspace_uri: REPO_INFRA,
    branch: "nebula/apply-pre-network",
    root_path: "environments/pre",
    scope_id: "sub-pre-0005",
    age: 20,
    rounds: [
      {
        content: "generate",
        query: "Add the pre-production network changes",
        outcome: "completed",
        pullRequest: {
          url: "https://github.com/contoso/infra-platform/pull/247",
          number: 247,
        },
      },
      {
        content: "apply_create",
        query: "Apply the planned network changes to pre-production",
        outcome: "completed",
      },
    ],
  },
  {
    uuid: "5f2c1a80-0007-4b7e-9c31-a1b2c3d4e007",
    username: "alice@example.com",
    operation: "generate",
    provider: "azure",
    workspace_uri: REPO_INFRA,
    branch: "nebula/failed-keyvault",
    root_path: "environments/dev",
    scope_id: "sub-dev-0001",
    age: 26,
    rounds: [
      {
        content: "generate",
        query: "Create a Key Vault with private endpoint and DNS zone",
        outcome: "failed",
        message:
          "Terraform validation failed: azurerm_private_dns_zone requires provider version >= 3.80",
        stoppedAt: 4,
      },
    ],
  },
  {
    uuid: "5f2c1a80-0008-4b7e-9c31-a1b2c3d4e008",
    username: MOCK_USER_EMAIL,
    operation: "generate",
    provider: "azure",
    workspace_uri: REPO_INFRA,
    branch: "nebula/generate-partial-openai",
    root_path: "environments/dev",
    scope_id: "sub-dev-0001",
    age: 30,
    rounds: [
      {
        content: "generate_partial",
        query:
          "Create a resource group, storage account, and Azure OpenAI service in West Europe",
        outcome: "completed",
      },
    ],
  },
  {
    uuid: "5f2c1a80-0009-4b7e-9c31-a1b2c3d4e009",
    username: "bob@example.com",
    operation: "drift",
    provider: "azure",
    workspace_uri: REPO_INFRA,
    branch: "nebula/drift-failed-lock",
    root_path: "environments/dev",
    scope_id: "sub-dev-0001",
    age: 34,
    rounds: [
      {
        content: "drift_failed",
        query: "Detect and fix drift in my Azure networking resources",
        outcome: "failed",
        message:
          "Failed to acquire state lock. Another terraform operation is currently running.",
        stoppedAt: 3,
      },
    ],
  },
  {
    uuid: "5f2c1a80-0010-4b7e-9c31-a1b2c3d4e010",
    username: MOCK_USER_EMAIL,
    operation: "drift",
    provider: "azure",
    workspace_uri: REPO_INFRA,
    branch: "nebula/drift-partial-keyvault",
    root_path: "environments/dev",
    scope_id: "sub-dev-0001",
    age: 38,
    rounds: [
      {
        content: "drift_partial",
        query:
          "Remediate drift on storage, NSG, and key vault in dev environment",
        outcome: "completed",
      },
    ],
  },
  {
    uuid: "5f2c1a80-0011-4b7e-9c31-a1b2c3d4e011",
    username: MOCK_USER_EMAIL,
    operation: "drift",
    provider: "azure",
    workspace_uri: REPO_INFRA,
    branch: "nebula/partial-drift-storage",
    root_path: "environments/dev",
    scope_id: "sub-dev-0001",
    age: 42,
    rounds: [
      {
        content: "partial_drift",
        query: "Check drift only on storage accounts in the dev environment",
        outcome: "completed",
      },
    ],
  },
  {
    uuid: "5f2c1a80-0012-4b7e-9c31-a1b2c3d4e012",
    username: "bob@example.com",
    operation: "drift",
    provider: "azure",
    workspace_uri: REPO_INFRA,
    branch: "nebula/partial-drift-failed-net",
    root_path: "environments/pre",
    scope_id: "sub-pre-0005",
    age: 46,
    rounds: [
      {
        content: "partial_drift_failed",
        query:
          "Scan for drift on networking resources only in pre-production",
        outcome: "failed",
        message:
          "Failed to download required providers from registry.terraform.io: connection refused.",
        stoppedAt: 2,
      },
    ],
  },
  {
    uuid: "5f2c1a80-0013-4b7e-9c31-a1b2c3d4e013",
    username: MOCK_USER_EMAIL,
    operation: "drift",
    provider: "azure",
    workspace_uri: REPO_INFRA,
    branch: "nebula/partial-drift-partial-nsg",
    root_path: "environments/dev",
    scope_id: "sub-dev-0001",
    age: 50,
    rounds: [
      {
        content: "partial_drift_partial",
        query: "Check and fix drift on VNet, subnet, and NSG in dev",
        outcome: "completed",
      },
    ],
  },
  {
    uuid: "5f2c1a80-0014-4b7e-9c31-a1b2c3d4e014",
    username: "bob@example.com",
    operation: "import",
    provider: "azure",
    workspace_uri: REPO_LEGACY,
    branch: "nebula/import-failed-kv",
    root_path: "environments/pro",
    scope_id: "sub-pro-0009",
    is_blocked: true,
    age: 54,
    rounds: [
      {
        content: "import_failed",
        query:
          "Import existing Azure resources from resource group rg-legacy-prod",
        outcome: "failed",
        message:
          "Insufficient permissions: Microsoft.KeyVault/vaults/read required.",
        stoppedAt: 3,
      },
    ],
  },
  {
    uuid: "5f2c1a80-0015-4b7e-9c31-a1b2c3d4e015",
    username: MOCK_USER_EMAIL,
    operation: "import",
    provider: "azure",
    workspace_uri: REPO_LEGACY,
    branch: "nebula/import-partial-psql",
    root_path: "environments/pro",
    scope_id: "sub-pro-0009",
    age: 58,
    rounds: [
      {
        content: "import_partial",
        query:
          "Import resource group, storage account, key vault, and PostgreSQL from rg-legacy-prod",
        outcome: "completed",
      },
    ],
  },
  {
    // Iteration rejected by the filter: `uncompleted` is terminal, and
    // the earlier round's artifacts must stay on screen.
    uuid: "5f2c1a80-0016-4b7e-9c31-a1b2c3d4e016",
    username: MOCK_USER_EMAIL,
    operation: "generate",
    provider: "azure",
    workspace_uri: REPO_INFRA,
    branch: "nebula/rejected-followup",
    root_path: "environments/dev",
    scope_id: "sub-dev-0001",
    age: 62,
    rounds: [
      {
        content: "generate",
        query: "Create a storage account with a lifecycle policy",
        outcome: "completed",
      },
      {
        content: "generate",
        query: "What is the weather in Madrid?",
        outcome: "uncompleted",
        message:
          "This request is not related to infrastructure as code. I can only help with provisioning, drift detection and importing cloud resources.",
      },
    ],
  },
  {
    // Destructive plan — drives the high-impact warning banner.
    uuid: "5f2c1a80-0017-4b7e-9c31-a1b2c3d4e017",
    username: "alice@example.com",
    operation: "generate",
    provider: "azure",
    workspace_uri: REPO_INFRA,
    branch: "nebula/decommission-legacy-vms",
    root_path: "environments/pro",
    scope_id: "sub-pro-0009",
    is_blocked: true,
    age: 70,
    rounds: [
      {
        content: "destructive",
        query: "Decommission the legacy VM scale set and its public IPs",
        outcome: "completed",
      },
    ],
  },
  {
    // Destroy-only plan, owned by the mock user and locked: the round to
    // walk the unblock flow on. Apply answers 403 while `is_blocked` is
    // set; PATCH /admin/sessions/{id}/toggle_lock clears it and the same
    // apply then takes off.
    uuid: "5f2c1a80-0018-4b7e-9c31-a1b2c3d4e018",
    username: MOCK_USER_EMAIL,
    operation: "generate",
    provider: "azure",
    workspace_uri: REPO_INFRA,
    branch: "nebula/remove-legacy-etl",
    root_path: "environments/pro",
    scope_id: "sub-pro-0009",
    is_blocked: true,
    age: 1,
    rounds: [
      {
        content: "remove_resource",
        query:
          "Remove the legacy ETL data factory and its export storage account from the pro environment",
        outcome: "completed",
        pullRequest: {
          url: "https://github.com/contoso/infra-platform/pull/318",
          number: 318,
        },
      },
    ],
  },
  {
    // Drift remediated and committed, but no pull request yet: `rounds[0]`
    // carries artifacts and an empty `pull_requests`, so the results view
    // rests on "create PR" with nothing to view or merge. Owned by the mock
    // user and unlocked, so the create-then-merge walkthrough runs from
    // /user/sessions — and because PUT /repository/pr mutates the round it
    // lands on, this is the session to spend instead of the drift baseline.
    uuid: "5f2c1a80-0019-4b7e-9c31-a1b2c3d4e019",
    username: MOCK_USER_EMAIL,
    operation: "drift",
    provider: "azure",
    workspace_uri: REPO_INFRA,
    branch: "nebula/drift-no-pr-nsg",
    root_path: "environments/pre",
    scope_id: "sub-pre-0005",
    age: 3,
    rounds: [
      {
        content: "drift",
        query:
          "Detect and remediate drift on the pre-production network security groups",
        outcome: "completed",
      },
    ],
  },
];

export function buildSeedSessions(): SessionDetail[] {
  return SESSION_SPECS.map(buildSession);
}

// ─── Other mocked payloads ────────────────────────────────────

let nextPrNumber = 400;

/** Response of PUT /repository/pr. */
export function createMockPullRequest(
  overrides: Partial<PullRequestDTO> = {},
): PullRequestDTO {
  const number = nextPrNumber++;
  return {
    id: number,
    url: `${REPO_INFRA}/pull/${number}`,
    status: "open",
    ...overrides,
  };
}

/**
 * Response of POST /auth/authorize. Core maps the authz service's
 * `{authorized, portal_url, reason}` (see contracts/openapi/authz.v1.yaml)
 * onto this camelCase shape before it reaches the browser.
 */
export function createMockAuthorizeResponse(
  authorized: boolean,
  scope: string,
): AuthorizeResponse {
  return authorized
    ? { result: true, message: `Access granted to ${scope}.` }
    : {
        result: false,
        message: `You do not have the required role on ${scope}. Request access through the cloud portal.`,
        portalUrl: "https://portal.example.com/access-request",
      };
}

export const MOCK_ME: AdminUserEntry = {
  id: 1,
  email: MOCK_USER_EMAIL,
  display_name: "Mock User",
  operation_role: "devops",
  panel_role: "admin",
  issuer: "https://login.example.com",
  subject: "00000000-0000-0000-0000-000000000001",
  created_at: iso(hoursAgo(24 * 120)),
};

export const MOCK_USERS: AdminUserEntry[] = [
  MOCK_ME,
  {
    id: 2,
    email: "alice@example.com",
    display_name: "Alice Alvarez",
    operation_role: "devops",
    panel_role: "editor",
    issuer: "https://login.example.com",
    subject: "00000000-0000-0000-0000-000000000002",
    created_at: iso(hoursAgo(24 * 95)),
  },
  {
    id: 3,
    email: "bob@example.com",
    display_name: "Bob Bermejo",
    operation_role: "developer",
    panel_role: "viewer",
    issuer: "https://login.example.com",
    subject: "00000000-0000-0000-0000-000000000003",
    created_at: iso(hoursAgo(24 * 80)),
  },
  {
    id: 4,
    email: "carol@example.com",
    display_name: "Carol Cano",
    operation_role: "developer",
    panel_role: null,
    issuer: "https://login.example.com",
    subject: "00000000-0000-0000-0000-000000000004",
    created_at: iso(hoursAgo(24 * 40)),
  },
  {
    id: 5,
    email: "dave@partner.example.com",
    display_name: null,
    operation_role: "developer",
    panel_role: null,
    issuer: "https://partner-idp.example.com",
    subject: "00000000-0000-0000-0000-000000000005",
    created_at: iso(hoursAgo(24 * 6)),
  },
];

// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

/**
 * POST /iac/{generate,drift,apply}.
 *
 * All three are fire-and-forget: they persist a session (or a new round
 * on an existing one), hand the work to a background task and answer 202
 * with nothing but a `session_id`. No status is written synchronously —
 * which is exactly why the client has `waitForNewRound`. The handlers
 * below reproduce that: they register a pending run and return; the SSE
 * handler is what actually advances it.
 */

import { http, HttpResponse, delay } from "msw";
import type { MockContentType } from "../data";
import { schedule } from "../runtime";
import { mockState } from "../state";
import { makeSessionDetail } from "../state";
import {
  matchQueryTrigger,
  matchRepoTrigger,
  matchScenarioTrigger,
  QUERY_TRIGGER,
} from "../triggers";
import type {
  ApplyRequest,
  BaseIacRequest,
  DriftRequest,
  SessionDetail,
  TerraformProvider,
} from "@/types/api";

const CONTENT_TYPES: MockContentType[] = [
  "generate",
  "generate_partial",
  "generate_multi",
  "drift",
  "drift_failed",
  "drift_partial",
  "partial_drift",
  "partial_drift_failed",
  "partial_drift_partial",
  "apply",
  "apply_create",
  "apply_create_update",
  "apply_destroy",
  "apply_mixed",
  "import",
  "import_failed",
  "import_partial",
  "destructive",
  "remove_resource",
];

/** Verbs that mark the session's request as a removal. */
const REMOVAL_INTENT = /\b(remove|delete|destroy|decommission|tear\s?down)\b/i;

function unprocessable(message: string) {
  return HttpResponse.json(
    { detail: [{ loc: ["body"], msg: message, type: "value_error" }] },
    { status: 422 },
  );
}

/** `BaseIacRequest` accepts exactly one of `repo_uri` / `session_id`. */
function validateBase(body: BaseIacRequest) {
  const hasRepo = !!body.repo_uri;
  const hasSession = !!body.session_id;
  if (hasRepo === hasSession) {
    return unprocessable(
      "Provide exactly one of 'repo_uri' (first call) or 'session_id' (iteration).",
    );
  }
  if (hasRepo && !body.terraform_providers) {
    return unprocessable("'terraform_providers' is required on the first call.");
  }
  if (hasSession && body.iac_path) {
    return unprocessable("'iac_path' cannot be changed on an iteration.");
  }
  if (body.repo_uri && matchRepoTrigger(body.repo_uri)) {
    return HttpResponse.json(
      { detail: `Repository is not accessible: ${body.repo_uri}` },
      { status: 400 },
    );
  }
  return null;
}

/** Which fixture bundle the run should produce. */
function pickContent(query: string, fallback: MockContentType): MockContentType {
  const requested = matchScenarioTrigger(query);
  if (requested && (CONTENT_TYPES as string[]).includes(requested)) {
    return requested as MockContentType;
  }
  return fallback;
}

/**
 * Which apply log an apply round should produce. Apply carries no query
 * of its own — it re-runs the plan already stored on the session — so
 * the fixture is inferred from what that session originally asked for:
 * a removal replays as a destroy log, anything else as a create log.
 */
function applyFallback(query: string): MockContentType {
  return REMOVAL_INTENT.test(query) ? "apply_destroy" : "apply_create";
}

interface Outcome {
  outcome: "completed" | "failed" | "uncompleted";
  message?: string;
}

function pickOutcome(query: string, failTrigger: string): Outcome {
  const trigger = matchQueryTrigger(query);
  if (trigger === QUERY_TRIGGER.NOT_IAC) {
    return {
      outcome: "uncompleted",
      message:
        "This request is not related to infrastructure as code. I can only help with provisioning, drift detection and importing cloud resources.",
    };
  }
  if (trigger === failTrigger) {
    return {
      outcome: "failed",
      message: `The run failed as requested by the '${trigger}' trigger.`,
    };
  }
  return { outcome: "completed" };
}

/** Create the session a first call implies. */
function startSession(body: BaseIacRequest, operation: SessionDetail["operation"]) {
  const uuid = crypto.randomUUID();
  const detail = makeSessionDetail({
    uuid,
    username: null,
    operation,
    provider: (body.terraform_providers ?? "azure") as TerraformProvider,
    first_query: body.q,
    workspace_uri: body.repo_uri ?? "",
    current_status: "started",
    in_flight: true,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    workspace: {
      uri: body.repo_uri ?? "",
      branch: `nebula/${uuid.slice(0, 8)}`,
      root_path: body.iac_path ?? null,
    },
    scope_id: body.scope_id ?? "mock-scope",
    rounds: [],
    history: [],
  });
  mockState.addSession(detail);
  return detail;
}

/** Register the round an IaC call is about to run, first call or iteration. */
async function acceptRun(
  body: BaseIacRequest,
  operation: SessionDetail["operation"],
  sseOperation: string,
  content: MockContentType,
  failTrigger: string,
) {
  const invalid = validateBase(body);
  if (invalid) return invalid;

  let detail = body.session_id
    ? mockState.getSession(body.session_id)
    : startSession(body, operation);
  if (!detail) {
    return HttpResponse.json({ detail: "Session not found" }, { status: 404 });
  }
  detail = detail as SessionDetail;

  const round = mockState.appendRound(detail.uuid, {
    query: body.q,
    created_at: new Date().toISOString(),
  });
  if (!round) {
    return HttpResponse.json({ detail: "Session not found" }, { status: 404 });
  }

  const { outcome, message } = pickOutcome(body.q, failTrigger);
  schedule({
    sessionId: detail.uuid,
    roundId: round.id,
    roundNumber: round.number,
    content: pickContent(body.q, content),
    operation: sseOperation,
    outcome,
    message,
  });

  return HttpResponse.json({ session_id: detail.uuid }, { status: 202 });
}

export const iacActionHandlers = [
  http.post("/api/v1/iac/generate", async ({ request }) => {
    await delay(300);
    const body = (await request.json()) as BaseIacRequest;
    return acceptRun(
      body,
      "generate",
      "generate",
      "generate",
      QUERY_TRIGGER.GENERATION_FAILED,
    );
  }),

  http.post("/api/v1/iac/drift", async ({ request }) => {
    await delay(300);
    const body = (await request.json()) as DriftRequest;
    const partial = body.is_partial === true;
    return acceptRun(
      body,
      "drift",
      partial ? "partial_drift" : "drift",
      partial ? "partial_drift" : "drift",
      QUERY_TRIGGER.DRIFT_FAILED,
    );
  }),

  // Apply reuses the session's stored plan: session_id only, no query.
  http.post("/api/v1/iac/apply", async ({ request }) => {
    await delay(300);
    const body = (await request.json()) as ApplyRequest;
    const detail = body.session_id
      ? mockState.getSession(body.session_id)
      : undefined;
    if (!detail) {
      return HttpResponse.json({ detail: "Session not found" }, { status: 404 });
    }
    // Mirrors the core's apply guard: a locked session is refused until
    // an operator clears the lock via the admin toggle.
    if (detail.is_blocked) {
      return HttpResponse.json(
        {
          detail:
            "Apply is locked for this session. An operator must unblock it before the plan can be applied.",
        },
        { status: 403 },
      );
    }

    const round = mockState.appendRound(detail.uuid, {
      query: detail.first_query ?? "Apply the stored plan",
      created_at: new Date().toISOString(),
    });
    if (!round) {
      return HttpResponse.json(
        { detail: "Session not found" },
        { status: 404 },
      );
    }

    const { outcome, message } = pickOutcome(
      detail.first_query ?? "",
      QUERY_TRIGGER.APPLY_FAILED,
    );
    schedule({
      sessionId: detail.uuid,
      roundId: round.id,
      roundNumber: round.number,
      content: pickContent(
        detail.first_query ?? "",
        applyFallback(detail.first_query ?? ""),
      ),
      operation: "apply",
      outcome,
      message,
    });

    return HttpResponse.json({ session_id: detail.uuid }, { status: 202 });
  }),
];

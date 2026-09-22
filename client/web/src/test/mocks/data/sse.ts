// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

/**
 * Progress event sequences for GET /events/subscribe/{id}.
 *
 * The backend does not push transitions: it polls the session's *last*
 * status every 5s and re-emits it, so duplicates are normal and the
 * client must be idempotent. The stream opens with a `: keepalive`
 * comment and the server closes it after COMPLETED, UNCOMPLETED or
 * FAILED. The sequences below reproduce all of that — including the
 * duplicate re-emissions, which is the part a naive mock gets wrong.
 */

import type { SessionEventData, SseStatus } from "@/types/api";

export interface SseStep {
  /** Milliseconds to wait before writing this event. */
  delay: number;
  data: SessionEventData;
}

/** The comment line the backend writes before any data frame. */
export const SSE_KEEPALIVE = ": keepalive\n\n";

/**
 * Knobs for the stream's realism. The defaults are what a browser wants;
 * a test that drives a full run turns `realism` off (no random retries or
 * duplicate frames) and raises `speed` so the sequence finishes at once.
 */
export const sseOptions = {
  /** Inject validation retries and duplicate poll frames. */
  realism: true,
  /** Divides every delay. */
  speed: 1,
};

/** How the mocked run should end. */
export type SseOutcome = "completed" | "failed" | "uncompleted";

const STAGE_MESSAGES: Record<string, string> = {
  generate: "Generating Terraform code...",
  drift: "Detecting infrastructure drift...",
  partial_drift: "Scanning targeted resources for drift...",
  import: "Scanning and importing existing resources...",
  apply: "Applying the stored plan...",
};

/** Statuses the orchestrator can bounce back from on a validation retry. */
const RETRYABLE: SseStatus[] = ["GENERATING", "VALIDATING"];

const RETRY_MESSAGES: Partial<Record<SseStatus, string[]>> = {
  FILTERING: ["Re-evaluating resource scope...", "Adjusting resource filters..."],
  GENERATING: [
    "Validation found issues, regenerating code...",
    "Retrying generation with adjusted parameters...",
    "Refining generated code after feedback...",
  ],
  VALIDATING: [
    "Re-validating after regeneration...",
    "Running terraform validate again...",
  ],
};

function pickRandom<T>(arr: T[]): T {
  return arr[Math.floor(Math.random() * arr.length)];
}

function step(
  delay: number,
  status: SseStatus,
  message: string,
): SseStep {
  return {
    delay: Math.round(delay / sseOptions.speed),
    data: { status_msg: status, detail: { message } },
  };
}

/**
 * Re-emit the current status once, the way the 5s poll does when a stage
 * outlives one tick. Keeps the client's duplicate handling exercised.
 */
function withPollDuplicates(steps: SseStep[]): SseStep[] {
  if (!sseOptions.realism) return steps;
  const result: SseStep[] = [];
  for (const current of steps) {
    result.push(current);
    const terminal =
      current.data.status_msg === "COMPLETED" ||
      current.data.status_msg === "FAILED" ||
      current.data.status_msg === "UNCOMPLETED";
    if (terminal || Math.random() > 0.35) continue;
    // The backend's poll interval, scaled like every other delay.
    result.push({
      delay: Math.round(5000 / sseOptions.speed),
      data: current.data,
    });
  }
  return result;
}

/**
 * Bounce a validation failure back to GENERATING before moving on —
 * the orchestrator's validation loop as the client sees it.
 */
function injectRetries(steps: SseStep[]): SseStep[] {
  if (!sseOptions.realism) return steps;
  const result: SseStep[] = [];
  for (let i = 0; i < steps.length; i++) {
    result.push(steps[i]);

    const status = steps[i].data.status_msg;
    if (!RETRYABLE.includes(status)) continue;
    if (Math.random() > 0.4) continue;

    const previous = steps[i - 1]?.data.status_msg;
    if (!previous || previous === "STARTED") continue;

    result.push(
      step(
        3000,
        previous,
        pickRandom(
          RETRY_MESSAGES[previous] ?? [`Retrying ${previous.toLowerCase()}...`],
        ),
      ),
      step(
        3600,
        status,
        pickRandom(
          RETRY_MESSAGES[status] ?? [`Resuming ${status.toLowerCase()}...`],
        ),
      ),
    );
  }
  return result;
}

/**
 * The event sequence for one round.
 *
 * `operation` selects the wording of the generating stage; an `apply`
 * run skips filtering/generating/validating entirely, matching the
 * status timeline the apply handler writes.
 */
export function createSseEventSequence(
  operation: string = "generate",
  outcome: SseOutcome = "completed",
  failureMessage?: string,
): SseStep[] {
  const started = step(0, "STARTED", "Analyzing your request...");

  if (outcome === "uncompleted") {
    return [
      started,
      step(900, "FILTERING", "Identifying relevant resources..."),
      step(
        2200,
        "UNCOMPLETED",
        failureMessage ??
          "This request is not related to infrastructure as code.",
      ),
    ];
  }

  const isApply = operation === "apply";
  const stages: SseStep[] = isApply
    ? [started, step(1500, "APPLY", STAGE_MESSAGES.apply)]
    : [
        started,
        step(900, "FILTERING", "Identifying relevant resources..."),
        step(1400, "GENERATING", STAGE_MESSAGES[operation] ?? STAGE_MESSAGES.generate),
        step(2000, "VALIDATING", "Validating generated code with terraform..."),
      ];

  if (outcome === "failed") {
    return [
      ...stages,
      step(
        2500,
        "FAILED",
        failureMessage ??
          (isApply
            ? "Apply failed: terraform apply returned errors. One or more resources could not be created."
            : "Generation failed: unable to produce valid Terraform after the maximum number of validation retries."),
      ),
    ];
  }

  const full = [
    ...stages,
    step(1500, "REPORT", "Preparing report..."),
    step(
      1000,
      "COMPLETED",
      isApply ? "Apply finished." : "Infrastructure code ready.",
    ),
  ];

  return withPollDuplicates(isApply ? full : injectRetries(full));
}

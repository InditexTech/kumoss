// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

/**
 * Drives the mock suite through the real service layer, so the fixtures
 * can't drift from the client contract without a test going red.
 */

import { describe, it, expect, beforeEach, afterEach } from "vitest";
import {
  setSessionLock,
  setUserRoles,
  listUsers,
  listAdminSessions,
} from "@/services/core/admin";
import { subscribeToSession } from "@/services/core/events";
import {
  applyInfrastructure,
  generateInfrastructure,
} from "@/services/core/iac_actions";
import { createPullRequest, mergePullRequest, parseRepository } from "@/services/core/iac_code";
import {
  checkApplyAllowed,
  getSessionDetail,
  listUserSessions,
} from "@/services/core/sessions";
import { authorizeUser } from "@/services/core/authorization";
import { sendNotification } from "@/services/notifications/notification";
import { NotificationSeverity } from "@/types/api_notifications";
import { resolveSessionOutcome } from "@/services/workflows/session_outcome";
import { artifactLabel } from "@/components/Sessions/SessionData/ArtifactContent";
import {
  buildSeedSessions,
  REPRO_IDS,
  sseOptions,
  MOCK_USER_EMAIL,
} from "./data";
import { clearRuns } from "./runtime";
import { seedMockData, seedReproData } from "./seed";
import { lastSessionStatus, mockState } from "./state";
import { CLOUD_TRIGGER, QUERY_TRIGGER, REPO_TRIGGER } from "./triggers";

beforeEach(() => {
  mockState.clear();
  clearRuns();
  seedMockData();
  sseOptions.realism = false;
  sseOptions.speed = 200;
});

afterEach(() => {
  mockState.clear();
  clearRuns();
  sseOptions.realism = true;
  sseOptions.speed = 1;
});

/** Collect the stream's frames until it closes. */
function drainStream(sessionId: string): Promise<string[]> {
  return new Promise((resolve, reject) => {
    const seen: string[] = [];
    const connection = subscribeToSession(sessionId);
    const timer = setTimeout(() => {
      connection.close();
      reject(new Error(`stream never closed; saw ${seen.join(",")}`));
    }, 8_000);

    connection.onmessage = (event) => {
      const parsed = JSON.parse(event.data);
      seen.push(parsed.status_msg);
      if (["COMPLETED", "UNCOMPLETED", "FAILED"].includes(parsed.status_msg)) {
        clearTimeout(timer);
        connection.close();
        resolve(seen);
      }
    };
    connection.onerror = () => {
      clearTimeout(timer);
      reject(new Error("stream errored"));
    };
  });
}

describe("seeded sessions", () => {
  it("lists the caller's own sessions, hiding other users'", async () => {
    const page = await listUserSessions({ page_size: 100 });
    expect(page.items.length).toBeGreaterThan(0);
    expect(page.items.every((s) => s.username === MOCK_USER_EMAIL)).toBe(true);
  });

  it("lists every user's sessions on the admin endpoint", async () => {
    const page = await listAdminSessions({ page_size: 100 });
    expect(page.total).toBe(buildSeedSessions().length);
    expect(new Set(page.items.map((s) => s.username)).size).toBeGreaterThan(1);
  });

  it("only serializes history when asked", async () => {
    const [seed] = mockState.listSessions();
    expect((await getSessionDetail(seed.uuid)).history).toBeNull();
    const withHistory = await getSessionDetail(seed.uuid, {
      includeHistory: true,
    });
    expect(withHistory.history?.length).toBeGreaterThan(0);
  });

  it("resolves a completed round from its presigned artifacts", async () => {
    const seed = mockState
      .listSessions()
      .find(
        (s) => s.current_status === "completed" && s.rounds[0].reports.length > 0,
      )!;

    const outcome = await resolveSessionOutcome(seed.uuid);
    expect(outcome.kind).toBe("results");
    if (outcome.kind !== "results") return;

    expect(outcome.report?.status).toBeTruthy();
    expect(outcome.code).toContain("<Terraform_Plan>");
    expect(outcome.targets?.length).toBeGreaterThan(0);
  });

  it("keeps the prior round's artifacts when an iteration is rejected", async () => {
    const seed = mockState
      .listSessions()
      .find((s) => s.current_status === "uncompleted")!;

    const outcome = await resolveSessionOutcome(seed.uuid);
    expect(outcome.kind).toBe("rejected");
    if (outcome.kind !== "rejected") return;
    expect(outcome.rationale).toMatch(/not related to infrastructure/i);
    expect(outcome.prior?.code).toContain("<Terraform_Plan>");
  });

  it("routes an apply round to the apply-results outcome", async () => {
    const seed = mockState
      .listSessions()
      .find((s) => s.rounds.some((r) => r.statuses.some((x) => x.status === "apply")))!;

    const outcome = await resolveSessionOutcome(seed.uuid);
    expect(outcome.kind).toBe("apply-results");
  });

  it("surfaces a failed round's reason", async () => {
    const seed = mockState
      .listSessions()
      .find((s) => s.current_status === "failed")!;

    const outcome = await resolveSessionOutcome(seed.uuid);
    expect(outcome.kind).toBe("failed");
    if (outcome.kind !== "failed") return;
    expect(outcome.message.length).toBeGreaterThan(0);
  });

  it("keys a drift round's plan so it labels as a drift operation", async () => {
    // `artifactLabel` reads the flavour off the object key, the way it does
    // against a real bucket. A seed that keys every plan the same way would
    // show "Terraform Plan" on drift rounds in `dev:mock` while production
    // showed "Drift Operation" — the fixture has to carry the prefix too.
    const seed = mockState
      .listSessions()
      .find((s) => s.operation === "drift" && s.rounds.some((r) => r.plans.length > 0))!;
    const plan = seed.rounds.flatMap((r) => r.plans)[0];

    expect(artifactLabel("plan", plan)).toBe("Drift Operation");
  });
});

describe("live run", () => {
  it("generates: 202 → SSE → artifacts on the new round", async () => {
    const { session_id } = await generateInfrastructure({
      repo_uri: "https://github.com/contoso/infra-platform",
      terraform_providers: "azure",
      q: "Create a storage account in West Europe",
    });
    expect(session_id).toBeTruthy();

    // Nothing is written synchronously — the round exists but is silent.
    const before = await getSessionDetail(session_id);
    expect(before.rounds).toHaveLength(1);
    expect(before.rounds[0].statuses).toHaveLength(0);

    const statuses = await drainStream(session_id);
    expect(statuses[0]).toBe("STARTED");
    expect(statuses[statuses.length - 1]).toBe("COMPLETED");

    const outcome = await resolveSessionOutcome(session_id);
    expect(outcome.kind).toBe("results");
  });

  it("does not record a duplicate poll frame as a second status", async () => {
    sseOptions.realism = true; // re-enables duplicate frames and retries
    const { session_id } = await generateInfrastructure({
      repo_uri: "https://github.com/contoso/infra-platform",
      terraform_providers: "azure",
      q: "Create a storage account in West Europe",
    });
    await drainStream(session_id);

    const detail = await getSessionDetail(session_id);
    const statuses = detail.rounds.flatMap((r) => r.statuses);
    const consecutiveRepeat = statuses.some(
      (entry, i) => i > 0 && statuses[i - 1].status === entry.status,
    );
    expect(consecutiveRepeat).toBe(false);
  });

  it("rejects an off-topic query with a terminal UNCOMPLETED", async () => {
    const { session_id } = await generateInfrastructure({
      repo_uri: "https://github.com/contoso/infra-platform",
      terraform_providers: "azure",
      q: `${QUERY_TRIGGER.NOT_IAC} what is the weather?`,
    });
    expect(await drainStream(session_id)).toContain("UNCOMPLETED");
    expect((await resolveSessionOutcome(session_id)).kind).toBe("rejected");
  });

  it("fails the run when the failure trigger is used", async () => {
    const { session_id } = await generateInfrastructure({
      repo_uri: "https://github.com/contoso/infra-platform",
      terraform_providers: "azure",
      q: `${QUERY_TRIGGER.GENERATION_FAILED} build something`,
    });
    expect(await drainStream(session_id)).toContain("FAILED");
  });

  it("rejects a request that sets neither repo_uri nor session_id", async () => {
    await expect(
      generateInfrastructure({ q: "no target at all" }),
    ).rejects.toMatchObject({ status: 422 });
  });
});

describe("blocked apply", () => {
  /** The caller's own locked session — the destroy-only removal round. */
  function lockedSeed() {
    return mockState
      .listSessions()
      .find((s) => s.username === MOCK_USER_EMAIL && s.is_blocked)!;
  }

  it("serves a destroy-only plan for the removal round", async () => {
    const outcome = await resolveSessionOutcome(lockedSeed().uuid);
    expect(outcome.kind).toBe("results");
    if (outcome.kind !== "results") return;

    expect(outcome.code).toContain("will be destroyed");
    expect(outcome.code).toContain("Plan: 0 to add, 0 to change, 3 to destroy.");
    expect(outcome.report?.summary).toMatchObject({ create: 0, delete: 3 });
    expect(outcome.report?.potential_impact?.banner?.level).toBe("high");
  });

  it("refuses apply while locked, and runs it once unblocked", async () => {
    const seed = lockedSeed();
    expect(await checkApplyAllowed(seed.uuid)).toBe(false);
    await expect(
      applyInfrastructure({ session_id: seed.uuid }),
    ).rejects.toMatchObject({ status: 403 });

    // The refusal must not have left a round behind.
    expect((await getSessionDetail(seed.uuid)).rounds).toHaveLength(1);

    expect(await setSessionLock(seed.uuid, false)).toEqual({
      uuid: seed.uuid,
      is_blocked: false,
    });
    expect(await checkApplyAllowed(seed.uuid)).toBe(true);

    const { session_id } = await applyInfrastructure({ session_id: seed.uuid });
    expect(session_id).toBe(seed.uuid);

    const statuses = await drainStream(session_id);
    expect(statuses).toContain("APPLY");
    expect(statuses[statuses.length - 1]).toBe("COMPLETED");

    const outcome = await resolveSessionOutcome(session_id);
    expect(outcome.kind).toBe("apply-results");
    if (outcome.kind !== "apply-results") return;

    // A removal replays as a destroy log, not the create one.
    expect(outcome.report?.apply_summary).toMatchObject({
      created: 0,
      destroyed: 4,
    });
    // An apply round carries the log, not a plan to apply.
    expect(outcome.round.plans).toEqual([]);

    const detail = await getSessionDetail(session_id);
    expect(detail.rounds).toHaveLength(2);
  });
});

describe("other endpoints", () => {
  it("toggles the session lock and echoes is_blocked", async () => {
    const [seed] = mockState.listSessions();
    expect(await setSessionLock(seed.uuid, true)).toEqual({
      uuid: seed.uuid,
      is_blocked: true,
    });
    expect((await getSessionDetail(seed.uuid)).is_blocked).toBe(true);
  });

  it("lists users and persists a role change", async () => {
    const before = await listUsers({ page_size: 100 });
    const target = before.items.find((u) => u.panel_role === "viewer")!;
    const updated = await setUserRoles(target.id, {
      operation_role: "devops",
      panel_role: null,
    });
    expect(updated).toMatchObject({ operation_role: "devops", panel_role: null });

    const after = await listUsers({ page_size: 100 });
    expect(after.items.find((u) => u.id === target.id)?.panel_role).toBeNull();
  });

  it("creates a PR (201) and merges it (204)", async () => {
    const [seed] = mockState.listSessions();
    const pr = await createPullRequest({ session_id: seed.uuid });
    expect(pr).toMatchObject({ status: "open" });
    expect(pr.url).toContain("/pull/");
    await expect(mergePullRequest({ session_id: seed.uuid })).resolves.toBeUndefined();
  });

  it("parses a repo into root modules, and honours the triggers", async () => {
    expect((await parseRepository("https://github.com/x/y")).roots.length).toBeGreaterThan(0);
    expect((await parseRepository(REPO_TRIGGER.NO_IAC)).roots).toEqual([]);
    await expect(parseRepository(REPO_TRIGGER.INACCESSIBLE)).rejects.toMatchObject({
      status: 404,
    });
  });

  it("accepts a support notification (202) and honours its trigger", async () => {
    const request = {
      kind: "support.contact_team",
      severity: NotificationSeverity.WARNING,
      subject: "Support request",
      body: "The user asked for help with a plan that deletes resources.",
    };
    expect(await sendNotification(request)).toMatchObject({
      delivery_id: expect.stringContaining("mock-delivery-"),
    });
    await expect(
      sendNotification({ ...request, body: QUERY_TRIGGER.NOTIFY_FAILED }),
    ).rejects.toMatchObject({ status: 502 });
  });

  it("authorizes, and returns a portal URL when denied", async () => {
    const allowed = await authorizeUser({
      cloud: "azure",
      project_name: "platform",
      environment: "dev",
    });
    expect(allowed).toMatchObject({ result: true });

    const denied = await authorizeUser({
      cloud: CLOUD_TRIGGER.UNAUTHORIZED,
      project_name: "platform",
      environment: "pro",
    });
    expect(denied.result).toBe(false);
    expect(denied.portalUrl).toBeTruthy();
  });
});

// ─── Reproduction fixtures ────────────────────────────────────
// These pin the *shapes* the session-recovery findings need, not the
// buggy behaviour they currently produce, so the assertions stay green
// once the findings are fixed. The one behavioural claim asserted here
// — that the resolver answers "in-progress" — is correct behaviour; the
// findings live downstream of it, in settleOutcome/handleOutcome.
describe("reproduction fixtures", () => {
  beforeEach(() => {
    seedReproData();
  });

  /**
   * `drainStream` resolves only on a terminal frame, which is exactly
   * what these sessions never produce. This collects what the client
   * does see instead: the same non-terminal frame on every reconnect,
   * until it exhausts its retries and gives up. `retryBaseMs: 1`
   * collapses the 2s/4s/8s backoff so the test finishes.
   */
  function drainNonTerminal(sessionId: string): Promise<string[]> {
    return new Promise((resolve, reject) => {
      const seen: string[] = [];
      const connection = subscribeToSession(sessionId, undefined, {
        retryBaseMs: 1,
      });
      const timer = setTimeout(() => {
        connection.close();
        reject(new Error(`stream terminated; saw ${seen.join(",")}`));
      }, 4_000);

      connection.onmessage = (event) => {
        seen.push(JSON.parse(event.data).status_msg);
      };
      connection.onerror = () => {
        clearTimeout(timer);
        connection.close();
        resolve(seen);
      };
    });
  }

  it("REPRO-1: session-level and round-level last status disagree", async () => {
    const detail = await getSessionDetail(REPRO_IDS.flap, {
      includeHistory: true,
    });

    // What the SSE stream polls (core: get_last_status(session_id)).
    expect(lastSessionStatus(detail)?.status).toBe("completed");
    expect(detail.current_status).toBe("completed");

    // What resolveSessionOutcome reads (the last round).
    const lastRound = detail.rounds[detail.rounds.length - 1];
    expect(detail.rounds).toHaveLength(2);
    expect(lastRound.statuses).toHaveLength(0);
    expect(lastRound.code_changes).toHaveLength(0);

    // The stream therefore replays a terminal frame for a live round...
    expect(await drainStream(REPRO_IDS.flap)).toEqual(["COMPLETED"]);
    // ...while the resolver correctly reports the round as unfinished.
    expect((await resolveSessionOutcome(REPRO_IDS.flap)).kind).toBe("in-progress");
  });

  it("REPRO-2: an orphaned run holds the lock over a non-terminal status", async () => {
    const detail = await getSessionDetail(REPRO_IDS.orphanLocked);
    const lastRound = detail.rounds[detail.rounds.length - 1];

    expect(detail.in_flight).toBe(true);
    expect(lastRound.statuses[lastRound.statuses.length - 1].status).toBe("generating");
    expect(lastRound.statuses.map((s) => s.status)).not.toContain("failed");

    // No terminal frame is ever emitted, so the client reconnects and
    // sees the same stale status again — which is what defeats the 90s
    // inactivity watchdog: traffic arrives, the state never advances.
    const frames = await drainNonTerminal(REPRO_IDS.orphanLocked);
    expect(frames.length).toBeGreaterThan(1);
    expect(new Set(frames)).toEqual(new Set(["GENERATING"]));
    expect((await resolveSessionOutcome(REPRO_IDS.orphanLocked)).kind).toBe("in-progress");
  });

  it("REPRO-2b: the control case differs only in the lock", async () => {
    const locked = await getSessionDetail(REPRO_IDS.orphanLocked);
    const unlocked = await getSessionDetail(REPRO_IDS.orphanUnlocked);

    expect(unlocked.in_flight).toBe(false);
    expect(unlocked.current_status).toBe(locked.current_status);
    // Same resolver verdict despite the opposite lock — which is why an
    // `in_flight` gate cannot distinguish the two.
    expect((await resolveSessionOutcome(REPRO_IDS.orphanUnlocked)).kind).toBe("in-progress");
  });

  it("REPRO-3: the latch pair resolves to opposite kinds", async () => {
    expect((await resolveSessionOutcome(REPRO_IDS.latchFrom)).kind).toBe("in-progress");
    expect((await resolveSessionOutcome(REPRO_IDS.latchTo)).kind).toBe("results");
  });

  it("keeps the fixtures out of the default seed", async () => {
    mockState.clear();
    seedMockData();
    // The admin list is unscoped, so it counts every seeded session.
    const page = await listAdminSessions({ page_size: 100 });
    expect(page.total).toBe(buildSeedSessions().length);
    expect(page.items.some((s) => s.uuid === REPRO_IDS.flap)).toBe(false);
  });
});

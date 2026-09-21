// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

export { createMockTerraformReport, getScenario } from "./content";
export type { MockContentType, Scenario, ScenarioFile } from "./content";

export {
  ARTIFACT_BASE,
  clearArtifacts,
  makeCodeChangeRef,
  makePlanRef,
  makeReportRef,
  resolveArtifact,
} from "./artifacts";

export {
  buildSeedSessions,
  buildSession,
  createMockAuthorizeResponse,
  createMockPullRequest,
  MOCK_ME,
  MOCK_USER_EMAIL,
  MOCK_USERS,
  SESSION_SPECS,
  toSummary,
} from "./sessions";
export type { RoundSpec, SessionSpec } from "./sessions";

export { buildReproSessions, REPRO_IDS, REPRO_SPECS } from "./repro";

export { createSseEventSequence, SSE_KEEPALIVE, sseOptions } from "./sse";
export type { SseOutcome, SseStep } from "./sse";

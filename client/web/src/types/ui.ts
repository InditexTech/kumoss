// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import type { Dispatch, SetStateAction } from "react";
import type { ComplianceReport, TerraformReport } from "./index";
import type {
  HistoryEntry,
  OperationType,
  SessionStatus,
  TerraformProvider,
  WorkspaceRef,
} from "./api";

export type StateSetter<T> = Dispatch<SetStateAction<T>>;

// ─── Screen ─────────────────────────────────────────────────

export type WizardStep =
  | "query"
  | "repository_url"
  | "iac_path"
  | "provider"
  | "cloud_scope";
export type HomeView = "wizard" | "planning" | "result" | "apply-results";

export interface ApplyResultsData {
  sessionId: string;
  buildId?: string;
  status: string;
  message: string;
  errorMessage: string;
  timestamp: string;
  resultsUrl?: string;
  applyReport?: TerraformReport | null;
}

export type PrApprovalStep = "initial" | "confirming";

// ─── Pipeline Phases ────────────────────────────────────────

export const PHASE = {
  INIT: "phase0",
  RUNNING: "phase1",
  REPORT: "phase2",
  COMPLETE: "phase3",
  FINALIZING: "phase4",
} as const;

export type PipelinePhase = (typeof PHASE)[keyof typeof PHASE];

// ─── Event Status ───────────────────────────────────────────

export const EVENT_STATUS = {
  COMPLETED: "COMPLETED",
  UNCOMPLETED: "UNCOMPLETED",
  FAILED: "FAILED",
  REPORT: "REPORT",
  VALIDATING: "VALIDATING",
  APPLY: "APPLY",
} as const;

export type EventStatus = (typeof EVENT_STATUS)[keyof typeof EVENT_STATUS];

// ─── Assistant Message ──────────────────────────────────────

export interface AssistantMsgState {
  msg: string;
  pipelineStep: PipelinePhase;
  sseStatus: string;
  showPR: boolean;
  showTFApply: boolean;
  showPipeline: boolean;
  isApplyMode: boolean;
}

// ─── Session ────────────────────────────────────────────────

export interface Session {
  uuid?: string;
  operation?: OperationType;
  provider?: TerraformProvider;
  scope_id?: string;
  first_query?: string;
  workspace?: Partial<WorkspaceRef>;
  /** Failed sessions can't be resumed server-side; gates the follow-up input. */
  current_status?: SessionStatus;
  is_blocked?: boolean;
  history?: HistoryEntry[];
  terraform_report?: TerraformReport;
  compliance_report?: ComplianceReport;
  code?: string;
  planTargets?: string[];
  /**
   * File names in `code` whose body is raw content rather than a diff.
   * `code` is a flat blob, so the shape cannot be recovered from it.
   */
  newFiles?: string[];
  applyResults?: ApplyResultsData;
}

export interface PrDetails {
  url?: string;
  number?: number;
  lastPrStep?: PrApprovalStep;
  /**
   * Session-local: set once this PR has been merged, so the report view stops
   * offering the merge again. Cannot survive a refresh — the rehydration path
   * rebuilds PR state from `PullRequestRef`, which carries no status.
   * See `useSessionLoader`.
   */
  merged?: boolean;
}

// ─── Mode ───────────────────────────────────────────────────

export const MODE = {
  GENERATE: "generate",
  DRIFT: "drift",
  PARTIAL_DRIFT: "partial_drift",
  IMPORT: "import",
  PARTIAL_IMPORT: "partial_import",
} as const;

export type Mode = (typeof MODE)[keyof typeof MODE];

export interface ModeContextValue {
  mode: Mode;
  setMode: (newMode: Mode) => void;
  toggleMode: () => void;
  cycleMode: () => void;
  isGenerateMode: boolean;
  isDriftMode: boolean;
  isPartialDriftMode: boolean;
  isImportMode: boolean;
  isPartialImportMode: boolean;
  isAnyDriftMode: boolean;
  isAnyImportMode: boolean;
}

// ─── Notifications ─────────────────────────────────────────

export type NotificationType = "success" | "warning" | "failure";

export interface NotificationAction {
  label: string;
  href?: string;
  onClick?: () => void;
}

export interface NotificationData {
  id: string;
  type: NotificationType;
  message: string;
  action?: NotificationAction;
}

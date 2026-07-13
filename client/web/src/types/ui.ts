// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import type { Dispatch, SetStateAction } from "react";
import type { TerraformReport } from "./index";
import type { HistoryEntry } from "./api";

export type StateSetter<T> = Dispatch<SetStateAction<T>>;

// ─── Screen ─────────────────────────────────────────────────

export type WizardStep =
  | "query"
  | "repository_url"
  | "iac_path"
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

export type PrApprovalStep = "initial" | "confirming" | "high_impact_warning";

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
  FAILED: "FAILED",
  REPORT: "REPORT",
  VALIDATING: "VALIDATING",
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

export interface SessionFilter {
  project?: string;
  cloud?: string;
  environment?: string;
  user_email?: string;
  unique_repository_name?: string;
  [key: string]: unknown;
}

export interface Session {
  session_id?: string;
  cloud?: string;
  project?: string;
  environment?: string;
  repositoryUrl?: string;
  uniqueRepositoryName?: string;
  branchName?: string;
  firstQuery?: string;
  userQueries: string[];
  validatorProvider?: string;
  terraform_targets?: string[];
  terraform_report?: TerraformReport;
  full_history?: HistoryEntry[];
  pipeline_url?: string;
  apply_allowed?: boolean;
  code?: string;
  applyResults?: ApplyResultsData;
}

export interface PrDetails {
  prUrl?: string;
  pipelineUrl?: string;
  applyUrl?: string;
  id?: number;
  lastPrStep?: PrApprovalStep;
}

// ─── Mode ───────────────────────────────────────────────────

export const MODE = {
  GENERATE: "generate",
  DRIFT: "drift",
  PARTIAL_DRIFT: "partial_drift",
  IMPORT: "import",
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
  isAnyDriftMode: boolean;
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

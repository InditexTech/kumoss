// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import type { PaginatedResponse } from "@/types/api";

export type OperationKind = "generate" | "drift" | "import" | "apply";

/** Only drift and import can be scheduled. */
export type ScheduleKind = Extract<OperationKind, "drift" | "import">;

export type ScheduleOperationStatus =
  | "pending"
  | "running"
  | "succeeded"
  | "failed"
  | "cancelled";

export interface Schedule {
  uuid: string;
  owner_email: string | null;
  name: string;
  kind: ScheduleKind;
  cron: string;
  enabled: boolean;
  params: Record<string, unknown>;
  next_run_at: string | null;
  last_run_at: string | null;
  created_at: string;
}

export interface ScheduleOperation {
  uuid: string;
  session_uuid: string;
  schedule_uuid: string | null;
  kind: OperationKind;
  status: ScheduleOperationStatus;
  params: Record<string, unknown>;
  scheduled_at: string;
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
  created_at: string;
}

export type PaginatedSchedules = PaginatedResponse<Schedule>;
export type PaginatedOperations = PaginatedResponse<ScheduleOperation>;

export interface CreateScheduleRequest {
  name: string;
  kind: ScheduleKind;
  cron: string;
  params: Record<string, unknown>;
  enabled: boolean;
}

export interface UpdateScheduleRequest {
  name?: string;
  cron?: string;
  params?: Record<string, unknown>;
  enabled?: boolean;
}

// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import type { PaginatedResponse } from "@/types/api";

export type ScheduleKind = "GENERATE" | "DRIFT" | "APPLY" | "IMPORT";

export type ScheduleOperationStatus =
  | "PENDING"
  | "RUNNING"
  | "SUCCEEDED"
  | "FAILED"
  | "CANCELLED";

export interface Schedule {
  uuid: string;
  user_id: string | null;
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
  session_uuid: string | null;
  schedule_uuid: string | null;
  kind: ScheduleKind;
  status: ScheduleOperationStatus;
  params: Record<string, unknown>;
  scheduled_at: string;
  started_at: string | null;
  finished_at: string | null;
  attempt: number;
  max_attempts: number;
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
  user_id: string;
  enabled: boolean;
}

export interface UpdateScheduleRequest {
  name?: string;
  cron?: string;
  params?: Record<string, unknown>;
  enabled?: boolean;
}

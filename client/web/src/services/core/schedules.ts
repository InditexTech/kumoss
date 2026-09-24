// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { apiFetch } from "@/services/api";
import type {
  CreateScheduleRequest,
  PaginatedSchedules,
  Schedule,
  UpdateScheduleRequest,
} from "@/types/api_scheduler";

const BASE = "/api/v1/schedules";

export interface ListSchedulesParams {
  page?: number;
  page_size?: number;
  username?: string;
}

export async function listSchedules(
  params: ListSchedulesParams = {},
): Promise<PaginatedSchedules> {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") {
      query.set(key, String(value));
    }
  }
  const qs = query.toString();
  return apiFetch<PaginatedSchedules>(qs ? `${BASE}?${qs}` : BASE);
}

export async function getSchedule(scheduleId: string): Promise<Schedule> {
  return apiFetch<Schedule>(
    `${BASE}/${encodeURIComponent(scheduleId)}`,
  );
}

export async function createSchedule(
  request: CreateScheduleRequest,
): Promise<Schedule> {
  return apiFetch<Schedule>(BASE, {
    method: "POST",
    body: JSON.stringify(request),
  });
}

export async function updateSchedule(
  scheduleId: string,
  request: UpdateScheduleRequest,
): Promise<Schedule> {
  return apiFetch<Schedule>(
    `${BASE}/${encodeURIComponent(scheduleId)}`,
    {
      method: "PATCH",
      body: JSON.stringify(request),
    },
  );
}

export async function deleteSchedule(scheduleId: string): Promise<void> {
  await apiFetch<void>(
    `${BASE}/${encodeURIComponent(scheduleId)}`,
    { method: "DELETE" },
  );
}

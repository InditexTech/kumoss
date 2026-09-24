// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { apiFetch } from "@/services/api";
import type {
  PaginatedOperations,
  ScheduleKind,
  ScheduleOperationStatus,
  ScheduleOperation,
} from "@/types/api_scheduler";

const BASE = "/api/v1/operations";

export interface ListOperationsParams {
  page?: number;
  page_size?: number;
  session_id?: string;
  kind?: ScheduleKind;
  status?: ScheduleOperationStatus;
  schedule_id?: number;
  schedule_uuid?: string;
}

export async function listOperations(
  params: ListOperationsParams = {},
): Promise<PaginatedOperations> {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") {
      query.set(key, String(value));
    }
  }
  const qs = query.toString();
  return apiFetch<PaginatedOperations>(qs ? `${BASE}?${qs}` : BASE);
}

export async function getOperation(
  operationId: string,
): Promise<ScheduleOperation> {
  return apiFetch<ScheduleOperation>(
    `${BASE}/${encodeURIComponent(operationId)}`,
  );
}

export async function cancelOperation(
  operationId: string,
): Promise<{ status: string }> {
  return apiFetch<{ status: string }>(
    `${BASE}/${encodeURIComponent(operationId)}/cancel`,
    { method: "POST" },
  );
}

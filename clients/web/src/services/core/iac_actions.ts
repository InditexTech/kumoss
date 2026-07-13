// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { apiFetch } from "@/services/api";
import {
  GenerateRequest,
  DriftRequest,
  ApplyRequest,
  IacSessionResponse,
} from "@/types/api";

const BASE = "/api/v1/iac";

/** POST /v1/iac/generate — Generate Infrastructure */
export async function generateInfrastructure(
  request: GenerateRequest,
): Promise<IacSessionResponse> {
  return apiFetch<IacSessionResponse>(`${BASE}/generate`, {
    method: "POST",
    body: JSON.stringify(request),
  });
}

/** POST /v1/iac/drift — Drift Detection Remediation */
export async function driftDetectionRemediation(
  request: DriftRequest,
): Promise<IacSessionResponse> {
  return apiFetch<IacSessionResponse>(`${BASE}/drift`, {
    method: "POST",
    body: JSON.stringify(request),
  });
}

/** POST /v1/iac/apply — Apply Infrastructure */
export async function applyInfrastructure(
  request: ApplyRequest,
): Promise<IacSessionResponse> {
  return apiFetch<IacSessionResponse>(`${BASE}/apply`, {
    method: "POST",
    body: JSON.stringify(request),
  });
}

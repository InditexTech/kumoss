// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

export function extractProjectName(workspaceUri?: string | null): string {
  if (!workspaceUri) return "-";
  const segments = workspaceUri.replace(/\/+$/, "").split("/");
  return segments[segments.length - 1] || workspaceUri;
}
export { extractProjectName } from "@/services/workflows/session_outcome";

// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { getLocalItem, setLocalItem } from "./storage";

const MERGED_PR_PREFIX = "nebula:merged-pr";

function mergedPrKey(sessionId: string, prId: number): string {
  return `${MERGED_PR_PREFIX}:${sessionId}:${prId}`;
}

export function isPullRequestMerged(sessionId: string, prId: number): boolean {
  return getLocalItem(mergedPrKey(sessionId, prId)) === "1";
}

export function markPullRequestMerged(sessionId: string, prId: number): void {
  setLocalItem(mergedPrKey(sessionId, prId), "1");
}

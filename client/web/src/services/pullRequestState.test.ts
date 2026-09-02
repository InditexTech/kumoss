// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { beforeEach, describe, expect, it } from "vitest";
import {
  isPullRequestMerged,
  markPullRequestMerged,
} from "./pullRequestState";

describe("pull request state", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("persists merged state by session and pull request", () => {
    markPullRequestMerged("sess-1", 42);

    expect(isPullRequestMerged("sess-1", 42)).toBe(true);
    expect(isPullRequestMerged("sess-1", 43)).toBe(false);
    expect(isPullRequestMerged("sess-2", 42)).toBe(false);
  });
});

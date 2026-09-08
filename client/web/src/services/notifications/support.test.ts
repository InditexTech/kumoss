// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect } from "vitest";
import type { UserInfo } from "@/types";
import { buildSupportContext, buildSupportLinks, buildSupportSubject } from "./support";

const user: UserInfo = {
  id: 1,
  email: "someone@example.com",
  displayName: "Someone",
  operationRole: "developer",
  panelRole: null,
};

describe("support notification builders", () => {
  it("buildSupportContext maps session fields and keeps missing ones as null", () => {
    const ctx = buildSupportContext({
      user,
      session: { session_id: "s1", cloud: "gcp", firstQuery: "add a bucket", userQueries: [] },
      prDetails: {},
      extra: { trigger: "manual" },
    });
    expect(ctx).toMatchObject({
      user_email: "someone@example.com",
      user_name: "Someone",
      session_id: "s1",
      cloud: "gcp",
      request: "add a bucket",
      project: null,
      pull_request: null,
      trigger: "manual",
    });
  });

  it("buildSupportLinks adds the session page and the PR when present", () => {
    expect(
      buildSupportLinks({ session_id: "s1", userQueries: [] }, { prUrl: "https://x/pr/1" }, "https://nebula.example"),
    ).toEqual([
      { label: "Open session", url: "https://nebula.example/home/results/s1" },
      { label: "Pull request", url: "https://x/pr/1" },
    ]);
    expect(buildSupportLinks({ userQueries: [] }, {}, "https://nebula.example")).toEqual([]);
  });

  it("buildSupportSubject names the user and the session", () => {
    expect(buildSupportSubject("Support request", user, { session_id: "s1", userQueries: [] })).toBe(
      "Support request from someone@example.com – session s1",
    );
    expect(buildSupportSubject("Support question", null, { userQueries: [] })).toBe(
      "Support question from unknown user",
    );
  });
});

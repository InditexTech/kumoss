// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { http, HttpResponse, delay } from "msw";
import { createMockPullRequest } from "../data";
import { mockState } from "../state";
import {
  matchQueryTrigger,
  matchRepoTrigger,
  QUERY_TRIGGER,
  REPO_TRIGGER,
} from "../triggers";
import type { CreatePrRequest, MergePrRequest } from "@/types/api";

/** Root modules a scan finds; the wizard offers these as `iac_path`. */
const IAC_ROOTS = [
  "environments/dev",
  "environments/pre",
  "environments/pro",
  "modules/networking",
];

export const repositoryHandlers = [
  // 201 + PullRequestDTO. PR creation runs synchronous LLM work server
  // side, hence the client's 5-minute timeout override.
  http.put("/api/v1/repository/pr", async ({ request }) => {
    await delay(600);
    const body = (await request.json()) as CreatePrRequest;
    const detail = mockState.getSession(body.session_id);
    if (!detail) {
      return HttpResponse.json({ detail: "Session not found" }, { status: 404 });
    }
    if (matchQueryTrigger(detail.first_query ?? "") === QUERY_TRIGGER.PR_CREATE_FAILED) {
      return HttpResponse.json(
        { detail: "Failed to create the pull request: branch already merged." },
        { status: 502 },
      );
    }

    const pr = createMockPullRequest({
      url: `${detail.workspace_uri}/pull/${Math.floor(Math.random() * 900) + 100}`,
    });
    const round = detail.rounds[detail.rounds.length - 1];
    if (round) {
      round.pull_requests = [
        ...round.pull_requests,
        { provider: "GITHUB", url: pr.url, number: pr.id },
      ];
    }
    return HttpResponse.json(pr, { status: 201 });
  }),

  // Merge answers 204 with no body.
  http.put("/api/v1/repository/pr/merge", async ({ request }) => {
    await delay(500);
    const body = (await request.json()) as MergePrRequest;
    const detail = mockState.getSession(body.session_id);
    if (!detail) {
      return HttpResponse.json({ detail: "Session not found" }, { status: 404 });
    }
    if (matchQueryTrigger(detail.first_query ?? "") === QUERY_TRIGGER.PR_MERGE_FAILED) {
      return HttpResponse.json(
        { detail: "Merge conflict: the pull request cannot be merged." },
        { status: 409 },
      );
    }
    return new HttpResponse(null, { status: 204 });
  }),

  http.post("/api/v1/repository/parse", async ({ request }) => {
    await delay(700);
    const { repo_uri } = (await request.json()) as { repo_uri: string };
    switch (matchRepoTrigger(repo_uri)) {
      case REPO_TRIGGER.INACCESSIBLE:
        return HttpResponse.json(
          { detail: "Repository is not accessible or does not exist." },
          { status: 404 },
        );
      case REPO_TRIGGER.SCAN_FAILED:
        return HttpResponse.json(
          { detail: "Failed to scan the repository for Terraform root modules." },
          { status: 500 },
        );
      case REPO_TRIGGER.NO_IAC:
        return HttpResponse.json({ roots: [] });
      default:
        return HttpResponse.json({ roots: IAC_ROOTS });
    }
  }),
];

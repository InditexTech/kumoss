// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

/**
 * Builders for support notifications.
 *
 * Both entry points that reach a human (the header's support modal and
 * the "Contact team" / "Request review" buttons on the results and PR
 * views) attach the same session metadata so whoever picks the message
 * up in Slack can jump straight to the session. The metadata travels in
 * the contract's free-form `context` (rendered as fields by the
 * notifications service) and `links` (rendered as buttons).
 */

import type { UserInfo } from "@/types";
import type { Session, PrDetails } from "@/types/ui";
import type { NotificationLink } from "@/types/api_notifications";

export interface SupportContextInput {
  user: UserInfo | null;
  session: Session;
  prDetails: PrDetails;
  extra?: Record<string, unknown>;
}

/** Session metadata for `NotificationRequest.context`. Nullish values are
 * kept as `null`; the notifications service drops empty fields. */
export function buildSupportContext({
  user,
  session,
  prDetails,
  extra = {},
}: SupportContextInput): Record<string, unknown> {
  return {
    user_email: user?.email ?? null,
    user_name: user?.displayName ?? null,
    session_id: session.session_id ?? null,
    cloud: session.cloud ?? null,
    project: session.project ?? null,
    environment: session.environment ?? null,
    repository: session.repositoryUrl ?? null,
    branch: session.branchName ?? null,
    request: session.firstQuery ?? null,
    status: session.current_status ?? null,
    pull_request: prDetails.prUrl ?? null,
    ...extra,
  };
}

/** Deep links for `NotificationRequest.links`: the session results page
 * (same origin as the SPA) and the pull request when one exists. */
export function buildSupportLinks(
  session: Session,
  prDetails: PrDetails,
  origin: string = globalThis.location?.origin ?? "",
): NotificationLink[] {
  const links: NotificationLink[] = [];
  if (session.session_id && origin) {
    links.push({
      label: "Open session",
      url: `${origin}/home/results/${session.session_id}`,
    });
  }
  if (prDetails.prUrl) {
    links.push({ label: "Pull request", url: prDetails.prUrl });
  }
  return links;
}

/** Single-line subject: who, and which session. */
export function buildSupportSubject(
  prefix: string,
  user: UserInfo | null,
  session: Session,
): string {
  const who = user?.email ?? "unknown user";
  const where = session.session_id ? ` – session ${session.session_id}` : "";
  return `${prefix} from ${who}${where}`;
}

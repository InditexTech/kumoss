<!--
SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)

SPDX-License-Identifier: Apache-2.0
-->

# Admin portal

The Nebula web application has one portal for looking at sessions, with two views:

- **Your sessions** (`/user/sessions`): every signed-in user sees the sessions they own, opens their details and artifacts, and jumps back into a session to continue it.
- **Admin panel** (`/admin`): users who hold an **admin-panel role** see every user's sessions, can lock or unlock the apply of a session, and (for panel admins) manage roles.

This guide explains how to sign in and reach both views, what each one shows, the two role groups behind them, and how to perform the common administrative tasks. It describes what the current API and UI implement; operations that do not exist (deleting users or sessions, for example) are not described.

Related guides: [User guide](user-guide.md) (what session owners do in the wizard), [OIDC setup](oidc-setup.md) (login and the first administrator), [Operating modes](modes.md) (what sessions do and what the operation roles gate), [Monitoring with Phoenix](monitoring.md).

## Signing in and finding the portal

1. Open the application. With OIDC enabled you are redirected to your identity provider and back; with authentication disabled (blank `oidc.issuer_url`, the checked-in default) you land in the wizard directly as the built-in local developer. If your token expires the application shows "Your session has expired. Please sign in again."
2. The **user icon** in the header opens your user page (`/user`), which has three sections: **Profile** (name, e-mail, sign-out), **Session History** with a "View all sessions" button that opens your sessions view, and, only for users with a panel role, **Admin** with an "Admin Panel" button that opens the admin panel.
3. The **Sessions** panel in the footer of the wizard lists your most recent sessions; "View all" opens the same sessions view, and selecting an entry opens that session's detail directly (`/user/sessions?session=<id>`).
4. Users without a panel role who type `/admin` are redirected to the home page.

## Two independent role groups

Every user record in Nebula's database carries two roles that solve different problems.

**Operation roles** decide which Infrastructure as Code (IaC) operations a user may run on their own sessions. They are hierarchical and every user has one.

| Operation role | Grants |
|---|---|
| `developer` | Generate Infrastructure, create and merge pull requests, apply a pinned plan on sessions they own. |
| `devops` | Everything `developer` can do, plus Partial and Full Drift Remediation. The UI also reserves the Import Infrastructure mode for `devops`. |

**Admin-panel roles** decide what a user may do in the admin panel. They are hierarchical too, and they are optional: most users have no panel role and only see their own sessions.

| Panel role | Grants |
|---|---|
| none | Own sessions only. |
| `viewer` | Read-only view of every user's sessions in the admin panel. |
| `editor` | `viewer` plus lock and unlock the apply of any session. |
| `admin` | `editor` plus user and role management. |

A panel role says nothing about IaC permissions. A panel `admin` with operation role `developer` cannot run drift remediation, and cannot apply or merge on somebody else's session: acting on a session belongs to its owner only, whatever the panel role. Conversely, operation roles say nothing about the admin panel: a `devops` user without a panel role sees only their own sessions.

Session access rules enforced by the API:

- The **owner** can always read a session and is the only one who can act on it (continue it, create or merge its pull request, apply).
- A user with **any panel role** can read any session, both through the admin routes and through the regular session routes, including its live event stream.
- Everyone else receives `403 Not the session owner`.

## Your sessions view

Reached from the user page or the footer. It lists the sessions you own, newest first, with these columns: query, project, type, cloud, status, apply lock, and creation time. Controls:

- **Search** by project name, query text, or session id, plus **type** (`generate`, `drift`, `import`) and **status** (`generating`, `completed`, `uncompleted`, `failed`) filters. Results are paginated.
- **Apply column.** A read-only lock icon showing whether apply and pull-request merge are currently blocked for that session. Owners cannot change it; only a panel editor or admin can, from the admin panel.

Clicking a row opens the detail panel with: type, cloud, status, failure message when present, duration, a timeline of statuses per round with the artifacts attached to each (report, apply report, drift report, Terraform plan, changed files), and additional information (session id, IaC path, scope, repository link, pull-request links). Artifacts render inline: JSON reports as change tables with impact and cost sections, plans as code, and code changes as file diffs.

**Reload Session** (shown unless the session failed) reopens the session in the wizard, in the mode the session was created with, so you can review the results, create or merge the pull request, apply, or continue the conversation. Failed sessions cannot be resumed; start a new one.

The conversation history is not shown in this view; it is available in the admin panel.

## Admin panel

Reached from the "Admin Panel" button on the user page. It has a **Sessions** tab for every panel role and a **Users** tab for panel `admin` only.

### Sessions tab

The table lists sessions from every user with these columns: user (local part of the e-mail), session id (first eight characters; the full id on hover), query, project, type, cloud, status, apply lock, and creation time.

Controls:

- **Search by user email** and **Search by project name, query or session id**, plus the same **type** and **status** filters as the user view. Results are paginated.
- **Apply column.** Viewers see the same read-only lock icon as owners. For editors and admins the icon becomes a button (its accessible name is "Lock apply" or "Unlock apply") that toggles the lock; the detail panel shows the same state as the text "Apply Locked" or "Apply Open".
- **Phoenix.** A link that opens `/monitoring/projects` in a new tab, where the traces of every run live. The link is not filtered by session; search by session id in Phoenix. See [Monitoring with Phoenix](monitoring.md).

The detail panel shows everything the owner sees plus the conversation **History** (every user request and answer in the session) and, for editors and admins, the "Apply Locked" or "Apply Open" toggle. "Reload Session" is available here too and opens the session in the wizard.

### Users tab (panel `admin` only)

The table lists users (display name with the e-mail underneath, or the e-mail alone when there is no display name), **Operation role** (`Developer`, `DevOps`), **Panel role** (`No access`, `Viewer`, `Editor`, `Admin`), and creation time, newest first. The page-size selector offers 10, 15, 25, and 50 rows (15 by default, remembered in the browser); the API itself accepts any `page_size` from 1 to 100. A search box matches e-mail or display name.

Changing a drop-down saves immediately by sending the user's complete role state to `PUT /admin/users/{user_id}/roles`. Rules enforced by the API:

- `operation_role` is required; every user always has one.
- `panel_role` may be `viewer`, `editor`, `admin`, or omitted; omitting it removes panel access.
- A panel admin cannot set their own panel role to anything but `admin` (`409 A panel admin cannot remove their own admin role.`). The UI disables that drop-down for your own row. An admin may still change their own operation role.
- Unknown user id: `404`.

## Permission matrix

The matrix reflects what the backend enforces. The UI hides or disables controls accordingly.

| Capability | No panel role | `viewer` | `editor` | `admin` |
|---|---|---|---|---|
| Sign in, run sessions allowed by the operation role | yes | yes | yes | yes |
| View own sessions, details, artifacts, lock state; reopen own sessions | yes | yes | yes | yes |
| Open the admin panel | no | yes | yes | yes |
| List sessions across all users, paginated | no | yes | yes | yes |
| Filter by type and status; search by user e-mail, project, query text, or session id | no | yes | yes | yes |
| Open any user's session detail, including conversation history | no | yes | yes | yes |
| View any session's statuses, reports, plans, code-change artifacts, repository link, pull-request links, lock state | no | yes | yes | yes |
| Open Phoenix from the admin sessions tab | no | yes | yes | yes |
| Receive support requests sent from the web application's header (see below) | no | no | yes | yes |
| Lock or unlock the apply of a session | no | no | yes | yes |
| List and search users | no | no | no | yes |
| Assign operation roles | no | no | no | yes |
| Assign or remove panel roles | no | no | no | yes |
| Remove one's own panel `admin` role | no | no | no | **no** (`409`) |
| Act on another user's session (continue, create or merge PR, apply) | no | no | no | no (owner only) |
| Delete a user or a session | not implemented | not implemented | not implemented | not implemented |

Backend routes behind the matrix (all under `/api/v1`):

| Route | Who |
|---|---|
| `GET /sessions`, `GET /sessions/{session_id}` | Any signed-in user; the list is always scoped to the caller, the detail is owner or any panel role |
| `GET /events/subscribe/{session_id}` | Owner or any panel role |
| `GET /admin/sessions`, `GET /admin/sessions/{session_id}` | panel `viewer` or higher |
| `PATCH /admin/sessions/{session_id}/toggle_lock` | panel `editor` or higher |
| `GET /admin/users`, `PUT /admin/users/{user_id}/roles` | panel `admin` |

Missing or invalid credentials yield `401`; an insufficient panel role yields `403 Requires admin-panel role '<role>' or higher`.

## Support requests

The chat-bubble icon in the application header ("Support") and the "Contact team" / "Request review" buttons in the results views open a form that calls `POST /api/v1/notifications`. Any signed-in user can send one. The core forwards it to the notifications sidecar with an audience made of the caller's e-mail plus every user holding a panel role of `editor` or higher; the bundled sidecar posts it to Slack. When `services.notifications.enabled` is `false` the route answers `503 Notifications are disabled.`; when delivery fails it answers `502 Notification was not delivered.`

## Who gets which roles

**With authentication disabled** (blank `oidc.issuer_url`), every request runs as the built-in local development identity, which holds `devops` and panel `admin`. Anyone who can reach the stack has full access to both views; use this only on an isolated workstation.

**With OIDC enabled**, a new user is created on first login with operation role `developer` and no panel role: they can generate infrastructure and see their own sessions, nothing more. The first administrator comes from one of two places:

- `admin.default_root_email` in `config.yaml`: the user whose token carries that e-mail with `email_verified: true` is elevated to `devops` and panel `admin` at login. The elevation is one-way and is re-checked on every request. Only identity providers that emit `email_verified` in access tokens (Keycloak, for instance) can use this path.
- A one-off database grant for providers that never emit `email_verified` (Entra ID, Auth0, Okta). See [Bootstrap admin](oidc-setup.md#bootstrap-admin).

After that, the administrator manages everyone else from the Users tab. The bootstrap elevation is re-applied on every request of the root user, so demoting that user from the Users tab is undone the next time they call the API; clear `admin.default_root_email` and rebuild first if you really need to demote them.

With authentication disabled there is no identity provider to sign out of, but the "Log out" action still works locally: it clears the user in the browser and shows the login screen. Pressing *Sign In* re-fetches `GET /api/v1/users/me` and puts you straight back in as the dev identity.

Do not confuse this with the authorization sidecar. Its `NEBULA_AUTHZ_ROOT_ADMIN_EMAIL` grants the sidecar's *own* `admin` role inside the sidecar's JSON role store. The core never reads that store; the sidecar is consulted only for cloud-project authorization checks when `services.authz.enabled` is `true`.

## Session locks

A lock (`is_blocked` on the session) prevents two actions by the owner: apply (`409 Session ... is blocked; apply is not allowed.`) and pull-request merge (`409 Session ... is blocked; PR merge is not allowed.`). It does not prevent reading the session, continuing the conversation, or creating a pull request. Owners see the lock state in their sessions view and in the results view of the wizard but cannot change it.

Locks are set in two ways:

- **Automatically** at the end of a generate round when the compliance check fails or, with `orchestration.block_on_high_impact`, when the report's impact banner is `high`. A later generate round that passes cleanly clears the lock again. Notifications are sent when the notifications sidecar is enabled.
- **Manually** by a panel editor or admin, in either direction, from the admin panel.

## Walkthroughs

### Checking on your own session

1. Open the footer **Sessions** panel or your user page and choose "View all sessions".
2. Filter by status or search by project to find the session. The Apply column tells you whether apply and merge are currently blocked.
3. Open the row to read the report, the plan, and the changed files.
4. Press **Reload Session** to return to the wizard for that session and continue: create the pull request, merge it, apply, or send a follow-up request.

### Reviewing a failed session (panel `viewer` or higher)

1. Open the admin panel, Sessions tab. Filter **status** to `failed`, or search by the user's e-mail.
2. Open the session. Read the failure message and the timeline; the last status message usually names the failing step (validation, plan, apply).
3. Expand the round's artifacts. A `Terraform Plan` or drift report shows engine output; a `Report` shows what the model concluded. Code-change artifacts show exactly what was written.
4. Open **History** to read the conversation, including declined or reformulated requests.
5. Use the **Phoenix** link to inspect the traces for the session id when you need the prompts, tool calls, or model outputs behind a step.
6. Failed sessions cannot be resumed; ask the owner to start a new session with the corrected request.

### Locking or unlocking the apply of a session (panel `editor` or higher)

Use a lock when a report looks risky but the automatic lock did not trigger, or when a change must wait for an out-of-band approval. Use an unlock after the automatic lock (failed compliance or `high` impact) has been reviewed and accepted.

1. Admin panel, Sessions tab. Find the session (search by user e-mail, project, or session id).
2. Press **Lock apply** or **Unlock apply** in the Apply column, or open the detail panel and toggle **Apply Open** / **Apply Locked**.
3. While locked, the owner receives `409` on apply and on pull-request merge. Creating the pull request is still possible so that reviewers can read the diff.
4. After unlocking, the owner can merge and apply from the results view of their session.

### Promoting a user to DevOps (panel `admin`)

1. Admin panel, Users tab. Search by e-mail or name.
2. Change **Operation role** from `Developer` to `DevOps`. The change is saved immediately.
3. The user sees the drift modes on their next page load; roles are read from `/api/v1/users/me` when the application starts.

### Granting viewer, editor, or admin panel access (panel `admin`)

1. Admin panel, Users tab. Find the user.
2. Set **Panel role** to `Viewer` (read all sessions), `Editor` (also lock and unlock), or `Admin` (also manage users). Choose `No access` to remove panel access.
3. The new panel user finds the **Admin Panel** button on their user page after reloading.

Remember that granting a panel role does not change what the user can do to infrastructure; adjust the operation role separately if needed.

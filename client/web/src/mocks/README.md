<!--
SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)

SPDX-License-Identifier: Apache-2.0
-->

# Mock API

[MSW](https://mswjs.io/) v2 mocks of the browser-facing `/api/v1` surface. The same handler set serves two consumers:

| Consumer | Entry | Store | Unhandled request |
|---|---|---|---|
| Vitest | `server.ts` (via `src/test/setup.ts`) | **empty** — each test adds what it needs | fails the test |
| Dev browser | `browser.ts` (via `main.tsx`, `VITE_MOCK_API=true`) | seeded with 19 sessions | warns |

```bash
npm run dev:mock     # Vite on :5173, mocks on, no backend needed
npm run dev          # mocks off — needs the docker compose stack
```

Mocks are enabled by `VITE_MOCK_API=true`; `main.tsx` awaits `startMockWorker()` **before** `loadAuthConfig()`, otherwise the bootstrap fetch escapes the interceptor.

## What these mocks mirror

The browser-facing API has **no OpenAPI spec** — `contracts/openapi/` covers the internal sidecars (`authz`, `iac`, `mapping`, `notifications`), which the browser never calls. The truth sources are therefore:

- `core/src/api/v1/*.py` + `core/src/api/dtos.py` + `core/src/domains/dto.py` — the routes and payloads
- `src/types/api.ts` — the client's hand-written mirror of them
- `src/services/core/*.ts` — the exact paths, methods and status codes the client issues

Where a contract *is* the source, core reshapes it before the browser sees it — e.g. authz's `{authorized, portal_url, reason}` (`contracts/openapi/authz.v1.yaml`) is served to the client as `{result, message, portalUrl}`. The mock reproduces the client-side shape.

## Directory structure

```
src/mocks/
  browser.ts        Service Worker entry (dev) — seeds, then starts
  server.ts         Node entry (tests) — starts empty
  seed.ts           Installs the seed sessions; browser only
  state.ts          In-memory session store + makeStatus/makeRound/makeSessionDetail
  runtime.ts        Pending-run registry: POST schedules, SSE executes
  triggers.ts       Magic input values for deterministic failures
  mocks.test.ts     Drives the mocks through the real service layer
  data/
    content.ts      18 scenario bundles: code, plans, reports, history
    artifacts.ts    Presigned-URL registry backing /mock-artifacts
    sessions.ts     Session aggregate builder + the 17 seeds + users
    sse.ts          Progress-event sequences
    index.ts        Re-exports
  handlers/
    index.ts        Aggregates the modules below
    auth.ts         /auth/config, /auth/authorize
    users.ts        /users/me
    sessions.ts     /sessions, /sessions/:id  (+ shared list helpers)
    admin.ts        /admin/sessions*, /admin/users*
    iac_actions.ts  /iac/{generate,drift,apply}
    events.ts       /events/subscribe/:id  (SSE)
    repository.ts   /repository/pr, /pr/merge, /parse
    notifications.ts /notifications  (support requests)
    artifacts.ts    /mock-artifacts/*  (blob storage stand-in)
```

## Endpoints

| Method | Path | Status | Response |
|---|---|---|---|
| GET | `/api/v1/auth/config` | 200 | `AuthConfigResponse` — blank `issuer_url` (auth disabled) |
| POST | `/api/v1/auth/authorize` | 200 | `AuthorizeResponse` `{result, message, portalUrl?}` |
| GET | `/api/v1/users/me` | 200 | `UserMeResponse` |
| GET | `/api/v1/sessions` | 200 | `PaginatedResponse<SessionSummary>`, self-scoped |
| GET | `/api/v1/sessions/:id` | 200 / 404 | `SessionDetail`; `history` only with `?include_history=true` |
| GET | `/api/v1/admin/sessions` | 200 | Same DTO, all users, `+user_email` filter |
| GET | `/api/v1/admin/sessions/:id` | 200 / 404 | `SessionDetail` |
| PATCH | `/api/v1/admin/sessions/:id/toggle_lock` | 200 | `{locked}` in → `SessionLockResponse {uuid, is_blocked}` out |
| GET | `/api/v1/admin/users` | 200 | `PaginatedResponse<AdminUserEntry>` (5 users) |
| PUT | `/api/v1/admin/users/:id/roles` | 200 | `AdminUserEntry`; full-state assignment, persists in memory |
| POST | `/api/v1/iac/generate` | **202** / 422 | `{session_id}` |
| POST | `/api/v1/iac/drift` | **202** / 422 | `{session_id}`; `is_partial` selects the partial-drift scenario |
| POST | `/api/v1/iac/apply` | **202** / 403 / 404 | `{session_id}`; `session_id` only — no query, no targets |
| GET | `/api/v1/events/subscribe/:id` | 200 / 404 | `text/event-stream` |
| PUT | `/api/v1/repository/pr` | **201** | `PullRequestDTO {id, url, status}` |
| PUT | `/api/v1/repository/pr/merge` | **204** | no body |
| POST | `/api/v1/repository/parse` | 200 / 404 / 500 | `{roots: string[]}` |
| POST | `/api/v1/notifications` | **202** / 502 | `NotificationAccepted {delivery_id}`; the "Contact team" support request |
| GET | `/mock-artifacts/*` | 200 / 403 | raw artifact content |

Paginated list responses are `{items, total, page, page_size, total_pages}`; `page_size` defaults to 20 and `total_pages` is 0 when empty, as the backend computes it.

## The async session model

Nothing about a run is synchronous, and the mocks preserve that:

1. `POST /iac/*` persists a session (first call, needs `repo_uri` + `terraform_providers`) or appends a round (iteration, needs `session_id`), registers a **pending run** in `runtime.ts`, and answers `202 {session_id}`. **No status is written yet** — which is precisely why the client has `waitForNewRound`.
2. `GET /events/subscribe/:id` executes the pending run: `: keepalive`, then `data: {"status_msg": …, "detail": {"message": …}}` frames, mirroring each into the store so a concurrent `GET /sessions/:id` agrees with the stream.
3. During the `REPORT` frame the round's artifacts are uploaded to the artifact store and attached as `ReportRef` / `TerraformPlanRef` / `CodeChangeRef`.
4. The server closes the stream after `COMPLETED`, `UNCOMPLETED` or `FAILED`.
5. The client re-reads `GET /sessions/:id`, then GETs each presigned URL (`resolveSessionOutcome`).

Two fidelity details worth knowing, both reproduced deliberately:

- **Duplicate frames are normal.** The backend polls the session's *last* status every 5s rather than pushing transitions, so the same frame can arrive repeatedly. `withPollDuplicates` re-emits ~35% of frames.
- **`UNCOMPLETED` is a resting terminal state.** A filter-rejected round produces no artifacts and no `COMPLETED` ever follows.

`sseOptions` (in `data/sse.ts`) turns the random retries/duplicates off and speeds the sequence up — see `mocks.test.ts`.

## Artifacts

Round output is never inlined. Each file, plan and report is registered in `data/artifacts.ts` and exposed as a presigned URL under `/mock-artifacts/<session>/round-<n>/…?se=…&sig=…`, fetched with a bare `fetch` (no auth headers) exactly as `fetchArtifactContent` does against real blob storage. An unknown key answers **403**, which is what an expired SAS token looks like and what triggers the client's session-refetch retry.

Code is reassembled by the client into the LLM's tagged form:

```
<Terraform_Plan>…</Terraform_Plan>
<main.tf>…</main.tf>
```

Tag names match `[\w.-]+`; `Terraform_Plan` feeds the Plan tab, every other tag becomes a file tab.

## Scenarios

`data/content.ts` holds 19 bundles selected by `MockContentType`:

| Family | Types |
|---|---|
| generate | `generate`, `generate_partial`, `generate_multi`, `destructive`, `remove_resource` |
| drift | `drift`, `drift_failed`, `drift_partial` |
| partial drift | `partial_drift`, `partial_drift_failed`, `partial_drift_partial` |
| apply | `apply`, `apply_create`, `apply_create_update`, `apply_destroy`, `apply_mixed` |
| import | `import`, `import_failed`, `import_partial` |

`getScenario(type)` splits a bundle into `{files, plan, targets, report, history, reportType}` — the per-artifact form the session builder needs. Reports follow `core/src/domains/dto.py`: `potential_impact {banner, summary, bullet_points}` and `estimated_costs {currency, total_fixed_monthly_cost, introduction_paragraph, breakdown[{resource_type, pricing_model, fixed_monthly_cost, notes}]}` with `pricing_model ∈ {fixed, usage_based, free}`.

`destructive` is a *migration* (things are created as well as destroyed); `remove_resource` is a **pure removal** — a destroy-only plan with nothing created or replaced, which is the case the apply lock exists for.

Prefix a query with `mock:<type>` (e.g. `mock:destructive add a bucket`) to force a specific bundle in the browser.

An apply round has no query of its own, so its log is inferred from the session's original request: a removal (`remove | delete | destroy | decommission | tear down`) replays as `apply_destroy`, anything else as `apply_create`.

## Seed sessions (browser only)

19 sessions across 3 users, covering every state the UI renders — completed, failed, in-flight, filter-rejected, multi-round, and generate→apply chains:

| # | Operation | Provider | Status | Notes |
|---|---|---|---|---|
| 1 | generate | azure | completed | baseline storage account |
| 2 | drift | azure | completed | networking remediation |
| 3 | import | azure | completed | locked (`is_blocked`) |
| 4 | generate | azure | completed | **2 rounds** + PR; merges code changes across rounds |
| 5 | generate | gcp | generating | in flight |
| 6 | generate | azure | completed | **generate + apply round**, PR #247 |
| 7 | generate | azure | failed | provider version conflict |
| 8 | generate | azure | completed | partial generation |
| 9 | drift | azure | failed | state lock |
| 10 | drift | azure | completed | partial remediation |
| 11 | drift | azure | completed | targeted (partial) drift |
| 12 | drift | azure | failed | registry unreachable |
| 13 | drift | azure | completed | targeted, partial result |
| 14 | import | azure | failed | insufficient permissions, locked |
| 15 | import | azure | completed | partial import |
| 16 | generate | azure | **uncompleted** | round 2 rejected; round 1's artifacts stay visible |
| 17 | generate | azure | completed | destructive plan → high-impact banner |
| 18 | generate | azure | completed | destroy-only removal, **locked** — the unblock-then-apply walkthrough |

### Walking the blocked-apply flow (session 18)

Session 18 belongs to `mock-user@example.com`, so it is listed under both `/user/sessions` and `/admin/sessions`. Its single round removes three production resources and nothing else, and it ships `is_blocked: true`:

1. Open the session's results. `POST /iac/apply` answers **403** (`checkApplyAllowed` → `false`), and no round is created.
2. Unblock it: the lock toggle on the session card, or `PATCH /api/v1/admin/sessions/{id}/toggle_lock` with `{"locked": false}` → `{uuid, is_blocked: false}`.
3. Apply again. It now returns **202**, streams `STARTED → APPLY → REPORT → COMPLETED`, and the new round resolves to the `apply-results` view carrying the `apply_destroy` log.

`mocks.test.ts` → `describe("blocked apply")` drives exactly this sequence.

Sessions owned by `alice@example.com` / `bob@example.com` appear only under `/admin/sessions`; `/sessions` self-scopes to `mock-user@example.com`.

## Reproduction fixtures

`data/repro.ts` holds five deliberately broken sessions for the session-recovery review findings. They are seeded by `seedReproData()` — called from `browser.ts` only, **not** from `seedMockData()`, so `mocks.test.ts` still counts the 19 seeds and every other test keeps declaring its own world. A test that wants one calls `buildReproSessions()` itself.

Each carries its finding number in the UUID (`…-90NN-…b00N`), the branch, the `nebula-repro` repo and the query text, so the table row and the URL both name the fixture causing the behaviour.

| Finding | Session (deep link `/home/results/<uuid>`) | Fixture shape | What the UI does today |
|---|---|---|---|
| 1 | `…-9001-…b001` | 2 rounds; round 2 INSERTed with **zero statuses**, session's last status is round 1's `completed` | Row reads **completed**; opening it flaps planning ⇄ results and fires a false "Pipeline completed" notification |
| 2 | `…-9002-…b002` | 1 round resting on `generating`, `in_flight: true`, 26h old | Spinner that never resolves and never errors |
| 2b | `…-9003-…b003` | Same ladder, `in_flight: false` | Identical spinner — the control showing an `in_flight` gate can't tell 2 from 2b |
| 3 | `…-9004-…b004` → `…-9005-…b005` | in-progress session, then a completed one | Nothing yet: needs a `results/:A → results/:B` transition without a remount, which no affordance produces (a URL edit reloads and remounts) |

Finding 1 works because of a fidelity detail the mocks already had: `handlers/events.ts` answers a no-pending-run stream from `detail.statuses` — the *session's* last status, exactly as `core/src/api/v1/events.py` does via `DatabaseService.get_last_status(session_id)` — while `resolveSessionOutcome` reads the *last round's* last status. The two agree except in the window finding 1 models, and `stoppedAt: 0` holds that window open indefinitely instead of for one DB round trip.

Finding 2's endless spinner comes from the client, not the mock: a stream that closes without a terminal frame raises `SSE stream closed` (`services/core/events.ts`), retries 3×, then `onerror` → `checkSessionStatus` → `in_progress` → resubscribe. Every reconnect delivers a frame, so the 90s inactivity watchdog never trips.

Two `SessionSpec` knobs exist for these: `stoppedAt: 0` (empty status sequence) and `in_flight` (override the `!terminal` derivation, which cannot express a stuck lock over a live status).

Delete `data/repro.ts`, its `data/index.ts` re-export, the `seedReproData()` call and the `describe("reproduction fixtures")` block together once the findings are fixed.

## Error triggers

Case-insensitive; repository and cloud values match exactly, query values match by prefix (so `error:not-iac create a vm` works). Defined in `triggers.ts`.

| Input field | Value | Result |
|---|---|---|
| Repository URL | `error://inaccessible` | `POST /repository/parse` → 404; IaC POST → 400 |
| Repository URL | `error://scan-failed` | `POST /repository/parse` → 500 |
| Repository URL | `error://no-iac` | `POST /repository/parse` → `{roots: []}` |
| Cloud scope | `error-unauthorized` | `POST /auth/authorize` → `{result: false, portalUrl}` |
| Query | `error:not-iac` | 202, then SSE ends `UNCOMPLETED` with a rationale |
| Query | `error:generation-failed` | 202, then SSE ends `FAILED` |
| Query | `error:drift-failed` | same, on `/iac/drift` |
| Query | `error:apply-failed` | same, on `/iac/apply` |
| Query | `error:pr-create-failed` | `PUT /repository/pr` → 502 |
| Query | `error:pr-merge-failed` | `PUT /repository/pr/merge` → 409 |
| Notification subject/body | `error:notify-failed` | `POST /notifications` → 502 |

Note that a rejected query is **not** a 4xx: the backend accepts it, runs the filter, and reports the rejection over SSE.

## Using the mocks in tests

The store starts empty and `onUnhandledRequest: "error"` is on, so a test declares exactly the world it needs:

```typescript
import { mockState, makeSessionDetail, makeRound, makeStatus } from "@/mocks/state";

mockState.addSession(
  makeSessionDetail({
    uuid: "s1",
    rounds: [makeRound({ statuses: [makeStatus("started"), makeStatus("completed")] })],
  }),
);
```

Override a single endpoint with `server.use(...)`; seed the full browser fixture set with `seedMockData()` from `seed.ts`.

## Adding to the mocks

**A new endpoint** — add it to the handler module matching its `services/core/` counterpart (create one and register it in `handlers/index.ts` if none fits). Mirror the real status code; `HttpResponse.json(body, {status})`, or `new HttpResponse(null, {status: 204})` for empty bodies.

**A new scenario** — in `data/content.ts`: add the value to `MockContentType`, a tagged bundle to `RESPONSE_MAP`, an entry to `PLAN_TEXT` and `HISTORY`, a report factory, and a case in `createMockTerraformReport`. `getScenario` and `deriveTargets` then work with no further changes.

**A new seed session** — append a `SessionSpec` to `SESSION_SPECS` in `data/sessions.ts`. Round outcomes are `completed | failed | uncompleted | running`; only `completed` rounds get artifacts, matching the backend.

## Troubleshooting

**Empty code/plan tabs** — the bundle needs `<filename.tf>` wrapping; raw HCL renders nothing.

**403 from `/mock-artifacts/…`** — the key isn't registered. Artifacts are created per session build, so a stale URL from a previous page load (or a `mockState.clear()`) will miss.

**MSW warns about an unhandled request** — an `/api/` path with no handler. With no backend behind Vite it will simply fail to connect, so add the handler.

**Mocks not intercepting** — `npm run dev` does not enable them; use `npm run dev:mock`. In tests, check `src/test/setup.ts` is in the Vitest `setupFiles`.

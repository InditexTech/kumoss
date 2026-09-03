<!--
SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)

SPDX-License-Identifier: Apache-2.0
-->
# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

This directory (`client/web`) is the React frontend ("Nebula Web Client") of the Nebula monorepo — an LLM-powered Infrastructure-as-Code platform. The client kicks off async IaC operations against the core FastAPI backend and streams session progress over SSE.

## Commands

All run from `client/web`. Node ≥ 20 is required for the test toolchain (Vitest 4).

| Action | Command |
|---|---|
| Dev server (port 5173) | `npm run dev` |
| Lint | `npm run lint` |
| Tests (watch) | `npm run test` |
| Tests (single run) | `npm run test:ci` |
| Single test file | `npx vitest run src/services/api.test.ts` |
| Single test by name | `npx vitest run -t "test name"` |
| Coverage | `npm run test:coverage` (thresholds enforced: 30% statements/lines, 25% branches/functions) |
| Production build | `npm run build` |

## Running against the backend

- All API calls use same-origin relative paths (`/api/v1/...`). There is **no Vite dev proxy** in `vite.config.js`, so `npm run dev` alone has no backend.
- The full stack runs via `docker compose up --build` from the repo root, browsed at `http://localhost`. The `proxy` (nginx) compose service serves a **static production build** of this app baked into the `nebula-nginx` image (`nginx/Dockerfile` runs `npm ci && npm run build`) and routes `/api` → `core:8000`, with a dedicated buffering-off location for the SSE endpoint.
- To see frontend changes in the stack, rebuild the proxy: `docker compose build proxy && docker compose up -d proxy` (from repo root). `docker compose watch` hot-reloads only the `core` backend, not this client.
- `npm run dev:mock` sets `VITE_MOCK_API=true` but is currently inert: the MSW browser-worker bootstrap in `src/main.tsx` is commented out and `src/mocks/browser.ts` does not exist. MSW is only active in tests (node server).

## Architecture

**Layering (top to bottom):** components/pages → hooks → `services/workflows` → `services/core` → `services/api.ts`.

- `services/api.ts` — `apiFetch<T>`: JSON fetch wrapper with `credentials: "include"` and a 60s default timeout (AbortController). Throws `ApiError` carrying HTTP status/body and a humanized `detail` (unwraps JSON-encoded upstream errors, e.g. GitHub's, that the backend relays inside `detail`). `getApiErrorMessage` produces display text.
- `services/core/` — one module per backend resource: `iac_actions` (generate/drift/apply — all return a `session_id`), `iac_code` (PR create/merge, repo parse), `sessions` + `sessionsCache`, `events` (SSE), `authorization`, `admin`. Public surface is re-exported from `services/index.ts`.
- `services/workflows/` — multi-step orchestrations consumed by hooks: `terraform_action` picks the IaC endpoint from the current mode and returns the session id; `session_outcome`; `initial_information`.
- `hooks/` — bind workflows/services to component state (`useWizardTerraform`, `use_terraform_actions`, `useSessionLoader`, `useWizardNavigation`, …).
- Contexts: `SessionContext` wraps the whole app in `main.tsx`; `Mode`, `Auth`, `Notification`, `AssistantMsg`, `Shell` live under `src/contexts/`.

**Async session flow:** an IaC action POST returns 202 with a `session_id` → the client subscribes to `/api/v1/events/subscribe/:id` via `subscribeToSession` (`services/core/events.ts`) — a hand-rolled SSE client over `fetch` + `ReadableStream` (not `EventSource`, so custom headers work) with 3 retries and exponential backoff, exposing an EventSource-like `{onmessage, onerror, close}`. `checkSessionStatus` maps a session's `current_status`; `uncompleted` is a resting terminal state (no `completed` ever follows it).

**Modes** (`MODE` in `src/types/ui.ts`, user-facing options in `src/constants/modes.ts`): `GENERATE`, `DRIFT`, `PARTIAL_DRIFT`, and `IMPORT`. Beware: `MODE.IMPORT` triggers the **apply** endpoint (reuses the session's stored plan; takes no query or targets).

**Routing** (`src/router.tsx`): the wizard lives under `/home` with lazy routes — index (wizard) → `planning` → `results/:sessionId` → `apply-results/:sessionId`; plus `/admin/*`, `/user`, `/user/sessions`.

**Types:** `src/types/api.ts` (plus `api_mapper.ts`, `api_notifications.ts`) hand-mirror the core FastAPI contract (`core/src/api/v1/`); there is no codegen for the client-facing API (repo-root `contracts/` covers only the internal microservices).

**Path alias:** `@/` → `src/` (configured in both vite and tsconfig).

## Testing

- Vitest 4 with jsdom and `globals: true` (no need to import `describe`/`it`). Tests live next to sources as `src/**/*.test.{ts,tsx}`.
- `src/test/setup.ts` starts the MSW node server with `onUnhandledRequest: "error"` — any fetch without a handler fails the test. Default handlers in `src/mocks/handlers.ts` (sessions list/detail, backed by `src/mocks/state.ts`); override per-test with `server.use(...)`. Setup also mocks `lottie-react` and stubs `scrollIntoView`.
- Use `renderWithProviders` / `renderHookWithProviders` / `createWrapper` from `src/test/render.tsx` — they wrap MemoryRouter (initial entry `/home`) plus Session/Mode providers, with opt-in Notification and AssistantMsg providers.

## Conventions

- Every file starts with the SPDX header (`SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)` / `SPDX-License-Identifier: Apache-2.0`) — REUSE compliance is enforced in CI and pre-commit; include it in new files.
- The client uses no env vars. Auth/OIDC settings come from the backend: `main.tsx` awaits `loadAuthConfig()` (`GET /api/v1/auth/config`, stored in `src/services/auth.ts`) before rendering; blank `issuer_url` = auth disabled (dev mode).
- Production builds drop `console` and `debugger` statements (esbuild `drop`), so don't rely on console output in prod.
- TypeScript is strict; ESLint uses a flat config — unused vars are warnings, prefix intentionally-unused args with `_`.

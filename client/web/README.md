<!--
SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)

SPDX-License-Identifier: Apache-2.0
-->

# Kumoss Web Client

React frontend for the Kumoss IaC generation platform.

## Quick Start

Prerequisites: Node 24 (as in `nginx/Dockerfile`, which builds this client for the Docker stack).

```bash
cd client/web
npm install
npm run dev
```

The dev server starts on `http://localhost:5173`. API calls use same-origin
`/api/v1/...` paths and are not proxied by Vite — to exercise the app against
the backend, run the Docker stack below and browse `http://localhost`.

## Docker (full stack)

From the repo root:

```bash
docker compose up --build
```

This starts the full stack (core API, microservices, databases, Phoenix
tracer, and the nginx proxy, which serves a production build of this client).
Browse to `http://localhost`.

The client is baked into the `kumoss-nginx` image as a static build. After
changing frontend code, rebuild the proxy to see the changes:

```bash
docker compose build proxy && docker compose up -d proxy
```

`docker compose watch` syncs `core/` into the container; restart the core (`docker compose restart core`) to pick up changes. It does not touch this client at all.

## Commands

| Action | Command |
|--------|---------|
| Dev server | `npm run dev` |
| Lint | `npm run lint` |
| Tests | `npm run test` |
| Tests (CI) | `npm run test:ci` |
| Coverage | `npm run test:coverage` |
| Production build | `npm run build` |
| Preview build | `npm run preview` |

> MSW request mocking is active in tests only (the node server starts in
> `src/test/setup.ts`). There is no browser worker and no mock dev mode.

## Stack

- React 18 + TypeScript 5.7
- Vite 6.4
- MUI 7 (Material UI)
- React Router 7
- `oidc-client-ts` 3.5 + `react-oidc-context` 3.3 (OIDC login; inert in dev mode)
- Vitest + React Testing Library + MSW

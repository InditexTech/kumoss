<!--
SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)

SPDX-License-Identifier: Apache-2.0
-->

# Nebula Web Client

React frontend for the Nebula IaC generation platform.

## Quick Start

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

The client is baked into the `nebula-nginx` image as a static build. After
changing frontend code, rebuild the proxy to see the changes:

```bash
docker compose build proxy && docker compose up -d proxy
```

`docker compose watch` hot-reloads the core backend only, not this client.

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

> `npm run dev:mock` still exists in `package.json` but is currently a no-op:
> the MSW browser-worker bootstrap in `src/main.tsx` is commented out and
> `src/mocks/browser.ts` does not exist. MSW request mocking is active in
> tests only.

## Stack

- React 18 + TypeScript 5.7
- Vite 6.4
- MUI 7 (Material UI)
- React Router 7
- Vitest + React Testing Library + MSW

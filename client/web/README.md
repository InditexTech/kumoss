<!--
SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)

SPDX-License-Identifier: Apache-2.0
-->

# Nebula Web Client

React frontend for the Nebula IaC generation platform.

## Quick Start

```bash
cd clients/web
npm install
npm run dev
```

The dev server starts on `http://localhost:5173`. API calls proxy to
`http://localhost:8000` (start the backend with `docker compose up` from the
repo root).

## Docker (full stack)

From the repo root:

```bash
docker compose up --build
```

This starts the full stack (API, services, database, Phoenix tracer, nginx
proxy, and Vite dev server). Browse to `http://localhost`.

Use `docker compose watch` for hot-reload during development.

## Commands

| Action | Command |
|--------|---------|
| Dev server | `npm run dev` |
| Dev server (mocked API) | `npm run dev:mock` |
| Lint | `npm run lint` |
| Tests | `npm run test` |
| Tests (CI) | `npm run test:ci` |
| Coverage | `npm run test:coverage` |
| Production build | `npm run build` |
| Preview build | `npm run preview` |

## Stack

- React 18 + TypeScript 5.7
- Vite 6.4
- MUI 7 (Material UI)
- React Router 7
- Vitest + React Testing Library + MSW

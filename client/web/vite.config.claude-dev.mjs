// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

// Untracked dev-only config: serve the worktree source live on :5173
// with /api proxied to the compose `core` service (the nginx proxy
// serves a stale baked build; this is the live-iteration path).
import { defineConfig, mergeConfig } from 'vite'
import baseFactory from './vite.config.js'

export default defineConfig((env) =>
  mergeConfig(baseFactory(env), {
    server: {
      host: true,
      port: 5173,
      hmr: { clientPort: 5173 },
      proxy: {
        '/api': { target: 'http://core:8000', changeOrigin: true },
      },
    },
  }),
)

// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'
import { fileURLToPath } from 'url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

// https://vite.dev/config/
export default defineConfig(({ mode }) => ({
  plugins: [react()],
  assetsInclude: ['**/*.lottie'],
  resolve: {
    alias: { '@': path.resolve(__dirname, './src') },
    dedupe: ['react', 'react-dom'],
  },
  optimizeDeps: {
    include: ['monaco-editor', '@monaco-editor/react', '@monaco-editor/loader'],
  },
  ...(mode === 'production' && {
    esbuild: {
      drop: ['console', 'debugger'],
    },
  }),
  server: {
    hmr: {
      clientPort: 80,
    },
    watch: {
      usePolling: true,
    },
  },
}))

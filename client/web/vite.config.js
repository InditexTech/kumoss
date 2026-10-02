// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'
import { fileURLToPath } from 'url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const minify = {
    compress: { dropConsole: true, dropDebugger: true },
    mangle: true,
    codegen: true,
  }
  return {
    plugins: [react()],
    assetsInclude: ['**/*.lottie'],
    resolve: {
      alias: {
        '@': path.resolve(__dirname, './src'),
        'lottie-react': 'lottie-react/build/index.es.js',
      },
      dedupe: ['react', 'react-dom'],
    },
    optimizeDeps: {
      include: ['monaco-editor', '@monaco-editor/react', '@monaco-editor/loader'],
    },
    ...(mode === 'production' && {
      build: { rolldownOptions: { output: { minify } } },
      worker: { rolldownOptions: { output: { minify } } },
    }),
    server: {
      hmr: {
        clientPort: 80,
      },
      watch: {
        usePolling: true,
      },
    },
  }
})

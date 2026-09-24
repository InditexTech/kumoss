// SPDX-FileCopyrightText: 2026 Industria de Diseño Textil S.A. INDITEX
//
// SPDX-License-Identifier: Apache-2.0

// Capture a chrome-free PNG from a delivered Archify viewer.
//
// The viewer HTML is an interactive application: it paints a toolbar
// ("Light / Classic / Present / Export") top right and a zoom bar
// ("PATH MAP LENS ... 100% +") bottom right. Screenshotting the page as-is
// bakes both into the image — which is how the pre-existing
// system-architecture.png came to carry them.
//
// The viewer's own print stylesheet already names those elements, so this
// script hides exactly that set rather than inventing its own list. It drives
// Chrome over the DevTools Protocol using Node's built-in WebSocket (Node 18+),
// so there is no dependency to install.
//
// Usage:
//   node capture-png.mjs <input.html> <output.png> [--width 2048] [--theme light]
//
// Chrome is located via ARCHIFY_CHROME, or CHROME_PATH, or the Playwright
// cache. See README.adoc for the full render recipe.

import { spawn } from 'node:child_process'
import { mkdtemp, writeFile, rm } from 'node:fs/promises'
import { existsSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'

// The same selector set the viewer's own `@media print` block hides. Keeping
// this list identical to the stylesheet's is deliberate: if a future Archify
// version adds a new chrome element, it will be added there, and this comment
// is the pointer telling the next person to re-copy it.
const CHROME_SELECTORS = '.toolbar, .diagram-nav, .focus-chip, .guided-views, .archify-toast, .no-print'

// Not chrome, and deliberately kept out of the list above: the viewer's own
// title, repeated as an <h1> over the diagram. A still is only ever read
// embedded in a page, and every page that embeds one already carries that
// same line as the section heading directly above it, so the capture drops
// it. `partials/interactive-diagram.adoc` hides the same element in the live
// frame, which is what keeps the two forms the same picture. The standalone
// viewer, read on its own with no heading around it, keeps its title.
const TITLE_SELECTOR = '.container > .header'

function findChrome () {
  const candidates = [
    process.env.ARCHIFY_CHROME,
    process.env.CHROME_PATH,
    `${process.env.HOME}/.cache/ms-playwright/chromium-1148/chrome-linux/chrome`,
    '/usr/bin/google-chrome',
    '/usr/bin/chromium',
  ].filter(Boolean)
  const found = candidates.find((p) => existsSync(p))
  if (!found) {
    throw new Error(
      'No Chrome or Chromium found. Set ARCHIFY_CHROME to an executable path.'
    )
  }
  return found
}

function parseArgs (argv) {
  const [input, output, ...rest] = argv
  if (!input || !output) {
    throw new Error('Usage: node capture-png.mjs <input.html> <output.png> [--width N] [--theme light|dark]')
  }
  const opts = { input: resolve(input), output: resolve(output), width: 2048, theme: 'light' }
  for (let i = 0; i < rest.length; i += 2) {
    const key = rest[i]?.replace(/^--/, '')
    const value = rest[i + 1]
    if (key === 'width') opts.width = Number(value)
    else if (key === 'theme') opts.theme = value
    else throw new Error(`Unknown option: ${rest[i]}`)
  }
  if (!Number.isFinite(opts.width) || opts.width <= 0) throw new Error('--width must be a positive number')
  if (!['light', 'dark'].includes(opts.theme)) throw new Error('--theme must be light or dark')
  return opts
}

// Minimal CDP client. Each send() resolves when its matching id comes back;
// events are dispatched to a single optional listener.
function connect (wsUrl) {
  return new Promise((resolvePromise, rejectPromise) => {
    const ws = new WebSocket(wsUrl)
    const pending = new Map()
    let nextId = 1
    let onEvent = null

    ws.onmessage = (raw) => {
      const msg = JSON.parse(raw.data)
      if (msg.id && pending.has(msg.id)) {
        const { ok, fail } = pending.get(msg.id)
        pending.delete(msg.id)
        msg.error ? fail(new Error(`${msg.error.message} (${msg.method ?? 'cdp'})`)) : ok(msg.result)
      } else if (onEvent) {
        onEvent(msg)
      }
    }
    ws.onerror = () => rejectPromise(new Error(`WebSocket error on ${wsUrl}`))
    ws.onopen = () =>
      resolvePromise({
        send (method, params = {}) {
          const id = nextId++
          ws.send(JSON.stringify({ id, method, params }))
          return new Promise((ok, fail) => pending.set(id, { ok, fail }))
        },
        set onEvent (fn) { onEvent = fn },
        close () { ws.close() },
      })
  })
}

const delay = (ms) => new Promise((r) => setTimeout(r, ms))

async function waitForPageTarget (httpBase, fileUrl, timeoutMs = 20000) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    try {
      const targets = await (await fetch(`${httpBase}/json/list`)).json()
      const page = targets.find((t) => t.type === 'page' && t.url.startsWith(fileUrl.slice(0, 40)))
      if (page?.webSocketDebuggerUrl) return page.webSocketDebuggerUrl
    } catch {
      // Chrome's HTTP endpoint is not up yet; keep polling.
    }
    await delay(150)
  }
  throw new Error('Timed out waiting for the Chrome page target')
}

async function main () {
  const opts = parseArgs(process.argv.slice(2))
  if (!existsSync(opts.input)) throw new Error(`Input not found: ${opts.input}`)

  const chrome = findChrome()
  const profile = await mkdtemp(join(tmpdir(), 'archify-capture-'))
  const fileUrl = pathToFileURL(opts.input).href

  const proc = spawn(chrome, [
    '--headless=new',
    '--disable-gpu',
    '--no-sandbox',
    '--hide-scrollbars',
    '--force-device-scale-factor=1',
    `--user-data-dir=${profile}`,
    `--window-size=${opts.width},1320`,
    '--remote-debugging-port=0',
    fileUrl,
  ], { stdio: ['ignore', 'ignore', 'pipe'] })

  let stderr = ''
  const wsEndpoint = await new Promise((ok, fail) => {
    const timer = setTimeout(() => fail(new Error(`Chrome did not report a DevTools port.\n${stderr}`)), 20000)
    proc.stderr.on('data', (chunk) => {
      stderr += chunk
      const match = stderr.match(/DevTools listening on (ws:\/\/[^\s]+)/)
      if (match) { clearTimeout(timer); ok(match[1]) }
    })
    proc.on('exit', (code) => { clearTimeout(timer); fail(new Error(`Chrome exited (${code}).\n${stderr}`)) })
  })

  const httpBase = wsEndpoint.replace(/^ws:\/\//, 'http://').replace(/\/devtools\/browser\/.*$/, '')

  try {
    const pageWs = await waitForPageTarget(httpBase, fileUrl)
    const cdp = await connect(pageWs)
    await cdp.send('Page.enable')
    await cdp.send('Runtime.enable')

    // The viewer lays itself out in JS after load, so give it a beat before
    // measuring anything.
    await delay(2500)

    // Pin the theme and remove the interactive chrome. Done in the page rather
    // than via print-media emulation so the captured palette is the one the
    // reader actually sees, not the print override.
    const { result } = await cdp.send('Runtime.evaluate', {
      returnByValue: true,
      expression: `(() => {
        document.documentElement.setAttribute('data-theme', ${JSON.stringify(opts.theme)});
        const style = document.createElement('style');
        style.textContent = ${JSON.stringify(CHROME_SELECTORS + ', ' + TITLE_SELECTOR)} + '{display:none !important}';
        document.head.appendChild(style);

        // The viewer is built as a full-viewport application, so its body is
        // as tall as the window whatever the diagram needs — measuring
        // scrollHeight bakes a dead band under short diagrams (the sequence
        // ones are roughly a third empty). Measure the real content instead:
        // the lowest bottom edge of any visible element still on the page,
        // after the chrome above has been hidden.
        const root = document.querySelector('.container') || document.body;
        let bottom = 0;
        for (const el of root.querySelectorAll('*')) {
          const style = getComputedStyle(el);
          if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') continue;
          const rect = el.getBoundingClientRect();
          if (rect.width === 0 || rect.height === 0) continue;
          bottom = Math.max(bottom, rect.bottom + window.scrollY);
        }
        const pad = 24;
        return {
          width: Math.ceil(document.body.getBoundingClientRect().width),
          height: Math.ceil(bottom + pad),
        };
      })()`,
    })
    if (result.subtype === 'error') throw new Error(`Page evaluation failed: ${result.description}`)
    const { width, height } = result.value

    // Let the layout settle after the chrome is removed.
    await delay(500)

    const shot = await cdp.send('Page.captureScreenshot', {
      format: 'png',
      captureBeyondViewport: true,
      clip: { x: 0, y: 0, width, height, scale: 1 },
    })
    await writeFile(opts.output, Buffer.from(shot.data, 'base64'))
    cdp.close()
    console.log(`${opts.output}  ${width}x${height}  theme=${opts.theme}`)
  } finally {
    proc.kill()
    // Chrome may still be flushing its profile as we tear down, which makes
    // the rmdir race and throw ENOTEMPTY. A leftover temp directory is not a
    // capture failure, so never let it mask a successful PNG.
    await rm(profile, { recursive: true, force: true }).catch(() => {})
  }
}

main().catch((err) => {
  console.error(err.message)
  process.exit(1)
})

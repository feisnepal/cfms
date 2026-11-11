#!/usr/bin/env node
/**
 * run-e2e-with-cap.mjs — runs `playwright test` under a hard wall-clock cap.
 *
 * Why: the serial Playwright suite can exceed an ops time budget; this wrapper
 * guarantees it is killed once `E2E_TIMEOUT_MS` (default 25 min, under a
 * 30-min allowance) elapses, and exits non-zero so CI / scripts notice.
 *
 * Usage:  node scripts/run-e2e-with-cap.mjs [playwright args...]
 * Env:    E2E_TIMEOUT_MS  total wall-clock cap in ms (default 25 * 60 * 1000)
 *
 * Cross-platform: uses `taskkill /T /F` on win32, process-group SIGTERM on POSIX.
 */
import { spawn } from 'node:child_process'

const DEFAULT_TIMEOUT_MS = 25 * 60 * 1000
const parsed = Number(process.env.E2E_TIMEOUT_MS)
const timeoutMs = Number.isFinite(parsed) && parsed > 0 ? parsed : DEFAULT_TIMEOUT_MS

// The serial, map-heavy suite exhausts Node's default heap (~2GB) — raise it.
// Overridable via E2E_NODE_HEAP_MB; NODE_OPTIONS is passed to the Playwright run.
const heapMb = Number(process.env.E2E_NODE_HEAP_MB) || 4096
const extraNodeOpts = `--max-old-space-size=${heapMb}`
process.env.NODE_OPTIONS = process.env.NODE_OPTIONS
  ? `${process.env.NODE_OPTIONS} ${extraNodeOpts}`
  : extraNodeOpts

const passthrough = process.argv.slice(2)

// Windows: spawning through `cmd.exe` (shell: true) concatenates args without
// escaping, so `|`, `&`, spaces etc. in passthrough args are mis-parsed. Quote
// each arg so cmd passes it through as a single token.
const winQuoted = passthrough.map((a) => `"${a}"`)
const child = spawn(
  'npx',
  ['playwright', 'test', ...(process.platform === 'win32' ? winQuoted : passthrough)],
  {
    stdio: 'inherit',
    shell: process.platform === 'win32',
    detached: process.platform !== 'win32',
  }
)

const killTree = (pid) => {
  if (process.platform === 'win32') {
    spawn('taskkill', ['/pid', String(pid), '/T', '/F'], { stdio: 'ignore' })
  } else {
    try {
      process.kill(-pid, 'SIGTERM')
    } catch {
      try {
        process.kill(pid, 'SIGTERM')
      } catch {
        /* already gone */
      }
    }
  }
}

const timer = setTimeout(() => {
  console.error(
    `\n[run-e2e-with-cap] HARD CAP of ${timeoutMs}ms exceeded — killing Playwright tree.`
  )
  killTree(child.pid)
}, timeoutMs)
timer.unref?.()

child.on('close', (code) => {
  clearTimeout(timer)
  process.exitCode = code ?? 1
})
child.on('error', (err) => {
  console.error('[run-e2e-with-cap] failed to spawn Playwright:', err)
  process.exit(1)
})

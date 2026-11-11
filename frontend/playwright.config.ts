import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  // Serial: the login endpoint sits behind two Starlette BaseHTTPMiddleware
  // layers (add_security_headers, _deprecation_header) which hit a known
  // concurrent-EndOfStream race — under 6 parallel logins the response is lost
  // and a request hangs. One worker (the CI setting) is deterministic.
  workers: 1,
  reporter: 'html',
  use: {
    baseURL: 'http://localhost:3001',
    trace: 'on-first-retry',
    actionTimeout: 30000,
    navigationTimeout: 60000,
    storageState: './e2e/helpers/storageState.json',
  },
  projects: [
    {
      name: 'chromium',
      // 1440x900: at shorter windows (the Desktop Chrome default is 1280x720) the Layers list and the status bar can cover the
      // Imported Layers panel's "Add layer" button.
      use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } },
    },
  ],
  webServer: {
    command: 'npm run dev',
    port: 3001,
    reuseExistingServer: !process.env.CI,
    timeout: 120000,
  },
})

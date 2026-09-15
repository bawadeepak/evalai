import { defineConfig, devices } from '@playwright/test'

// The e2e server creates an isolated temporary data directory, seeds and runs
// the labelled demo, starts a worker and serves the built UI on 8320.
export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 90_000,
  expect: { timeout: 15_000 },
  reporter: [['list']],
  outputDir: './test-results',
  use: {
    baseURL: 'http://127.0.0.1:8320',
    trace: 'retain-on-failure',
    acceptDownloads: true,
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: {
    command: 'uv run --frozen python -m eval_triage.testing.e2e_server',
    cwd: '..',
    url: 'http://127.0.0.1:8320/api/v1/health',
    timeout: 300_000,
    reuseExistingServer: false,
    stdout: 'pipe',
    stderr: 'pipe',
  },
})

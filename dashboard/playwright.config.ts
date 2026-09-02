import { defineConfig, devices } from "@playwright/test";

/**
 * End-to-end tests run against fixture mode: the API is started with a scratch
 * database seeded with clearly labelled synthetic data, so the suite needs no
 * Garmin account and touches no real health data.
 *
 * `scripts/e2e-server.sh` prepares that database and starts both processes.
 */
const WEB_PORT = Number(process.env.PACEBOARD_E2E_WEB_PORT ?? 3100);

export default defineConfig({
  testDir: "./e2e",
  timeout: 45_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : [["list"]],
  use: {
    baseURL: `http://127.0.0.1:${WEB_PORT}`,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: "bash ../scripts/e2e-server.sh",
    url: `http://127.0.0.1:${WEB_PORT}`,
    reuseExistingServer: !process.env.CI,
    timeout: 180_000,
    stdout: "pipe",
    stderr: "pipe",
  },
});

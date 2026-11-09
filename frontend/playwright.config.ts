import { defineConfig, devices } from '@playwright/test';

const PORT = 4174;
const BASE_URL = `http://127.0.0.1:${PORT}`;

/**
 * E2E tests run against the Vite dev server with the Django API replaced by scripted responses
 * (see e2e/fixtures/tripPlan.ts), so they need no backend, no network and no API keys.
 */
export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  retries: 0,
  reporter: [['list']],
  use: {
    baseURL: BASE_URL,
    locale: 'en-US',
    timezoneId: 'America/Chicago',
    trace: 'retain-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } },
    },
  ],
  webServer: {
    command: `npm run dev -- --host 127.0.0.1 --port ${PORT} --strictPort`,
    url: BASE_URL,
    reuseExistingServer: true,
    timeout: 60_000,
  },
});

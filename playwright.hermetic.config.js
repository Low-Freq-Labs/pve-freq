const { defineConfig, devices } = require('@playwright/test');

const port = Number(process.env.PVE_FREQ_HERMETIC_PORT || '8877');
const python = process.env.PVE_FREQ_PYTHON || 'python3';
const baseURL = `http://127.0.0.1:${port}`;

module.exports = defineConfig({
  testDir: './tests/e2e',
  timeout: 30_000,
  expect: { timeout: 8_000 },
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: [['line']],
  webServer: {
    command: `${python} -m tests.support.hermetic_dashboard --port ${port}`,
    url: `${baseURL}/healthz`,
    reuseExistingServer: false,
    timeout: 30_000
  },
  use: {
    baseURL,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'off',
    viewport: { width: 1440, height: 1000 }
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] }
    }
  ]
});

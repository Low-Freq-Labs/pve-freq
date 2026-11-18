const { defineConfig, devices } = require('@playwright/test');

const baseURL = process.env.PVE_FREQ_BASE_URL || 'https://10.25.255.50:8888';
const chromiumExecutablePath = process.env.PVE_FREQ_CHROMIUM_EXECUTABLE || '';

module.exports = defineConfig({
  testDir: './tests/e2e',
  testMatch: 'live-safe.spec.js',
  grep: /\bL0[1-4] /,
  globalSetup: require.resolve('./tests/e2e/support/terminal-global-setup.js'),
  metadata: { terminalMode: 'live' },
  timeout: 6 * 60 * 1000,
  expect: { timeout: 45_000 },
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: 0,
  reporter: [['line']],
  use: {
    baseURL,
    ignoreHTTPSErrors: true,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'off',
    viewport: { width: 1440, height: 1000 }
  },
  projects: [{
    name: 'chromium',
    use: {
      ...devices['Desktop Chrome'],
      ...(chromiumExecutablePath ? { launchOptions: { executablePath: chromiumExecutablePath } } : {})
    }
  }]
});

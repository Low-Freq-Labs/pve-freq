const { defineConfig, devices } = require('@playwright/test');

const chromiumExecutablePath = process.env.PVE_FREQ_CHROMIUM_EXECUTABLE || '';
const outputDir = process.env.PVE_FREQ_F4_ARTIFACT_DIR;
if (!outputDir) throw new Error('PVE_FREQ_F4_ARTIFACT_DIR is required');

module.exports = defineConfig({
  testDir: './tests/e2e',
  timeout: 45_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  forbidOnly: true,
  retries: 0,
  outputDir,
  reporter: [['junit', { outputFile: process.env.PLAYWRIGHT_JUNIT_OUTPUT_NAME }]],
  use: {
    ignoreHTTPSErrors: true,
    trace: 'off',
    screenshot: 'off',
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

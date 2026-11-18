const { defineConfig, devices } = require('@playwright/test');
const mode = process.env.PVE_FREQ_UI_MODE;
const origin = process.env.PVE_FREQ_UI_ORIGIN;
if (!['local', 'live'].includes(mode) || !origin) throw new Error('Run through npm run ui:check');
module.exports = defineConfig({
  testDir: './tests/ui', testMatch: 'inspection.spec.js',
  timeout: 90_000, expect: { timeout: 10_000 }, fullyParallel: false, retries: 0,
  ...(mode === 'local' ? { webServer: {
    command: `${process.env.PVE_FREQ_PYTHON} -m tests.support.hermetic_dashboard --tls --port ${process.env.PVE_FREQ_HERMETIC_PORT}`,
    url: `${origin}/healthz`, ignoreHTTPSErrors: true, reuseExistingServer: false, timeout: 30_000
  } } : {}),
  use: {
    baseURL: origin, ...devices['Desktop Chrome'], viewport: { width: 1440, height: 1000 },
    ignoreHTTPSErrors: mode === 'local' || process.env.PVE_FREQ_UI_INSECURE_TLS === '1',
    serviceWorkers: 'block', acceptDownloads: false,
    trace: 'off', screenshot: 'off', video: 'off'
  },
  projects: [{ name: 'chromium' }]
});

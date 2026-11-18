// Explicitly synthetic consumer ports only. No server or implicit live target.
const { defineConfig } = require('@playwright/test');
module.exports = defineConfig({
  testDir: './tests/e2e', testMatch: ['cockpit-view.spec.js', 'cockpit-workspaces.spec.js'],
  workers: 1, fullyParallel: false, retries: 0, forbidOnly: true,
  timeout: 45_000, expect: { timeout: 5_000 },
  outputDir: './test-results/cockpit', reporter: [['line']],
  use: { browserName: 'chromium', serviceWorkers: 'block', acceptDownloads: false,
    viewport: { width: 1440, height: 1000 }, screenshot: 'only-on-failure', trace: 'off', video: 'off' },
});

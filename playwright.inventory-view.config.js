// Isolated synthetic consumer checks only: no server, credentials or live URL.
const path = require('node:path');
let playwright;
try { playwright = require('@playwright/test'); }
catch (error) {
  if (error.code !== 'MODULE_NOT_FOUND') throw error;
  playwright = require(require.resolve('@playwright/test', {
    paths: (process.env.NODE_PATH || '').split(path.delimiter).filter(Boolean)
  }));
}
module.exports = playwright.defineConfig({
  testDir: './tests/e2e', testMatch: ['pve-inventory-view.spec.js', 'pve-source-config.spec.js'],
  timeout: 20_000, expect: { timeout: 5_000 }, workers: 1,
  fullyParallel: false, retries: 0, forbidOnly: true,
  outputDir: './test-results/inventory-view', reporter: [['line']],
  use: {
    browserName: 'chromium', serviceWorkers: 'block', acceptDownloads: false,
    viewport: { width: 1280, height: 900 },
    screenshot: 'only-on-failure', trace: 'off', video: 'off'
  }
});

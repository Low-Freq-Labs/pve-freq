// Synthetic display-consumer checks only; no product server or live target.
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
  testDir: './tests/e2e', testMatch: ['registered-lab-panel.spec.js', 'registered-lab-controller.spec.js'],
  timeout: 20_000, expect: { timeout: 5_000 }, workers: 1,
  fullyParallel: false, retries: 0, forbidOnly: true,
  outputDir: './test-results/registered-lab-panel', reporter: [['line']],
  use: {
    browserName: 'chromium', serviceWorkers: 'block', acceptDownloads: false,
    viewport: { width: 1280, height: 900 },
    screenshot: 'only-on-failure', trace: 'off', video: 'off'
  }
});

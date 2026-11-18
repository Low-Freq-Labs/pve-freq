// Synthetic actual-source join only. Parent owns the first browser execution.
const path = require('node:path');
let playwright;
try { playwright = require('@playwright/test'); }
catch (error) {
  if (error.code !== 'MODULE_NOT_FOUND') throw error;
  playwright = require(require.resolve('@playwright/test', {paths: (process.env.NODE_PATH || '').split(path.delimiter).filter(Boolean)}));
}
const evidence = '/home/freq-agents/projects/pve-freq/evidence/morty-lab-window-ui-20261113/composition';
module.exports = playwright.defineConfig({
  testDir: './tests/e2e', testMatch: 'lab-window-composition.spec.js', timeout: 25000,
  expect: {timeout: 5000}, workers: 1, fullyParallel: false, retries: 0, forbidOnly: true,
  outputDir: path.join(evidence, 'artifacts'), reporter: [['line'], ['json', {outputFile: path.join(evidence, 'results.json')}]],
  use: {browserName: 'chromium', serviceWorkers: 'block', acceptDownloads: false,
    viewport: {width: 1440, height: 1000}, screenshot: 'only-on-failure', trace: 'off', video: 'off'}
});

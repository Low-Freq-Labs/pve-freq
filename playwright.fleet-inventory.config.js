// Dedicated local synthetic-state check; no default live endpoint.
const path = require('node:path');
let playwright;
try { playwright = require('@playwright/test'); }
catch (error) {
  if (error.code !== 'MODULE_NOT_FOUND') throw error;
  playwright = require(require.resolve('@playwright/test', {
    paths: (process.env.NODE_PATH || '').split(path.delimiter).filter(Boolean)
  }));
}
const port = Number(process.env.PVE_FREQ_FLEET_PORT);
const evidence = process.env.PVE_FREQ_FLEET_EVIDENCE;
const python = process.env.PVE_FREQ_PYTHON;
if (!Number.isInteger(port) || port < 1024 || port > 65535 || !evidence || !python)
  throw new Error('Set explicit local port, existing evidence directory and Python path');
if (!path.isAbsolute(evidence) || !path.isAbsolute(python) || /[\r\n"`$\\]/.test(python))
  throw new Error('Use absolute evidence/Python paths and a shell-safe Python path');
module.exports = playwright.defineConfig({
  testDir: './tests/e2e', testMatch: 'fleet-inventory-unavailable.spec.js',
  timeout: 30_000, expect: { timeout: 7_000 }, workers: 1,
  fullyParallel: false, retries: 0, forbidOnly: true,
  outputDir: path.join(evidence, 'artifacts'),
  reporter: [['line'], ['json', { outputFile: path.join(evidence, 'results.json') }]],
  webServer: {
    command: `"${python}" -m tests.support.fleet_inventory_dashboard --port ${port}`,
    url: `https://127.0.0.1:${port}/healthz`,
    ignoreHTTPSErrors: true, reuseExistingServer: false, timeout: 15_000,
    gracefulShutdown: { signal: 'SIGTERM', timeout: 5_000 },
  },
  use: {
    baseURL: `https://127.0.0.1:${port}`, browserName: 'chromium',
    ignoreHTTPSErrors: true, serviceWorkers: 'block', acceptDownloads: false,
    viewport: { width: 1440, height: 1000 },
    screenshot: 'only-on-failure', trace: 'off', video: 'off',
  },
});

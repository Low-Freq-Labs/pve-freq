// Actual prestarted product only. No fixture server or implicit live target.
const fs = require('node:fs');
const path = require('node:path');
const { isIP } = require('node:net');
const { defineConfig } = require('@playwright/test');

let target;
try { target = new URL(process.env.PVE_FREQ_DEMO_URL); }
catch { throw new Error('PVE_FREQ_DEMO_URL must be an explicit HTTPS origin'); }
if (target.protocol !== 'https:' || target.username || target.password ||
    target.pathname !== '/' || target.search || target.hash) {
  throw new Error('PVE_FREQ_DEMO_URL must be an HTTPS origin without credentials or a path');
}
const expectation = process.env.PVE_FREQ_DEMO_EXPECT || 'observed';
const resolveIP = process.env.PVE_FREQ_DEMO_RESOLVE_IP;
if (resolveIP && !isIP(resolveIP)) {
  throw new Error('PVE_FREQ_DEMO_RESOLVE_IP must be an IP address');
}
if (!['observed', 'populated', 'empty', 'unavailable'].includes(expectation)) {
  throw new Error('PVE_FREQ_DEMO_EXPECT must be observed, populated, empty or unavailable');
}
const evidence = process.env.PVE_FREQ_DEMO_EVIDENCE;
if (!evidence || !path.isAbsolute(evidence) || !fs.statSync(evidence).isDirectory() ||
    fs.realpathSync(evidence).startsWith(fs.realpathSync(__dirname) + path.sep) ||
    fs.realpathSync(evidence) === fs.realpathSync(__dirname) ||
    (process.env.TEST_WORKER_INDEX === undefined && fs.readdirSync(evidence).length)) {
  throw new Error('PVE_FREQ_DEMO_EVIDENCE must be an existing empty absolute evidence directory outside the source checkout');
}
module.exports = defineConfig({
  testDir: './tests/e2e', testMatch: 'real-inventory.spec.js',
  workers: 1, fullyParallel: false, retries: 0, forbidOnly: true,
  timeout: 120_000, expect: { timeout: 20_000 },
  outputDir: path.join(evidence, 'artifacts'),
  reporter: [['line'], ['json', { outputFile: path.join(evidence, 'results.json') }]],
  use: {
    baseURL: target.origin, browserName: 'chromium',
    ignoreHTTPSErrors: process.env.PVE_FREQ_DEMO_INSECURE_TLS === '1',
    serviceWorkers: 'block', acceptDownloads: false,
    viewport: { width: 1440, height: 1000 },
    // Session-only routing preserves the URL hostname and TLS verification.
    launchOptions: { args: resolveIP ? ['--host-resolver-rules=MAP ' + target.hostname + ' ' + resolveIP] : [] },
    // Explicit screenshots happen only after authenticated credential clearing.
    screenshot: 'off', trace: 'off', video: 'off',
  },
});

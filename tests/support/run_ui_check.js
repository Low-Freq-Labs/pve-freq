#!/usr/bin/env node
'use strict';

// Development-only entrypoint. Never selects a live endpoint implicitly.
const fs = require('node:fs');
const path = require('node:path');
const { createHash } = require('node:crypto');
const { spawnSync, execFileSync } = require('node:child_process');
const { parseArgs } = require('node:util');
const ROOT = path.resolve(__dirname, '../..');

function main() {
  const { values } = parseArgs({ options: {
    mode: { type: 'string', default: 'local' },
    journey: { type: 'string', default: 'smoke' },
    url: { type: 'string' },
    'output-root': { type: 'string' },
    port: { type: 'string', default: '8879' },
    headed: { type: 'boolean' },
    'insecure-tls': { type: 'boolean' },
    help: { type: 'boolean' }
  } });
  if (values.help) {
    console.log(`Usage: npm run ui:check -- [options]
  --mode local|live         Default: isolated local dashboard fixture
  --journey smoke|navigation|accessibility|baseline
  --url https://host:port   Required in live mode; no embedded credentials
  --output-root DIR        Parent for a NEW private evidence directory
  --port PORT              Local fixture port (default 8879)
  --headed                 Show Chromium (requires a display)
  --insecure-tls           Explicitly accept self-signed live certificates

Live mode supports smoke and navigation only. It blocks operational API requests;
results prove browser shell behavior, not fleet health or operational correctness.
Live credentials: PVE_FREQ_ADMIN_USER and PVE_FREQ_ADMIN_PASSWORD_FILE.
Local full behavior checks: --journey baseline (includes known open failures).`);
    return 0;
  }
  if (!['local', 'live'].includes(values.mode)) throw new Error('mode must be local or live');
  if (!['smoke', 'navigation', 'accessibility', 'baseline'].includes(values.journey)) {
    throw new Error('unknown journey');
  }
  if (!/^\d+$/.test(values.port) || +values.port < 1024 || +values.port > 65535) {
    throw new Error('port must be between 1024 and 65535');
  }
  let origin;
  if (values.mode === 'live') {
    if (!['smoke', 'navigation'].includes(values.journey)) throw new Error('live mode permits smoke or navigation only');
    if (!values.url) throw new Error('live mode requires an explicit --url');
    const target = new URL(values.url);
    if (target.protocol !== 'https:' || target.username || target.password || target.search || target.hash || target.pathname !== '/') {
      throw new Error('live URL must be an HTTPS origin without credentials, path, query or fragment');
    }
    origin = target.origin;
    // Validate before creating output or launching a browser. Never print secrets.
    require('../e2e/support/terminal-global-setup').adminCredentials();
  } else {
    if (values.url) throw new Error('--url is only supported in explicit live mode');
    origin = `https://127.0.0.1:${values.port}`;
  }
  const parent = path.resolve(values['output-root'] || path.join(ROOT, 'test-results', 'ui-check'));
  fs.mkdirSync(parent, { recursive: true });
  const run = fs.mkdtempSync(path.join(parent, 'run-'));
  fs.chmodSync(run, 0o700);
  const git = args => execFileSync('git', args, { cwd: ROOT, encoding: 'utf8' }).trim();
  const metadata = {
    startedAt: new Date().toISOString(), mode: values.mode, journey: values.journey,
    target: origin, revision: git(['rev-parse', 'HEAD']),
    workingTree: git(['status', '--short']), node: process.version,
    playwright: require('@playwright/test/package.json').version,
    checkedFileHashes: Object.fromEntries([
      'tests/support/run_ui_check.js', 'playwright.ui.config.js',
      'playwright.hermetic.config.js', 'tests/ui/inspection.spec.js',
      'tests/e2e/support/ui-inspection-policy.js', 'tests/support/hermetic_dashboard.py',
      'tests/e2e/hermetic-dashboard.spec.js', 'tests/e2e/accessibility-semantics.spec.js',
      'tests/e2e/zero-state-web-ux.spec.js', 'freq/data/web/app.html',
      'freq/data/web/js/presentation.js', 'freq/data/web/js/app.js', 'freq/data/web/js/router.js', 'freq/data/web/css/app.css'
    ].map(file => [file, createHash('sha256').update(fs.readFileSync(path.join(ROOT, file))).digest('hex')])),
    limitation: values.mode === 'live'
      ? 'Guarded shell inspection. Operational API requests are blocked; no fleet acceptance claimed.'
      : 'Real dashboard with synthetic backend fixtures; no live infrastructure acceptance claimed.'
  };
  fs.writeFileSync(path.join(run, 'run.json'), JSON.stringify(metadata, null, 2) + '\n', { mode: 0o600 });
  const focused = ['smoke', 'navigation'].includes(values.journey);
  const args = ['test', '--config=' + (focused ? 'playwright.ui.config.js' : 'playwright.hermetic.config.js'),
    '--workers=1', '--retries=0', '--reporter=line,json', '--output=' + path.join(run, 'artifacts')];
  if (values.journey === 'accessibility') args.push('--grep', '^.*H09 ');
  if (values.headed) args.push('--headed');
  const env = { ...process.env,
    PLAYWRIGHT_BROWSERS_PATH: process.env.PLAYWRIGHT_BROWSERS_PATH || path.join(ROOT, '.playwright'),
    PVE_FREQ_PYTHON: process.env.PVE_FREQ_PYTHON || path.join(ROOT, '.venv/bin/python'),
    PVE_FREQ_HERMETIC_PORT: values.port,
    PVE_FREQ_UI_MODE: values.mode, PVE_FREQ_UI_JOURNEY: values.journey,
    PVE_FREQ_UI_ORIGIN: origin, PVE_FREQ_UI_INSECURE_TLS: values['insecure-tls'] ? '1' : '0',
    PLAYWRIGHT_JSON_OUTPUT_FILE: path.join(run, 'results.json')
  };
  console.log(`Evidence: ${run}`);
  const log = fs.openSync(path.join(run, 'browser.log'), 'wx', 0o600);
  const result = spawnSync(process.execPath, [require.resolve('@playwright/test/cli'), ...args], {
    cwd: ROOT, env, stdio: ['ignore', log, log], timeout: 20 * 60 * 1000
  });
  fs.closeSync(log);
  metadata.finishedAt = new Date().toISOString();
  metadata.exitCode = result.status === null ? 1 : result.status;
  if (result.error) metadata.runnerError = result.error.code || 'runner failure';
  if (result.signal) metadata.signal = result.signal;
  fs.writeFileSync(path.join(run, 'run.json'), JSON.stringify(metadata, null, 2) + '\n', { mode: 0o600 });
  console.log(`${metadata.exitCode === 0 ? 'PASS' : 'FAIL'}: ${values.mode} ${values.journey}. ${metadata.limitation}`);
  return metadata.exitCode;
}
try { process.exitCode = main(); }
catch (error) { console.error(`UI check refused: ${error.message}`); process.exitCode = 2; }

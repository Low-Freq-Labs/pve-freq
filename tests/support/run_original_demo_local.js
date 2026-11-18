#!/usr/bin/env node
'use strict';
// Explicitly synthetic provider; original CLI, configuration, auth and HTTP.
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const net = require('node:net');
const crypto = require('node:crypto');
const { spawn } = require('node:child_process');
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
const requireTrue = value => { if (!value) throw Error('check_failed'); };
const bounded = (work, milliseconds = 6000) => new Promise(resolve => {
  const timer = setTimeout(() => resolve(false), milliseconds);
  Promise.resolve(work).then(() => { clearTimeout(timer); resolve(true); }, () => { clearTimeout(timer); resolve(false); });
});

async function freePort(port) {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once('error', () => reject(Error('port_unavailable')));
    server.listen(port, '127.0.0.1', () => {
      const selected = server.address().port;
      server.close(() => resolve(selected));
    });
  });
}
async function main() {
  process.umask(0o077);
  const source = process.env.PVE_FREQ_DEMO_SOURCE;
  const python = process.env.PVE_FREQ_PYTHON;
  const evidence = process.env.PVE_FREQ_DEMO_EVIDENCE;
  const expectCockpit = process.env.PVE_FREQ_EXPECT_COCKPIT === '1';
  requireTrue(source && python && evidence && [source, python, evidence].every(path.isAbsolute));
  requireTrue(fs.statSync(source).isDirectory() && fs.statSync(evidence).isDirectory());
  requireTrue(fs.readdirSync(evidence).length === 0 && !fs.realpathSync(evidence).startsWith(fs.realpathSync(source) + path.sep));
  const { chromium } = require('playwright');
  const runtime = fs.mkdtempSync(path.join(os.tmpdir(), 'pve-original-synthetic-'));
  fs.chmodSync(runtime, 0o700);
  const children = [], handles = [], secrets = [];
  const result = { kind: 'synthetic local original-server integration', passed: false,
    checks: [], provider: null, cleanup: {}, startedAt: new Date().toISOString(),
    browserExceptions: 0, externalRequestsBlocked: 0,
    cockpit: { required: expectCockpit, verified: false, screenshots: [], workspaces: [] },
    realHarness: { required: process.env.PVE_FREQ_VERIFY_REAL_HARNESS === '1', verified: false },
    processRestartVerified: false,
    limitation: 'Synthetic TLS provider with browser origin guard only; no live PVE, installation or native acceptance. Process restart assertions have not yet completed.' };
  let browser, browserServer, launchPromise, context, productPort, stage = 'prepare', interrupted = 0;
  let cancel;
  const cancellation = new Promise((_, reject) => { cancel = reject; });
  const onInt = () => { interrupted = 130; cancel(Error('interrupted')); };
  const onTerm = () => { interrupted = 143; cancel(Error('interrupted')); };
  process.on('SIGINT', onInt); process.on('SIGTERM', onTerm);
  const privateWrite = (name, value) => { const file = path.join(runtime, name); fs.writeFileSync(file, value, { mode: 0o600 }); return file; };
  function child(command, args, label, env = process.env) {
    requireTrue(!interrupted);
    const stdout = fs.openSync(path.join(runtime, label + '.stdout'), 'wx', 0o600);
    const stderr = fs.openSync(path.join(runtime, label + '.stderr'), 'wx', 0o600);
    handles.push(stdout, stderr);
    const proc = spawn(command, args, { cwd: source, env, stdio: ['ignore', stdout, stderr] });
    proc.on('error', () => { proc.spawnFailed = true; });
    children.push({ proc, label });
    return proc;
  }
  async function stop(proc) {
    if (proc.exitCode !== null || proc.signalCode !== null || proc.spawnFailed) return 'already-exited';
    proc.kill('SIGTERM');
    for (let i = 0; i < 60 && proc.exitCode === null && proc.signalCode === null; i++) await pause(100);
    if (proc.exitCode === null && proc.signalCode === null) {
      proc.kill('SIGKILL');
      for (let i = 0; i < 30 && proc.exitCode === null && proc.signalCode === null; i++) await pause(100);
      requireTrue(proc.exitCode !== null || proc.signalCode !== null);
      return 'forced';
    }
    return 'graceful';
  }
  async function ready(port, proc) {
    for (let i = 0; i < 200; i++) {
      requireTrue(!proc.spawnFailed && proc.exitCode === null && proc.signalCode === null);
      const connected = await new Promise(resolve => {
        const socket = net.connect(port, '127.0.0.1');
        socket.setTimeout(200);
        socket.once('connect', () => { socket.destroy(); resolve(true); });
        socket.once('error', () => resolve(false));
        socket.once('timeout', () => { socket.destroy(); resolve(false); });
      });
      if (connected) return;
      await pause(100);
    }
    throw Error('readiness_failed');
  }
  try {
    const journey = async () => {
    await freePort(8006);
    const port = await freePort(0);
    productPort = port;
    const cert = path.join(runtime, 'localhost.crt'), key = path.join(runtime, 'localhost.key');
    const openssl = child('openssl', ['req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
      '-subj', '/CN=localhost', '-addext', 'subjectAltName=IP:127.0.0.1,DNS:localhost',
      '-keyout', key, '-out', cert], 'openssl');
    await new Promise(resolve => {
      const timer = setTimeout(resolve, 30_000);
      const done = () => { clearTimeout(timer); resolve(); };
      openssl.once('exit', done); openssl.once('error', done);
    });
    requireTrue(openssl.exitCode === 0);
    const password = crypto.randomBytes(24).toString('hex'), tokenSecret = crypto.randomBytes(24).toString('hex');
    secrets.push(password, tokenSecret);
    privateWrite('password', password);
    const token = privateWrite('token.json', JSON.stringify({ id: 'observer@pve!demo', secret: tokenSecret }));
    const counts = path.join(runtime, 'provider-counts.json');
    const provider = child(python, [path.join(__dirname, 'pve_demo_fixture.py'), '--cert', cert,
      '--key', key, '--token-file', token, '--counts', counts], 'provider');
    await ready(8006, provider);
    const conf = path.join(runtime, 'conf'), credentials = path.join(runtime, 'credentials');
    fs.mkdirSync(conf); fs.mkdirSync(credentials);
    fs.writeFileSync(path.join(conf, 'freq.toml'), '[paths]\ncredentials_dir = ' + JSON.stringify(credentials) +
      '\n[services]\ntls_cert = ' + JSON.stringify(cert) + '\ntls_key = ' + JSON.stringify(key) +
      '\ndashboard_port = ' + port + '\nwatchdog_enabled = false\n[pve]\nnodes = []\n', { mode: 0o600 });
    fs.writeFileSync(path.join(conf, 'hosts.toml'), 'hosts = []\n', { mode: 0o600 });
    const env = { ...process.env, FREQ_DIR: runtime, PYTHONPATH: source, PYTHONUNBUFFERED: '1' };
    const product = child(python, ['-m', 'freq', 'serve', '--read-only', '--bind', '127.0.0.1', '--port', String(port)], 'product', env);
    stage = 'original-startup';
    await ready(port, product);
    const output = fs.readFileSync(path.join(runtime, 'product.stdout'), 'utf8');
    const match = output.match(/FIRST-ADMIN CLAIM[^\r\n]*\bclaim=([^\s]+)/);
    requireTrue(match);
    const claim = match[1]; secrets.push(claim); privateWrite('claim', claim);
    requireTrue(!interrupted);
    launchPromise = chromium.launchServer({timeout: 15000, handleSIGINT: false, handleSIGTERM: false}).then(server => {
      browserServer = server;
      children.push({ proc: server.process(), label: 'browser' });
      return server;
    });
    await launchPromise;
    requireTrue(!interrupted);
    browser = await chromium.connect(browserServer.wsEndpoint());
    context = await browser.newContext({ ignoreHTTPSErrors: true, serviceWorkers: 'block', acceptDownloads: false,
      viewport: { width: 1440, height: 1000 } });
    const origin = 'https://127.0.0.1:' + port;
    await context.route('**/*', route => {
      if (new URL(route.request().url()).origin === origin) return route.continue();
      result.externalRequestsBlocked++;
      return route.abort('blockedbyclient');
    });
    await context.routeWebSocket('**/*', socket => {
      if (new URL(socket.url()).origin === origin.replace('https:', 'wss:')) {
        socket.connectToServer(); return;
      }
      result.externalRequestsBlocked++;
      socket.close();
    });
    const page = await context.newPage();
    page.setDefaultTimeout(20_000);
    result.http = [];
    result.browserInventoryGets = 0;
    page.on('request', request => {
      if (new URL(request.url()).origin === origin && new URL(request.url()).pathname === '/api/pve/inventory' && request.method() === 'GET') result.browserInventoryGets++;
    });
    result.browserExceptions = 0;
    page.on('response', response => {
      const url = new URL(response.url());
      if (url.pathname.startsWith('/api/')) result.http.push({path: url.pathname, method: response.request().method(), status: response.status()});
    });
    page.on('pageerror', () => { result.browserExceptions++; });
    const response = pathname => page.waitForResponse(res => new URL(res.url()).origin === origin && new URL(res.url()).pathname === pathname);
    const check = (name, value) => { requireTrue(value); result.checks.push(name); };
    const settledHome = async state => {
      if (!expectCockpit) return;
      const previousStage = stage;
      stage = previousStage + '-home-observation';
      await page.locator(`#home-view #home-widgets[data-state="${state}"] .pve-cockpit[aria-busy="false"]`).waitFor();
      check('home-observation-settled-before-fleet', true);
      stage = previousStage;
    };
    stage = 'first-admin';
    await page.goto(origin + '/');
    await page.locator('#operator-user').fill('synthetic_admin');
    await page.locator('#operator-pass').fill(password);
    await page.locator('#operator-pass2').fill(password);
    await page.locator('#operator-claim').fill(claim);
    const create = response('/api/setup/create-admin');
    await page.locator('#operator-form').evaluate(form => form.requestSubmit());
    const created = await create;
    check('original-first-admin-session', created.status() === 200 && (await created.json()).session_started === true);
    await page.goto(origin + '/');
    const verified = await page.evaluate(async () => (await fetch('/api/auth/verify')).json());
    check('original-session-after-navigation', verified.valid === true && verified.user === 'synthetic_admin');
    await settledHome('empty');
    const inventory = response('/api/pve/inventory');
    await page.getByRole('navigation', { name: 'Primary' }).locator('[data-view="fleet"]').click();
    const first = await inventory;
    check('original-empty-inventory', first.status() === 200 && (await first.json()).state === 'unconfigured');
    await page.locator('#pve-inventory-report[data-state="empty"]').waitFor();
    stage = 'create-source';
    await page.getByLabel('PVE addresses', { exact: true }).fill('127.0.0.1');
    await page.getByLabel('API token ID', { exact: true }).fill('observer@pve!demo');
    await page.getByLabel('API token secret', { exact: true }).fill(tokenSecret);
    await page.getByLabel('Trusted CA certificate (optional)', { exact: true }).fill(fs.readFileSync(cert, 'utf8'));
    const saved = response('/api/pve/endpoints'), observed = response('/api/pve/inventory');
    await page.getByRole('button', { name: 'Save PVE source configuration', exact: true }).click();
    const saving = await saved;
    check('original-source-create', saving.status() === 200 && (await saving.json()).ok === true);
    await page.locator('#pve-host-configuration form').waitFor({ state: 'detached' });
    let previousUptime = null;
    const assertInventory = async res => {
      const body = await res.json();
      check('original-service-verified-tls-synthetic-rows', res.status() === 200 && body.state === 'ok' &&
        body.sources.some(source => source.nodes.some(row => row.node === 'synthetic-node') && source.guests.some(row => row.vmid === 6101)));
      await page.locator('#pve-inventory-report[data-state="ready"]').waitFor();
      await page.locator('[data-inventory-kind="guest"]').filter({ hasText: 'synthetic-guest' }).waitFor();
      const guest = body.sources.flatMap(source => source.guests).find(row => row.vmid === 6101);
      check('fresh-synthetic-provider-observation', Number.isInteger(guest.uptime) && (previousUptime === null || guest.uptime > previousUptime));
      previousUptime = guest.uptime;
      await page.getByRole('button', { name: 'Details for synthetic-guest', exact: true }).click();
      const previousStage = stage;
      stage = previousStage + '-uptime-details';
      await page.locator('[data-inventory-detail] dt').filter({ hasText: /^Uptime$/ })
        .locator('xpath=following-sibling::dd[1]').filter({ hasText: new RegExp('^' + guest.uptime + ' seconds$') }).waitFor();
      stage = previousStage;
    };
    await assertInventory(await observed);
    stage = 'details-refresh-reload';
    await page.getByRole('button', { name: 'Details for synthetic-guest', exact: true }).click();
    check('guest-details', (await page.locator('[data-inventory-detail]').textContent()).includes('6101'));
    await page.getByRole('button', { name: 'Details for synthetic-node', exact: true }).click();
    check('node-details', (await page.locator('[data-inventory-detail]').textContent()).includes('synthetic-node'));
    const refreshed = response('/api/pve/inventory');
    await page.getByRole('button', { name: 'Refresh inventory', exact: true }).click();
    await assertInventory(await refreshed);
    const reloaded = response('/api/pve/inventory');
    await page.reload();
    await assertInventory(await reloaded);
    if (expectCockpit) {
      stage = 'synthetic-original-cockpit-workspaces';
      const primary = page.getByRole('navigation', { name: 'Primary' });
      const snapshot = async name => {
        check('screenshot-credential-fields-cleared', await page.locator('input[type="password"], #operator-claim')
          .evaluateAll(inputs => inputs.every(input => input.value === '')));
        await page.evaluate(() => {
          let label = document.getElementById('synthetic-evidence-label');
          if (!label) { label = document.createElement('p'); label.id = 'synthetic-evidence-label'; document.body.prepend(label); }
          label.textContent = 'SYNTHETIC LOCAL ORIGINAL-SERVER COCKPIT — NOT LIVE PVE';
          window.scrollTo(0, 0);
        });
        const file = 'synthetic-cockpit-' + name + '.png';
        await page.screenshot({ path: path.join(evidence, file), fullPage: true, mask: [page.locator('input[type="password"]')] });
        result.cockpit.screenshots.push({ file, ...await page.evaluate(() => ({ width: innerWidth, height: innerHeight,
          documentWidth: document.documentElement.scrollWidth })) });
      };
      const homeRead = response('/api/pve/inventory');
      await primary.locator('[data-view="home"]').click();
      const homeResponse = await homeRead, homeBody = await homeResponse.json();
      check('home-original-inventory-read', homeResponse.status() === 200 && homeBody.state === 'ok');
      const home = page.locator('#home-view #home-widgets .pve-cockpit');
      await home.waitFor();
      await home.locator('.cockpit-node-group').first().waitFor();
      await home.locator('[data-inventory-kind="guest"]').filter({ hasText: 'synthetic-guest' }).waitFor();
      check('home-original-node-count', await home.locator('[data-inventory-kind="node"]').count() === homeBody.sources.reduce((total, host) => total + host.nodes.length, 0));
      await snapshot('home-1440');
      const beforeWorkspaces = result.browserInventoryGets;
      const workspaces = [['network', 'topology'], ['storage', 'nas'], ['pve-firewall', 'security'],
        ['docker', 'docker'], ['security', 'security'], ['vault', 'vault'], ['tools', 'tools'], ['settings', 'settings']];
      for (const [view, workspace] of workspaces) {
        await primary.locator(`[data-view="${view}"]`).click();
        const mounted = page.locator(`.cockpit-workspace[data-workspace="${workspace}"]:visible`);
        await mounted.waitFor();
        await snapshot(view + '-1440');
        const tabs = mounted.getByRole('group').getByRole('button');
        for (let index = 0; index < await tabs.count(); index++) {
          await tabs.nth(index).click();
          check('workspace-local-tab-selected', await tabs.nth(index).getAttribute('aria-pressed') === 'true');
          const controls = mounted.locator('[data-action-unavailable="true"]');
          check('workspace-native-disabled-operations', await controls.count() > 0 &&
            await controls.evaluateAll(buttons => buttons.every(button => button.disabled)));
          await controls.evaluateAll(buttons => buttons.forEach(button => button.click()));
        }
        result.cockpit.workspaces.push(view);
      }
      check('workspaces-no-extra-browser-inventory-get', result.browserInventoryGets === beforeWorkspaces);
      const fleetRead = response('/api/pve/inventory');
      await primary.locator('[data-view="fleet"]').click();
      await assertInventory(await fleetRead);
      await snapshot('fleet-1440');
      await page.setViewportSize({ width: 390, height: 844 });
      try {
        await snapshot('fleet-390');
        stage = 'phone-menu-network-deep-route';
        const menu = page.getByRole('button', { name: 'Menu', exact: true });
        check('phone-primary-initially-collapsed', !(await primary.isVisible()));
        await menu.click();
        await primary.waitFor();
        check('phone-menu-expanded', await menu.getAttribute('aria-expanded') === 'true');
        const beforeNetwork = result.browserInventoryGets;
        await primary.locator('[data-view="network"]').click();
        await page.locator('.cockpit-workspace[data-workspace="topology"]:visible').waitFor();
        check('phone-network-route', new URL(page.url()).pathname === '/dashboard/network');
        await page.reload();
        await page.locator('.cockpit-workspace[data-workspace="topology"]:visible').waitFor();
        const phoneIdentity = await page.evaluate(async () => (await fetch('/api/auth/verify')).json());
        check('network-deep-reload-authenticated', phoneIdentity.valid === true && phoneIdentity.user === 'synthetic_admin');
        if (!(await primary.isVisible())) await menu.click();
        await primary.waitFor();
        check('network-deep-reload-menu-expanded', await menu.getAttribute('aria-expanded') === 'true');
        check('network-deep-reload-route-and-nav', new URL(page.url()).pathname === '/dashboard/network' &&
          await primary.locator('[data-view="network"]').getAttribute('aria-current') === 'page');
        check('network-deep-reload-no-browser-inventory-get', result.browserInventoryGets === beforeNetwork);
        check('phone-workspace-table-caption-readable', await page.locator('.cockpit-workspace .cockpit-table').evaluateAll(tables =>
          tables.length > 0 && tables.every(table => {
            const caption = table.querySelector('caption');
            return getComputedStyle(table).display === 'table' && caption &&
              caption.getBoundingClientRect().width >= 200 && caption.getBoundingClientRect().height < 120;
          })));
        await snapshot('network-phone-reloaded-390');
        const phoneFleet = response('/api/pve/inventory');
        await primary.locator('[data-view="fleet"]').click();
        await assertInventory(await phoneFleet);
        result.cockpit.phoneMenuNavigationVerified = true;
        result.cockpit.networkAuthenticatedDeepReloadVerified = true;
      } finally { await page.setViewportSize({ width: 1440, height: 1000 }); }
      result.cockpit.verified = true;
    }
    await page.evaluate(() => { const label = document.createElement('p'); label.textContent = 'SYNTHETIC LOCAL ORIGINAL-SERVER INTEGRATION'; document.body.prepend(label); });
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({ path: path.join(evidence, 'synthetic-original-server.png'), fullPage: true, mask: [page.locator('input[type="password"]')] });
    stage = 'logout';
    await page.locator('#header-user-btn').click();
    const loggedOut = response('/api/auth/logout');
    await page.getByRole('button', { name: 'LOG OUT', exact: true }).click();
    check('original-logout', (await loggedOut).status() === 200);
    check('session-revoked', !(await page.evaluate(async () => (await fetch('/api/auth/verify')).json())).valid);
    if (result.realHarness.required) {
      stage = 'separate-original-real-harness';
      const harnessEvidence = path.join(evidence, 'synthetic-real-harness');
      fs.mkdirSync(harnessEvidence, { mode: 0o700 });
      const cli = path.join(path.dirname(require.resolve('playwright/package.json')), 'cli.js');
      const config = path.resolve(__dirname, '../../playwright.real-inventory.config.js');
      const harness = child(process.execPath, [cli, 'test', '--config=' + config, '--workers=1', '--retries=0'], 'real-harness', {
        ...env, PVE_FREQ_DEMO_URL: origin, PVE_FREQ_DEMO_USER: 'synthetic_admin',
        PVE_FREQ_DEMO_PASSWORD_FILE: path.join(runtime, 'password'), PVE_FREQ_DEMO_EVIDENCE: harnessEvidence,
        PVE_FREQ_DEMO_EXPECT: 'populated', PVE_FREQ_EXPECT_COCKPIT: '1', PVE_FREQ_DEMO_REQUIRE_FILTER: '1',
        PVE_FREQ_DEMO_INSECURE_TLS: '1', PVE_FREQ_DEMO_SYNTHETIC: '1', PVE_FREQ_DEMO_RESOLVE_IP: '',
      });
      const completed = await bounded(new Promise(resolve => { harness.once('exit', resolve); harness.once('error', resolve); }), 150000);
      result.realHarness = { required: true, verified: completed && harness.exitCode === 0,
        exitCode: harness.exitCode, timedOut: !completed, syntheticProvider: true,
        evidenceDirectory: 'synthetic-real-harness', separateBrowserAndSession: true };
      check('separate-original-real-harness-passed', result.realHarness.verified);
    }
    stage = 'same-runtime-process-restart';
    result.cleanup.firstProductShutdown = await stop(product);
    check('first-product-graceful-shutdown', result.cleanup.firstProductShutdown === 'graceful');
    await freePort(port);
    check('first-product-listener-closed', true);
    const restarted = child(python, ['-m', 'freq', 'serve', '--read-only', '--bind', '127.0.0.1', '--port', String(port)], 'product-restart', env);
    await ready(port, restarted);
    check('restart-no-first-admin-claim', !fs.readFileSync(path.join(runtime, 'product-restart.stdout'), 'utf8').includes('FIRST-ADMIN CLAIM'));
    // The first session was explicitly revoked. Reauthenticate through the
    // original login form; no session state is supplied to the restarted server.
    await page.goto(origin + '/');
    check('restart-requires-reauthentication', !(await page.evaluate(async () => (await fetch('/api/auth/verify')).json())).valid);
    await page.locator('#login-overlay').waitFor({ state: 'visible' });
    await page.locator('#login-user').fill('synthetic_admin');
    await page.locator('#login-pass').fill(password);
    const login = response('/api/auth/login');
    await page.locator('#login-pass').press('Enter');
    check('restart-original-password-login', (await login).status() === 200);
    await page.locator('#login-overlay').waitFor({ state: 'hidden' });
    const restartIdentity = await page.evaluate(async () => (await fetch('/api/auth/verify')).json());
    check('restart-same-durable-user', restartIdentity.valid === true && restartIdentity.user === 'synthetic_admin');
    await settledHome('ready');
    const restartedInventory = response('/api/pve/inventory');
    await page.getByRole('navigation', { name: 'Primary' }).locator('[data-view="fleet"]').click();
    await assertInventory(await restartedInventory);
    stage = 'restart-persisted-metadata';
    const metadata = await page.evaluate(async () => {
      const res = await fetch('/api/pve/endpoints');
      const body = await res.json();
      return {status: res.status, addresses: body.addresses, token_principal: body.token_principal, ca_configured: body.ca_configured};
    });
    check('restart-persisted-endpoint-token-ca-metadata', metadata.status === 200 &&
      Array.isArray(metadata.addresses) && metadata.addresses.length === 1 && metadata.addresses[0] === '127.0.0.1' &&
      metadata.token_principal === 'observer@pve' && metadata.ca_configured === true);
    const configured = page.locator('#pve-host-configuration');
    await configured.getByText('Token principal: observer@pve', { exact: true }).waitFor();
    await configured.getByText('Trusted CA certificate: Configured', { exact: true }).waitFor();
    check('restart-create-form-remains-absent', await configured.locator('form').count() === 0);
    await page.evaluate(() => { const label = document.createElement('p'); label.textContent = 'SYNTHETIC LOCAL ORIGINAL-SERVER AFTER PROCESS RESTART'; document.body.prepend(label); });
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({ path: path.join(evidence, 'synthetic-original-server-restart.png'), fullPage: true, mask: [page.locator('input[type="password"]')] });
    stage = 'restart-logout';
    await page.locator('#header-user-btn').click();
    const secondLogout = response('/api/auth/logout');
    await page.getByRole('button', { name: 'LOG OUT', exact: true }).click();
    check('restart-original-logout', (await secondLogout).status() === 200);
    check('restart-session-revoked', !(await page.evaluate(async () => (await fetch('/api/auth/verify')).json())).valid);
    result.processRestartVerified = true;
    result.limitation = 'Synthetic TLS provider with browser origin guard only. Tested one graceful original-server process restart with the same private runtime, persisted user/source/token/CA and fresh password login; no session persistence, live PVE, installation or native acceptance claimed.';
    check('no-unexpected-server-errors', !result.http.some(row => row.status >= 500));
    check('no-browser-exceptions', result.browserExceptions === 0);
    check('same-origin-browser-journey', result.externalRequestsBlocked === 0);
    result.passed = true;
    };
    await Promise.race([journey(), cancellation]);
  } catch (_) { result.failureStage = stage; }
  finally {
    const stopOwned = async owned => {
      try {
        result.cleanup[owned.label] = await stop(owned.proc);
        if (result.cleanup[owned.label] === 'forced') result.passed = false;
      }
      catch (_) { result.cleanup[owned.label] = 'failed'; result.passed = false; }
    };
    // Start application/provider teardown before waiting on any browser port.
    const processClosure = Promise.all(children.filter(owned => owned.label !== 'browser').map(stopOwned));
    const browserClosure = (async () => {
      if (launchPromise) await bounded(launchPromise, 16000);
      const contextClosed = context ? await bounded(context.close(), 3000) : true;
      const browserClosed = browserServer ? await bounded(browserServer.close()) : browser ? await bounded(browser.close()) : true;
      result.cleanup.browserClose = contextClosed && browserClosed;
      if (!result.cleanup.browserClose) result.passed = false;
      const owned = children.find(child => child.label === 'browser');
      if (owned) await stopOwned(owned);
    })();
    await Promise.all([browserClosure, processClosure]);
    try {
      const counts = JSON.parse(fs.readFileSync(path.join(runtime, 'provider-counts.json'), 'utf8'));
      requireTrue(Number.isInteger(counts.inventory) && Number.isInteger(counts.denied));
      result.provider = { inventory: counts.inventory, denied: counts.denied };
      if (counts.inventory < 4 || counts.denied !== 0) result.passed = false;
    }
    catch (_) { result.passed = false; }
    for (const fd of handles) { try { fs.closeSync(fd); } catch (_) {} }
    try {
      await freePort(8006);
      if (productPort) await freePort(productPort);
      result.cleanup.listenersClosed = true;
    } catch (_) { result.cleanup.listenersClosed = false; result.passed = false; }
    fs.rmSync(runtime, { recursive: true, force: true });
    result.cleanup.runtimeRemoved = !fs.existsSync(runtime);
    result.interrupted = interrupted || null;
    if (interrupted || result.browserExceptions || result.externalRequestsBlocked) result.passed = false;
    result.finishedAt = new Date().toISOString();
    result.cleanup.evidenceByteScan = 'passed; binary/text byte matching, no image OCR';
    const scanEvidence = directory => {
      for (const name of fs.readdirSync(directory)) {
        const file = path.join(directory, name), stat = fs.lstatSync(file);
        if (stat.isDirectory()) { scanEvidence(file); continue; }
        const bytes = stat.isFile() ? fs.readFileSync(file) : null;
        if (!bytes || secrets.some(secret => bytes.includes(Buffer.from(secret)))) {
          fs.unlinkSync(file);
          result.cleanup.evidenceByteScan = 'secret-bearing or nonregular artifact removed';
          result.passed = false;
        }
      }
    };
    scanEvidence(evidence);
    const safe = JSON.stringify(result, null, 2);
    requireTrue(!secrets.some(secret => safe.includes(secret)));
    fs.writeFileSync(path.join(evidence, 'synthetic-original-server.json'), safe, { mode: 0o600 });
    process.stdout.write(result.passed ? 'Synthetic original-server integration passed.\n' : 'Synthetic original-server integration failed; inspect sanitized evidence.\n');
    process.exitCode = interrupted || (result.passed ? 0 : 1);
    process.removeListener('SIGINT', onInt); process.removeListener('SIGTERM', onTerm);
  }
}
main().catch(() => { process.stderr.write('Synthetic original-server runner could not complete; no private logs emitted.\n'); process.exitCode = 1; });

#!/usr/bin/env node
'use strict';

// Opt-in native acceptance runner. No request interception, provider client,
// power HTTP helper, automatic retry, or restoration action exists here.
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const net = require('node:net');
const https = require('node:https');
const tls = require('node:tls');
const crypto = require('node:crypto');
const ROOT = path.resolve(__dirname, '../..');
const PREFIX = 'PVE_FREQ_LAB_';
const NAMES = ['URL', 'USER', 'PASSWORD_FILE', 'CA_FILE', 'TARGET_REF', 'REGISTRATION_REVISION',
  'EXPECT_SOURCE', 'EVIDENCE', 'SOURCE_REVISION', 'WINDOW_START', 'WINDOW_END', 'SELECTED_CYCLE', 'RESOLVE_IP'];
const GUEST = '/api/lab/guest', POWER = '/api/lab/power', OPS = '/api/lab/operations/';
const HEX32 = /^[a-f0-9]{32}$/, HEX64 = /^[a-f0-9]{64}$/;
const utc = value => typeof value === 'string' && /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?(?:Z|\+00:00)$/.test(value) &&
  Number.isFinite(Date.parse(value)) && new Date(value).toISOString().slice(0, 19) === value.slice(0, 19);
const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);
function check(value) { if (!value) throw Error('acceptance_check_failed'); }
function bounded(promise, ms = 15000) {
  let timer;
  return Promise.race([promise, new Promise((_, reject) => { timer = setTimeout(() => reject(Error('deadline')), ms); })])
    .finally(() => clearTimeout(timer));
}
function privateFile(name) {
  check(path.isAbsolute(name) && fs.realpathSync(name) === name);
  const stat = fs.statSync(name);
  check(stat.isFile() && (stat.mode & 0o777) === 0o600 && stat.size > 0 && stat.size <= 1048576);
  if (typeof process.getuid === 'function') check(stat.uid === process.getuid());
  return fs.readFileSync(name);
}
function preflight(origin, ca, ip) {
  return new Promise((resolve, reject) => {
    const options = {method: 'GET', ca: [...tls.rootCertificates, ca], rejectUnauthorized: true, timeout: 10000};
    if (ip) options.lookup = (hostname, settings, callback) => {
      if (hostname !== origin.hostname) return callback(Error('unexpected_lookup'));
      const answer = {address: ip, family: net.isIP(ip)};
      callback(null, settings && settings.all ? [answer] : answer.address, answer.family);
    };
    const request = https.request(new URL('/dashboard/registered-lab', origin), options, response => {
      const verified = response.socket.authorized === true;
      response.resume();
      response.on('end', () => verified && response.statusCode === 200 ? resolve() : reject(Error('tls_preflight')));
    });
    request.on('timeout', () => request.destroy(Error('deadline')));
    request.on('error', () => reject(Error('tls_preflight')));
    request.end();
  });
}
function publicOperation(op) {
  return {ref: op.ref, action: op.action, phase: op.phase, acknowledgement: op.acknowledgement,
    task: {state: op.task.state, exit: op.task.exit},
    recordedGuestObservation: {state: op.observation.state, observedAt: op.observation.observed_at}};
}
async function main() {
  if (process.argv.includes('--help')) {
    console.log('Usage: node tests/support/run_registered_lab_browser.js\nExplicit environment inputs:\n' +
      NAMES.map(name => PREFIX + name).join('\n') + '\nRESOLVE_IP is optional. SELECTED_CYCLE must explicitly equal shutdown-start.\n' +
      'Without selection: zero network, browser, credential reads or power actions; no acceptance claim.\n' +
      'Selected: original browser login and exactly two UI power intents within the explicit UTC window.\n' +
      'PASSWORD_FILE must be an absolute owner-private 0600 file. CA_FILE must be absolute.\n' +
      'EVIDENCE must be an existing empty private directory outside this checkout. NODE_PATH supplies shared Playwright.');
    return;
  }
  check(process.argv.length === 2);
  if (!process.env[PREFIX + 'SELECTED_CYCLE']) {
    console.log(JSON.stringify({status: 'UNSELECTED', acceptance: false, networkRequests: 0, browserLaunched: false, powerActions: 0}));
    return;
  }
  let stage = 'configuration', evidence = null, runtime = null, profile = null, server = null, browser = null, context = null, page = null, password = null;
  let loggedIn = false, revoked = false, fatal = null, shutdownSeen = false, crossOriginMutations = 0;
  const requests = [], powers = [], guests = [], operations = [], secretBytes = [], responseWork = new Set();
  const requestInfo = new WeakMap();
  const receipt = {schema: 'pve-freq-registered-lab-browser-receipt-v1', status: 'FAILED', acceptance: false,
    selectedCycle: 'shutdown-start', startedAt: new Date().toISOString(), restoreObserved: false, restorationRequired: false,
    tls: {nodeStrictVerified: false, browserStrictDefaultTrust: true, certificateBypass: false}, outcomes: []};
  let interruptCleanup = null;
  const interrupt = () => {
    fatal = 'interrupted';
    // Cancel the owned browser immediately so pending actionability/click
    // work cannot continue merely because the signal handler returned.
    // This handler performs no HTTP/provider cleanup or restoration.
    const closing = [];
    if (context) closing.push(bounded(context.close(), 3000));
    if (server) closing.push(bounded(server.kill(), 3000));
    else if (browser) closing.push(bounded(browser.close(), 3000));
    interruptCleanup = Promise.allSettled(closing);
  };
  process.on('SIGINT', interrupt); process.on('SIGTERM', interrupt);
  try {
    const env = Object.fromEntries(NAMES.map(name => [name, process.env[PREFIX + name]]));
    check(env.SELECTED_CYCLE === 'shutdown-start');
    NAMES.filter(name => name !== 'RESOLVE_IP').forEach(name => check(typeof env[name] === 'string' && env[name].length > 0));
    const origin = new URL(env.URL);
    check(origin.protocol === 'https:' && !origin.username && !origin.password && origin.pathname === '/' && !origin.search && !origin.hash);
    check(/^[a-f0-9]{40}$/.test(env.SOURCE_REVISION) && HEX64.test(env.REGISTRATION_REVISION));
    check(env.TARGET_REF.length <= 512 && env.EXPECT_SOURCE.length <= 512 && !/[\u0000-\u001f\u007f]/.test(env.TARGET_REF + env.EXPECT_SOURCE));
    check(utc(env.WINDOW_START) && utc(env.WINDOW_END));
    const start = Date.parse(env.WINDOW_START), end = Date.parse(env.WINDOW_END);
    check(end > start);
    function windowOpen() { check(!fatal && Date.now() >= start && Date.now() < end); }
    windowOpen();
    if (env.RESOLVE_IP) check(net.isIP(env.RESOLVE_IP) !== 0 && /^[a-z0-9.-]+$/i.test(origin.hostname) && net.isIP(origin.hostname) === 0);
    check(path.isAbsolute(env.EVIDENCE) && fs.realpathSync(env.EVIDENCE) === env.EVIDENCE);
    const relative = path.relative(ROOT, env.EVIDENCE);
    check(relative.startsWith('..' + path.sep) || path.isAbsolute(relative));
    const evidenceStat = fs.statSync(env.EVIDENCE);
    check(evidenceStat.isDirectory() && (evidenceStat.mode & 0o777) === 0o700 && fs.readdirSync(env.EVIDENCE).length === 0);
    evidence = env.EVIDENCE;
    receipt.sourceRevision = env.SOURCE_REVISION;
    receipt.sourceRevisionBasis = 'Operator-supplied deployment pin; remote revision is not independently attested by this runner.';
    receipt.runnerSHA256 = crypto.createHash('sha256').update(fs.readFileSync(__filename)).digest('hex');
    receipt.origin = origin.origin;
    receipt.window = {start: env.WINDOW_START, end: env.WINDOW_END};
    receipt.resolver = env.RESOLVE_IP ? {mode: 'session-only override', hostname: origin.hostname, address: env.RESOLVE_IP, normalDNSProven: false} :
      {mode: 'system DNS or literal origin', normalDNSProven: false};
    receipt.target = {ref: env.TARGET_REF, registrationRevision: env.REGISTRATION_REVISION, source: env.EXPECT_SOURCE,
      node: 'branch-pve', kind: 'qemu', vmid: 120, name: 'branch-test-vm'};
    stage = 'private-inputs';
    const passwordBytes = privateFile(env.PASSWORD_FILE);
    secretBytes.push(passwordBytes);
    check(passwordBytes.length <= 4096);
    password = passwordBytes.toString('utf8').replace(/\r?\n$/, '');
    secretBytes.push(Buffer.from(password));
    check(password.length > 0 && !/[\r\n\u0000]/.test(password));
    check(path.isAbsolute(env.CA_FILE) && fs.realpathSync(env.CA_FILE) === env.CA_FILE && fs.statSync(env.CA_FILE).isFile());
    const ca = fs.readFileSync(env.CA_FILE, 'utf8');
    check(ca.length > 0 && ca.length <= 1048576);
    stage = 'strict-tls-preflight';
    await preflight(origin, ca, env.RESOLVE_IP);
    receipt.tls.nodeStrictVerified = true;
    windowOpen();
    stage = 'browser-launch';
    runtime = fs.mkdtempSync(path.join(os.tmpdir(), 'pve-lab-browser-'));
    fs.chmodSync(runtime, 0o700);
    // Suppress inherited debug channels before loading the browser driver;
    // tracing, video and request/body logging are never enabled.
    process.env.DEBUG = ''; delete process.env.PWDEBUG; delete process.env.DEBUG_FILE;
    const {chromium} = require('playwright');
    const args = env.RESOLVE_IP ? ['--host-resolver-rules=MAP ' + origin.hostname + ' ' +
      (net.isIP(env.RESOLVE_IP) === 6 ? '[' + env.RESOLVE_IP + ']' : env.RESOLVE_IP)] : [];
    // launchServer exposes only this runner's owned process for bounded cleanup.
    // Playwright creates its private temporary profile under os.tmpdir().
    server = await chromium.launchServer({headless: true, args, downloadsPath: path.join(runtime, 'downloads')});
    windowOpen();
    const profileArg = server.process().spawnargs.find(arg => arg.startsWith('--user-data-dir='));
    check(profileArg);
    profile = profileArg.slice('--user-data-dir='.length);
    check(path.dirname(profile) === fs.realpathSync(os.tmpdir()) && (fs.statSync(profile).mode & 0o777) === 0o700);
    browser = await chromium.connect(server.wsEndpoint());
    windowOpen();
    context = await browser.newContext({viewport: {width: 1440, height: 1000}, acceptDownloads: false, ignoreHTTPSErrors: false});
    windowOpen();
    context.setDefaultTimeout(15000);
    page = context.pages()[0] || await context.newPage();
    function bad() { fatal = fatal || 'original-response-or-request-refused'; }
    let originalTarget = null;
    function targetDTO(dto) {
      check(object(dto) && dto.schema === 'pve-freq-lab-guest-view-v1' && object(dto.target));
      const t = dto.target;
      check(t.ref === env.TARGET_REF && t.registration_revision === env.REGISTRATION_REVISION && t.source === env.EXPECT_SOURCE &&
        t.node === 'branch-pve' && t.kind === 'qemu' && t.vmid === 120 && t.name === 'branch-test-vm');
      check(typeof t.estate === 'string' && t.estate.length > 0 && t.estate.length <= 512 && !/[\u0000-\u001f\u007f]/.test(t.estate));
      if (originalTarget) check(['ref', 'registration_revision', 'estate', 'source', 'node', 'kind', 'vmid', 'name', 'qualified_at', 'expires_at'].every(key => originalTarget[key] === t[key]));
      else originalTarget = {...t};
      // The selected window is the server-enforced qualification window.
      check(utc(t.qualified_at) && utc(t.expires_at) && t.qualified_at === env.WINDOW_START && t.expires_at === env.WINDOW_END);
      check(object(dto.observation) && ['running', 'stopped'].includes(dto.observation.state) && utc(dto.observation.observed_at));
      check(typeof dto.busy === 'boolean' && object(dto.capabilities) && dto.capabilities.lab_only === true &&
        Array.isArray(dto.capabilities.actions) && dto.capabilities.actions.includes('start') && dto.capabilities.actions.includes('shutdown'));
      return dto;
    }
    function operationDTO(value, item) {
      check(object(value) && value.schema === 'pve-freq-lab-operation-view-v1' && object(value.operation));
      const op = value.operation;
      check(HEX32.test(op.ref) && op.target_ref === env.TARGET_REF && op.registration_revision === env.REGISTRATION_REVISION &&
        op.retired === false && op.action === item.action && op.expected_state === item.expectedState);
      check(['dispatching', 'acknowledged', 'running', 'succeeded', 'failed', 'rejected', 'uncertain'].includes(op.phase) &&
        ['pending', 'received', 'not_submitted', 'uncertain'].includes(op.acknowledgement) && object(op.task) &&
        ['unknown', 'running', 'succeeded', 'failed'].includes(op.task.state) && [null, 'OK', 'failed', 'unknown'].includes(op.task.exit) &&
        object(op.observation) && ['unknown', 'running', 'stopped'].includes(op.observation.state));
      check(op.observation.state === 'unknown' ? op.observation.observed_at === null : utc(op.observation.observed_at));
      if (item.opRef) check(item.opRef === op.ref); else item.opRef = op.ref;
      return op;
    }
    page.on('request', request => {
      try {
        const url = new URL(request.url()), method = request.method();
        if (url.origin !== origin.origin) { if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(method)) { crossOriginMutations++; bad(); } return; }
        const info = {number: requests.length + 1, path: url.pathname, method, at: Date.now()};
        requests.push(info); requestInfo.set(request, info);
        if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(method) && !url.pathname.startsWith('/api/auth/')) {
          if (url.pathname === POWER) { shutdownSeen = true; receipt.restoreObserved = false; }
          check(url.pathname === POWER && method === 'POST' && !url.search && powers.length < 2);
          const raw = request.postData();
          const body = request.postDataJSON();
          check(typeof raw === 'string' && Buffer.byteLength(raw) <= 4096 && raw === JSON.stringify(body));
          const action = powers.length === 0 ? 'shutdown' : 'start', expectedState = action === 'shutdown' ? 'running' : 'stopped';
          check(object(body) && Object.keys(body).sort().join(',') === 'action,expected_state,registration_revision,request_key,target_ref');
          check(Object.values(body).every(value => typeof value === 'string') && body.action === action && body.expected_state === expectedState &&
            body.target_ref === env.TARGET_REF && body.registration_revision === env.REGISTRATION_REVISION && /^[\x21-\x7e]{1,128}$/.test(body.request_key));
          check(!powers.some(item => item.key === body.request_key));
          // This listener detects emission after the fact; it cannot prevent it.
          windowOpen();
          powers.push({action, expectedState, key: body.request_key, number: info.number, opRef: null});
        }
        if (url.pathname.startsWith('/api/lab/')) check(!url.search &&
          ((url.pathname === GUEST && method === 'GET') || (url.pathname === POWER && method === 'POST') ||
            (method === 'GET' && /^\/api\/lab\/operations\/[a-f0-9]{32}$/.test(url.pathname))));
      } catch (_) { bad(); }
    });
    page.on('requestfailed', request => { const info = requestInfo.get(request); if (info && info.path.startsWith('/api/lab/')) bad(); });
    page.on('response', response => {
      const task = (async () => {
        const request = response.request(), info = requestInfo.get(request);
        if (!info || !info.path.startsWith('/api/lab/')) return;
        check(response.status() >= 200 && response.status() < 300);
        const dto = await response.json();
        if (info.path === GUEST) {
          targetDTO(dto);
          check(Date.parse(dto.observation.observed_at) >= info.at - 1000 && Date.parse(dto.observation.observed_at) <= Date.now() + 5000);
          guests.push({number: info.number, dto});
        } else {
          const item = info.path === POWER ? powers.find(entry => entry.number === info.number) : powers[powers.length - 1];
          check(item);
          if (info.path !== POWER) check(item.opRef && info.path === OPS + item.opRef);
          const op = operationDTO(dto, item);
          operations.push({number: info.number, via: info.path === POWER ? 'submission' : 'original-operation-read', op});
          check(!['failed', 'rejected', 'uncertain'].includes(op.phase) && !['not_submitted', 'uncertain'].includes(op.acknowledgement) && op.task.state !== 'failed');
        }
      })().catch(() => bad());
      responseWork.add(task); task.finally(() => responseWork.delete(task));
    });
    async function waitUntil(predicate, ms = 15000) {
      const deadline = Date.now() + ms;
      while (Date.now() < deadline) {
        windowOpen();
        if (await predicate()) return;
        await new Promise(resolve => setTimeout(resolve, 100));
      }
      throw Error('observation_deadline');
    }
    const panel = page.locator('#registered-lab-workspace');
    async function fact(section, label) {
      return section.locator('dt').filter({hasText: new RegExp('^' + label + '$')}).evaluate(item => item.nextElementSibling.textContent);
    }
    async function screenshot(filename) {
      await page.locator('input[type="password"]').evaluateAll(inputs => inputs.forEach(input => { input.value = ''; input.removeAttribute('value'); }));
      check(await page.locator('input[type="password"]').evaluateAll(inputs => inputs.every(input => input.value === '')));
      await page.screenshot({path: path.join(evidence, filename), fullPage: true, mask: [page.locator('input[type="password"]')], timeout: 10000});
    }
    stage = 'original-login';
    await page.goto(new URL('/dashboard/registered-lab', origin).href, {waitUntil: 'domcontentloaded'});
    if (!env.RESOLVE_IP && !net.isIP(origin.hostname.replace(/^\[|\]$/g, ''))) receipt.resolver.normalDNSProven = true;
    await page.locator('#login-overlay').waitFor({state: 'visible'});
    await page.locator('#login-user').fill(env.USER);
    await page.locator('#login-pass').fill(password);
    const loginResponse = page.waitForResponse(response => new URL(response.url()).origin === origin.origin &&
      new URL(response.url()).pathname === '/api/auth/login' && response.request().method() === 'POST').catch(() => null);
    await page.locator('#login-pass').press('Enter');
    const login = await loginResponse;
    check(login && login.status() === 200);
    loggedIn = true;
    await page.locator('#login-overlay').waitFor({state: 'hidden'});
    await page.locator('#login-pass').fill('').catch(() => {});
    await panel.waitFor({state: 'visible'});
    stage = 'initial-current-guest';
    await waitUntil(() => guests.length > 0);
    const initial = guests[guests.length - 1];
    check(initial.dto.observation.state === 'running' && initial.dto.busy === false && initial.dto.operation === null);
    await waitUntil(async () => { try { return await fact(panel.locator('[data-lab-target]'), 'Current guest observation') === 'Running'; } catch (_) { return false; } });
    await page.waitForFunction(() => {
      const root = document.querySelector('#registered-lab-workspace');
      return root && Array.from(root.querySelectorAll('button')).some(button => button.textContent === 'Shut down' && !button.disabled);
    });
    await screenshot('01-initial-running.png');
    receipt.target.estate = initial.dto.target.estate;
    receipt.target.qualifiedAt = initial.dto.target.qualified_at;
    receipt.target.expiresAt = initial.dto.target.expires_at;
    receipt.initialObservation = {state: 'running', observedAt: initial.dto.observation.observed_at};
    async function cycle(action, state, filename) {
      windowOpen();
      stage = action + '-trusted-click';
      const before = powers.length, deadline = Date.now() + 120000;
      const button = panel.getByRole('button', {name: action === 'shutdown' ? 'Shut down' : 'Start', exact: true});
      check(await button.isEnabled());
      // Early refusal only; the original server expiry check governs dispatch.
      windowOpen();
      await button.click();
      stage = action + '-original-operation-observation';
      await waitUntil(() => powers.length === before + 1 && !!powers[before].opRef, 20000);
      const item = powers[before];
      // Respect the consumer's 60-second automatic observation policy. The
      // outer wait is bounded at 120 seconds and never triggers a retry/refresh.
      await waitUntil(() => operations.some(entry => entry.via === 'original-operation-read' && entry.op.ref === item.opRef &&
        entry.op.phase === 'succeeded' && entry.op.acknowledgement === 'received' && entry.op.task.state === 'succeeded' &&
        entry.op.task.exit === 'OK' && entry.op.observation.state === state), Math.max(1, deadline - Date.now()));
      const terminal = operations.find(entry => entry.via === 'original-operation-read' && entry.op.ref === item.opRef &&
        entry.op.phase === 'succeeded' && entry.op.acknowledgement === 'received' && entry.op.task.state === 'succeeded' &&
        entry.op.task.exit === 'OK' && entry.op.observation.state === state);
      stage = action + '-separate-current-guest';
      await waitUntil(() => guests.some(entry => entry.number > terminal.number && entry.dto.observation.state === state && entry.dto.busy === false));
      const fresh = guests.find(entry => entry.number > terminal.number && entry.dto.observation.state === state && entry.dto.busy === false);
      const targetSection = panel.locator('[data-lab-target]'), operationSection = panel.locator('[data-lab-operation]');
      await waitUntil(async () => { try { return await fact(targetSection, 'Current guest observation') === (state === 'running' ? 'Running' : 'Stopped'); } catch (_) { return false; } });
      check(await fact(operationSection, 'Submission acknowledgement') === 'Acknowledged');
      check(await fact(operationSection, 'Provider task observation') === 'Success');
      check(await fact(operationSection, 'Operation guest observation') === (state === 'running' ? 'Running' : 'Stopped'));
      const nextAction = panel.getByRole('button', {name: action === 'shutdown' ? 'Start' : 'Shut down', exact: true});
      await waitUntil(() => nextAction.isEnabled());
      receipt.outcomes.push({operation: publicOperation(terminal.op), freshGuestObservation: {state, observedAt: fresh.dto.observation.observed_at},
        originalOperationGETObserved: true, separateCurrentGuestGETObserved: true});
      if (action === 'start') receipt.restoreObserved = true;
      await screenshot(filename);
    }
    await cycle('shutdown', 'stopped', '02-shutdown-task-and-fresh-stopped.png');
    await cycle('start', 'running', '03-start-task-and-fresh-running.png');
    check(powers.length === 2 && powers[0].action === 'shutdown' && powers[1].action === 'start' && powers[0].key !== powers[1].key);
    stage = 'original-logout';
    await page.locator('#header-user-btn').click();
    const logoutResponse = page.waitForResponse(response => new URL(response.url()).origin === origin.origin && new URL(response.url()).pathname === '/api/auth/logout').catch(() => null);
    await page.getByRole('button', {name: 'LOG OUT', exact: true}).click();
    const logout = await logoutResponse;
    check(logout && logout.status() === 200);
    loggedIn = false;
    check(await page.evaluate(async () => {
      const response = await fetch('/api/auth/verify', {credentials: 'same-origin', cache: 'no-store'});
      const value = await response.json(); return value.valid === false;
    }));
    revoked = true;
    windowOpen();
    receipt.status = 'PASSED'; receipt.acceptance = true;
  } catch (_) {
    receipt.failedStage = stage;
    receipt.failure = fatal || 'acceptance-check-or-deadline-failed';
    if (page && evidence) {
      try {
        await page.locator('input[type="password"]').evaluateAll(inputs => inputs.forEach(input => { input.value = ''; input.removeAttribute('value'); }));
        check(await page.locator('input[type="password"]').evaluateAll(inputs => inputs.every(input => input.value === '')));
        await page.screenshot({path: path.join(evidence, 'failure.png'), fullPage: true, mask: [page.locator('input[type="password"]')], timeout: 5000});
      } catch (_) { receipt.failureScreenshot = 'unavailable'; }
    }
  } finally {
    if (interruptCleanup) await bounded(interruptCleanup, 4000).catch(() => {});
    // Authentication cleanup only. Never submit a provider action here.
    if (context && page && loggedIn && !page.isClosed() && new URL(page.url()).origin === receipt.origin) {
      try {
        check(await page.locator('#registered-lab-workspace').isVisible());
        await page.locator('#header-user-btn').click({timeout: 3000});
        const response = page.waitForResponse(value => new URL(value.url()).origin === receipt.origin && new URL(value.url()).pathname === '/api/auth/logout', {timeout: 5000}).catch(() => null);
        await page.getByRole('button', {name: 'LOG OUT', exact: true}).click({timeout: 3000});
        const logout = await response;
        if (logout && logout.status() === 200) {
          revoked = await bounded(page.evaluate(async () => (await (await fetch('/api/auth/verify', {credentials: 'same-origin', cache: 'no-store'})).json()).valid === false), 5000);
        }
      } catch (_) { receipt.logoutCleanup = 'unconfirmed'; }
    }
    if (context) { try { await bounded(context.close(), 5000); } catch (_) { receipt.contextCleanup = 'forced-browser-close'; } }
    if (browser) { try { await bounded(browser.close(), 5000); } catch (_) { /* The owned server is closed below. */ } }
    if (server) {
      try { await bounded(server.close(), 5000); }
      catch (_) {
        try { await bounded(server.kill(), 5000); }
        catch (_) {
          const process = server.process();
          if (process.exitCode === null && process.signalCode === null) process.kill('SIGKILL');
          try { await bounded(new Promise(resolve => {
            if (process.exitCode !== null || process.signalCode !== null) resolve(); else process.once('exit', resolve);
          }), 5000); } catch (_) { receipt.browserCleanup = 'unconfirmed'; receipt.acceptance = false; receipt.status = 'FAILED'; }
        }
      }
    }
    await bounded(Promise.allSettled(Array.from(responseWork)), 5000).catch(() => {});
    if (profile) { try { fs.rmSync(profile, {recursive: true, force: true, maxRetries: 2, retryDelay: 100}); } catch (_) { receipt.profileCleanup = 'unconfirmed'; receipt.acceptance = false; receipt.status = 'FAILED'; } }
    if (runtime) { try { fs.rmSync(runtime, {recursive: true, force: true, maxRetries: 2, retryDelay: 100}); } catch (_) { receipt.runtimeCleanup = 'unconfirmed'; receipt.acceptance = false; receipt.status = 'FAILED'; } }
    process.removeListener('SIGINT', interrupt); process.removeListener('SIGTERM', interrupt);
    receipt.sessionRevocationConfirmed = revoked;
    receipt.restorationRequired = shutdownSeen && !receipt.restoreObserved;
    receipt.finishedAt = new Date().toISOString();
    receipt.operationObservations = operations.map(entry => ({via: entry.via, facts: publicOperation(entry.op)}));
    receipt.requestCounts = {guestGET: requests.filter(item => item.method === 'GET' && item.path === GUEST).length,
      powerPOST: requests.filter(item => item.method === 'POST' && item.path === POWER).length,
      originalOperationGET: requests.filter(item => item.method === 'GET' && item.path.startsWith(OPS)).length,
      crossOriginMutations,
      otherNonAuthMutations: requests.filter(item => ['POST', 'PUT', 'PATCH', 'DELETE'].includes(item.method) && item.path !== POWER && !item.path.startsWith('/api/auth/')).length};
    receipt.limits = 'Original UI/API evidence only; deployment pin supplied by operator. Separate operation-recorded and fresh guest facts. No fallback, resubmission or automatic power cleanup. Password scan covers literal bytes in files, not OCR or decoded image content.';
    if (fatal) { receipt.acceptance = false; receipt.status = 'FAILED'; receipt.failure = fatal; }
    if (receipt.acceptance && (!revoked || receipt.requestCounts.powerPOST !== 2 || receipt.requestCounts.otherNonAuthMutations !== 0 || receipt.requestCounts.crossOriginMutations !== 0)) { receipt.acceptance = false; receipt.status = 'FAILED'; }
    if (evidence) {
      const containsSecret = bytes => secretBytes.some(secret => secret.length > 0 && bytes.includes(secret));
      // Recursively scan every artifact, including binary screenshots, before
      // publishing the receipt. Suspect artifacts are withheld, never printed.
      let clean = true;
      function scan(directory) {
        for (const name of fs.readdirSync(directory)) {
          const filename = path.join(directory, name), stat = fs.lstatSync(filename);
          if (stat.isDirectory()) scan(filename);
          else if (!stat.isFile() || containsSecret(fs.readFileSync(filename))) { clean = false; fs.rmSync(filename, {force: true}); }
        }
      }
      try {
        // Include receipt bytes in the same password scan before its release.
        const candidate = JSON.stringify(receipt, null, 2) + '\n';
        if (containsSecret(Buffer.from(candidate))) clean = false;
        scan(evidence);
        receipt.passwordByteScan = clean ? 'passed' : 'failed-artifacts-withheld';
        if (!clean) { receipt.acceptance = false; receipt.status = 'FAILED'; }
        const final = JSON.stringify(receipt, null, 2) + '\n';
        if (!containsSecret(Buffer.from(final))) fs.writeFileSync(path.join(evidence, 'receipt.json'), final, {mode: 0o600});
        else fs.writeFileSync(path.join(evidence, 'receipt.json'), '{"status":"FAILED","acceptance":false,"failure":"receipt-withheld-secret-byte-match"}\n', {mode: 0o600});
      } catch (_) { receipt.acceptance = false; receipt.status = 'FAILED'; }
    }
    password = null; secretBytes.forEach(bytes => bytes.fill(0));
    console.log(JSON.stringify({status: receipt.status, acceptance: receipt.acceptance, stage: receipt.failedStage || stage,
      restoreObserved: receipt.restoreObserved, restorationRequired: receipt.restorationRequired}));
    if (!receipt.acceptance) process.exitCode = 1;
  }
}
main().catch(() => { console.log('{"status":"FAILED","acceptance":false,"stage":"configuration"}'); process.exitCode = 1; });

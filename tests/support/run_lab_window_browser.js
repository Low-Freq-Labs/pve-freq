#!/usr/bin/env node
'use strict';
// Selected request-only acceptance. No power, console or withdrawal sender.
const fs = require('node:fs'), path = require('node:path'), os = require('node:os');
const https = require('node:https'), tls = require('node:tls'), net = require('node:net'), crypto = require('node:crypto');
const { execFileSync } = require('node:child_process');
const ROOT = path.resolve(__dirname, '../..'), PREFIX = 'PVE_FREQ_LAB_WINDOW_', WINDOW = '/api/lab/window', GUEST = '/api/lab/guest';
const check = value => { if (!value) throw Error('request_acceptance_failed'); };
const hash = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const keys = (value, names) => object(value) && Object.keys(value).length === names.length && names.every(name => Object.prototype.hasOwnProperty.call(value, name));
const identity = value => typeof value === 'string' && value.trim().length > 0 && value.length <= 512 && !/[\u0000-\u001f\u007f-\u009f]/.test(value);
const utc = value => typeof value === 'string' && /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?(?:Z|\+00:00)$/.test(value) &&
  Number.isFinite(Date.parse(value)) && new Date(value).toISOString().slice(0, 19) === value.slice(0, 19);
function bounded(promise, ms = 15000) {
  let timer;
  return Promise.race([promise, new Promise((_, reject) => { timer = setTimeout(() => reject(Error('deadline')), ms); })])
    .finally(() => clearTimeout(timer));
}
function policy(revision) {
  const text = execFileSync('git', ['show', revision + ':freq/services/standard_qemu_asset_policy.py'],
    { cwd: ROOT, encoding: 'utf8', timeout: 10000, maxBuffer: 1048576, stdio: ['ignore', 'pipe', 'pipe'] });
  const rows = [...text.matchAll(/^\s*\('([^']+)', '([^']+)', '([^']+)', (\d+), '([a-f0-9]{64})'\),$/gm)]
    .map(row => ({ target: row[1], mime: row[3], bytes: Number(row[4]), sha256: row[5] }));
  check(rows.length === 24 && new Set(rows.map(row => row.target)).size === 24 && rows.every(row =>
    (row.target === '/' || row.target.startsWith('/static/')) && !row.target.startsWith('//') && row.bytes > 0 && row.bytes <= 4194304));
  return { rows, sha256: hash(Buffer.from(text)) };
}
async function main() {
  // Deliberately before file reads, driver imports, timers or network activity.
  if (!process.env[PREFIX + 'SELECTED_CASE']) {
    process.stdout.write(JSON.stringify({ status: 'UNSELECTED', acceptance: false, networkRequests: 0, browserLaunched: false,
      credentialReads: 0, qualificationPosts: 0, powerPosts: 0 }) + '\n'); return;
  }
  check(process.argv.length === 2);
  const names = ['SELECTED_CASE', 'URL', 'USER', 'PASSWORD_FILE', 'EVIDENCE', 'SOURCE_REVISION', 'TARGET_REF',
    'CONFIGURATION_REVISION', 'POLICY_REVISION', 'EXPECT_SOURCE', 'CASE_START', 'CASE_END', 'CA_FILE', 'RESOLVE_IP'];
  const env = Object.fromEntries(names.map(name => [name, process.env[PREFIX + name]]));
  check(env.SELECTED_CASE === 'request-only');
  names.filter(name => !['CA_FILE', 'RESOLVE_IP'].includes(name)).forEach(name => check(typeof env[name] === 'string' && env[name].length > 0));
  check(utc(env.CASE_START) && utc(env.CASE_END));
  const start = Date.parse(env.CASE_START), end = Date.parse(env.CASE_END);
  check(end > start && Date.now() >= start && Date.now() < end);
  const origin = new URL(env.URL);
  check(origin.protocol === 'https:' && !origin.username && !origin.password && origin.pathname === '/' && !origin.search && !origin.hash);
  check(/^[a-f0-9]{40}$/.test(env.SOURCE_REVISION) && /^[a-f0-9]{64}$/.test(env.CONFIGURATION_REVISION) && /^[a-f0-9]{64}$/.test(env.POLICY_REVISION));
  check(identity(env.TARGET_REF) && identity(env.EXPECT_SOURCE));
  if (env.RESOLVE_IP) check(net.isIP(env.RESOLVE_IP) !== 0 && !net.isIP(origin.hostname) && /^[a-z0-9.-]+$/i.test(origin.hostname));
  process.umask(0o077);
  let evidence, runtime, profile, server, browser, context, page, launch, password, fatal = null, stage = 'configuration';
  let loggedIn = false, revoked = false, sequence = 0, windowClickArmed = false;
  const activeRequests = new Set(), secretBytes = [], windowPosts = [], order = new WeakMap(), replies = new WeakMap();
  const result = { schema: 'pve-freq-request-only-window-browser-v1', acceptance: false, status: 'FAILED', startedAt: new Date().toISOString(),
    selectedCase: 'request-only', caseFence: { start: env.CASE_START, end: env.CASE_END }, assets: [], checks: [], mutations: [],
    apiServerErrors: [], browserExceptions: 0, externalRequests: 0, screenshots: [], cleanup: {}, submissionOutcome: 'not-submitted',
    limitation: 'One original admin qualification request only; no power, console or automatic withdrawal. External case fence is early client refusal/emission auditing; server policy controls the grant. Logout verify:false is not independent backend window-history retirement proof.' };
  const cancel = reason => {
    fatal = fatal || reason;
    for (const request of activeRequests) request.destroy();
    if (context) bounded(context.close(), 3000).catch(() => {});
    if (browser) bounded(browser.close(), 3000).catch(() => {});
    if (server) bounded(server.kill(), 3000).catch(() => {});
  };
  const fence = () => check(!fatal && Date.now() >= start && Date.now() < end);
  const record = name => { fence(); result.checks.push(name); };
  const interrupt = () => cancel('interrupted');
  process.on('SIGINT', interrupt); process.on('SIGTERM', interrupt);
  const timer = setTimeout(() => cancel('case-or-journey-deadline'), Math.min(180000, Math.max(1, end - Date.now())));
  try {
    check(path.isAbsolute(env.EVIDENCE) && fs.realpathSync(env.EVIDENCE) === env.EVIDENCE);
    const relative = path.relative(ROOT, env.EVIDENCE), stat = fs.statSync(env.EVIDENCE);
    check((relative.startsWith('..' + path.sep) || path.isAbsolute(relative)) && stat.isDirectory() && (stat.mode & 0o777) === 0o700 &&
      (typeof process.getuid !== 'function' || stat.uid === process.getuid()) && fs.readdirSync(env.EVIDENCE).length === 0);
    evidence = env.EVIDENCE;
    result.origin = origin.origin; result.sourceRevision = env.SOURCE_REVISION; result.runnerSHA256 = hash(fs.readFileSync(__filename));
    result.sourceRevisionBasis = 'Operator-supplied deployment pin; served frontend bytes checked, backend process pin verified separately.';
    result.resolver = env.RESOLVE_IP ? { mode: 'explicit session-only override', address: env.RESOLVE_IP, normalDNSProven: false } : { mode: 'system DNS or literal origin', override: false };
    stage = 'source-preflight';
    for (const file of ['freq/services/lab_power_qualification.py', 'freq/api/lab_qualification.py']) {
      try { check(execFileSync('git', ['show', env.SOURCE_REVISION + ':' + file],
        { cwd: ROOT, encoding: 'utf8', timeout: 10000, maxBuffer: 1048576, stdio: ['ignore', 'pipe', 'pipe'] }).length > 0); }
      catch (_) { fatal = 'selected-source-missing-qualification-backend'; throw Error('source_unavailable'); }
    }
    const selected = policy(env.SOURCE_REVISION); result.assetPolicySHA256 = selected.sha256;
    let ca;
    if (env.CA_FILE) {
      check(path.isAbsolute(env.CA_FILE) && fs.realpathSync(env.CA_FILE) === env.CA_FILE);
      const info = fs.statSync(env.CA_FILE); check(info.isFile() && info.size > 0 && info.size <= 1048576);
      ca = [...tls.rootCertificates, fs.readFileSync(env.CA_FILE, 'utf8')];
    }
    stage = 'strict-tls-exact-24-assets'; fence();
    for (const expected of selected.rows) {
      fence();
      const observed = await new Promise((resolve, reject) => {
        const options = { method: 'GET', rejectUnauthorized: true, ...(ca ? { ca } : {}) };
        if (env.RESOLVE_IP) options.lookup = (hostname, settings, callback) => {
          if (hostname !== origin.hostname) return callback(Error('unexpected_lookup'));
          const answer = { address: env.RESOLVE_IP, family: net.isIP(env.RESOLVE_IP) };
          callback(null, settings && settings.all ? [answer] : answer.address, answer.family);
        };
        let size = 0; const chunks = [];
        const request = https.request(new URL(expected.target, origin), options, response => {
          const authorized = response.socket.authorized === true;
          response.on('data', bytes => { size += bytes.length; if (size > expected.bytes) request.destroy(Error('asset_limit')); else chunks.push(bytes); });
          response.on('error', reject); response.on('aborted', () => reject(Error('asset_truncated')));
          response.on('end', () => resolve({ status: response.statusCode, authorized,
            mime: String(response.headers['content-type'] || '').split(';')[0].trim(), raw: Buffer.concat(chunks) }));
        });
        activeRequests.add(request); const timeout = setTimeout(() => request.destroy(Error('deadline')), 10000);
        request.on('close', () => { clearTimeout(timeout); activeRequests.delete(request); });
        request.on('error', () => reject(Error('asset_or_tls_unavailable'))); request.end();
      });
      check(observed.authorized && observed.status === 200 && observed.mime === expected.mime && observed.raw.length === expected.bytes && hash(observed.raw) === expected.sha256);
      result.assets.push({ ...expected });
    }
    result.tls = { nodeStrictVerified: true, browserStrictDefaultTrust: true, certificateBypass: false };
    record('24-assets-exact-bytes-mime-and-strict-node-tls');
    stage = 'private-input'; fence();
    check(path.isAbsolute(env.PASSWORD_FILE) && fs.realpathSync(env.PASSWORD_FILE) === env.PASSWORD_FILE);
    const info = fs.statSync(env.PASSWORD_FILE);
    check(info.isFile() && (info.mode & 0o777) === 0o600 && info.size > 0 && info.size <= 4096 &&
      (typeof process.getuid !== 'function' || info.uid === process.getuid()));
    const bytes = fs.readFileSync(env.PASSWORD_FILE); secretBytes.push(bytes);
    password = new TextDecoder('utf-8', { fatal: true }).decode(bytes).replace(/(?:\r\n|\n)$/, '');
    check(password.length > 0 && !/[\r\n\u0000]/.test(password)); secretBytes.push(Buffer.from(password));
    stage = 'strict-browser-launch'; fence();
    runtime = fs.mkdtempSync(path.join(os.tmpdir(), 'pve-request-window-')); fs.chmodSync(runtime, 0o700);
    delete process.env.DEBUG; delete process.env.PWDEBUG; delete process.env.NODE_DEBUG;
    const { chromium } = require('playwright');
    launch = chromium.launchServer({ headless: true, timeout: 15000, handleSIGINT: false, handleSIGTERM: false,
      downloadsPath: path.join(runtime, 'downloads'), args: env.RESOLVE_IP ? ['--host-resolver-rules=MAP ' + origin.hostname + ' ' + env.RESOLVE_IP] : [] })
      .then(value => { server = value; if (fatal) bounded(server.kill(), 3000).catch(() => {}); return value; });
    await launch;
    const profileArg = server.process().spawnargs.find(value => value.startsWith('--user-data-dir=')); check(profileArg); profile = profileArg.slice('--user-data-dir='.length);
    check(path.dirname(profile) === fs.realpathSync(os.tmpdir()) && (fs.statSync(profile).mode & 0o777) === 0o700); fence();
    browser = await chromium.connect(server.wsEndpoint());
    context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, ignoreHTTPSErrors: false, serviceWorkers: 'block', acceptDownloads: false });
    context.setDefaultTimeout(20000); page = await context.newPage();
    page.on('pageerror', () => { result.browserExceptions++; });
    page.on('request', request => {
      order.set(request, ++sequence); const url = new URL(request.url()), method = request.method();
      if (['http:', 'https:', 'ws:', 'wss:'].includes(url.protocol) && url.origin !== origin.origin) { result.externalRequests++; cancel('unexpected-origin'); }
      if (!['GET', 'HEAD', 'OPTIONS'].includes(method)) {
        result.mutations.push({ method, path: url.pathname });
        if (url.origin === origin.origin && method === 'POST' && url.pathname === WINDOW) {
          result.submissionOutcome = 'unknown';
          try {
            fence(); const raw = request.postData(), payload = request.postDataJSON();
            check(windowClickArmed && windowPosts.length === 0 && JSON.stringify(payload) === raw && Object.keys(payload).sort().join(',') === 'configuration_revision,policy_revision,request_key,target_ref' &&
              Object.values(payload).every(value => typeof value === 'string') && payload.target_ref === env.TARGET_REF && payload.configuration_revision === env.CONFIGURATION_REVISION &&
              payload.policy_revision === env.POLICY_REVISION && /^[\x21-\x7e]{1,128}$/.test(payload.request_key));
            windowClickArmed = false; secretBytes.push(Buffer.from(payload.request_key)); windowPosts.push(request);
          } catch (_) { cancel('unexpected-window-intent'); }
        } else if (url.origin !== origin.origin || method !== 'POST' || !['/api/auth/login', '/api/auth/logout'].includes(url.pathname)) cancel('unexpected-non-auth-mutation');
      }
    });
    page.on('websocket', () => { result.externalRequests++; cancel('unexpected-websocket'); });
    page.on('response', response => {
      replies.set(response.request(), ++sequence); const url = new URL(response.url());
      if (url.origin === origin.origin && url.pathname.startsWith('/api/') && response.status() >= 500)
        result.apiServerErrors.push({ method: response.request().method(), path: url.pathname, status: response.status() });
    });
    const waiting = (method, target, predicate = async () => true) => page.waitForResponse(async response =>
      new URL(response.url()).origin === origin.origin && new URL(response.url()).pathname === target &&
      response.request().method() === method && await predicate(response)).catch(() => null);
    const verify = async () => {
      const value = await page.evaluate(async () => { const response = await fetch('/api/auth/verify', { credentials: 'same-origin', cache: 'no-store' });
        const data = await response.json(); return { status: response.status, valid: data.valid, user: data.user, role: data.role, csrf: data.csrf_token }; });
      if (typeof value.csrf === 'string' && value.csrf) secretBytes.push(Buffer.from(value.csrf)); delete value.csrf; return value;
    };
    const metadata = dto => {
      check(keys(dto, ['schema', 'target', 'policy', 'window', 'busy', 'can_request', 'reason']) && dto.schema === 'pve-freq-lab-window-v1' &&
        keys(dto.target, ['ref', 'configuration_revision', 'estate', 'source', 'node', 'kind', 'vmid', 'name']) && dto.target.ref === env.TARGET_REF &&
        dto.target.configuration_revision === env.CONFIGURATION_REVISION && dto.target.source === env.EXPECT_SOURCE && dto.target.kind === 'qemu' &&
        identity(dto.target.estate) && identity(dto.target.node) && identity(dto.target.name) && Number.isSafeInteger(dto.target.vmid) && dto.target.vmid > 0 &&
        keys(dto.policy, ['enabled', 'revision', 'duration_seconds', 'audience']) && dto.policy.enabled === true && dto.policy.revision === env.POLICY_REVISION && dto.policy.duration_seconds === 900 &&
        dto.policy.audience === 'original_session' && typeof dto.busy === 'boolean' && typeof dto.can_request === 'boolean' &&
        (dto.reason === null || (typeof dto.reason === 'string' && /^[a-z][a-z0-9_]{0,127}$/.test(dto.reason))));
      check(dto.window === null || (keys(dto.window, ['ref', 'state', 'registration_revision', 'qualified_at', 'expires_at', 'error']) &&
        identity(dto.window.ref) && ['preparing', 'active', 'expired', 'rejected', 'retired'].includes(dto.window.state)));
      return dto;
    };
    const snapshot = async file => {
      fence(); await page.locator('input[type="password"]').evaluateAll(inputs => inputs.forEach(input => { input.value = ''; input.removeAttribute('value'); }));
      check(await page.locator('input[type="password"]').evaluateAll(inputs => inputs.every(input => input.value === '')));
      await page.evaluate(() => window.scrollTo(0, 0));
      await page.screenshot({ path: path.join(evidence, file), fullPage: true, mask: [page.locator('input[type="password"]')], timeout: 10000 }); result.screenshots.push(file);
    };
    stage = 'original-admin-login'; fence();
    const entry = await page.goto(new URL('/dashboard/registered-lab', origin).href, { waitUntil: 'domcontentloaded' });
    check(entry.status() === 200 && new URL(page.url()).origin === origin.origin && hash(await entry.body()) === selected.rows.find(row => row.target === '/').sha256);
    await page.locator('#login-overlay').waitFor({ state: 'visible' }); fence();
    await page.locator('#login-user').fill(env.USER); await page.locator('#login-pass').fill(password);
    const loginWait = waiting('POST', '/api/auth/login'), initialWindow = waiting('GET', WINDOW), initialGuest = waiting('GET', GUEST);
    fence(); await page.locator('#login-pass').press('Enter'); check((await loginWait)?.status() === 200); loggedIn = true;
    await page.locator('#login-overlay').waitFor({ state: 'hidden' });
    const session = await verify(); check(session.status === 200 && session.valid === true && session.user === env.USER && ['admin', 'protected'].includes(session.role));
    const originalCookie = (await context.cookies(origin.origin)).find(cookie => cookie.name === 'freq_session');
    check(originalCookie && originalCookie.value); secretBytes.push(Buffer.from(originalCookie.value));
    const initial = await initialWindow, before = metadata(await initial.json()), diagnosticResponse = await initialGuest, diagnostic = await diagnosticResponse.json();
    check(initial.status() === 200 && before.window === null && before.can_request === true && before.busy === false && before.reason === null);
    const matchesTarget = target => object(target) && target.ref === env.TARGET_REF && ['estate', 'source', 'node', 'kind', 'vmid', 'name'].every(key => target[key] === before.target[key]);
    check(diagnosticResponse.status() === 200 && keys(diagnostic, ['schema', 'target', 'capabilities', 'observation', 'busy', 'operation']) && diagnostic.schema === 'pve-freq-lab-guest-view-v1' && matchesTarget(diagnostic.target) &&
      keys(diagnostic.capabilities, ['lab_only', 'actions']) && diagnostic.capabilities.lab_only === true && Array.isArray(diagnostic.capabilities.actions) && diagnostic.capabilities.actions.length === 0 &&
      diagnostic.busy === false && diagnostic.operation === null && ['running', 'stopped'].includes(diagnostic.observation?.state));
    const power = page.locator('#registered-lab-workspace');
    for (const name of ['Start', 'Shut down']) { await power.getByRole('button', { name, exact: true }).waitFor(); check(await power.getByRole('button', { name, exact: true }).isDisabled()); }
    check(windowPosts.length === 0); record('configured-policy-and-diagnostic-guest-with-no-auto-post');
    await snapshot('01-request-only-before.png');
    stage = 'one-trusted-window-request';
    const postWait = waiting('POST', WINDOW), confirmedWait = waiting('GET', WINDOW, async response => (await response.json()).window?.state === 'active');
    const guestWait = waiting('GET', GUEST, async response => (await response.json()).capabilities?.actions?.includes('shutdown'));
    const button = page.getByRole('button', { name: 'Request lab window', exact: true });
    check(await button.isEnabled()); fence(); windowClickArmed = true;
    await button.click({ timeout: Math.max(1, Math.min(20000, end - Date.now())) });
    const post = await postWait; check(post); const admitted = metadata(await post.json());
    check(post.status() === 201 && admitted.window?.state === 'active');
    const grant = admitted.window;
    check(identity(grant.ref) && /^[a-f0-9]{64}$/.test(grant.registration_revision) && utc(grant.qualified_at) && utc(grant.expires_at) &&
      Date.parse(grant.expires_at) - Date.parse(grant.qualified_at) === 900000 && Date.parse(grant.qualified_at) <= Date.now() && Date.now() < Date.parse(grant.expires_at) && grant.error === null);
    check(grant.registration_revision !== env.CONFIGURATION_REVISION && grant.registration_revision !== diagnostic.target.registration_revision);
    result.submissionOutcome = 'acknowledged-active';
    stage = 'separate-metadata-and-current-guest';
    const confirmedResponse = await confirmedWait; check(confirmedResponse); const confirmed = metadata(await confirmedResponse.json());
    const freshResponse = await guestWait; check(freshResponse); const fresh = await freshResponse.json();
    check(confirmedResponse.status() === 200 && confirmed.window.ref === grant.ref && ['registration_revision', 'qualified_at', 'expires_at'].every(key => confirmed.window[key] === grant[key]) &&
      order.get(confirmedResponse.request()) > replies.get(post.request()) && order.get(freshResponse.request()) > replies.get(confirmedResponse.request()) &&
      freshResponse.status() === 200 && fresh.schema === 'pve-freq-lab-guest-view-v1' && matchesTarget(fresh.target) &&
      fresh.target.registration_revision === grant.registration_revision && fresh.target.qualified_at === grant.qualified_at && fresh.target.expires_at === grant.expires_at &&
      fresh.capabilities?.lab_only === true && fresh.capabilities.actions?.join(',') === 'start,shutdown' && fresh.busy === false && fresh.operation === null &&
      ['running', 'stopped'].includes(fresh.observation?.state) && utc(fresh.observation.observed_at));
    const eligible = fresh.observation.state === 'running' ? 'Shut down' : 'Start', disabled = eligible === 'Start' ? 'Shut down' : 'Start';
    await page.waitForFunction(name => Array.from(document.querySelectorAll('#registered-lab-workspace button')).some(button => button.textContent === name && !button.disabled), eligible);
    check(await power.getByRole('button', { name: disabled, exact: true }).isDisabled() && await button.isDisabled());
    result.grant = { ref: grant.ref, registrationRevision: grant.registration_revision, qualifiedAt: grant.qualified_at, expiresAt: grant.expires_at };
    result.target = { ...before.target }; result.freshGuestObservation = { state: fresh.observation.state, observedAt: fresh.observation.observed_at };
    result.powerEligibilityObserved = eligible; record('one-window-post-independent-metadata-then-fresh-guest-no-power-click');
    await snapshot('02-request-only-active-1440.png'); await page.setViewportSize({ width: 390, height: 844 });
    try { check(await page.evaluate(() => document.documentElement.scrollWidth <= 390)); await snapshot('03-request-only-active-390.png'); }
    finally { await page.setViewportSize({ width: 1440, height: 1000 }); }
    stage = 'original-logout'; await page.locator('#header-user-btn').click(); const logoutWait = waiting('POST', '/api/auth/logout');
    await page.getByRole('button', { name: 'LOG OUT', exact: true }).click(); check((await logoutWait)?.status() === 200); loggedIn = false;
    check((await verify()).valid === false); revoked = true; record('original-session-verify-invalid-after-logout');
    result.firstSessionRevocationConfirmed = true;
    stage = 'fresh-original-session-login'; fence();
    await context.clearCookies();
    await page.goto(new URL('/dashboard/registered-lab', origin).href, { waitUntil: 'domcontentloaded' });
    await page.locator('#login-overlay').waitFor({ state: 'visible' }); fence();
    await page.locator('#login-user').fill(env.USER); await page.locator('#login-pass').fill(password);
    const secondLogin = waiting('POST', '/api/auth/login'), secondWindow = waiting('GET', WINDOW), secondGuest = waiting('GET', GUEST);
    fence(); revoked = false; await page.locator('#login-pass').press('Enter'); check((await secondLogin)?.status() === 200); loggedIn = true;
    await page.locator('#login-overlay').waitFor({ state: 'hidden' });
    const secondSession = await verify();
    check(secondSession.status === 200 && secondSession.valid === true && secondSession.user === env.USER && ['admin', 'protected'].includes(secondSession.role));
    const secondCookie = (await context.cookies(origin.origin)).find(cookie => cookie.name === 'freq_session');
    check(secondCookie && secondCookie.value && secondCookie.value !== originalCookie.value); secretBytes.push(Buffer.from(secondCookie.value));
    stage = 'fresh-session-no-inherited-window-or-power';
    const secondWindowResponse = await secondWindow, secondGuestResponse = await secondGuest;
    check(secondWindowResponse && secondGuestResponse);
    const ungranted = metadata(await secondWindowResponse.json()), secondDiagnostic = await secondGuestResponse.json();
    check(secondWindowResponse.status() === 200 && ungranted.window === null &&
      secondGuestResponse.status() === 200 && keys(secondDiagnostic, ['schema', 'target', 'capabilities', 'observation', 'busy', 'operation']) &&
      secondDiagnostic.schema === 'pve-freq-lab-guest-view-v1' && matchesTarget(secondDiagnostic.target) &&
      ['registration_revision', 'qualified_at', 'expires_at'].every(key => secondDiagnostic.target[key] === diagnostic.target[key]) &&
      keys(secondDiagnostic.capabilities, ['lab_only', 'actions']) && secondDiagnostic.capabilities.lab_only === true &&
      Array.isArray(secondDiagnostic.capabilities.actions) && secondDiagnostic.capabilities.actions.length === 0 &&
      secondDiagnostic.busy === false && secondDiagnostic.operation === null && ['running', 'stopped'].includes(secondDiagnostic.observation?.state) && utc(secondDiagnostic.observation.observed_at));
    await page.waitForFunction(canRequest => {
      const root = document.querySelector('#registered-lab-workspace');
      const buttons = root ? Array.from(root.querySelectorAll('button')) : [];
      return ['Start', 'Shut down'].every(name => buttons.some(button => button.textContent === name && button.disabled)) &&
        Array.from(document.querySelectorAll('button')).some(button => button.textContent === 'Request lab window' && button.disabled === !canRequest);
    }, ungranted.can_request);
    check(windowPosts.length === 1); result.freshSession = { cookieChanged: true, inheritedWindow: false, actions: [],
      canRequest: ungranted.can_request, reason: ungranted.reason, observedState: secondDiagnostic.observation.state, observedAt: secondDiagnostic.observation.observed_at };
    record('fresh-cookie-session-has-no-inherited-grant-or-power-no-second-request');
    stage = 'second-original-logout'; fence();
    await page.locator('#header-user-btn').click(); const secondLogout = waiting('POST', '/api/auth/logout');
    await page.getByRole('button', { name: 'LOG OUT', exact: true }).click(); check((await secondLogout)?.status() === 200); loggedIn = false;
    check((await verify()).valid === false); revoked = true; record('second-original-session-verify-invalid-after-logout');
    check(windowPosts.length === 1 && result.apiServerErrors.length === 0 && result.browserExceptions === 0 && result.externalRequests === 0);
    result.status = 'PASSED'; result.acceptance = true;
  } catch (_) { result.failureStage = stage; result.failure = fatal || 'request-check-or-deadline-failed'; }
  finally {
    clearTimeout(timer); for (const request of activeRequests) request.destroy();
    if (page && context && loggedIn && !page.isClosed()) {
      try {
        await page.locator('#header-user-btn').click({ timeout: 3000 });
        const waiting = page.waitForResponse(response => new URL(response.url()).origin === origin.origin && new URL(response.url()).pathname === '/api/auth/logout', { timeout: 5000 }).catch(() => null);
        await page.getByRole('button', { name: 'LOG OUT', exact: true }).click({ timeout: 3000 });
        if ((await waiting)?.status() === 200) revoked = await bounded(page.evaluate(async () => (await (await fetch('/api/auth/verify')).json()).valid === false), 5000);
      } catch (_) { result.cleanup.logout = 'unconfirmed'; }
    }
    if (launch) await bounded(launch, 16000).catch(() => {});
    for (const [name, close] of [['contextClosed', () => context && context.close()], ['browserClosed', () => server ? server.close() : browser && browser.close()]]) {
      try { await bounded(Promise.resolve(close()), 5000); result.cleanup[name] = true; } catch (_) { result.cleanup[name] = false; result.acceptance = false; }
    }
    if (server) {
      const child = server.process();
      if (child.exitCode === null && child.signalCode === null) { await bounded(server.kill(), 3000).catch(() => {});
        if (child.exitCode === null && child.signalCode === null) child.kill('SIGKILL');
        await bounded(new Promise(resolve => { if (child.exitCode !== null || child.signalCode !== null) resolve(); else child.once('exit', resolve); }), 5000).catch(() => {}); }
      result.cleanup.browserProcessClosed = child.exitCode !== null || child.signalCode !== null;
      if (!result.cleanup.browserProcessClosed) result.acceptance = false;
    }
    for (const [name, directory] of [['profileRemoved', profile], ['runtimeRemoved', runtime]]) {
      try { if (directory) fs.rmSync(directory, { recursive: true, force: true, maxRetries: 2 }); result.cleanup[name] = !directory || !fs.existsSync(directory); }
      catch (_) { result.cleanup[name] = false; result.acceptance = false; }
    }
    password = null; process.removeListener('SIGINT', interrupt); process.removeListener('SIGTERM', interrupt);
    result.sessionRevocationConfirmed = revoked;
    result.counts = { windowPOST: result.mutations.filter(row => row.method === 'POST' && row.path === WINDOW).length,
      powerPOST: result.mutations.filter(row => row.method === 'POST' && row.path === '/api/lab/power').length,
      consolePOST: result.mutations.filter(row => row.method === 'POST' && row.path.startsWith('/api/lab/console')).length,
      otherNonAuthMutations: result.mutations.filter(row => !(row.method === 'POST' && [WINDOW, '/api/auth/login', '/api/auth/logout'].includes(row.path))).length };
    result.finishedAt = new Date().toISOString();
    if (!revoked || fatal || result.counts.windowPOST !== 1 || result.counts.powerPOST !== 0 || result.counts.consolePOST !== 0 || result.counts.otherNonAuthMutations !== 0) result.acceptance = false;
    if (!result.acceptance) result.status = 'FAILED';
    if (evidence) {
      const contains = bytes => secretBytes.some(secret => secret.length && bytes.includes(secret)); let clean = true;
      const scan = directory => { for (const name of fs.readdirSync(directory)) { const file = path.join(directory, name), stat = fs.lstatSync(file);
        if (stat.isDirectory()) scan(file); else if (!stat.isFile() || contains(fs.readFileSync(file))) { fs.rmSync(file, { force: true }); clean = false; } } };
      try {
        scan(evidence); if (contains(Buffer.from(JSON.stringify(result)))) clean = false;
        result.secretByteScan = clean ? 'passed; recursive literal bytes, no OCR' : 'failed; suspect artifacts withheld';
        if (!clean) { result.acceptance = false; result.status = 'FAILED'; }
        const output = Buffer.from(JSON.stringify(result, null, 2) + '\n');
        if (!contains(output)) fs.writeFileSync(path.join(evidence, 'request-only-window.json'), output, { mode: 0o600 });
        else result.acceptance = false;
      } catch (_) { result.acceptance = false; }
    }
    process.stdout.write(result.acceptance ? 'Request-only window acceptance passed.\n' : 'Request-only window acceptance failed; inspect sanitized receipt.\n');
    process.exitCode = result.acceptance ? 0 : 1;
  }
}
main().catch(() => { process.stderr.write('Request-only runner configuration failed; private details withheld.\n'); process.exitCode = 1; });

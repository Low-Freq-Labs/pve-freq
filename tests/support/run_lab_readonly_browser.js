#!/usr/bin/env node
'use strict';
// Original normal-443 read acceptance only. No grant, power or console helper.
const fs = require('node:fs'), path = require('node:path'), os = require('node:os');
const https = require('node:https'), tls = require('node:tls'), crypto = require('node:crypto');
const { execFileSync } = require('node:child_process');
const ROOT = path.resolve(__dirname, '../..'), PREFIX = 'PVE_FREQ_READONLY_';
const GUEST = '/api/lab/guest', INVENTORY = '/api/pve/inventory';
function check(value) { if (!value) throw Error('read_acceptance_failed'); }
function bounded(promise, ms = 15000) {
  let timer;
  return Promise.race([promise, new Promise((_, reject) => { timer = setTimeout(() => reject(Error('deadline')), ms); })])
    .finally(() => clearTimeout(timer));
}
const hash = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const utc = value => typeof value === 'string' && /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?(?:Z|\+00:00)$/.test(value) &&
  Number.isFinite(Date.parse(value)) && new Date(value).toISOString().slice(0, 19) === value.slice(0, 19);
function assetPolicy(revision) {
  const source = execFileSync('git', ['show', revision + ':freq/services/standard_qemu_asset_policy.py'],
    { cwd: ROOT, encoding: 'utf8', timeout: 10000, maxBuffer: 1048576, stdio: ['ignore', 'pipe', 'pipe'] });
  const rows = [...source.matchAll(/^\s*\('([^']+)', '([^']+)', '([^']+)', (\d+), '([a-f0-9]{64})'\),$/gm)]
    .map(row => ({ target: row[1], key: row[2], mime: row[3], bytes: Number(row[4]), sha256: row[5] }));
  check(rows.length === 21 && new Set(rows.map(row => row.target)).size === 21);
  check(rows.every(row => (row.target === '/' || row.target.startsWith('/static/')) && !row.target.startsWith('//') &&
    row.bytes > 0 && row.bytes <= 4 * 1024 * 1024));
  return { rows, policySHA256: hash(Buffer.from(source)) };
}
async function main() {
  check(process.argv.length === 2);
  process.umask(0o077);
  const env = Object.fromEntries(['URL', 'USER', 'PASSWORD_FILE', 'EVIDENCE', 'SOURCE_REVISION', 'CA_FILE', 'EXPECT_LAB_VIEW']
    .map(name => [name, process.env[PREFIX + name]]));
  const receipt = { schema: 'pve-freq-normal-read-browser-v1', passed: false, startedAt: new Date().toISOString(),
    checks: [], assets: [], labReads: [], apiServerErrors: [], mutations: [], externalRequests: 0, browserExceptions: 0, cleanup: {},
    limitation: 'Original normal-443 read/UI evidence only. Operator-supplied deployment pin is checked separately. No qualification, power, console or provider-effect acceptance. Secret scanning is literal bytes, not OCR.' };
  let evidence, runtime, profile, server, browser, context, page, password, stage = 'configuration', fatal = null, revoked = false;
  let launch, loggedIn = false;
  const secrets = [], requests = new Set();
  const guard = () => check(!fatal);
  const record = name => { guard(); receipt.checks.push(name); };
  const cancel = reason => {
    fatal = fatal || reason;
    for (const request of requests) request.destroy();
    if (context) bounded(context.close(), 3000).catch(() => {});
    if (server) bounded(server.kill(), 3000).catch(() => {});
  };
  const interrupt = () => cancel('interrupted');
  const journeyDeadline = setTimeout(() => cancel('journey-deadline'), 120000);
  process.on('SIGINT', interrupt); process.on('SIGTERM', interrupt);
  try {
    for (const name of ['URL', 'USER', 'PASSWORD_FILE', 'EVIDENCE', 'SOURCE_REVISION', 'EXPECT_LAB_VIEW']) check(typeof env[name] === 'string' && env[name].length > 0);
    check(/^[a-f0-9]{40}$/.test(env.SOURCE_REVISION) && ['status-only', 'unavailable'].includes(env.EXPECT_LAB_VIEW));
    const origin = new URL(env.URL);
    check(origin.protocol === 'https:' && !origin.username && !origin.password && origin.pathname === '/' && !origin.search && !origin.hash && (!origin.port || origin.port === '443'));
    check(path.isAbsolute(env.EVIDENCE) && fs.realpathSync(env.EVIDENCE) === env.EVIDENCE);
    const relative = path.relative(ROOT, env.EVIDENCE), stat = fs.statSync(env.EVIDENCE);
    check((relative.startsWith('..' + path.sep) || path.isAbsolute(relative)) && stat.isDirectory() && (stat.mode & 0o777) === 0o700 && fs.readdirSync(env.EVIDENCE).length === 0);
    evidence = env.EVIDENCE;
    receipt.origin = origin.origin; receipt.sourceRevision = env.SOURCE_REVISION;
    receipt.sourceRevisionBasis = 'Operator supplied; this runner verifies pinned asset bytes, not server process/deployment ownership.';
    receipt.expectedLabView = env.EXPECT_LAB_VIEW;
    receipt.runnerSHA256 = hash(fs.readFileSync(__filename));
    const policy = assetPolicy(env.SOURCE_REVISION); receipt.policySHA256 = policy.policySHA256;
    let ca;
    if (env.CA_FILE) {
      check(path.isAbsolute(env.CA_FILE) && fs.realpathSync(env.CA_FILE) === env.CA_FILE);
      const info = fs.statSync(env.CA_FILE); check(info.isFile() && info.size > 0 && info.size <= 1048576);
      ca = [...tls.rootCertificates, fs.readFileSync(env.CA_FILE, 'utf8')];
    }
    stage = 'strict-tls-and-exact-assets';
    const readAsset = expected => new Promise((resolve, reject) => {
      guard();
      let timer, size = 0; const chunks = [];
      const request = https.request(new URL(expected.target, origin), { method: 'GET', rejectUnauthorized: true, ...(ca ? { ca } : {}) }, response => {
        const authorized = response.socket.authorized === true;
        response.on('data', chunk => { size += chunk.length; if (size > expected.bytes) request.destroy(Error('asset_limit')); else chunks.push(chunk); });
        response.on('error', reject);
        response.on('aborted', () => reject(Error('asset_truncated')));
        response.on('end', () => {
          try {
            const raw = Buffer.concat(chunks), mime = String(response.headers['content-type'] || '').split(';')[0].trim().toLowerCase();
            check(authorized && response.statusCode === 200 && size === expected.bytes && mime === expected.mime && hash(raw) === expected.sha256);
            resolve({ target: expected.target, bytes: size, mime, sha256: expected.sha256 });
          } catch (_) { reject(Error('asset_or_tls_mismatch')); }
        });
      });
      requests.add(request); timer = setTimeout(() => request.destroy(Error('deadline')), 10000);
      request.on('close', () => { clearTimeout(timer); requests.delete(request); });
      request.on('error', () => reject(Error('asset_or_tls_unavailable'))); request.end();
    });
    for (let index = 0; index < policy.rows.length; index += 4) receipt.assets.push(...await Promise.all(policy.rows.slice(index, index + 4).map(readAsset)));
    receipt.tls = { nodeStrictVerified: true, browserStrictDefaultTrust: true, certificateBypass: false, resolverOverride: false };
    record('all-21-pinned-assets-size-sha256-mime-and-strict-node-tls');
    stage = 'private-password';
    check(path.isAbsolute(env.PASSWORD_FILE) && fs.realpathSync(env.PASSWORD_FILE) === env.PASSWORD_FILE);
    const passwordStat = fs.statSync(env.PASSWORD_FILE);
    check(passwordStat.isFile() && (passwordStat.mode & 0o777) === 0o600 && passwordStat.size > 0 && passwordStat.size <= 4096 &&
      (typeof process.getuid !== 'function' || passwordStat.uid === process.getuid()));
    const bytes = fs.readFileSync(env.PASSWORD_FILE); secrets.push(bytes);
    password = new TextDecoder('utf-8', { fatal: true }).decode(bytes).replace(/(?:\r\n|\n)$/, '');
    check(password.length > 0 && !/[\r\n\u0000]/.test(password)); secrets.push(Buffer.from(password));
    stage = 'strict-browser-launch'; guard();
    runtime = fs.mkdtempSync(path.join(os.tmpdir(), 'pve-normal-read-')); fs.chmodSync(runtime, 0o700);
    delete process.env.DEBUG; delete process.env.PWDEBUG; delete process.env.NODE_DEBUG;
    const { chromium } = require('playwright');
    launch = chromium.launchServer({ headless: true, timeout: 15000, handleSIGINT: false, handleSIGTERM: false,
      downloadsPath: path.join(runtime, 'downloads') }).then(value => { server = value; return value; });
    await launch;
    const profileArg = server.process().spawnargs.find(value => value.startsWith('--user-data-dir='));
    check(profileArg); profile = profileArg.slice('--user-data-dir='.length);
    check(path.dirname(profile) === fs.realpathSync(os.tmpdir()) && (fs.statSync(profile).mode & 0o777) === 0o700);
    guard();
    browser = await chromium.connect(server.wsEndpoint());
    context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, ignoreHTTPSErrors: false, serviceWorkers: 'block', acceptDownloads: false });
    context.setDefaultTimeout(15000); page = await context.newPage();
    page.on('pageerror', () => { receipt.browserExceptions++; });
    page.on('request', request => {
      const url = new URL(request.url()), method = request.method();
      if (['http:', 'https:', 'ws:', 'wss:'].includes(url.protocol) && url.origin !== origin.origin) {
        receipt.externalRequests++; cancel('unexpected-origin-request');
      }
      if (!['GET', 'HEAD', 'OPTIONS'].includes(method)) {
        receipt.mutations.push({ method, path: url.pathname });
        if (url.origin !== origin.origin || method !== 'POST' || !['/api/auth/login', '/api/auth/logout'].includes(url.pathname)) {
          fatal = 'unexpected-non-auth-mutation'; bounded(context.close(), 3000).catch(() => {});
        }
      }
    });
    page.on('websocket', () => { receipt.externalRequests++; cancel('unexpected-websocket'); }); // No socket is needed.
    page.on('response', response => {
      const url = new URL(response.url());
      if (url.origin === origin.origin && url.pathname.startsWith('/api/') && response.status() >= 500)
        receipt.apiServerErrors.push({ method: response.request().method(), path: url.pathname, status: response.status() });
    });
    const responseFor = target => page.waitForResponse(response => new URL(response.url()).origin === origin.origin &&
      new URL(response.url()).pathname === target && response.request().method() === 'GET').catch(() => null);
    const verify = () => page.evaluate(async () => {
      const response = await fetch('/api/auth/verify', { credentials: 'same-origin', cache: 'no-store' });
      const data = await response.json(); return { status: response.status, valid: data.valid, user: data.user, role: data.role };
    });
    const snapshot = async name => {
      await page.locator('input[type="password"]').evaluateAll(inputs => inputs.forEach(input => { input.value = ''; input.removeAttribute('value'); }));
      check(await page.locator('input[type="password"]').evaluateAll(inputs => inputs.every(input => input.value === '')));
      await page.evaluate(() => window.scrollTo(0, 0));
      await page.screenshot({ path: path.join(evidence, name), fullPage: true, mask: [page.locator('input[type="password"]')], timeout: 10000 });
    };
    stage = 'original-admin-login';
    const entry = await page.goto(new URL('/dashboard/home', origin).href, { waitUntil: 'domcontentloaded' });
    guard(); check(new URL(page.url()).origin === origin.origin && entry.status() === 200 &&
      hash(await entry.body()) === policy.rows.find(row => row.target === '/').sha256);
    await page.locator('#login-overlay').waitFor({ state: 'visible' });
    await page.locator('#login-user').fill(env.USER); await page.locator('#login-pass').fill(password);
    const loginWait = page.waitForResponse(response => new URL(response.url()).origin === origin.origin && new URL(response.url()).pathname === '/api/auth/login' && response.request().method() === 'POST').catch(() => null);
    await page.locator('#login-pass').press('Enter'); check((await loginWait).status() === 200); loggedIn = true;
    await page.locator('#login-overlay').waitFor({ state: 'hidden' });
    const identity = await verify(); check(identity.status === 200 && identity.valid === true && identity.user === env.USER && identity.role === 'admin');
    await page.locator('#home-widgets .pve-cockpit[aria-busy="false"]').waitFor();
    record('original-admin-cookie-session');
    const primary = page.getByRole('navigation', { name: 'Primary' });
    const fleet = async () => {
      const waiting = responseFor(INVENTORY); await primary.locator('[data-view="fleet"]').click();
      const response = await waiting, dto = await response.json();
      check(response.status() === 200 && dto.schema === 1 && dto.read_only === true && ['ok', 'partial'].includes(dto.state) && Array.isArray(dto.sources));
      const nodes = dto.sources.flatMap(source => source.nodes), guests = dto.sources.flatMap(source => source.guests);
      check(nodes.length > 0 && guests.length > 0 && dto.sources.every(source => typeof source.source === 'string' && source.source.length > 0 &&
        ['ok', 'unavailable'].includes(source.state) && Array.isArray(source.nodes) && Array.isArray(source.guests)));
      check(nodes.every(node => object(node) && typeof node.node === 'string' && node.node.length > 0) &&
        guests.every(guest => object(guest) && ['qemu', 'lxc'].includes(guest.type) && Number.isSafeInteger(guest.vmid) && guest.vmid > 0 && typeof guest.node === 'string'));
      const root = page.locator('#pve-inventory-report'); await root.locator('.pve-cockpit[aria-busy="false"]').waitFor();
      check(await root.locator('[data-inventory-kind="node"]').count() === nodes.length && await root.locator('[data-inventory-kind="guest"]').count() === guests.length);
      const first = guests[0], host = root.locator('.pve-inventory-host').filter({ has: page.getByRole('heading', { name: dto.sources.find(source => source.guests.includes(first)).source, exact: true }) });
      const row = host.locator('[data-inventory-kind="guest"]').filter({ has: page.getByText(`ID ${first.vmid} · ${first.node}`, { exact: true }) })
        .filter({ has: page.getByText(first.type === 'qemu' ? 'VM' : 'LXC', { exact: true }) });
      await row.getByRole('button', { name: /^Details for / }).click();
      check((await root.locator('[data-inventory-detail]').textContent()).includes(String(first.vmid)));
      receipt.fleet = { state: dto.state, nodes: nodes.length, guests: guests.length, kinds: [...new Set(guests.map(guest => guest.type))] };
    };
    const lab = async waiting => {
      const response = await waiting, dto = await response.json(), status = response.status();
      if (status !== 200 && !(env.EXPECT_LAB_VIEW === 'unavailable' && ((status === 404 && dto.error === 'not_found') ||
          (status === 503 && ['registration_unavailable', 'registration_expired'].includes(dto.error))))) {
        const known = ['not_found', 'registration_unavailable', 'registration_expired', 'invalid_registration', 'credentials_unavailable',
          'provider_unavailable', 'configuration_unavailable', 'operation_unavailable', 'invalid_response', 'state_mismatch', 'registration_changed', 'session_retired', 'authentication_required'];
        receipt.labReads.push({ status, mode: 'unexpected', error: known.includes(dto && dto.error) ? dto.error : 'unrecognized_error' });
        check(false);
      }
      const panel = page.locator('#registered-lab-workspace'); await panel.waitFor();
      await panel.getByRole('button', { name: 'Start', exact: true }).waitFor();
      check(await panel.getByRole('button', { name: 'Start', exact: true }).isDisabled() && await panel.getByRole('button', { name: 'Shut down', exact: true }).isDisabled());
      if (env.EXPECT_LAB_VIEW === 'status-only') {
        const target = dto.target;
        check(status === 200 && dto.schema === 'pve-freq-lab-guest-view-v1' && object(target) && target.source === '10.25.10.203' &&
          target.node === 'branch-pve' && target.kind === 'qemu' && target.vmid === 120 && target.name === 'branch-test-vm' &&
          typeof target.ref === 'string' && /^[a-f0-9]{64}$/.test(target.registration_revision) &&
          utc(target.qualified_at) && utc(target.expires_at) && Date.parse(target.expires_at) > Date.parse(target.qualified_at) &&
          object(dto.capabilities) && dto.capabilities.lab_only === true && Array.isArray(dto.capabilities.actions) && dto.capabilities.actions.length === 0 &&
          object(dto.observation) && ['running', 'stopped', 'unknown'].includes(dto.observation.state) && typeof dto.busy === 'boolean');
        await panel.getByRole('heading', { name: 'branch-test-vm', exact: true }).waitFor();
        check((await panel.locator('[data-lab-target]').textContent()).includes('10.25.10.203'));
        receipt.labReads.push({ status, mode: 'status-only', source: target.source, node: target.node, kind: target.kind, vmid: target.vmid,
          name: target.name, actions: [], observedState: dto.observation.state });
      } else {
        check(object(dto) && ((status === 404 && dto.error === 'not_found') ||
          (status === 503 && ['registration_unavailable', 'registration_expired'].includes(dto.error))));
        await page.waitForFunction(() => !document.querySelector('#registered-lab-workspace [data-lab-target] h4') &&
          document.querySelector('#registered-lab-workspace .lab-registration-state').textContent === 'Registration unavailable');
        check(!(await panel.textContent()).includes('branch-test-vm'));
        receipt.labReads.push({ status, mode: 'unavailable', error: dto.error, targetClaim: false });
      }
    };
    stage = 'original-fleet-read'; await fleet(); await snapshot('01-fleet-readonly.png'); record('populated-original-fleet-and-details');
    stage = 'original-lab-read';
    const initialLab = responseFor(GUEST); await primary.locator('[data-view="registered-lab"]').click(); await lab(initialLab);
    await snapshot('02-lab-readonly.png');
    stage = 'lab-deep-reload'; const reloadLab = responseFor(GUEST); await page.reload({ waitUntil: 'domcontentloaded' }); await lab(reloadLab);
    const afterReload = await verify();
    check(new URL(page.url()).pathname === '/dashboard/registered-lab' && afterReload.valid === true && afterReload.user === env.USER && afterReload.role === 'admin'); record('lab-exact-mode-deep-reload-and-session');
    await page.setViewportSize({ width: 390, height: 844 });
    try {
      check(await page.evaluate(() => document.documentElement.scrollWidth <= 390)); await snapshot('03-lab-phone-readonly.png');
      if (!(await primary.isVisible())) await page.getByRole('button', { name: 'Menu', exact: true }).click();
      await fleet(); check(await page.evaluate(() => document.documentElement.scrollWidth <= 390)); await snapshot('04-fleet-phone-readonly.png');
    } finally { await page.setViewportSize({ width: 1440, height: 1000 }); }
    record('phone-lab-and-fleet-no-overflow');
    stage = 'logout'; await page.locator('#header-user-btn').click();
    const logoutWait = page.waitForResponse(response => new URL(response.url()).origin === origin.origin && new URL(response.url()).pathname === '/api/auth/logout' && response.request().method() === 'POST').catch(() => null);
    await page.getByRole('button', { name: 'LOG OUT', exact: true }).click(); check((await logoutWait).status() === 200); loggedIn = false;
    check((await verify()).valid === false); revoked = true; record('logout-session-revocation');
    const unexpected = receipt.apiServerErrors.filter(row => !(env.EXPECT_LAB_VIEW === 'unavailable' && row.method === 'GET' && row.path === GUEST && row.status === 503));
    check(unexpected.length === 0 && receipt.browserExceptions === 0 && receipt.externalRequests === 0 && !fatal);
    check(receipt.mutations.every(row => row.method === 'POST' && ['/api/auth/login', '/api/auth/logout'].includes(row.path)));
    receipt.passed = true;
  } catch (_) { receipt.failureStage = stage; receipt.failure = fatal || 'read-check-or-deadline-failed'; }
  finally {
    clearTimeout(journeyDeadline);
    for (const request of requests) request.destroy();
    if (page && context && loggedIn && !page.isClosed()) {
      try {
        await bounded(page.locator('#header-user-btn').click({ timeout: 3000 }), 4000);
        const waiting = page.waitForResponse(response => new URL(response.url()).origin === receipt.origin && new URL(response.url()).pathname === '/api/auth/logout', { timeout: 5000 }).catch(() => null);
        await page.getByRole('button', { name: 'LOG OUT', exact: true }).click({ timeout: 3000 });
        if ((await waiting).status() === 200) revoked = await bounded(page.evaluate(async () => (await (await fetch('/api/auth/verify')).json()).valid === false), 5000);
      } catch (_) { receipt.cleanup.logout = 'unconfirmed'; }
    }
    if (launch) await bounded(launch, 16000).catch(() => {});
    for (const [name, close] of [['contextClosed', () => context && context.close()], ['browserClosed', () => server ? server.close() : browser && browser.close()]]) {
      try { await bounded(Promise.resolve(close()), 5000); receipt.cleanup[name] = true; }
      catch (_) { receipt.cleanup[name] = false; receipt.passed = false; }
    }
    if (server) {
      const child = server.process();
      if (child.exitCode === null && child.signalCode === null) {
        await bounded(server.kill(), 3000).catch(() => {});
        if (child.exitCode === null && child.signalCode === null) child.kill('SIGKILL');
        await bounded(new Promise(resolve => { if (child.exitCode !== null || child.signalCode !== null) resolve(); else child.once('exit', resolve); }), 5000).catch(() => {});
      }
      receipt.cleanup.browserProcessClosed = child.exitCode !== null || child.signalCode !== null;
      if (!receipt.cleanup.browserProcessClosed) receipt.passed = false;
    }
    for (const [name, directory] of [['profileRemoved', profile], ['runtimeRemoved', runtime]]) {
      try { if (directory) fs.rmSync(directory, { recursive: true, force: true, maxRetries: 2 }); receipt.cleanup[name] = !directory || !fs.existsSync(directory); }
      catch (_) { receipt.cleanup[name] = false; receipt.passed = false; }
    }
    password = null; process.removeListener('SIGINT', interrupt); process.removeListener('SIGTERM', interrupt);
    receipt.sessionRevocationConfirmed = revoked; receipt.finishedAt = new Date().toISOString();
    receipt.powerWindowConsolePosts = receipt.mutations.filter(row => !['/api/auth/login', '/api/auth/logout'].includes(row.path)).length;
    if (!revoked || fatal || receipt.powerWindowConsolePosts) receipt.passed = false;
    if (evidence) {
      const contains = bytes => secrets.some(secret => secret.length && bytes.includes(secret));
      let clean = true;
      const scan = directory => { for (const name of fs.readdirSync(directory)) {
        const file = path.join(directory, name), stat = fs.lstatSync(file);
        if (stat.isDirectory()) scan(file);
        else if (!stat.isFile() || contains(fs.readFileSync(file))) { fs.rmSync(file, { force: true }); clean = false; }
      } };
      try {
        scan(evidence); if (contains(Buffer.from(JSON.stringify(receipt)))) clean = false;
        receipt.secretByteScan = clean ? 'passed; recursive literal bytes, no OCR' : 'failed; artifacts withheld';
        if (!clean) { receipt.passed = false; receipt.failure = 'secret-byte-scan-failed'; }
        const output = Buffer.from(JSON.stringify(receipt, null, 2) + '\n');
        if (!contains(output)) fs.writeFileSync(path.join(evidence, 'readonly-browser.json'), output, { mode: 0o600 });
        else receipt.passed = false;
      } catch (_) { receipt.passed = false; }
    }
    process.stdout.write(receipt.passed ? 'Normal read-only browser acceptance passed.\n' : 'Normal read-only browser acceptance failed; inspect sanitized receipt.\n');
    process.exitCode = receipt.passed ? 0 : 1;
  }
}
main().catch(() => { process.stderr.write('Read-only runner configuration failed; private details withheld.\n'); process.exitCode = 1; });

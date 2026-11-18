#!/usr/bin/env node
'use strict';
// Original CLI/auth/HTTP/controller composition against an explicitly synthetic
// loopback TLS provider. Never native-PVE, installation or live acceptance.
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const net = require('node:net');
const crypto = require('node:crypto');
const { spawn } = require('node:child_process');
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
const requireTrue = value => { if (!value) throw Error('check_failed'); };
const bounded = (work, ms = 6000) => new Promise(resolve => {
  const timer = setTimeout(() => resolve(false), ms);
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
  const source = process.env.PVE_FREQ_DEMO_SOURCE, python = process.env.PVE_FREQ_PYTHON;
  const evidence = process.env.PVE_FREQ_DEMO_EVIDENCE;
  requireTrue(source && python && evidence && [source, python, evidence].every(path.isAbsolute));
  requireTrue(fs.statSync(source).isDirectory() && fs.statSync(python).isFile() && fs.statSync(evidence).isDirectory());
  const realSource = fs.realpathSync(source), realEvidence = fs.realpathSync(evidence);
  requireTrue(realEvidence !== realSource && !realEvidence.startsWith(realSource + path.sep) && fs.readdirSync(evidence).length === 0);
  const { chromium } = require('playwright');
  const runtime = fs.mkdtempSync(path.join(os.tmpdir(), 'pve-original-lab-synthetic-'));
  fs.chmodSync(runtime, 0o700);
  const children = [], handles = [], secrets = [], requestKeys = [], publicReads = [];
  const result = { kind: 'SYNTHETIC ORIGINAL LAB CLI', passed: false, startedAt: new Date().toISOString(),
    checks: [], operations: [], screenshots: [], http: [], browserExceptions: 0, externalRequestsBlocked: 0, cleanup: {},
    processRestartVerified: false, sameSessionRecoveryVerified: false, readOnlyModeVerified: false,
    limitation: 'Original local CLI/auth/API/browser with synthetic loopback TLS provider only. Browser TLS exception is fixture-only; upstream provider verification remains original and strict. No live PVE, native action or installed acceptance.' };
  let browserServer, browser, context, launchPromise, productPort, stage = 'prepare', interrupted = 0, publicFailure = false, closing = false;
  let cancel;
  const cancellation = new Promise((_, reject) => { cancel = reject; });
  const interrupt = code => { interrupted = code; cancel(Error('interrupted')); };
  const onInt = () => interrupt(130), onTerm = () => interrupt(143);
  process.on('SIGINT', onInt); process.on('SIGTERM', onTerm);
  const write = (file, bytes) => { fs.writeFileSync(file, bytes, { mode: 0o600 }); return file; };
  const check = (name, okay) => { requireTrue(!interrupted && okay); result.checks.push(name); };
  function child(command, args, label, env = process.env) {
    requireTrue(!interrupted && !closing);
    const out = fs.openSync(path.join(runtime, label + '.stdout'), 'wx', 0o600);
    const err = fs.openSync(path.join(runtime, label + '.stderr'), 'wx', 0o600);
    handles.push(out, err);
    const proc = spawn(command, args, { cwd: source, env, stdio: ['ignore', out, err] });
    proc.on('error', () => { proc.spawnFailed = true; });
    children.push({ proc, label }); return proc;
  }
  async function stop(proc) {
    if (proc.exitCode !== null || proc.signalCode !== null || proc.spawnFailed) return 'already-exited';
    proc.kill('SIGTERM');
    for (let i = 0; i < 60 && proc.exitCode === null && proc.signalCode === null; i++) await pause(100);
    if (proc.exitCode === null && proc.signalCode === null) {
      proc.kill('SIGKILL');
      for (let i = 0; i < 30 && proc.exitCode === null && proc.signalCode === null; i++) await pause(100);
      requireTrue(proc.exitCode !== null || proc.signalCode !== null); return 'forced';
    }
    return 'graceful';
  }
  async function ready(port, proc) {
    for (let i = 0; i < 200; i++) {
      requireTrue(!interrupted && !proc.spawnFailed && proc.exitCode === null && proc.signalCode === null);
      const connected = await new Promise(resolve => {
        const socket = net.connect(port, '127.0.0.1'); socket.setTimeout(200);
        socket.once('connect', () => { socket.destroy(); resolve(true); });
        socket.once('error', () => resolve(false));
        socket.once('timeout', () => { socket.destroy(); resolve(false); });
      });
      if (connected) return;
      await pause(100);
    }
    throw Error('readiness_failed');
  }
  function publicDocument(document) {
    const forbidden = new Set(['upid', 'actor', 'request_key', 'target_slot', 'credentials', 'token_id', 'token_secret', 'token_secret_file', 'ca_file']);
    function visit(value) {
      if (typeof value === 'string') requireTrue(!value.includes('UPID:') && !value.includes(runtime) && !secrets.some(secret => value.includes(secret)));
      else if (Array.isArray(value)) value.forEach(visit);
      else if (value && typeof value === 'object') Object.entries(value).forEach(([key, item]) => {
        requireTrue(!forbidden.has(key.toLowerCase())); visit(item);
      });
    }
    visit(document); return document;
  }
  const counts = () => JSON.parse(fs.readFileSync(path.join(runtime, 'provider-counts.json'), 'utf8'));
  try {
    const journey = async () => {
      await freePort(8006); productPort = await freePort(0);
      const cert = path.join(runtime, 'localhost.crt'), key = path.join(runtime, 'localhost.key');
      const openssl = child('openssl', ['req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1', '-subj', '/CN=localhost',
        '-addext', 'subjectAltName=IP:127.0.0.1,DNS:localhost', '-keyout', key, '-out', cert], 'openssl');
      await new Promise(resolve => {
        const timer = setTimeout(resolve, 30000);
        const done = () => { clearTimeout(timer); resolve(); };
        openssl.once('exit', done); openssl.once('error', done);
      });
      requireTrue(openssl.exitCode === 0);
      const password = crypto.randomBytes(24).toString('hex'), tokenSecret = crypto.randomBytes(24).toString('hex');
      secrets.push(password, tokenSecret);
      const conf = path.join(runtime, 'conf'), credentials = path.join(runtime, 'credentials');
      fs.mkdirSync(conf, { mode: 0o700 }); fs.mkdirSync(credentials, { mode: 0o700 });
      const secretFile = write(path.join(credentials, 'lab-token'), tokenSecret);
      const caFile = write(path.join(credentials, 'lab-ca.pem'), fs.readFileSync(cert));
      const tokenFile = write(path.join(runtime, 'provider-token.json'), JSON.stringify({ id: 'fixture@pve!lab', secret: tokenSecret }));
      write(path.join(conf, 'freq.toml'), '[paths]\ncredentials_dir = ' + JSON.stringify(credentials) +
        '\n[services]\ntls_cert = ' + JSON.stringify(cert) + '\ntls_key = ' + JSON.stringify(key) +
        '\ndashboard_port = ' + productPort + '\nwatchdog_enabled = false\n[pve]\nnodes = []\n');
      write(path.join(conf, 'hosts.toml'), 'hosts = []\n');
      const registration = {
        schema: 'pve-freq-lab-guest-v1', registration_id: crypto.randomUUID(),
        qualified_at: new Date(Date.now() - 60000).toISOString(), expires_at: new Date(Date.now() + 1800000).toISOString(),
        lab_only: true, estate: 'synthetic-local-lab', provider: '127.0.0.1', node: 'synthetic-node', guest_type: 'qemu',
        vmid: 6101, name: 'synthetic-lab-guest', instance_uuid: '12345678-1234-5678-9123-123456789abc',
        allowed_actions: ['status', 'start', 'shutdown'], qualification_ref: 'SYNTHETIC LOCAL FIXTURE ONLY; NOT NATIVE QUALIFICATION',
        credentials: { token_id: 'fixture@pve!lab', token_secret_file: secretFile, ca_file: caFile }
      };
      const rawRegistration = JSON.stringify(registration);
      const revision = crypto.createHash('sha256').update(rawRegistration).digest('hex');
      write(path.join(conf, 'lab-guest.json'), rawRegistration);
      stage = 'synthetic-provider-startup';
      const provider = child(python, [path.join(__dirname, 'lab_pve_fixture.py'), '--cert', cert, '--key', key,
        '--token-file', tokenFile, '--counts', path.join(runtime, 'provider-counts.json')], 'provider');
      await ready(8006, provider);
      const env = { ...process.env, FREQ_DIR: runtime, PYTHONPATH: source, PYTHONUNBUFFERED: '1' };
      const cli = ['-m', 'freq', 'serve', '--lab-cockpit', '--bind', '127.0.0.1', '--port', String(productPort)];
      let product = child(python, cli, 'product', env);
      stage = 'original-lab-cli-startup'; await ready(productPort, product);
      const match = fs.readFileSync(path.join(runtime, 'product.stdout'), 'utf8').match(/FIRST-ADMIN CLAIM[^\r\n]*\bclaim=([^\s]+)/);
      requireTrue(match); const claim = match[1]; secrets.push(claim);
      launchPromise = chromium.launchServer({ timeout: 15000, handleSIGINT: false, handleSIGTERM: false }).then(server => {
        browserServer = server; children.push({ proc: server.process(), label: 'browser' }); return server;
      });
      await launchPromise; requireTrue(!interrupted);
      browser = await chromium.connect(browserServer.wsEndpoint());
      context = await browser.newContext({ ignoreHTTPSErrors: true, serviceWorkers: 'block', acceptDownloads: false,
        viewport: { width: 1440, height: 1000 } });
      const origin = 'https://127.0.0.1:' + productPort;
      await context.route('**/*', route => {
        if (new URL(route.request().url()).origin === origin) return route.continue();
        result.externalRequestsBlocked++; return route.abort('blockedbyclient');
      });
      await context.routeWebSocket('**/*', socket => { result.externalRequestsBlocked++; socket.close(); });
      let sequence = 0;
      const order = new WeakMap(), postRequests = [];
      const page = await context.newPage(); page.setDefaultTimeout(20000);
      page.on('pageerror', () => { result.browserExceptions++; });
      page.on('request', request => {
        order.set(request, ++sequence);
        const url = new URL(request.url());
        if (url.origin === origin && request.method() === 'POST') postRequests.push(request);
      });
      page.on('response', response => {
        const url = new URL(response.url());
        if (url.origin !== origin || !url.pathname.startsWith('/api/')) return;
        result.http.push({ path: url.pathname, method: response.request().method(), status: response.status() });
        if (url.pathname.startsWith('/api/lab/')) publicReads.push((async () => {
          const body = publicDocument(await response.json());
          return { path: url.pathname, method: response.request().method(), order: order.get(response.request()), body };
        })().catch(() => { publicFailure = true; return null; }));
      });
      const response = (method, pathname, predicate = () => true) => {
        const pending = page.waitForResponse(async res => {
          const url = new URL(res.url());
          return url.origin === origin && url.pathname === pathname && res.request().method() === method && await predicate(res);
        }, { timeout: 30000 });
        // Some sibling waiters outlive a failed stage. Teardown may reject them;
        // attach a handler immediately while keeping their awaited failure intact.
        pending.catch(() => {}); return pending;
      };
      const fact = (label, target = false) => page.locator('#registered-lab-workspace ' + (target ? '[data-lab-target]' : '[data-lab-operation]'))
        .getByText(label, { exact: true }).locator('xpath=following-sibling::dd[1]');
      const textIs = async (locator, text) => { await locator.filter({ hasText: new RegExp('^' + text + '$') }).waitFor(); };
      const snapshot = async (name, phone = false) => {
        check('screenshot-secret-fields-cleared', await page.locator('input[type="password"], #operator-claim').evaluateAll(inputs => inputs.every(input => input.value === '')));
        await page.evaluate(() => {
          let label = document.getElementById('synthetic-lab-evidence-label');
          if (!label) { label = document.createElement('p'); label.id = 'synthetic-lab-evidence-label'; document.body.prepend(label); }
          label.textContent = 'SYNTHETIC ORIGINAL LAB CLI — NOT NATIVE PVE';
          label.style.cssText = 'margin:0;padding:10px;max-width:100%;overflow-wrap:anywhere;font-size:12px;color:#fff;background:#3b1765';
          window.scrollTo(0, 0);
        });
        const geometry = await page.evaluate(() => ({ width: innerWidth, height: innerHeight,
          documentWidth: document.documentElement.scrollWidth, clientWidth: document.documentElement.clientWidth }));
        if (phone) check('restored-running-lab-phone-no-document-overflow', geometry.width === 390 && geometry.documentWidth <= geometry.clientWidth);
        const file = name === 'route-return-1440' ? 'synthetic-original-lab.png' : 'synthetic-original-lab-' + name + '.png';
        await page.screenshot({ path: path.join(evidence, file), fullPage: true, mask: [page.locator('input[type="password"], #operator-claim')] });
        result.screenshots.push({ file, ...geometry });
      };
      const originalGet = pathname => page.evaluate(async route => {
        const res = await fetch(route, { credentials: 'same-origin', cache: 'no-store', redirect: 'error' });
        return { status: res.status, data: await res.json() };
      }, pathname);
      stage = 'first-admin';
      await page.goto(origin + '/setup');
      await page.locator('#operator-user').fill('synthetic_lab_admin');
      await page.locator('#operator-pass').fill(password); await page.locator('#operator-pass2').fill(password);
      await page.locator('#operator-claim').fill(claim);
      const created = response('POST', '/api/setup/create-admin');
      await page.locator('#operator-form').evaluate(form => form.requestSubmit());
      const createReply = await created, createData = await createReply.json();
      check('original-first-admin-session', createReply.status() === 200 && createData.session_started === true);
      if (typeof createData.csrf_token === 'string') secrets.push(createData.csrf_token);
      stage = 'original-lab-route-session';
      const initial = response('GET', '/api/lab/guest');
      await page.goto(origin + '/dashboard/registered-lab');
      const identity = await originalGet('/api/auth/verify');
      check('original-authenticated-deep-route', identity.status === 200 && identity.data.valid === true && identity.data.user === 'synthetic_lab_admin');
      const first = await initial, firstData = publicDocument(await first.json());
      check('original-registered-identity', first.status() === 200 && firstData.schema === 'pve-freq-lab-guest-view-v1' &&
        firstData.target.ref === registration.registration_id && firstData.target.registration_revision === revision &&
        firstData.target.source === '127.0.0.1' && firstData.target.node === 'synthetic-node' && firstData.target.kind === 'qemu' &&
        firstData.target.vmid === 6101 && firstData.target.name === 'synthetic-lab-guest' && firstData.observation.state === 'running');
      await textIs(fact('Current guest observation', true), 'Running');
      check('original-lab-nav-selected', await page.locator('#registered-lab-nav').getAttribute('aria-current') === 'page');
      const operationRefs = [];
      for (const [action, desired, control] of [['shutdown', 'stopped', 'Shut down'], ['start', 'running', 'Start']]) {
        stage = 'original-' + action + '-cycle';
        const submitted = response('POST', '/api/lab/power');
        const fresh = response('GET', '/api/lab/guest', async res => (await res.json()).observation?.state === desired);
        await page.getByRole('button', { name: control, exact: true }).click();
        const post = await submitted, postData = publicDocument(await post.json());
        const payload = post.request().postDataJSON();
        requireTrue(payload && Object.keys(payload).sort().join(',') === 'action,expected_state,registration_revision,request_key,target_ref');
        check('original-' + action + '-five-string-intent', Object.values(payload).every(value => typeof value === 'string') &&
          payload.action === action && payload.expected_state === (action === 'start' ? 'stopped' : 'running') &&
          payload.target_ref === registration.registration_id && payload.registration_revision === revision && /^[\x21-\x7e]{1,128}$/.test(payload.request_key));
        requestKeys.push(payload.request_key); secrets.push(payload.request_key);
        check('original-' + action + '-acknowledgement', [200, 202].includes(post.status()) && postData.schema === 'pve-freq-lab-operation-view-v1' &&
          /^[0-9a-f]{32}$/.test(postData.operation.ref) && postData.operation.action === action && postData.operation.acknowledgement === 'received');
        const ref = postData.operation.ref, operationPath = '/api/lab/operations/' + ref; operationRefs.push(ref);
        const completed = response('GET', operationPath, async res => {
          const dto = publicDocument(await res.json());
          return res.status() === 200 && dto.operation?.phase === 'succeeded' && dto.operation.task?.state === 'succeeded' && dto.operation.task.exit === 'OK';
        });
        let recoveryOrder = null;
        if (action === 'shutdown') {
          stage = 'same-session-active-shutdown-recovery';
          check('shutdown-acknowledged-before-terminal', !['succeeded', 'failed', 'rejected'].includes(postData.operation.phase) && counts().task < 2);
          const session = (await context.cookies(origin)).find(cookie => cookie.name === 'freq_session');
          requireTrue(session && session.value); secrets.push(session.value);
          const recovered = response('GET', '/api/lab/guest', async res => {
            const dto = publicDocument(await res.json());
            return res.status() === 200 && dto.operation?.ref === ref;
          });
          // The provider advances its task only through original operation GETs.
          // Reload immediately after ACK; do not manufacture a replacement key.
          await page.reload({ waitUntil: 'domcontentloaded' });
          const recoveredResponse = await recovered, recoveredData = publicDocument(await recoveredResponse.json());
          recoveryOrder = order.get(recoveredResponse.request());
          check('same-session-original-active-recovery-reference', recoveredData.busy === true &&
            recoveredData.operation.target_ref === registration.registration_id && recoveredData.operation.registration_revision === revision &&
            recoveredData.operation.retired === false && recoveredData.operation.action === 'shutdown');
          const afterReload = (await context.cookies(origin)).find(cookie => cookie.name === 'freq_session');
          check('reload-preserves-original-cookie-session', afterReload?.value === session.value);
          const powers = postRequests.filter(request => new URL(request.url()).pathname === '/api/lab/power');
          check('recovery-no-new-power-intent-or-key', powers.length === 1 && powers[0].postDataJSON().request_key === requestKeys[0]);
          stage = 'original-shutdown-cycle-after-recovery';
        }
        const terminal = await completed;
        const terminalData = publicDocument(await terminal.json());
        check('original-' + action + '-terminal-task-and-recorded-state', terminalData.operation.observation.state === desired &&
          terminalData.operation.target_ref === registration.registration_id && terminalData.operation.registration_revision === revision);
        const independent = await fresh, independentData = publicDocument(await independent.json());
        check('original-' + action + '-independent-current-read', independent.status() === 200 && independentData.schema === 'pve-freq-lab-guest-view-v1' &&
          independentData.observation.state === desired && order.get(independent.request()) > order.get(terminal.request()));
        await textIs(fact('Current guest observation', true), desired === 'running' ? 'Running' : 'Stopped');
        await textIs(fact('Provider task observation'), 'Success');
        const other = page.getByRole('button', { name: action === 'shutdown' ? 'Start' : 'Shut down', exact: true });
        await other.waitFor(); check('original-' + action + '-next-action-eligible', await other.isEnabled());
        const reads = await Promise.all(publicReads);
        check('original-' + action + '-consumer-observed-running-task', reads.some(read => read && read.path === operationPath && read.method === 'GET' && read.body.operation?.task?.state === 'running'));
        if (recoveryOrder !== null) {
          check('recovered-consumer-reads-same-original-operation', reads.some(read =>
            read && read.path === operationPath && read.method === 'GET' && read.order > recoveryOrder && read.body.operation?.ref === ref));
          result.sameSessionRecoveryVerified = true;
        }
        result.operations.push({ action, postStatus: post.status(), acknowledgement: 'received', task: 'succeeded', exit: 'OK', recordedState: desired, freshGuestState: desired });
        await snapshot(action + '-terminal-fresh-1440');
      }
      stage = 'restored-running-lab-phone-geometry';
      await page.setViewportSize({ width: 390, height: 844 });
      try {
        await textIs(fact('Current guest observation', true), 'Running');
        await textIs(fact('Provider task observation'), 'Success');
        await snapshot('start-terminal-fresh-390', true);
      } finally { await page.setViewportSize({ width: 1440, height: 1000 }); }
      check('two-distinct-private-intent-keys', requestKeys.length === 2 && requestKeys[0] !== requestKeys[1]);
      const nonAuth = postRequests.filter(request => !new URL(request.url()).pathname.startsWith('/api/auth/') && new URL(request.url()).pathname !== '/api/setup/create-admin');
      check('only-two-original-power-posts', nonAuth.length === 2 && nonAuth.every(request => new URL(request.url()).pathname === '/api/lab/power') &&
        nonAuth.map(request => request.postDataJSON().action).join(',') === 'shutdown,start');
      stage = 'frozen-original-terminal-history';
      const before = counts();
      for (const ref of operationRefs) {
        const historical = await originalGet('/api/lab/operations/' + ref); publicDocument(historical.data);
        check('same-session-frozen-terminal-history', historical.status === 200 && historical.data.operation.phase === 'succeeded');
      }
      const after = counts();
      check('terminal-history-no-provider-query', ['gets', 'config', 'status', 'task', 'controlPosts'].every(key => Number.isInteger(before[key]) && after[key] === before[key]));
      stage = 'route-retirement-and-synthetic-screenshot';
      await page.locator('#nav-items [data-view="home"]').click();
      check('lab-route-departure-removes-panel', await page.locator('#registered-lab-workspace .lab-panel-shell').count() === 0);
      const returned = response('GET', '/api/lab/guest');
      await page.locator('#registered-lab-nav').click(); await returned;
      await textIs(fact('Current guest observation', true), 'Running');
      await snapshot('route-return-1440');
      const logout = async label => {
        await page.locator('#header-user-btn').click(); const reply = response('POST', '/api/auth/logout');
        await page.getByRole('button', { name: 'LOG OUT', exact: true }).click();
        check(label + '-original-logout', (await reply).status() === 200);
        const verify = await originalGet('/api/auth/verify'); check(label + '-session-revoked', verify.data.valid === false);
        check(label + '-panel-retired', await page.locator('#registered-lab-workspace .lab-panel-shell').count() === 0);
      };
      await logout('first');
      stage = 'original-process-restart';
      check('original-product-graceful-restart-stop', await stop(product) === 'graceful');
      product = child(python, cli, 'product-restart', env); await ready(productPort, product);
      await page.goto(origin + '/dashboard/registered-lab');
      await page.locator('#login-overlay').waitFor({ state: 'visible' });
      await page.locator('#login-user').fill('synthetic_lab_admin'); await page.locator('#login-pass').fill(password);
      const login = response('POST', '/api/auth/login'), restarted = response('GET', '/api/lab/guest');
      await page.locator('#login-pass').press('Enter');
      const loginResponse = await login; check('restart-original-password-login', loginResponse.status() === 200);
      const restartedData = publicDocument(await (await restarted).json());
      check('restart-persisted-registration-and-current-state', restartedData.target.registration_revision === revision && restartedData.observation.state === 'running');
      await textIs(fact('Current guest observation', true), 'Running');
      for (const ref of operationRefs) {
        const foreign = await originalGet('/api/lab/operations/' + ref); publicDocument(foreign.data);
        check('restart-new-session-cannot-read-old-owner-operation', foreign.status === 404);
      }
      result.processRestartVerified = true;
      await logout('restart');
      stage = 'original-read-only-negative-startup';
      check('lab-product-stopped-before-read-only-phase', await stop(product) === 'graceful');
      const beforeReadOnly = counts();
      product = child(python, cli.map(argument => argument === '--lab-cockpit' ? '--read-only' : argument), 'product-read-only', env);
      await ready(productPort, product);
      await page.goto(origin + '/dashboard/registered-lab');
      await page.locator('#login-overlay').waitFor({ state: 'visible' });
      await page.locator('#login-user').fill('synthetic_lab_admin'); await page.locator('#login-pass').fill(password);
      const readOnlyLogin = response('POST', '/api/auth/login'), refusedGuest = response('GET', '/api/lab/guest');
      await page.locator('#login-pass').press('Enter');
      check('read-only-original-password-login', (await readOnlyLogin).status() === 200);
      check('read-only-original-guest-route-404', (await refusedGuest).status() === 404);
      const panel = page.locator('#registered-lab-workspace');
      await panel.locator('[data-lab-target]').waitFor();
      for (const name of ['Start', 'Shut down']) {
        const control = panel.getByRole('button', { name, exact: true });
        check('read-only-' + name.toLowerCase().replace(/ /g, '-') + '-native-disabled', await control.isDisabled());
        await control.evaluate(button => button.click());
      }
      for (const pathname of ['/api/lab/power', '/api/lab/operations/' + operationRefs[0]]) {
        const refused = await originalGet(pathname); publicDocument(refused.data);
        check('read-only-lab-api-404', refused.status === 404);
      }
      const afterReadOnly = counts();
      check('read-only-phase-no-provider-contact', ['gets', 'config', 'status', 'task', 'controlPosts'].every(key => beforeReadOnly[key] === afterReadOnly[key]));
      result.readOnlyModeVerified = true;
      await logout('read-only');
      await Promise.all(publicReads);
      check('public-lab-response-privacy', !publicFailure);
      check('no-additional-power-posts-after-restart', postRequests.filter(request => !new URL(request.url()).pathname.startsWith('/api/auth/') &&
        new URL(request.url()).pathname !== '/api/setup/create-admin').length === 2);
      check('no-browser-exceptions', result.browserExceptions === 0);
      check('no-external-browser-requests', result.externalRequestsBlocked === 0);
      check('no-unexpected-server-errors', !result.http.some(item => item.status >= 500));
      result.passed = true;
    };
    let deadline;
    try { await Promise.race([journey(), cancellation, new Promise((_, reject) => { deadline = setTimeout(() => reject(Error('journey_timeout')), 150000); })]); }
    finally { clearTimeout(deadline); }
  } catch (_) { result.failureStage = stage; }
  finally {
    closing = true;
    const closeChild = async owned => {
      try { result.cleanup[owned.label] = await stop(owned.proc); if (result.cleanup[owned.label] === 'forced') result.passed = false; }
      catch (_) { result.cleanup[owned.label] = 'failed'; result.passed = false; }
    };
    await Promise.all([
      Promise.all(children.filter(owned => owned.label !== 'browser').map(closeChild)),
      (async () => {
        if (launchPromise) await bounded(launchPromise, 16000);
        const contextClosed = context ? await bounded(context.close(), 3000) : true;
        const browserClosed = browserServer ? await bounded(browserServer.close()) : browser ? await bounded(browser.close()) : true;
        result.cleanup.browserClose = contextClosed && browserClosed;
        if (!result.cleanup.browserClose) result.passed = false;
        const owned = children.find(item => item.label === 'browser'); if (owned) await closeChild(owned);
      })()
    ]);
    await Promise.allSettled(publicReads);
    try {
      const safe = counts();
      const keys = ['gets', 'config', 'status', 'task', 'controlPosts', 'denied'];
      requireTrue(keys.every(key => Number.isInteger(safe[key]) && safe[key] >= 0));
      result.provider = Object.fromEntries(keys.map(key => [key, safe[key]]));
      result.provider.actions = Array.isArray(safe.actions) ? safe.actions.filter(action => ['shutdown', 'start'].includes(action)) : [];
      result.provider.initialState = safe.initialState; result.provider.finalState = safe.finalState;
      if (safe.controlPosts !== 2 || safe.denied !== 0 || safe.actions?.join(',') !== 'shutdown,start' || safe.initialState !== 'running' || safe.finalState !== 'running') result.passed = false;
    } catch (_) { result.passed = false; }
    for (const handle of handles) { try { fs.closeSync(handle); } catch (_) {} }
    try { await freePort(8006); if (productPort) await freePort(productPort); result.cleanup.listenersClosed = true; }
    catch (_) { result.cleanup.listenersClosed = false; result.passed = false; }
    try { fs.rmSync(runtime, { recursive: true, force: true }); result.cleanup.runtimeRemoved = !fs.existsSync(runtime); }
    catch (_) { result.cleanup.runtimeRemoved = false; result.passed = false; }
    result.cleanup.evidenceByteScan = 'passed; recursive binary/text secret-byte matching, no image OCR';
    function scan(directory) {
      for (const name of fs.readdirSync(directory)) {
        const file = path.join(directory, name), stat = fs.lstatSync(file);
        if (stat.isDirectory()) { scan(file); continue; }
        const bytes = stat.isFile() ? fs.readFileSync(file) : null;
        if (!bytes || secrets.some(secret => bytes.includes(Buffer.from(secret)))) {
          fs.unlinkSync(file); result.cleanup.evidenceByteScan = 'secret-bearing or nonregular artifact removed'; result.passed = false;
        }
      }
    }
    scan(evidence);
    result.interrupted = interrupted || null; result.finishedAt = new Date().toISOString();
    if (interrupted || result.browserExceptions || result.externalRequestsBlocked) result.passed = false;
    const safe = JSON.stringify(result, null, 2); requireTrue(!secrets.some(secret => safe.includes(secret)));
    write(path.join(evidence, 'synthetic-original-lab.json'), safe);
    process.stdout.write(result.passed ? 'Synthetic original lab integration passed.\n' : 'Synthetic original lab integration failed; inspect sanitized receipt.\n');
    process.exitCode = interrupted || (result.passed ? 0 : 1);
    process.removeListener('SIGINT', onInt); process.removeListener('SIGTERM', onTerm);
  }
}
main().catch(() => { process.stderr.write('Synthetic original lab runner could not complete; no private logs emitted.\n'); process.exitCode = 1; });

const { test, expect } = require('@playwright/test');
const { spawn } = require('node:child_process');
const CSRF = 'setup-csrf-token';

function completeStatus(state = 'complete') {
  return {
    ok: true,
    schema: 'zero-state-web-v1',
    state,
    setup_id: 'setup-opaque',
    active_discovery_id: 'discovery-opaque',
    active_contract_id: 'contract-opaque',
    active_init_job_id: 'init-opaque',
    initialized: state === 'complete',
    web_setup_complete: state === 'complete',
    setup_health: state === 'complete' ? 'configured' : state,
    setup_reason: state === 'complete' ? 'All durable setup truth is present.' : 'Setup is in progress.'
  };
}

function forbiddenKey(value) {
  const forbidden = new Set([
    'hosts_file', 'hosts_import', 'vm_contract', 'owned_vmids', 'template_vmids',
    'acknowledged_out_of_contract_vmids', 'device_credentials_file',
    'bootstrap_password_file', 'bootstrap_key_path', 'service_account_password_file',
    'dashboard_password_file'
  ]);
  let found = '';
  function visit(item) {
    if (!item || typeof item !== 'object' || found) return;
    Object.entries(item).forEach(([key, child]) => {
      if (key.endsWith('_file') || key.endsWith('_path') || forbidden.has(key)) found = key;
      visit(child);
    });
  }
  visit(value);
  return found;
}

test('browser and programmatic setup wizard builds an explicit fleet contract and verifies completion', async ({ browser }) => {
  test.setTimeout(45_000);
  async function startServer() {
    const child = spawn(process.env.PVE_FREQ_PYTHON || 'python3', ['-m', 'tests.support.hermetic_dashboard', '--profile', 'zero-state', '--port', '0'],
      { cwd: process.cwd(), env: { ...process.env, PYTHONUNBUFFERED: '1' }, stdio: ['ignore', 'pipe', 'pipe'] });
    let stdout = ''; let stderr = '';
    let claimFile = ''; let claimId = '';
    const exit = new Promise(resolve => child.once('exit', (code, signal) => resolve({ code, signal })));
    const ready = new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error('zero-state server readiness timed out')), 15_000);
      child.once('error', error => { clearTimeout(timer); reject(error); });
      let deliveryRead = false;
      child.stdout.setEncoding('utf8'); child.stderr.setEncoding('utf8');
      child.stdout.on('data', chunk => {
        stdout += chunk;
        const claim = stdout.match(/(?:^|\n)HERMETIC_FIRST_ADMIN_CLAIM_FILE (\S+) CLAIM_ID (\S+)(?:\r?\n|$)/);
        const listener = stdout.match(/(?:^|\n)HERMETIC_ZERO_STATE (https:\/\/127\.0\.0\.1:\d+)(?:\r?\n|$)/);
        if (claim) { claimFile = claim[1]; claimId = claim[2]; }
        if (listener && claimFile && !deliveryRead) {
          deliveryRead = true;
          const claimSecret = require('node:fs').readFileSync(claimFile, 'utf8');
          require('node:fs').unlinkSync(claimFile);
          clearTimeout(timer); resolve({ url: listener[1], claimSecret, claimId });
        }
      });
      child.stderr.on('data', chunk => { stderr += chunk; });
      exit.then(result => {
        if (!stdout.includes('HERMETIC_ZERO_STATE ')) { clearTimeout(timer); reject(new Error(`zero-state server exited before readiness (${result.code ?? result.signal})`)); }
      });
    });
    try { return { child, exit, ...(await ready), output: () => ({ stdout, stderr }) }; }
    catch (error) {
      if (child.exitCode === null && child.signalCode === null) child.kill('SIGKILL'); await exit; throw error;
    }
  }
  async function stopServer(server) {
    if (server.child.exitCode === null && server.child.signalCode === null) server.child.kill('SIGTERM');
    let timer;
    const result = await Promise.race([server.exit, new Promise(resolve => { timer = setTimeout(() => resolve(null), 10_000); })]);
    clearTimeout(timer);
    if (!result) { server.child.kill('SIGKILL'); await server.exit; throw new Error('zero-state server did not stop gracefully'); }
    const output = server.output();
    if (result.code !== 0 || result.signal !== null || !output.stdout.includes('HERMETIC_ZERO_STATE_AUDIT PASS')) {
      throw new Error(`zero-state child disk audit failed (code=${result.code}, signal=${result.signal}): ${output.stdout}${output.stderr}`);
    }
  }
  const server = await startServer();
  const context = await browser.newContext({ baseURL: server.url, ignoreHTTPSErrors: true });
  const page = await context.newPage();
  const setupPosts = []; let journeyError = null;
  page.on('request', request => {
    const url = new URL(request.url());
    if (request.method() !== 'POST' || !url.pathname.startsWith('/api/setup/')) return;
    let body = {}; try { body = request.postDataJSON(); } catch (_) {}
    setupPosts.push({ path: url.pathname, body, csrf: request.headers()['x-freq-csrf'] });
  });
  try {
    const setupScriptResponse = page.waitForResponse(response => new URL(response.url()).pathname === '/static/js/setup.js');
    const initialStatusResponse = page.waitForResponse(response => new URL(response.url()).pathname === '/api/setup/status');
    const documentResponse = await page.goto('/setup'); const scriptResponse = await setupScriptResponse;
    const statusResponse = await initialStatusResponse;
    expect(documentResponse.status()).toBe(200); expect(scriptResponse.status()).toBe(200);
    const headers = documentResponse.headers();
    expect(headers['strict-transport-security']).toContain('max-age=31536000');
    expect(headers['content-security-policy']).toContain("script-src 'self'"); expect(headers['x-frame-options']).toBe('DENY');
    expect(headers['x-content-type-options']).toBe('nosniff'); expect(headers['referrer-policy']).toBe('strict-origin-when-cross-origin');
    expect(headers['access-control-allow-origin']).toBeUndefined();
    const initialStatus = await statusResponse.json();
    expect(initialStatus).toMatchObject({ state: 'needs_operator', initialized: false, web_setup_complete: false });
    await expect(page.locator('#step-operator')).toBeVisible();
    await page.locator('#operator-user').fill('admin'); await page.locator('#operator-pass').fill('operator-password');
    await page.locator('#operator-pass2').fill('operator-password');
    await page.locator('#operator-claim').fill(server.claimSecret);
    const createResponsePromise = page.waitForResponse(response => new URL(response.url()).pathname === '/api/setup/create-admin');
    await page.locator('#operator-form').evaluate(form => form.requestSubmit()); const createResponse = await createResponsePromise;
    const create = await createResponse.json(); expect(createResponse.status()).toBe(200);
    expect(create).toMatchObject({ ok: true, schema: 'zero-state-web-v1', user: 'admin', role: 'admin', session_started: true, state: 'collecting' });
    expect(create.setup_id).toBeTruthy(); expect(create.csrf_token).toBeTruthy();
    const setCookie = await createResponse.headerValue('set-cookie');
    expect(setCookie).toContain('HttpOnly'); expect(setCookie).toContain('SameSite=Strict'); expect(setCookie).toContain('Secure');
    const cookies = await context.cookies();
    expect(cookies.filter(cookie => cookie.name === 'freq_session')).toEqual([expect.objectContaining({ httpOnly: true, secure: true, sameSite: 'Strict' })]);
    expect(await page.evaluate(() => document.cookie)).not.toContain('freq_session');
    await expect(page.locator('#step-connect')).toBeVisible();
    expect.soft(await page.locator('#bootstrap-user').inputValue()).toBe('root');
    await expect(page.locator('#bootstrap-user')).toBeEditable();
    const connectCopy = await page.locator('#step-connect .panel-copy').textContent();
    expect.soft(connectCopy).toContain('existing SSH login');
    expect.soft(connectCopy).toContain('used only');
    const verify = await page.evaluate(async () => (await fetch('/api/auth/verify')).json());
    expect(verify).toMatchObject({ valid: true, user: 'admin', role: 'admin', auth_mode: 'cookie' });
    expect(verify.csrf_token).toBe(create.csrf_token);
    const csrfProbe = await context.request.post(`${server.url}/api/setup/discovery/status?id=csrf-probe`, { data: {} });
    expect(csrfProbe.status()).toBe(403); expect((await csrfProbe.json()).error).toBe('CSRF token required');
    setupPosts.push({ path: '/api/setup/discovery/status', body: {}, csrf: undefined });
    await page.locator('#cluster-name').fill('dc01'); await page.locator('.node-host').fill('192.0.2.26');
    await page.locator('#bootstrap-user').fill('site-bootstrap');
    await page.locator('#bootstrap-pass').fill('bootstrap-password');
    await page.locator('#discovery-form').evaluate(form => form.requestSubmit());
    await expect(page.locator('#resource-rows tr[data-resource-id]')).toHaveCount(3);
    await expect(page.locator('#setup-health')).toHaveText('selecting'); await expect(page.locator('#review-count')).toHaveText('0 of 3 decided');
    const vm = page.locator('tr[data-resource-id="pve:pve01:qemu:100"]'); await vm.locator('input[value="owned"]').check();
    await vm.locator('.placement-select').selectOption('lab');
    const storage = page.locator('tr[data-resource-id="device:truenas:192.0.2.10"]');
    await storage.locator('input[value="owned"]').check();
    await storage.locator('.placement-select').selectOption('production');
    const unknown = page.locator('tr[data-resource-id="device:unknown:192.0.2.99"]');
    await expect(unknown.locator('input[value="owned"]')).toBeDisabled(); await expect(unknown).toContainText('ownership is unavailable in v1');
    await unknown.locator('input[value="acknowledged"]').check();
    await expect(page.locator('#save-contract')).toBeEnabled();
    const contractResponsePromise = page.waitForResponse(response => new URL(response.url()).pathname === '/api/setup/contract' && response.request().method() === 'POST');
    await page.locator('#save-contract').click(); const contractResponse = await contractResponsePromise;
    const contractBody = await contractResponse.json(); expect(contractResponse.status()).toBe(200);
    expect(contractBody.contract).toMatchObject({ revision: 1,
      counts: { owned_virtual: 1, templates: 0, acknowledged_virtual: 0, owned_devices: 1, acknowledged_devices: 1 }, ready: false });
    expect(contractBody.contract.id).toBeTruthy(); expect(contractBody.contract.sha256).toMatch(/^[a-f0-9]{64}$/);
    expect(contractBody.contract.credential_requirements).toEqual([expect.objectContaining({ resource_id: 'device:truenas:192.0.2.10', stored_fields: [], complete: false })]);
    await expect(page.locator('#step-credentials')).toBeVisible();
    await page.locator('[data-credential-field="username"]').fill('root');
    const partialResponsePromise = page.waitForResponse(response => new URL(response.url()).pathname === '/api/setup/device-credentials');
    await page.locator('#credentials-form').evaluate(form => form.requestSubmit()); const partialBody = await (await partialResponsePromise).json();
    expect(partialBody).toMatchObject({ ready: false, credentials: [{ resource_id: 'device:truenas:192.0.2.10', stored_fields: ['username'], complete: false }] });
    expect(JSON.stringify(partialBody)).not.toContain('root');
    await expect(page.locator('.stored-fields')).toContainText('Stored: username (values never returned)');
    await expect(page.locator('#setup-health')).toHaveText('credentials');
    await page.locator('[data-credential-field="password"]').fill('device-password');
    const readyResponsePromise = page.waitForResponse(response => new URL(response.url()).pathname === '/api/setup/device-credentials');
    await page.locator('#credentials-form').evaluate(form => form.requestSubmit()); const readyBody = await (await readyResponsePromise).json();
    expect(readyBody).toMatchObject({ ready: true, credentials: [{ resource_id: 'device:truenas:192.0.2.10', stored_fields: ['password', 'username'], complete: true }] });
    expect(JSON.stringify(readyBody)).not.toContain('device-password');
    await expect(page.locator('#step-launch')).toBeVisible();
    const serviceAccount = page.locator('#service-account');
    expect.soft(await serviceAccount.getAttribute('data-api-field')).toBe('service_account.username');
    expect.soft(await page.locator('#step-launch .panel-copy').textContent()).toContain('must differ from the bootstrap');
    await serviceAccount.fill('site-bootstrap');
    await page.locator('#service-pass').fill('service-password'); await page.locator('#service-pass2').fill('service-password');
    const equalityResponsePromise = page.waitForResponse(response => new URL(response.url()).pathname === '/api/setup/init/start');
    await page.locator('#launch-form').evaluate(form => form.requestSubmit()); const equalityResponse = await equalityResponsePromise;
    const equalityBody = await equalityResponse.json();
    const equalityRejected = equalityResponse.status() === 422;
    expect.soft(equalityResponse.status()).toBe(422);
    let initResponse = equalityResponse;
    if (equalityRejected) {
      expect(equalityBody).toMatchObject({ ok: false, error: { code: 'service_account_matches_bootstrap', field: 'service_account.username' } });
      expect(JSON.stringify(equalityBody)).not.toContain('site-bootstrap');
      await expect.soft(serviceAccount).toBeFocused();
      await expect.soft(page.locator('#form-error')).toBeVisible();
      await expect.soft(page.locator('#form-error')).toContainText('must differ');
      await expect.soft(page.locator('#service-pass')).toHaveValue('');
      await expect.soft(page.locator('#service-pass2')).toHaveValue('');
      const rejectedStatus = await page.evaluate(async () => (await fetch('/api/setup/status')).json());
      expect(rejectedStatus.active_init_job_id).toBeFalsy();
      await expect(page.locator('#step-launch')).toBeVisible();
      await serviceAccount.fill('freq-admin');
      await page.locator('#service-pass').fill('service-password'); await page.locator('#service-pass2').fill('service-password');
      const initResponsePromise = page.waitForResponse(response => new URL(response.url()).pathname === '/api/setup/init/start');
      await page.locator('#launch-form').evaluate(form => form.requestSubmit()); initResponse = await initResponsePromise;
    }
    const initBody = await initResponse.json(); expect(initResponse.status()).toBe(202);
    expect(initBody.job).toMatchObject({ state: 'queued' });
    expect(initBody.job.id).toBeTruthy();
    await expect(page.locator('#step-progress')).toBeVisible(); await expect(page.locator('#completion-card')).toBeHidden();
    await expect(page.locator('#progress-state')).toHaveText('running');
    await expect(page.locator('#progress-phase')).toHaveText('Fleet deployment');
    await expect(page.locator('#progress-message')).toHaveText('Running Fleet deployment.');
    expect((await page.locator('#progress-phase, #progress-message').allTextContents()).join('\n'))
      .not.toMatch(/[\u001B\u009B]|\[(?:1;36|0)m/);
    await expect(page.locator('#completion-card')).toBeVisible();
    await expect(page.locator('#progress-state')).toHaveText('complete');
    await expect(page.locator('#phase-log')).toContainText('Phase 12 / 12 - Verification');
    expect(await page.locator('#phase-log').textContent()).not.toMatch(/[\u001B\u009B]|\[(?:1;3[26]|0)m/);
    const logRefreshPromise = page.waitForResponse(response => new URL(response.url()).pathname === '/api/setup/init/logs');
    await page.locator('#refresh-logs').click();
    expect((await logRefreshPromise).status()).toBe(200);
    await expect(page.locator('#phase-log')).toContainText('Phase 12 / 12 - Verification');
    expect(await page.locator('#phase-log').textContent()).not.toMatch(/[\u001B\u009B]|\[(?:1;3[26]|0)m/);
    await expect(page.locator('#form-error')).toBeHidden();
    const finalTruth = await page.evaluate(async () => {
      const [statusResponse, verifyResponse] = await Promise.all([fetch('/api/setup/status'), fetch('/api/auth/verify')]);
      return { status: await statusResponse.json(), verify: await verifyResponse.json() };
    });
    expect(finalTruth.status).toMatchObject({ state: 'complete', initialized: true, web_setup_complete: true });
    expect(finalTruth.verify).toMatchObject({ valid: true, user: 'admin', role: 'admin' });
    expect(setupPosts).toHaveLength(equalityRejected ? 8 : 7);
    const csrfRejected = setupPosts.filter(post => post.path === '/api/setup/discovery/status');
    const accepted = setupPosts.filter(post => post.path !== '/api/setup/discovery/status');
    expect(csrfRejected).toEqual([{ path: '/api/setup/discovery/status', body: {}, csrf: undefined }]);
    const expectedPostPaths = ['/api/setup/create-admin', '/api/setup/discovery/start', '/api/setup/contract',
      '/api/setup/device-credentials', '/api/setup/device-credentials', '/api/setup/init/start'];
    if (equalityRejected) expectedPostPaths.push('/api/setup/init/start');
    expect(accepted.map(post => post.path)).toEqual(expectedPostPaths);
    for (const mutation of accepted) {
      expect(forbiddenKey(mutation.body), `${mutation.path} emitted a forbidden browser key`).toBe('');
      if (mutation.path === '/api/setup/create-admin') expect(mutation.csrf).toBeUndefined();
      else expect(mutation.csrf).toBe(create.csrf_token);
    }
    expect(accepted[1].body).toMatchObject({
      cluster: { name: 'dc01', nodes: [{ host: '192.0.2.26', name: 'pve01' }] },
      bootstrap: { username: 'site-bootstrap', password: 'bootstrap-password' }
    });
    expect(accepted[2].body.selections).toEqual([
      { resource_id: 'pve:pve01:qemu:100', disposition: 'owned', placement: 'lab' },
      { resource_id: 'device:truenas:192.0.2.10', disposition: 'owned', placement: 'production' },
      { resource_id: 'device:unknown:192.0.2.99', disposition: 'acknowledged' }
    ]);
    expect(accepted[3].body.credentials).toEqual([{ resource_id: 'device:truenas:192.0.2.10', username: 'root', secrets: {} }]);
    expect(accepted[4].body.credentials).toEqual([{ resource_id: 'device:truenas:192.0.2.10', secrets: { password: 'device-password' } }]);
    expect(accepted[5].body).toMatchObject({
      service_account: { username: 'site-bootstrap', password: 'service-password' },
      options: { ssh_mode: 'sudo', pdm: { mode: 'skip' }, ssl: { mode: 'defer' } }
    });
    if (equalityRejected) {
      expect(accepted[6].body).toMatchObject({
        service_account: { username: 'freq-admin', password: 'service-password' },
        options: { ssh_mode: 'sudo', pdm: { mode: 'skip' }, ssl: { mode: 'defer' } }
      });
    }
  } catch (error) { journeyError = error; throw error;
  } finally {
    await context.close();
    try { await stopServer(server);
    } catch (shutdownError) {
      if (journeyError) {
        throw new AggregateError([journeyError, shutdownError], `zero-state journey failed: ${journeyError.message}; terminal audit: ${shutdownError.message}`);
      }
      throw shutdownError;
    }
  }
});

test('complete state without both durable markers never reveals completion', async ({ browser }) => {
  test.setTimeout(60_000);
  const { runZeroStateFailureResume } = require('../support/zero_state_failure_resume');
  await runZeroStateFailureResume({ browser, expect, forbiddenKey });










});

test('successful empty discovery can freeze an explicit empty contract', async ({ browser }) => {
  test.setTimeout(60_000);
  async function startServer() {
    const child = spawn(process.env.PVE_FREQ_PYTHON || 'python3',
      ['-m', 'tests.support.hermetic_dashboard', '--profile', 'zero-state-empty', '--port', '0'],
      { cwd: process.cwd(), env: { ...process.env, PYTHONUNBUFFERED: '1' }, stdio: ['ignore', 'pipe', 'pipe'] });
    let stdout = ''; let stderr = '';
    let claimFile = ''; let claimId = '';
    const exit = new Promise(resolve => child.once('exit', (code, signal) => resolve({ code, signal })));
    const ready = new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error('zero-state empty server readiness timed out')), 15_000);
      child.once('error', error => { clearTimeout(timer); reject(error); });
      let deliveryRead = false;
      child.stdout.setEncoding('utf8'); child.stderr.setEncoding('utf8');
      child.stdout.on('data', chunk => {
        stdout += chunk;
        const claim = stdout.match(/(?:^|\n)HERMETIC_FIRST_ADMIN_CLAIM_FILE (\S+) CLAIM_ID (\S+)(?:\r?\n|$)/);
        const listener = stdout.match(/(?:^|\n)HERMETIC_ZERO_STATE (https:\/\/127\.0\.0\.1:\d+)(?:\r?\n|$)/);
        if (claim) { claimFile = claim[1]; claimId = claim[2]; }
        if (listener && claimFile && !deliveryRead) {
          deliveryRead = true;
          const claimSecret = require('node:fs').readFileSync(claimFile, 'utf8');
          require('node:fs').unlinkSync(claimFile);
          clearTimeout(timer); resolve({ url: listener[1], claimSecret, claimId });
        }
      });
      child.stderr.on('data', chunk => { stderr += chunk; });
      exit.then(result => {
        if (!stdout.includes('HERMETIC_ZERO_STATE ')) {
          clearTimeout(timer);
          reject(new Error(`zero-state empty server exited before readiness (${result.code ?? result.signal})`));
        }
      });
    });
    try { return { child, exit, ...(await ready), output: () => ({ stdout, stderr }) }; }
    catch (error) {
      if (child.exitCode === null && child.signalCode === null) child.kill('SIGKILL');
      await exit;
      throw error;
    }
  }
  async function stopServer(server) {
    if (server.child.exitCode === null && server.child.signalCode === null) server.child.kill('SIGTERM');
    let timer;
    const result = await Promise.race([
      server.exit,
      new Promise(resolve => { timer = setTimeout(() => resolve(null), 10_000); })
    ]);
    clearTimeout(timer);
    if (!result) {
      server.child.kill('SIGKILL');
      await server.exit;
      throw new Error('zero-state empty server did not stop gracefully');
    }
    const output = server.output();
    if (result.code !== 0 || result.signal !== null || !output.stdout.includes('HERMETIC_ZERO_STATE_AUDIT PASS')) {
      throw new Error(`zero-state empty child disk audit failed (code=${result.code}, signal=${result.signal}): ${output.stdout}${output.stderr}`);
    }
  }
  async function browserJson(page, path, options) {
    return page.evaluate(async ({ path, options }) => {
      const response = await fetch(path, options);
      const body = await response.json();
      return { status: response.status, body };
    }, { path, options });
  }

  const server = await startServer();
  const context = await browser.newContext({ baseURL: server.url, ignoreHTTPSErrors: true });
  const page = await context.newPage();
  const setupPosts = []; let journeyError = null;
  page.on('request', request => {
    const url = new URL(request.url());
    if (request.method() !== 'POST' || !url.pathname.startsWith('/api/setup/')) return;
    let body = {}; try { body = request.postDataJSON(); } catch (_) {}
    setupPosts.push({ path: url.pathname, body, csrf: request.headers()['x-freq-csrf'] });
  });
  try {
    await page.goto('/setup');
    await page.locator('#operator-user').fill('admin');
    await page.locator('#operator-pass').fill('operator-password');
    await page.locator('#operator-pass2').fill('operator-password');
    await page.locator('#operator-claim').fill(server.claimSecret);
    const createResponsePromise = page.waitForResponse(response => new URL(response.url()).pathname === '/api/setup/create-admin');
    await page.locator('#operator-form').evaluate(form => form.requestSubmit());
    const createResponse = await createResponsePromise;
    const create = await createResponse.json();
    expect(createResponse.status()).toBe(200);
    expect(create).toMatchObject({ ok: true, user: 'admin', role: 'admin', session_started: true, state: 'collecting' });
    expect(create.setup_id).toBeTruthy(); expect(create.csrf_token).toBeTruthy();
    const verify = await browserJson(page, '/api/auth/verify');
    expect(verify).toMatchObject({ status: 200, body: { valid: true, user: 'admin', role: 'admin', csrf_token: create.csrf_token } });

    await page.locator('#cluster-name').fill('dc01');
    await page.locator('.node-host').fill('192.0.2.26');
    await page.locator('#bootstrap-user').fill('wrong-user');
    await page.locator('#bootstrap-pass').fill('bootstrap-password');
    await page.locator('#discovery-form').evaluate(form => form.requestSubmit());
    await expect(page.locator('#form-error')).toContainText('Discovery could not complete from the declared PVE bootstrap targets.');
    await expect(page.locator('#review-surface')).toBeHidden();
    await expect(page.locator('#save-contract')).toBeDisabled();
    expect(setupPosts.filter(post => post.path === '/api/setup/contract')).toHaveLength(0);
    const failedContract = await browserJson(page, '/api/setup/contract');
    expect(failedContract).toMatchObject({ status: 404, body: { error: { code: 'contract_not_found' } } });

    await page.locator('button[data-step-target="connect"]').click();
    await page.locator('#bootstrap-user').fill('site-bootstrap');
    await page.locator('#bootstrap-pass').fill('bootstrap-password');
    await page.locator('#discovery-form').evaluate(form => form.requestSubmit());
    await expect(page.locator('.empty-resource-row')).toContainText('found no selectable resources or devices');
    await expect(page.locator('#resource-rows tr[data-resource-id]')).toHaveCount(0);
    await expect(page.locator('#node-truth .node-card')).toHaveCount(1);
    await expect(page.locator('#node-truth .node-card')).toContainText('pve01');
    await expect(page.locator('#node-truth .node-card')).toContainText('192.0.2.26');
    await expect(page.locator('#discovery-warnings')).toBeHidden();
    await expect(page.locator('#review-count')).toHaveText('0 of 0 decided');
    await expect(page.locator('#discovery-phase')).toHaveText('complete');
    await expect(page.locator('#discovery-count')).toHaveText('0 / 0');
    expect(await page.locator('#discovery-bar').evaluate(element => element.style.width)).toBe('100%');
    await expect(page.locator('#save-contract')).toBeEnabled();

    const selecting = await browserJson(page, '/api/setup/status');
    expect(selecting).toMatchObject({ status: 200, body: {
      state: 'selecting', setup_id: create.setup_id, active_contract_id: null,
      initialized: false, web_setup_complete: false
    } });
    expect(selecting.body.active_discovery_id).toBeTruthy();
    const noCsrf = await context.request.post(`${server.url}/api/setup/contract`, {
      headers: { Origin: server.url },
      data: {
        schema: 'zero-state-web-v1', setup_id: create.setup_id,
        discovery_id: selecting.body.active_discovery_id,
        client_request_id: '12345678-1234-4123-8123-123456789abc', selections: []
      }
    });
    expect(noCsrf.status()).toBe(403);
    expect((await noCsrf.json()).error).toBe('CSRF token required');
    const absentBeforeReload = await browserJson(page, '/api/setup/contract');
    expect(absentBeforeReload).toMatchObject({ status: 404, body: { error: { code: 'contract_not_found' } } });

    await page.reload();
    await expect(page.locator('.empty-resource-row')).toBeVisible();
    await expect(page.locator('#discovery-count')).toHaveText('0 / 0');
    await expect(page.locator('#save-contract')).toBeEnabled();
    expect(setupPosts.filter(post => post.path === '/api/setup/contract')).toHaveLength(0);
    const absentAfterReload = await browserJson(page, '/api/setup/contract');
    expect(absentAfterReload).toMatchObject({ status: 404, body: { error: { code: 'contract_not_found' } } });

    const contractRequestPromise = page.waitForRequest(request =>
      new URL(request.url()).pathname === '/api/setup/contract' && request.method() === 'POST');
    const contractResponsePromise = page.waitForResponse(response =>
      new URL(response.url()).pathname === '/api/setup/contract' && response.request().method() === 'POST');
    await page.locator('#save-contract').click();
    const contractRequest = await contractRequestPromise;
    const contractResponse = await contractResponsePromise;
    const contractRequestBody = contractRequest.postDataJSON();
    const contractBody = await contractResponse.json();
    expect(contractResponse.status()).toBe(200);
    expect(contractRequest.headers()['x-freq-csrf']).toBe(create.csrf_token);
    expect(contractRequestBody).toMatchObject({
      schema: 'zero-state-web-v1', setup_id: create.setup_id,
      discovery_id: selecting.body.active_discovery_id, selections: []
    });
    expect(contractRequestBody.client_request_id).toBeTruthy();
    expect(contractBody.contract).toMatchObject({
      discovery_id: selecting.body.active_discovery_id, revision: 1,
      counts: { owned_virtual: 0, templates: 0, acknowledged_virtual: 0, owned_devices: 0, acknowledged_devices: 0 },
      credential_requirements: [], ready: true
    });
    expect(contractBody.contract.id).toBeTruthy();
    expect(contractBody.contract.sha256).toMatch(/^[a-f0-9]{64}$/);
    await expect(page.locator('#step-credentials')).toBeVisible();
    await expect(page.locator('#step-launch')).toBeHidden();
    await expect(page.locator('#credential-count')).toHaveText('0 required');
    await expect(page.locator('#save-credentials')).toHaveText('Continue to launch');

    const ready = await browserJson(page, '/api/setup/status');
    expect(ready).toMatchObject({ status: 200, body: {
      state: 'ready', setup_id: create.setup_id,
      active_discovery_id: selecting.body.active_discovery_id,
      active_contract_id: contractBody.contract.id,
      initialized: false, web_setup_complete: false
    } });
    const durableContract = await browserJson(page, '/api/setup/contract');
    expect(durableContract).toMatchObject({ status: 200, body: { contract: {
      id: contractBody.contract.id, discovery_id: selecting.body.active_discovery_id,
      counts: contractBody.contract.counts, credential_requirements: [], ready: true
    } } });
    const credentialPostCount = setupPosts.filter(post => post.path === '/api/setup/device-credentials').length;
    await page.locator('#credentials-form').evaluate(form => form.requestSubmit());
    await expect(page.locator('#step-launch')).toBeVisible();
    expect(setupPosts.filter(post => post.path === '/api/setup/device-credentials')).toHaveLength(credentialPostCount);

    await page.reload();
    await expect(page.locator('#step-launch')).toBeVisible();
    await expect(page.locator('#contract-summary strong')).toHaveText(['0', '0', '0', '0', '0']);
    expect(setupPosts.filter(post => post.path === '/api/setup/contract')).toHaveLength(1);

    await page.locator('#service-pass').fill('service-password');
    await page.locator('#service-pass2').fill('service-password');
    const initRequestPromise = page.waitForRequest(request =>
      new URL(request.url()).pathname === '/api/setup/init/start' && request.method() === 'POST');
    const initResponsePromise = page.waitForResponse(response =>
      new URL(response.url()).pathname === '/api/setup/init/start');
    await page.locator('#launch-form').evaluate(form => form.requestSubmit());
    const initRequest = await initRequestPromise;
    const initResponse = await initResponsePromise;
    const initBody = await initResponse.json();
    expect(initResponse.status()).toBe(202);
    expect(initRequest.headers()['x-freq-csrf']).toBe(create.csrf_token);
    expect(initRequest.postDataJSON()).toMatchObject({
      schema: 'zero-state-web-v1', setup_id: create.setup_id,
      discovery_id: selecting.body.active_discovery_id, contract_id: contractBody.contract.id,
      service_account: { username: 'freq-admin', password: 'service-password' },
      options: { ssh_mode: 'sudo', pdm: { mode: 'skip' }, ssl: { mode: 'defer' } }
    });
    expect(initBody.job).toMatchObject({ state: 'queued' });
    expect(initBody.job.id).toBeTruthy();
    await expect(page.locator('#completion-card')).toBeHidden();
    await expect(page.locator('#progress-state')).toHaveText('complete', { timeout: 20_000 });
    await expect(page.locator('#completion-card')).toBeVisible();
    const finalTruth = await page.evaluate(async () => {
      const [statusResponse, verifyResponse] = await Promise.all([
        fetch('/api/setup/status'), fetch('/api/auth/verify')
      ]);
      return { status: await statusResponse.json(), verify: await verifyResponse.json() };
    });
    expect(finalTruth.status).toMatchObject({ state: 'complete', initialized: true, web_setup_complete: true });
    expect(finalTruth.verify).toMatchObject({ valid: true, user: 'admin', role: 'admin' });

    expect(setupPosts.map(post => post.path)).toEqual([
      '/api/setup/create-admin', '/api/setup/discovery/start', '/api/setup/discovery/start',
      '/api/setup/contract', '/api/setup/init/start'
    ]);
    for (const mutation of setupPosts) {
      expect(forbiddenKey(mutation.body), `${mutation.path} emitted a forbidden browser key`).toBe('');
      if (mutation.path === '/api/setup/create-admin') expect(mutation.csrf).toBeUndefined();
      else expect(mutation.csrf).toBe(create.csrf_token);
    }
  } catch (error) { journeyError = error; throw error;
  } finally {
    await context.close();
    try { await stopServer(server); }
    catch (shutdownError) {
      if (journeyError) {
        throw new AggregateError([journeyError, shutdownError], `zero-state empty journey failed: ${journeyError.message}; terminal audit: ${shutdownError.message}`);
      }
      throw shutdownError;
    }
  }
});

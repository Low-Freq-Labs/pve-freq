'use strict';

const { test, expect } = require('@playwright/test');
const { spawn } = require('node:child_process');
const path = require('node:path');

const ROOT = path.resolve(__dirname, '../..');
const SECRET = 'opnsense-bootstrap-secret';
let server;

async function startServer() {
  const child = spawn(process.env.PVE_FREQ_PYTHON || 'python3',
    ['-m', 'tests.support.hermetic_dashboard', '--profile', 'configured', '--port', '0'],
    { cwd: ROOT, stdio: ['ignore', 'pipe', 'pipe'] });
  let output = '';
  child.stdout.on('data', chunk => { output += chunk.toString(); });
  child.stderr.on('data', chunk => { output += chunk.toString(); });
  const deadline = Date.now() + 15_000;
  while (Date.now() < deadline) {
    const match = output.match(/HERMETIC_DASHBOARD (https?:\/\/[^\s]+)/);
    if (match) return { child, url: match[1] };
    if (child.exitCode !== null) throw new Error(`hermetic dashboard exited: ${output}`);
    await new Promise(resolve => setTimeout(resolve, 50));
  }
  child.kill('SIGTERM');
  throw new Error(`hermetic dashboard did not start: ${output}`);
}

async function login(page, observed = {}) {
  await page.route('**/api/**', async route => {
    const url = new URL(route.request().url());
    if (url.pathname.startsWith('/api/opnsense/')) return route.fallback();
    if (url.pathname === '/api/auth/logout') {
      observed.logoutCalls = (observed.logoutCalls || 0) + 1;
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true }) });
      return;
    }
    if (url.pathname === '/api/auth/login') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({
        ok: true, token: 'hermetic-session', csrf_token: 'hermetic-csrf', auth_mode: 'cookie', user: 'admin', role: 'admin'
      }) }); return;
    }
    if (url.pathname === '/api/auth/verify') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({
        valid: true, csrf_token: 'hermetic-csrf', auth_mode: 'cookie', user: 'admin', role: 'admin'
      }) }); return;
    }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true }) });
  });
  await page.goto(server.url, { waitUntil: 'domcontentloaded' });
  await page.locator('#login-overlay').waitFor({ state: 'hidden', timeout: 20_000 });
}

function state(overrides = {}) {
  return { managed: true, tls_sha256: 'a'.repeat(64), managed_user_count: 1,
    managed_key_count: 1, remote_present: true, local_present: true, ...overrides };
}

async function routeState(page, overrides = {}) {
  await page.route('**/api/opnsense/enrollment', async route => {
    if (route.request().method() === 'GET') {
      await route.fulfill({ status: 200, contentType: 'application/json',
        body: JSON.stringify({ ok: true, opnsense: state(overrides) }) });
      return;
    }
    await route.fallback();
  });
}

async function openSettings(page) {
  await page.locator('[data-view="settings"]').first().click();
  await expect(page.locator('#settings-view')).toBeVisible();
  await expect(page.locator('#opn-enrollment-state')).toContainText('Managed');
}

async function routeSetupCredentials(page, respond) {
  const resourceId = 'device:opnsense:172.20.0.1';
  await page.route('**/api/setup/**', async route => {
    const url = new URL(route.request().url());
    if (url.pathname === '/api/setup/status') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({
        setup_id: 'setup-eg11', state: 'credentials', initialized: false, web_setup_complete: false,
        active_discovery_id: 'discovery-eg11', active_contract_id: 'contract-eg11'
      }) }); return;
    }
    if (url.pathname === '/api/setup/discovery/status') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ discovery: {
        id: 'discovery-eg11', state: 'succeeded', progress: { phase: 'complete', current: 1, total: 1 },
        results: { resources: [], devices: [{ id: resourceId, kind: 'opnsense', label: 'opnsense-lab',
          host: '172.20.0.1', credential_fields: ['bootstrap_mode', 'username', 'password', 'api_key',
            'api_secret', 'tls_sha256', 'trust_on_first_use'] }] }
      } }) }); return;
    }
    if (url.pathname === '/api/setup/contract') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ contract: {
        id: 'contract-eg11', counts: { owned_virtual: 0, templates: 0, acknowledged_virtual: 0,
          owned_devices: 1, acknowledged_devices: 0 }, ready: false,
        credential_requirements: [{ resource_id: resourceId,
          required_any: [['bootstrap_mode', 'username', 'password', 'tls_sha256'],
            ['bootstrap_mode', 'username', 'password', 'trust_on_first_use'],
            ['bootstrap_mode', 'api_key', 'api_secret', 'tls_sha256'],
            ['bootstrap_mode', 'api_key', 'api_secret', 'trust_on_first_use']],
          stored_fields: [], complete: false, bootstrap_mode: '', tls_sha256: '', trust_on_first_use: false }]
      } }) }); return;
    }
    if (url.pathname === '/api/setup/device-credentials') return respond(route, resourceId);
    await route.fulfill({ status: 404, contentType: 'application/json', body: '{}' });
  });
  await page.route('**/api/auth/verify', async route => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({
      valid: true, user: 'admin', role: 'admin', csrf_token: 'setup-csrf', auth_mode: 'cookie'
    }) });
  });
}

test.beforeAll(async () => { server = await startServer(); });
test.afterAll(async () => { if (server && server.child) server.child.kill('SIGTERM'); });

test('setup card active API mode success sends one trust choice and clears secrets', async ({ page }) => {
  let payload;
  await routeSetupCredentials(page, async (route, resourceId) => {
    payload = route.request().postDataJSON();
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({
      ready: true, credentials: [{ resource_id: resourceId, stored_fields: ['api_key', 'api_secret',
        'bootstrap_mode', 'trust_on_first_use'], complete: true, bootstrap_mode: 'api', tls_sha256: '',
        trust_on_first_use: true }]
    }) });
  });
  await page.goto(`${server.url}/setup`, { waitUntil: 'domcontentloaded' });
  await expect(page.locator('#step-credentials')).toBeVisible();
  const card = page.locator('.opnsense-credential-card');
  await card.locator('[data-credential-field="username"]').fill('stale-web-user');
  await card.locator('[data-credential-field="password"]').fill(SECRET);
  await card.locator('[data-credential-field="bootstrap_mode"]').selectOption('api');
  await expect(card.locator('[data-credential-field="password"]')).toHaveValue('');
  await expect(card.locator('[data-credential-field="password"]')).toBeDisabled();
  await card.locator('[data-credential-field="api_key"]').fill('key-id');
  await card.locator('[data-credential-field="api_secret"]').fill(SECRET);
  await card.locator('[data-credential-field="trust_on_first_use"]').check();
  await expect(card.locator('[data-credential-field="tls_sha256"]')).toBeDisabled();
  await page.locator('#credentials-form').evaluate(form => form.requestSubmit());
  await expect.poll(() => payload).toBeTruthy();
  expect(payload.credentials).toEqual([{ resource_id: 'device:opnsense:172.20.0.1', bootstrap_mode: 'api',
    trust_on_first_use: true, secrets: { api_key: 'key-id', api_secret: SECRET } }]);
  await expect(card.locator('[data-credential-field="api_key"]')).toHaveValue('');
  await expect(card.locator('[data-credential-field="api_secret"]')).toHaveValue('');
  expect(JSON.stringify(payload.credentials[0])).not.toContain('stale-web-user');
});

test('setup card failure clears active secret and focuses the exact field', async ({ page }) => {
  await routeSetupCredentials(page, async route => {
    await route.fulfill({ status: 422, contentType: 'application/json', body: JSON.stringify({ ok: false, error: {
      code: 'opnsense_credential_invalid', message: 'Credential value is missing or unsafe.',
      field: 'credentials[0].secrets.password', details: []
    } }) });
  });
  await page.goto(`${server.url}/setup`, { waitUntil: 'domcontentloaded' });
  const card = page.locator('.opnsense-credential-card');
  await card.locator('[data-credential-field="username"]').fill('admin');
  await card.locator('[data-credential-field="password"]').fill(SECRET);
  await card.locator('[data-credential-field="tls_sha256"]').fill('a'.repeat(64));
  await page.locator('#credentials-form').evaluate(form => form.requestSubmit());
  await expect(page.locator('#form-error')).toContainText('Credential value is missing or unsafe.');
  await expect(card.locator('[data-credential-field="password"]')).toHaveValue('');
  await expect(card.locator('[data-credential-field="password"]')).toBeFocused();
});

test('mode-specific ephemeral enrollment excludes stale API fields after API to Web switch', async ({ page }) => {
  await routeState(page, { managed: false, managed_user_count: 0, managed_key_count: 0,
    remote_present: false, local_present: false, tls_sha256: '' });
  let payload;
  await page.route('**/api/opnsense/enrollment', async route => {
    if (route.request().method() === 'POST') {
      payload = route.request().postDataJSON();
      await route.fulfill({ status: 200, contentType: 'application/json',
        body: JSON.stringify({ ok: true, opnsense: state() }) });
      return;
    }
    await route.fallback();
  });
  await login(page); await openSettings(page);
  await page.locator('#opn-host').fill('172.20.0.1');
  await page.locator('#opn-bootstrap-mode').selectOption('api');
  await expect(page.locator('[data-opn-mode-fields="web"]').first()).toBeHidden();
  await expect(page.locator('[data-opn-mode-fields="api"]').first()).toBeVisible();
  await page.locator('#opn-bootstrap-api-key').fill('stale-key-id');
  await page.locator('#opn-bootstrap-api-secret').fill(SECRET);
  await page.locator('#opn-bootstrap-mode').selectOption('web');
  await expect(page.locator('#opn-bootstrap-api-key')).toHaveValue('');
  await expect(page.locator('#opn-bootstrap-api-secret')).toHaveValue('');
  await expect(page.locator('#opn-bootstrap-api-key')).toBeDisabled();
  await page.locator('#opn-bootstrap-username').fill('admin');
  await page.locator('#opn-bootstrap-password').fill(SECRET);
  await page.locator('#opn-trust-on-first-use').check();
  await page.locator('[data-action="opnEnrollmentSubmit"]').click();
  await expect.poll(() => payload).toBeTruthy();
  expect(payload).toEqual({ host: '172.20.0.1', bootstrap_mode: 'web', username: 'admin',
    password: SECRET, trust_on_first_use: true });
  await expect(page.locator('#opn-bootstrap-password')).toHaveValue('');
  expect(await page.evaluate(() => JSON.stringify(localStorage) + JSON.stringify(sessionStorage)))
    .not.toContain(SECRET);
});

test('field-focused closed failure', async ({ page }) => {
  await routeState(page, { managed: false, tls_sha256: '' });
  await page.route('**/api/opnsense/enrollment', async route => {
    if (route.request().method() !== 'POST') return route.fallback();
    await route.fulfill({ status: 422, contentType: 'application/json', body: JSON.stringify({
      ok: false, code: 'opnsense_credential_invalid', message: 'Credential rejected.', field: 'password', details: []
    }) });
  });
  await login(page); await openSettings(page);
  await page.locator('#opn-host').fill('172.20.0.9');
  await page.locator('#opn-bootstrap-username').fill('admin');
  await page.locator('#opn-bootstrap-password').fill(SECRET);
  await page.locator('#opn-trust-on-first-use').check();
  await page.locator('[data-action="opnEnrollmentSubmit"]').click();
  await expect(page.locator('#opn-enrollment-error')).toContainText('Credential rejected.');
  await expect(page.locator('#opn-bootstrap-password')).toBeFocused();
  await expect(page.locator('#opn-bootstrap-password')).toHaveValue('');
});

test('downstream auth 401 preserves the PVE-FREQ session and focuses credentials', async ({ page }) => {
  const observed = { logoutCalls: 0 };
  await routeState(page, { managed: false, tls_sha256: '' });
  await page.route('**/api/opnsense/enrollment', async route => {
    if (route.request().method() !== 'POST') return route.fallback();
    await route.fulfill({ status: 401, contentType: 'application/json', body: JSON.stringify({
      ok: false, code: 'opnsense_auth_failed', message: 'OPNsense rejected the bootstrap credentials.',
      field: 'credentials', details: []
    }) });
  });
  await login(page, observed); await openSettings(page);
  await page.locator('#opn-host').fill('172.20.0.9');
  await page.locator('#opn-bootstrap-username').fill('admin');
  await page.locator('#opn-bootstrap-password').fill(SECRET);
  await page.locator('#opn-trust-on-first-use').check();
  await page.locator('[data-action="opnEnrollmentSubmit"]').click();
  await expect(page.locator('#opn-enrollment-error')).toContainText('OPNsense rejected the bootstrap credentials.');
  await expect(page.locator('#opn-bootstrap-username')).toBeFocused();
  await expect(page.locator('#opn-bootstrap-password')).toHaveValue('');
  await expect(page.locator('#login-overlay')).toBeHidden();
  await expect(page.locator('#settings-view')).toBeVisible();
  expect(observed.logoutCalls).toBe(0);
});

test('generic 401 on the OPNsense route still logs out the PVE-FREQ session', async ({ page }) => {
  const observed = { logoutCalls: 0 };
  await routeState(page, { managed: false, tls_sha256: '' });
  await page.route('**/api/opnsense/enrollment', async route => {
    if (route.request().method() !== 'POST') return route.fallback();
    await route.fulfill({ status: 401, contentType: 'application/json', body: JSON.stringify({
      ok: false, code: 'session_expired', message: 'PVE-FREQ session expired.', field: '', details: []
    }) });
  });
  await login(page, observed); await openSettings(page);
  await page.locator('#opn-host').fill('172.20.0.9');
  await page.locator('#opn-bootstrap-username').fill('admin');
  await page.locator('#opn-bootstrap-password').fill(SECRET);
  await page.locator('#opn-trust-on-first-use').check();
  await page.locator('[data-action="opnEnrollmentSubmit"]').click();
  await expect(page.locator('#login-overlay')).toBeVisible();
  await expect.poll(() => observed.logoutCalls).toBe(1);
  await expect(page.locator('#login-user')).toBeFocused();
});

test('explicit certificate replacement', async ({ page }) => {
  await routeState(page);
  let calls = 0; let replacement;
  await page.route('**/api/opnsense/retrust', async route => {
    calls += 1; const body = route.request().postDataJSON();
    if (!body.confirm_replace) {
      await route.fulfill({ status: 409, contentType: 'application/json', body: JSON.stringify({
        ok: false, code: 'opnsense_retrust_failed', message: 'Replacement requires confirmation.',
        field: 'tls_sha256', details: [{ bound: 'a'.repeat(64), observed: 'b'.repeat(64) }]
      }) }); return;
    }
    replacement = body;
    await route.fulfill({ status: 200, contentType: 'application/json',
      body: JSON.stringify({ ok: true, opnsense: state({ tls_sha256: 'b'.repeat(64) }) }) });
  });
  await login(page); await openSettings(page);
  await page.locator('#opn-host').fill('172.20.0.1');
  await page.locator('#opn-bootstrap-username').fill('admin');
  await page.locator('#opn-bootstrap-password').fill(SECRET);
  await page.locator('#opn-trust-on-first-use').check();
  await page.locator('[data-action="opnRetrustSubmit"]').click();
  await expect(page.locator('#opn-retrust-compare')).toContainText('Bound');
  await expect(page.locator('#opn-retrust-compare')).toContainText('Observed');
  await expect(page.locator('[data-action="opnRetrustReplace"]')).toBeVisible();
  await page.locator('#opn-bootstrap-password').fill(SECRET);
  await page.locator('[data-action="opnRetrustReplace"]').click();
  await expect.poll(() => calls).toBe(2);
  expect(replacement.confirm_replace).toBe(true);
  expect(JSON.stringify(await page.locator('#opn-enrollment-state').textContent())).not.toContain(SECRET);
});

test('credential-gated removal', async ({ page }) => {
  await routeState(page);
  let removal;
  await page.route('**/api/opnsense/remove', async route => {
    removal = route.request().postDataJSON();
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({
      ok: true, opnsense: state({ managed: false, managed_user_count: 0, managed_key_count: 0,
        remote_present: false, local_present: false })
    }) });
  });
  await login(page); await openSettings(page);
  await page.locator('#opn-host').fill('172.20.0.1');
  await page.locator('#opn-bootstrap-username').fill('admin');
  await page.locator('#opn-bootstrap-password').fill(SECRET);
  await page.locator('#opn-tls-sha256').fill('a'.repeat(64));
  await expect(page.locator('[data-action="opnRemoveSubmit"]')).toBeDisabled();
  await page.locator('#opn-remove-confirm').check();
  await page.locator('[data-action="opnRemoveSubmit"]').click();
  await expect.poll(() => removal).toBeTruthy();
  expect(removal).toEqual({ host: '172.20.0.1', bootstrap_mode: 'web', username: 'admin',
    password: SECRET, tls_sha256: 'a'.repeat(64) });
  await expect(page.locator('#opn-bootstrap-password')).toHaveValue('');
  await expect(page.locator('#opn-remove-confirm')).not.toBeChecked();
});

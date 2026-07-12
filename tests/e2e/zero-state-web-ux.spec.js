const { test, expect } = require('@playwright/test');

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

test('browser-only wizard builds an explicit fleet contract and verifies completion', async ({ page }) => {
  let setupState = 'needs_operator';
  const mutations = [];

  await page.route('**/api/setup/status', route => {
    const payload = setupState === 'needs_operator'
      ? { ...completeStatus('needs_operator'), setup_id: null, active_discovery_id: null, active_contract_id: null, active_init_job_id: null, initialized: false, web_setup_complete: false }
      : completeStatus(setupState);
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(payload) });
  });
  await page.route('**/api/auth/verify', route => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({ valid: true, user: 'admin', role: 'admin', csrf_token: CSRF, auth_mode: 'cookie', session_ttl_s: 3600 })
  }));
  await page.route('**/api/setup/create-admin', async route => {
    const body = route.request().postDataJSON();
    mutations.push({ path: '/api/setup/create-admin', body, csrf: route.request().headers()['x-freq-csrf'] });
    expect(body).toMatchObject({ schema: 'zero-state-web-v1', username: 'admin' });
    expect(body.password).toBe('operator-password');
    expect(route.request().headers()['x-freq-csrf']).toBeUndefined();
    setupState = 'collecting';
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true, schema: 'zero-state-web-v1', setup_id: 'setup-opaque', user: 'admin', role: 'admin', session_started: true, csrf_token: CSRF, auth_mode: 'cookie', state: 'collecting' }) });
  });
  await page.route('**/api/setup/discovery/start', async route => {
    const body = route.request().postDataJSON();
    mutations.push({ path: '/api/setup/discovery/start', body, csrf: route.request().headers()['x-freq-csrf'] });
    expect(body.cluster.nodes).toEqual([{ host: '10.25.255.26', name: 'pve01' }]);
    expect(body.bootstrap).toEqual({ username: 'freq-ops', password: 'bootstrap-password' });
    setupState = 'discovering';
    return route.fulfill({ status: 202, contentType: 'application/json', body: JSON.stringify({ ok: true, schema: 'zero-state-web-v1', setup_id: 'setup-opaque', discovery: { id: 'discovery-opaque', state: 'queued', poll_after_ms: 500 } }) });
  });
  await page.route('**/api/setup/discovery/status?id=discovery-opaque', route => {
    setupState = 'selecting';
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({
      ok: true, schema: 'zero-state-web-v1', discovery: {
        id: 'discovery-opaque', state: 'succeeded', updated_at: '2026-07-12T06:00:09Z', poll_after_ms: 0,
        progress: { phase: 'complete', current: 3, total: 3, message: 'Discovered three selectable resources.' },
        results: {
          pve_nodes: [{ id: 'pve:pve01', host: '10.25.255.26', name: 'pve01', reachable: true, version: '8.4' }],
          resources: [{ id: 'pve:pve01:qemu:100', kind: 'vm', vmid: 100, name: 'pve-freq', node: 'pve01', status: 'running', ips: ['10.25.255.50'], suggested_disposition: 'owned', suggested_placement: 'production' }],
          devices: [
            { id: 'device:truenas:10.25.255.10', kind: 'truenas', label: 'storage-01', host: '10.25.255.10', reachable: true, credential_fields: ['username', 'password'], suggested_disposition: 'owned', suggested_placement: 'production' },
            { id: 'device:unknown:10.25.255.99', kind: 'unknown', label: 'unidentified-01', host: '10.25.255.99', reachable: true, credential_fields: [], suggested_disposition: 'acknowledged' }
          ],
          warnings: []
        }
      }
    }) });
  });
  await page.route('**/api/setup/contract', async route => {
    if (route.request().method() === 'GET') return route.fallback();
    const body = route.request().postDataJSON();
    mutations.push({ path: '/api/setup/contract', body, csrf: route.request().headers()['x-freq-csrf'] });
    expect(body.selections).toEqual([
      { resource_id: 'pve:pve01:qemu:100', disposition: 'owned', placement: 'lab' },
      { resource_id: 'device:truenas:10.25.255.10', disposition: 'owned', placement: 'production' },
      { resource_id: 'device:unknown:10.25.255.99', disposition: 'acknowledged' }
    ]);
    setupState = 'credentials';
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true, schema: 'zero-state-web-v1', contract: { id: 'contract-opaque', discovery_id: 'discovery-opaque', revision: 1, sha256: 'hash', counts: { owned_virtual: 1, templates: 0, acknowledged_virtual: 0, owned_devices: 1, acknowledged_devices: 1 }, credential_requirements: [{ resource_id: 'device:truenas:10.25.255.10', required_any: [['username', 'password']], stored_fields: [] }], ready: false } }) });
  });
  await page.route('**/api/setup/device-credentials', async route => {
    const body = route.request().postDataJSON();
    mutations.push({ path: '/api/setup/device-credentials', body, csrf: route.request().headers()['x-freq-csrf'] });
    expect(body.credentials).toEqual([{ resource_id: 'device:truenas:10.25.255.10', username: 'root', secrets: { password: 'device-password' } }]);
    setupState = 'ready';
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true, schema: 'zero-state-web-v1', contract_id: 'contract-opaque', credentials: [{ resource_id: 'device:truenas:10.25.255.10', stored_fields: ['username', 'password'], complete: true }], ready: true }) });
  });
  await page.route('**/api/setup/init/start', async route => {
    const body = route.request().postDataJSON();
    mutations.push({ path: '/api/setup/init/start', body, csrf: route.request().headers()['x-freq-csrf'] });
    expect(body).toMatchObject({ setup_id: 'setup-opaque', discovery_id: 'discovery-opaque', contract_id: 'contract-opaque', service_account: { username: 'freq-admin', password: 'service-password' }, options: { ssh_mode: 'sudo', pdm: { mode: 'skip' }, ssl: { mode: 'defer' } } });
    setupState = 'initializing';
    return route.fulfill({ status: 202, contentType: 'application/json', body: JSON.stringify({ ok: true, schema: 'zero-state-web-v1', job: { id: 'init-opaque', state: 'queued', poll_after_ms: 500 } }) });
  });
  await page.route('**/api/setup/init/status?id=init-opaque', route => {
    setupState = 'complete';
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true, schema: 'zero-state-web-v1', job: { id: 'init-opaque', state: 'succeeded', returncode: 0, initialized: true, web_setup_complete: true, poll_after_ms: 0, progress: { phase: 12, phase_name: 'Verification', current: 39, total: 39, message: 'All verification checks passed.' }, log_tail: ['[39/39] verification passed'] } }) });
  });

  await page.goto('/setup');
  await expect(page.locator('#step-operator')).toBeVisible();
  await page.locator('#operator-user').fill('admin');
  await page.locator('#operator-pass').fill('operator-password');
  await page.locator('#operator-pass2').fill('operator-password');
  await page.locator('#operator-form').evaluate(form => form.requestSubmit());

  await expect(page.locator('#step-connect')).toBeVisible();
  await page.locator('#cluster-name').fill('dc01');
  await page.locator('.node-host').fill('10.25.255.26');
  await page.locator('#bootstrap-user').fill('freq-ops');
  await page.locator('#bootstrap-pass').fill('bootstrap-password');
  await page.locator('#discovery-form').evaluate(form => form.requestSubmit());

  await expect(page.locator('#resource-rows tr')).toHaveCount(3);
  await expect(page.locator('#setup-health')).toHaveText('selecting');
  await expect(page.locator('#review-count')).toHaveText('0 of 3 decided');
  const vm = page.locator('tr[data-resource-id="pve:pve01:qemu:100"]');
  await vm.locator('input[value="owned"]').check();
  await vm.locator('.placement-select').selectOption('lab');
  const storage = page.locator('tr[data-resource-id="device:truenas:10.25.255.10"]');
  await storage.locator('input[value="owned"]').check();
  await storage.locator('.placement-select').selectOption('production');
  const unknown = page.locator('tr[data-resource-id="device:unknown:10.25.255.99"]');
  await expect(unknown.locator('input[value="owned"]')).toBeDisabled();
  await expect(unknown).toContainText('ownership is unavailable in v1');
  await unknown.locator('input[value="acknowledged"]').check();
  await expect(page.locator('#save-contract')).toBeEnabled();
  await page.locator('#save-contract').click();

  await expect(page.locator('#step-credentials')).toBeVisible();
  await page.locator('[data-credential-field="username"]').fill('root');
  await page.locator('[data-credential-field="password"]').fill('device-password');
  await page.locator('#credentials-form').evaluate(form => form.requestSubmit());

  await expect(page.locator('#step-launch')).toBeVisible();
  await page.locator('#service-pass').fill('service-password');
  await page.locator('#service-pass2').fill('service-password');
  await page.locator('#launch-form').evaluate(form => form.requestSubmit());

  await expect(page.locator('#completion-card')).toBeVisible();
  await expect(page.locator('#progress-state')).toHaveText('complete');
  await expect(page.locator('#phase-log')).toContainText('verification passed');
  await expect(page.locator('#form-error')).toBeHidden();

  expect(mutations).toHaveLength(5);
  for (const mutation of mutations) {
    expect(forbiddenKey(mutation.body), `${mutation.path} emitted a forbidden browser key`).toBe('');
    if (mutation.path !== '/api/setup/create-admin') expect(mutation.csrf).toBe(CSRF);
  }
});

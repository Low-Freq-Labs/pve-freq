const fs = require('node:fs');
const path = require('node:path');
const { test, expect } = require('@playwright/test');

const inventory = '/api/pve/cluster-observation/inventory';
const unavailable = 'Configured selections unavailable: the server did not find the inventory endpoint (HTTP 404). No selections were observed. Refresh explicitly to try a new inventory request.';
const genericUnavailable = 'Configured selections unavailable. Refresh explicitly to try a new inventory request.';
const revision = 'login-recovery-guidance-20261102-r1';

test('original canonical Fleet renders actual missing inventory as unavailable', async ({ page, context }, testInfo) => {
  const origin = testInfo.project.use.baseURL;
  const blocked = [];
  const inventoryRequests = [];
  const observations = [];
  const forbiddenActions = [];
  const injectedCases = [];
  await context.route('**/*', async route => {
    const request = route.request();
    const url = new URL(request.url());
    if (/\/cluster-observation\/(bind|read)$/.test(url.pathname))
      forbiddenActions.push({ method: request.method(), path: url.pathname });
    const get = request.method() === 'GET';
    const allowed = url.origin === origin && !request.redirectedFrom() && (
      get && (['/', '/dashboard', '/dashboard/fleet', '/dashboard/home',
        '/api/auth/verify', '/api/setup/status', inventory].includes(url.pathname) ||
        url.pathname.startsWith('/static/') && url.search === `?v=${revision}`) ||
      request.method() === 'POST' && ['/api/auth/login', '/api/auth/logout'].includes(url.pathname)
    );
    if (!allowed) {
      blocked.push({ method: request.method(), path: url.origin === origin ? url.pathname : 'off-origin' });
      return route.abort('blockedbyclient');
    }
    if (url.pathname === inventory) inventoryRequests.push(request.method());
    // Principal requests pass through untouched. Explicit auxiliary injection
    // handlers below take precedence only for their labeled consumer checks.
    return route.continue();
  });
  await context.routeWebSocket('**/*', socket => socket.close());

  async function actualInventory(trigger) {
    const pending = page.waitForResponse(response =>
      new URL(response.url()).pathname === inventory && response.request().method() === 'GET');
    await trigger();
    const response = await pending;
    const headers = await response.allHeaders();
    // Original UI cancels non200 bodies. Record browser status/headers without
    // fighting its cancellation; the separate direct request below records
    // an original-handler body under the same synthetic authenticated state.
    observations.push({ client: 'original-browser-consumer', method: response.request().method(), path: inventory,
      status: response.status(), body: 'not collected: original consumer cancels non200', headers: {
        'content-type': headers['content-type'], 'cache-control': headers['cache-control'],
        'x-request-id': headers['x-request-id'],
      } });
    expect(response.status()).toBe(404);
    expect(headers['x-request-id']).toMatch(/^[0-9a-f]{12}$/);
    expect(headers['cache-control']).toContain('no-store');
    expect(headers['content-type']).toContain('application/json');
  }

  try {
    const root = await page.goto('/', { waitUntil: 'domcontentloaded' });
    expect(root.status()).toBe(200);
    await expect(page.locator('#login-overlay')).toBeVisible();
    const anonymous = await context.request.get(inventory);
    expect(anonymous.status()).toBe(403);
    expect((await anonymous.json()).error).toBe('Authentication required');
    await page.locator('#login-user').fill('admin');
    await page.locator('#login-pass').fill('hermetic-dashboard-password');
    const login = page.waitForResponse(response => new URL(response.url()).pathname === '/api/auth/login'
      && response.request().method() === 'POST');
    await page.locator('#login-form').evaluate(form => form.requestSubmit());
    expect((await login).status()).toBe(200);
    await expect(page.locator('#login-overlay')).toBeHidden();
    const direct = await context.request.get(inventory);
    const raw = await direct.text(), body = JSON.parse(raw), directHeaders = direct.headers();
    expect(direct.status()).toBe(404);
    expect(body.error).toBe('not found');
    expect(body.path).toBe(inventory);
    expect(body.request_id).toMatch(/^[0-9a-f]{12}$/);
    expect(directHeaders['x-request-id']).toBe(body.request_id);
    expect(directHeaders['cache-control']).toContain('no-store');
    observations.push({ client: 'direct-shared-synthetic-session', method: 'GET', path: inventory,
      status: direct.status(), raw, headers: { 'content-type': directHeaders['content-type'],
        'cache-control': directHeaders['cache-control'], 'x-request-id': directHeaders['x-request-id'] } });
    const primary = page.getByRole('navigation', { name: 'Primary' });
    const fleet = primary.locator('[data-view="fleet"]');
    await actualInventory(() => fleet.click());
    await expect(page).toHaveURL(`${origin}/dashboard/fleet`);
    await expect(fleet).toHaveAttribute('aria-current', 'page');
    const cards = page.locator('#metrics-cards');
    await expect(cards.getByRole('status')).toHaveText(unavailable);
    await expect(cards.locator('[data-cluster-observation-selection]')).toHaveCount(0);
    await expect(cards).not.toContainText('No configured PVE nodes.');
    for (const id of ['guest-read-start', 'fleet-filter', 'term-type', 'term-target'])
      await expect(page.locator(`#${id}`)).toBeDisabled();
    await expect(page.locator('#fleet-sec-terminal')).toBeHidden();
    await expect(page.locator('#fleet-sec-terminal')).toHaveAttribute('inert', '');
    const refresh = cards.getByRole('button', { name: 'Refresh configured selections', exact: true });
    await expect(refresh).toBeEnabled();
    await refresh.focus();
    await actualInventory(() => page.keyboard.press('Enter'));
    await expect(cards.getByRole('status')).toHaveText(unavailable);
    await expect(cards.locator('[data-cluster-observation-selection]')).toHaveCount(0);
    expect(inventoryRequests).toEqual(['GET', 'GET']);
    expect(forbiddenActions).toEqual([]);
    await page.screenshot({ path: testInfo.outputPath('actual-inventory404-fleet.png'), fullPage: true });

    // These are explicit browser-injected responses, separate from the two
    // actual original-handler404 observations above. They establish consumer
    // distinctions only, never a positive original producer or session grant.
    let supplied;
    const injected = async route => { const selected = supplied;
      return route.fulfill({ status: selected.status,
      headers: { 'content-type': 'application/json', 'cache-control': 'no-store',
        'content-length': String(Buffer.byteLength(selected.body)) }, body: selected.body }); };
    await context.route(`**${inventory}`, injected);
    for (const row of [
      { label: 'injected403', status: 403, body: '{"error":"fixture"}', expected: genericUnavailable },
      { label: 'injected503', status: 503, body: '{"error":"fixture"}', expected: genericUnavailable },
      { label: 'injected200empty', status: 200,
        body: '{"nodes":[],"schema":"cluster-observation-inventory-v1","scope":"configured_source"}',
        expected: 'No configured PVE nodes.' },
      { label: 'injected200malformed', status: 200, body: '{"nodes":[]}', expected: genericUnavailable },
      { label: 'injected200null-selection', status: 200,
        body: '{"nodes":[{"label":"fixture-no-grant","selection_ref":null}],"schema":"cluster-observation-inventory-v1","scope":"configured_source"}',
        expected: 'Select a configured PVE node.' },
    ]) {
      supplied = row;
      const received = page.waitForResponse(response =>
        new URL(response.url()).pathname === inventory && response.request().method() === 'GET');
      await cards.getByRole('button', { name: 'Refresh configured selections', exact: true }).click();
      const actual = await received;
      expect(actual.status()).toBe(row.status);
      await expect(cards.getByRole('status')).toHaveText(row.expected);
      const selections = cards.locator('[data-cluster-observation-selection]');
      await expect(selections).toHaveCount(row.label === 'injected200null-selection' ? 1 : 0);
      if (row.label === 'injected200null-selection') await expect(selections).toBeDisabled();
      injectedCases.push({ label: row.label, expected: row.expected,
        suppliedStatus: row.status, observedStatus: actual.status(), observed: true });
    }
    await context.unroute(`**${inventory}`, injected);

    // Hold an old404 while leaving Fleet. Its completion must not publish
    // into Home; returning to Fleet then gets a new original-handler404.
    let release, entered, completed;
    const held = new Promise(resolve => { entered = resolve; });
    const gate = new Promise(resolve => { release = resolve; });
    const completion = new Promise(resolve => { completed = resolve; });
    const stale = async route => { entered(); await gate;
      try { await route.fulfill({ status: 404, contentType: 'application/json', body: '{"error":"stale-fixture"}' }); }
      catch (_) { /* Navigation may already have aborted the request. */ }
      finally { completed(); }
    };
    await context.route(`**${inventory}`, stale);
    await cards.getByRole('button', { name: 'Refresh configured selections', exact: true }).click();
    await held;
    await primary.locator('[data-view="home"]').click();
    await expect(page).toHaveURL(`${origin}/dashboard/home`);
    const retiredMarkup = await cards.innerHTML();
    release();
    await completion;
    await context.unroute(`**${inventory}`, stale);
    await expect(cards).toHaveJSProperty('innerHTML', retiredMarkup);
    await actualInventory(() => fleet.click());
    await expect(cards.getByRole('status')).toHaveText(unavailable);
    await expect(cards.locator('[data-cluster-observation-selection]')).toHaveCount(0);
    expect(forbiddenActions).toEqual([]);
    expect(fs.readFileSync(path.join(process.env.PVE_FREQ_FLEET_EVIDENCE, 'python-denials.jsonl'), 'utf8')).toBe('');
    expect(fs.readFileSync(path.join(process.env.PVE_FREQ_FLEET_EVIDENCE, 'server-rejections.jsonl'), 'utf8')).toBe('');
  } finally {
    await testInfo.attach('original-inventory-evidence', { contentType: 'application/json',
      body: Buffer.from(JSON.stringify({ scope: 'synthetic auth/config; actual original missing route404',
        observations, inventoryRequests, forbiddenActions, blocked, injectedCases }, null, 2)) });
  }
});

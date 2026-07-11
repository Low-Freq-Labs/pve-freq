const fs = require('node:fs');
const path = require('node:path');
const { test, expect } = require('@playwright/test');

const USER = 'admin';
const PASS = 'hermetic-dashboard-password';

async function apiLogin(request, password = PASS) {
  return request.post('/api/auth/login', {
    data: { username: USER, password }
  });
}

async function bearerSession(request) {
  const response = await apiLogin(request);
  expect(response.status()).toBe(200);
  return await response.json();
}

async function loginInBrowser(page) {
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await page.locator('#login-user').fill(USER);
  await page.locator('#login-pass').fill(PASS);
  await page.locator('#login-form').evaluate(form => form.requestSubmit());
  await page.locator('#login-overlay').waitFor({ state: 'hidden' });
}

test.describe('hermetic dashboard behavior oracle', () => {
  test('unauthenticated dashboard shows the login form', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('#login-overlay')).toBeVisible();
    await expect(page.locator('#login-pass')).toBeVisible();
  });

  test('unauthenticated dashboard keeps fleet content covered', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('#login-overlay')).toBeVisible();
    await expect(page.locator('#login-overlay')).toHaveCSS('display', /^(flex|block)$/);
  });

  test('bad password is rejected', async ({ request }) => {
    const response = await apiLogin(request, 'wrong-password');
    expect(response.status()).toBe(401);
    expect(await response.json()).toHaveProperty('error');
  });

  test('empty password is rejected', async ({ request }) => {
    const response = await request.post('/api/auth/login', {
      data: { username: USER, password: '' }
    });
    expect(response.status()).toBe(400);
  });

  test('successful login returns a session token and csrf token', async ({ request }) => {
    const response = await apiLogin(request);
    expect(response.status()).toBe(200);
    const body = await response.json();
    expect(body.ok).toBe(true);
    expect(body.token).toBeTruthy();
    expect(body.csrf_token).toBeTruthy();
  });

  test('login rejects GET', async ({ request }) => {
    expect((await request.get('/api/auth/login')).status()).toBe(405);
  });

  test('browser login reveals the real dashboard shell', async ({ page }) => {
    await loginInBrowser(page);
    await expect(page.locator('#login-overlay')).toBeHidden();
    await expect(page.locator('body')).toContainText(/FREQ|FLEET|Dashboard/i);
  });

  test('authenticated fleet overview returns cache truth', async ({ request }) => {
    const session = await bearerSession(request);
    const response = await request.get('/api/fleet/overview', {
      headers: { Authorization: `Bearer ${session.token}` }
    });
    expect(response.status()).toBe(200);
    const body = await response.json();
    expect(body.cached).toBe(true);
    expect(body.age_seconds).toEqual(expect.any(Number));
  });

  test('authenticated health returns host state', async ({ request }) => {
    const session = await bearerSession(request);
    const response = await request.get('/api/health', {
      headers: { Authorization: `Bearer ${session.token}` }
    });
    expect(response.status()).toBe(200);
    expect((await response.json()).hosts).toHaveLength(1);
  });

  test('mutation endpoint rejects GET', async ({ request }) => {
    const session = await bearerSession(request);
    const response = await request.get('/api/exec', {
      headers: { Authorization: `Bearer ${session.token}` }
    });
    expect(response.status()).toBe(405);
  });

  test('dashboard sends content-type protection', async ({ request }) => {
    const response = await request.get('/');
    expect(response.headers()['x-content-type-options']).toBe('nosniff');
  });

  test('dashboard denies framing', async ({ request }) => {
    const response = await request.get('/');
    expect(response.headers()['x-frame-options']).toBe('DENY');
  });

  test('dashboard sends a content security policy', async ({ request }) => {
    const response = await request.get('/');
    expect(response.headers()['content-security-policy']).toBeTruthy();
  });

  test('json api responses carry security headers', async ({ request }) => {
    const response = await request.get('/api/setup/status');
    expect(response.headers()['x-content-type-options']).toBe('nosniff');
  });

  test('anonymous fleet access is forbidden', async ({ request }) => {
    expect((await request.get('/api/fleet/overview')).status()).toBe(403);
  });

  test('fleet response exposes explicit freshness state', async ({ request }) => {
    const session = await bearerSession(request);
    const body = await (await request.get('/api/fleet/overview', {
      headers: { Authorization: `Bearer ${session.token}` }
    })).json();
    expect(body).toMatchObject({ cached: true, stale: false, probe_status: 'ok' });
  });

  test('health score is numeric and graded', async ({ request }) => {
    const session = await bearerSession(request);
    const response = await request.get('/api/fleet/health-score', {
      headers: { Authorization: `Bearer ${session.token}` }
    });
    expect(response.status()).toBe(200);
    const body = await response.json();
    expect(body.score).toEqual(expect.any(Number));
    expect(body.grade).toEqual(expect.any(String));
  });

  test('logout invalidates the browser session', async ({ page }) => {
    await loginInBrowser(page);
    expect((await (await page.request.get('/api/auth/verify')).json()).valid).toBe(true);
    expect((await page.request.post('/api/auth/logout')).status()).toBe(200);
    expect((await (await page.request.get('/api/auth/verify')).json()).valid).toBe(false);
  });

  test('unknown api endpoint returns json', async ({ request }) => {
    const session = await bearerSession(request);
    const response = await request.get('/api/hermetic-does-not-exist', {
      headers: { Authorization: `Bearer ${session.token}` }
    });
    expect(response.status()).toBe(404);
    expect(response.headers()['content-type']).toContain('application/json');
    expect(await response.json()).toHaveProperty('error');
  });

  test('served javascript is the checked-in application bundle', async ({ request }) => {
    const response = await request.get('/static/js/app.js');
    expect(response.status()).toBe(200);
    const source = fs.readFileSync(path.join(__dirname, '../../freq/data/web/js/app.js'), 'utf8');
    expect(await response.text()).toBe(source);
  });

  test('probe failure renders a visible transport failure indicator', async ({ page }) => {
    await page.route('**/api/health', async route => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          hosts: [],
          age_seconds: 4,
          probe_state: 'error',
          probe_status: 'error',
          probe_error: 'hermetic probe failure'
        })
      });
    });
    await page.route('**/api/fleet/overview', async route => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          cached: true,
          age_seconds: 4,
          stale: false,
          probe_status: 'error',
          probe_error: 'hermetic probe failure',
          pve_nodes: [],
          vms: [],
          physical: [],
          summary: {}
        })
      });
    });
    await page.goto('/');
    await page.evaluate(() => {
      localStorage.setItem('freq_admin_home_widgets', JSON.stringify(['w-fleet-stats']));
    });
    await loginInBrowser(page);
    await expect(page.locator('#sse-conn-status')).toHaveText('PROBE FAILED');
  });
});

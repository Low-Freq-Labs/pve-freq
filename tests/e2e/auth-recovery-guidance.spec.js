const fs = require('node:fs');
const path = require('node:path');
const { test, expect } = require('@playwright/test');
const COPY = 'Sign-in refused. Check your credentials. If you still cannot sign in, contact your installation operator through your established support channel. Credential recovery is unavailable in this interface.';
const DISCARD = 'Sign-in response discarded after editing. Server outcome is unconfirmed.';
const REVISION = 'login-recovery-guidance-20261102-r1';
const LOGIN = '/api/auth/login';
const CASES = [ ['wrong-password', 'admin'], ['unknown-user', 'unknown-fixture-user'], ['missing-hash', 'operator'] ];

async function contained(context, origin, census, blocked) {
  context.on('request', request => {
    const url = new URL(request.url());
    if (url.pathname.startsWith('/api/')) census.push({ method: request.method(), path: url.pathname });
  });
  await context.route('**/*', route => {
    const request = route.request(), url = new URL(request.url());
    const allowed = url.origin === origin && !request.redirectedFrom() && (
      request.method() === 'GET' && (['/', '/dashboard', '/api/auth/verify'].includes(url.pathname)
        || url.pathname.startsWith('/static/') && url.search === `?v=${REVISION}`)
      || request.method() === 'POST' && url.pathname === LOGIN);
    if (!allowed) { blocked.push({ method: request.method(), path: url.origin === origin ? url.pathname : 'off-origin' }); return route.abort('blockedbyclient'); }
    return route.continue();
  });
  await context.routeWebSocket('**/*', socket => socket.close());
}
async function submit(page, user) {
  await page.locator('#login-user').fill(user);
  await page.locator('#login-pass').fill('synthetic-rejected-password');
  await page.locator('#login-submit-btn').click();
}
async function noSession(context, origin) {
  expect((await context.cookies()).some(cookie => cookie.name === 'freq_session')).toBe(false);
  // Explicit test observation, outside product/browser request census.
  const verify = await context.request.get(`${origin}/api/auth/verify`);
  expect(verify.status()).toBe(200);
  expect((await verify.json()).valid).toBe(false);
}
function guardsClean() {
  for (const name of ['python-denials', 'guard-violations', 'server-rejections'])
    expect(fs.readFileSync(path.join(process.env.PVE_FREQ_AUTH_EVIDENCE, name + '.jsonl'), 'utf8'), name).toBe('');
}
function noRecovery(census) {
  expect(census.filter(entry => ![LOGIN, '/api/auth/verify'].includes(entry.path))).toEqual([]);
  expect(census.filter(entry => entry.path === LOGIN)).toEqual([{ method: 'POST', path: LOGIN }]);
}

for (const [label, user] of CASES) {
  test(`original401 ${label} gives identical conservative continuation`, async ({ browser }, testInfo) => {
    const origin = testInfo.project.use.baseURL;
    const context = await browser.newContext({ baseURL: origin, ignoreHTTPSErrors: true, serviceWorkers: 'block',
      acceptDownloads: false, viewport: { width: 1440, height: 1000 } });
    const census = [], blocked = [], evidence = [];
    try {
      await contained(context, origin, census, blocked);
      const page = await context.newPage();
      expect((await page.goto('/', { waitUntil: 'domcontentloaded' })).status()).toBe(200);
      await expect(page.locator('#login-overlay')).toBeVisible();
      await expect(page.locator('#login-error')).toBeEmpty();
      const pending = page.waitForResponse(response => new URL(response.url()).pathname === LOGIN && response.request().method() === 'POST');
      await submit(page, user);
      const response = await pending;
      expect(response.status()).toBe(401);
      expect(response.headers()['x-request-id']).toMatch(/^[0-9a-f]{12}$/);
      // Do not race the original consumer for a body it may cancel.
      evidence.push({ client: 'original-browser', status: response.status(), request_id: response.headers()['x-request-id'] });
      await expect(page.locator('#login-error')).toHaveText(COPY);
      await expect(page.locator('#login-pass')).toHaveValue('');
      await expect(page.locator('#login-submit-btn')).toBeEnabled();
      await expect(page.locator('#login-overlay')).toBeVisible();
      await expect(page.locator('#login-error a')).toHaveCount(0);
      // Separate direct original response under same fictional rejection ports;
      // never export credentials, cookies, tokens or complete response headers.
      const direct = await context.request.post(`${origin}${LOGIN}`, {
        headers: { Origin: origin }, data: { username: user, password: 'synthetic-rejected-password' }
      });
      expect(direct.status()).toBe(401);
      const body = await direct.json();
      expect(body.error).toBe('Invalid credentials');
      expect(body.request_id).toMatch(/^[0-9a-f]{12}$/);
      evidence.push({ client: 'direct-original', status: direct.status(), error: body.error, request_id: body.request_id });
      await noSession(context, origin);
      noRecovery(census);
      expect(blocked).toEqual([]);
      guardsClean();
      if (label === 'wrong-password') await page.screenshot({ path: testInfo.outputPath('refused-sign-in.png'), fullPage: true });
    } finally {
      await testInfo.attach('sanitized-auth-refusal', { contentType: 'application/json', body: Buffer.from(JSON.stringify({ label, evidence, browser_api_requests: census, blocked }, null, 2)) });
      await context.close();
    }
  });
}

test('labeled held original401 cannot overwrite an edited credential draft', async ({ browser }, testInfo) => {
  const origin = testInfo.project.use.baseURL;
  const context = await browser.newContext({ baseURL: origin, ignoreHTTPSErrors: true, serviceWorkers: 'block',
    acceptDownloads: false, viewport: { width: 1440, height: 1000 } });
  const census = [], blocked = [], evidence = [];
  let release;
  const released = new Promise(resolve => { release = resolve; });
  let arrived;
  const originalReady = new Promise(resolve => { arrived = resolve; });
  let completed;
  const deliveryComplete = new Promise(resolve => { completed = resolve; });
  try {
    await contained(context, origin, census, blocked);
    // Labeled transport hold only: fetch the original server and preserve reply.
    await context.route(`**${LOGIN}`, async route => {
      try {
        const request = route.request(), url = new URL(request.url());
        if (url.origin !== origin || url.pathname !== LOGIN || request.method() !== 'POST' || request.redirectedFrom()) {
          blocked.push({ method: request.method(), path: url.origin === origin ? url.pathname : 'off-origin' });
          return route.abort('blockedbyclient');
        }
        const actual = await route.fetch({ maxRedirects: 0 });
        expect(actual.status()).toBe(401);
        const body = await actual.json();
        expect(body.error).toBe('Invalid credentials');
        evidence.push({ scope: 'held-original401', status: actual.status(), error: body.error, request_id: body.request_id });
        arrived();
        await released;
        try { await route.fulfill({ response: actual }); evidence.push({ delivery: 'released-original-response' }); }
        catch (_) { evidence.push({ delivery: 'original-consumer-aborted-before-delivery' }); }
      } finally { completed(); }
    });
    const page = await context.newPage();
    expect((await page.goto('/', { waitUntil: 'domcontentloaded' })).status()).toBe(200);
    await expect(page.locator('#login-overlay')).toBeVisible();
    await submit(page, 'admin');
    await originalReady;
    await page.locator('#login-pass').fill('new-synthetic-draft');
    await expect(page.locator('#login-error')).toHaveText(DISCARD);
    release();
    await deliveryComplete;
    // Let delivered/aborted transport continuations cross a browser task boundary.
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    await expect(page.locator('#login-pass')).toHaveValue('new-synthetic-draft');
    await expect(page.locator('#login-error')).toHaveText(DISCARD);
    await expect(page.locator('#login-error')).not.toHaveText(COPY);
    await expect(page.locator('#login-submit-btn')).toBeEnabled();
    await noSession(context, origin);
    noRecovery(census);
    expect(blocked).toEqual([]);
    guardsClean();
  } finally {
    release();
    await testInfo.attach('labeled-held-original401', { contentType: 'application/json', body: Buffer.from(JSON.stringify({ evidence, browser_api_requests: census, blocked }, null, 2)) });
    await context.close();
  }
});

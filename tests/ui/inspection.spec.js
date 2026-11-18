const { test, expect } = require('@playwright/test');
const { adminCredentials } = require('../e2e/support/terminal-global-setup');
const { allowedRequest, installInspectionPolicy } = require('../e2e/support/ui-inspection-policy');

test('UI inspection: browser login, shell, navigation and session dialog', async ({ page, context }, testInfo) => {
  const live = process.env.PVE_FREQ_UI_MODE === 'live';
  const origin = process.env.PVE_FREQ_UI_ORIGIN;
  const blocked = new Set();
  const errors = [];
  const failedResponses = [];
  const snapshot = async name => {
    await page.screenshot({ path: testInfo.outputPath(name + '.png'), fullPage: true,
      mask: [page.locator('input[type="password"]')] });
  };
  page.on('pageerror', () => errors.push('Uncaught browser exception (message omitted to avoid leaking runtime data)'));
  page.on('response', response => {
    const url = new URL(response.url());
    if (response.status() >= 400 && (!live || allowedRequest(response.request().method(), response.url(), origin))) {
      failedResponses.push({ path: url.pathname, status: response.status() });
    }
  });
  if (live) await installInspectionPolicy(context, origin, blocked);
  const credentials = live ? adminCredentials() : { user: 'admin', password: 'hermetic-dashboard-password' };
  let authenticated = false;
  try {
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#login-overlay')).toBeVisible();
    try {
      await page.locator('#login-user').fill(credentials.user, { timeout: 5000 });
      await page.locator('#login-pass').fill(credentials.password, { timeout: 5000 });
      const login = page.waitForResponse(response => new URL(response.url()).pathname === '/api/auth/login' && response.request().method() === 'POST', { timeout: 10_000 });
      // Attach rejection handling before pressing Enter to avoid a dangling
      // response waiter if the input disappears or becomes disabled.
      const [response] = await Promise.all([login, page.locator('#login-pass').press('Enter', { timeout: 5000 })]);
      if (response.status() !== 200) throw new Error('Login rejected');
      await expect(page.locator('#login-overlay')).toBeHidden();
    } catch {
      // locator.fill errors contain the value being filled. Neither the original
      // error nor its cause may reach reporters. Remove the page before teardown
      // can capture form values or server-echoed credentials in an error snapshot.
      await page.close().catch(() => {});
      throw new Error('Credential entry or login failed; credential details withheld');
    }
    authenticated = true;
    await expect(page.getByRole('main')).toBeVisible();
    const primary = page.getByRole('navigation', { name: 'Primary' });
    await expect(primary).toBeVisible();
    await expect(page.locator('#home-view')).toBeVisible();
    await snapshot('initial-home');
    if (process.env.PVE_FREQ_UI_JOURNEY === 'navigation') {
      for (const view of ['fleet', 'docker', 'security', 'tools', 'settings', 'home']) {
        await primary.locator(`[data-view="${view}"]`).click();
        await expect(page.locator(`#${view}-view`)).toBeVisible();
        await expect(page).toHaveURL(`${origin}/dashboard/${view}`);
        await expect(primary.locator('[aria-current="page"]')).toHaveCount(1);
        await expect(primary.locator(`[data-view="${view}"]`)).toHaveAttribute('aria-current', 'page');
        await snapshot('navigation-' + view);
      }
    }
    const invoker = page.locator('#header-user-btn');
    await invoker.click();
    const session = page.getByRole('dialog', { name: 'Session' });
    await expect(session).toBeVisible();
    await expect(session.getByRole('button', { name: 'Close session dialog' })).toBeFocused();
    await page.keyboard.press('Escape');
    await expect(session).toBeHidden();
    await expect(invoker).toBeFocused();
    expect(errors, 'No uncaught browser errors').toEqual([]);
    // Optional/unavailable backend diagnostics are evidence, not a shell failure.
    // Entry/auth/version failures in live mode do invalidate the shell run.
    if (live) expect(failedResponses, 'Allowed browser entry APIs must succeed').toEqual([]);
  } finally {
    if (authenticated) await snapshot('final').catch(() => {});
    await testInfo.attach('inspection-diagnostics', { contentType: 'application/json', body: Buffer.from(JSON.stringify({
      mode: live ? 'live guarded shell' : 'local synthetic fixture',
      blockedRequests: [...blocked].sort(), uncaughtErrors: errors, failedResponses,
      coverageLimit: live ? 'Operational API requests were blocked; fleet correctness is untested.' : 'Synthetic fixture, not live infrastructure.'
    }, null, 2)) });
  }
});

const { test, expect } = require('@playwright/test');

const USER = process.env.PVE_FREQ_USER;
const PASS = process.env.PVE_FREQ_PASS;

function requireLiveCredentials() {
  test.skip(!USER || !PASS, 'Set PVE_FREQ_USER and PVE_FREQ_PASS for live dashboard E2E tests.');
}

async function login(page) {
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await page.locator('#login-user').fill(USER);
  await page.locator('#login-pass').fill(PASS);
  await page.locator('#login-form').evaluate(form => form.requestSubmit());
  await page.locator('#login-overlay').waitFor({ state: 'hidden', timeout: 20_000 });
}

async function api(page, path, options = {}) {
  return await page.evaluate(async ({ path, options }) => {
    const response = await fetch(path, options);
    let body = null;
    try {
      body = await response.json();
    } catch {
      body = await response.text();
    }
    return { status: response.status, body };
  }, { path, options });
}

async function goDocker(page) {
  await page.getByRole('button', { name: 'DOCKER', exact: true }).click();
  await page.locator('#services-container-cards .crd').first().waitFor({ timeout: 30_000 });
}

test.describe('live Docker controls', () => {
  test.beforeEach(async ({ page }) => {
    requireLiveCredentials();
    await login(page);
  });

  test('Plex logs button returns real output', async ({ page }) => {
    await goDocker(page);

    const plexCard = page.locator('#services-container-cards .crd').filter({ hasText: /^PLEX/i }).first();
    await expect(plexCard).toBeVisible();
    await plexCard.getByRole('button', { name: 'LOGS', exact: true }).click();

    const logs = page.locator('.container-logs-panel:visible, #container-logs:visible').first();
    await expect(logs).toBeVisible();
    await expect(logs).toContainText(/Plex Media Server|ls\.io-init|Critical: libusb_init|Starting Plex/i, { timeout: 20_000 });
    await expect(logs).not.toContainText(/Permission denied|not accessible|Failed to load/i);

    const direct = await api(page, '/api/containers/logs?host=plex&name=plex&lines=5');
    expect(direct.status).toBe(200);
    expect(direct.body.ok, JSON.stringify(direct.body, null, 2)).toBe(true);
    expect(direct.body.resolved_host).toBe('plex');
    expect(String(direct.body.output || '').length).toBeGreaterThan(10);
  });

  test('Plex restart button reports success and service comes back', async ({ page }) => {
    test.skip(
      process.env.PVE_FREQ_RUN_DOCKER_RESTART_E2E !== '1',
      'Plex restart bounces a real prod container; run explicitly when approved.'
    );
    test.setTimeout(90_000);
    await goDocker(page);

    const plexCard = page.locator('#services-container-cards .crd').filter({ hasText: /^PLEX/i }).first();
    await expect(plexCard).toBeVisible();
    await plexCard.getByRole('button', { name: 'RESTART', exact: true }).click();
    await page.locator('#modal-confirm-btn').click();

    await expect(page.locator('#toast-container')).toContainText(/plex restarted/i, { timeout: 30_000 });

    let last = null;
    for (let i = 0; i < 12; i += 1) {
      last = await api(page, '/api/containers/logs?host=plex&name=plex&lines=5');
      if (last.status === 200 && last.body && last.body.ok === true && String(last.body.output || '').length > 10) {
        return;
      }
      await page.waitForTimeout(5_000);
    }
    throw new Error(`plex did not return readable logs after restart: ${JSON.stringify(last)}`);
  });
});

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

async function goFleet(page) {
  await page.getByRole('button', { name: 'FLEET', exact: true }).click();
  await page.locator('.infra-role-card').first().waitFor({ timeout: 30_000 });
}

async function expectNoOperatorWarnings(page) {
  const banner = page.locator('#auth-truth-banner');
  if (await banner.isVisible().catch(() => false)) {
    await expect(banner).not.toContainText(/DOCTOR: WARNING|DOCTOR: ERROR|DEGRADED|UNHEALTHY|SSH probe down|auth failed|unreachable/i);
  }

  const toastWarnings = page.locator('#toast-container .toast').filter({
    hasText: /warning|error|degraded|ssh probe down|auth failed|unreachable/i
  });
  await expect(toastWarnings).toHaveCount(0);
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

async function waitForHealthyDoctor(page) {
  let last = null;
  for (let i = 0; i < 6; i += 1) {
    last = await api(page, '/api/doctor');
    if (
      last.status === 200 &&
      last.body &&
      last.body.status === 'healthy' &&
      last.body.failed === 0 &&
      last.body.warnings === 0
    ) {
      return last;
    }
    await page.waitForTimeout(5_000);
  }
  throw new Error(`doctor did not settle healthy: ${JSON.stringify(last)}`);
}

test.describe('live dashboard safe E2E', () => {
  test.beforeEach(async ({ page }) => {
    requireLiveCredentials();
    await login(page);
  });

  test('doctor and infra quick are clean', async ({ page }) => {
    const doctor = await waitForHealthyDoctor(page);
    expect(doctor.status).toBe(200);

    const quick = await api(page, '/api/infra/quick');
    expect(quick.status).toBe(200);
    expect(quick.body.probe_status).toBe('ok');

    const devices = quick.body.devices || [];
    expect(devices.length).toBeGreaterThanOrEqual(4);
    for (const dev of devices) {
      expect(dev.reachable, `${dev.label} should be reachable`).toBeTruthy();
      expect(dev.auth_failed, `${dev.label} should not auth-fail`).toBeFalsy();
    }
  });

  test('core system cards open and read-only actions produce visible output', async ({ page }) => {
    await goFleet(page);
    const cards = await page.locator('.infra-role-card:visible').count();
    expect(cards).toBeGreaterThanOrEqual(4);

    for (let i = 0; i < cards; i += 1) {
      const card = page.locator('.infra-role-card:visible').nth(i);
      const label = (await card.getAttribute('data-label')) || `card-${i}`;
      await card.click();
      await page.locator('#host-overlay.open').waitFor();
      await expect(page.locator('#hd-infra-out')).toHaveCount(1);

      const readButton = page.locator(
        '#host-overlay button:has-text("STATUS"), #host-overlay button:has-text("SYSTEM"), #host-overlay button:has-text("POOLS")'
      ).first();
      await expect(readButton, `${label} read button`).toBeVisible();
      await readButton.click();
      await expect(page.locator('#hd-infra-out')).toBeVisible();
      if (label.toLowerCase().includes('bmc')) {
        await expect(page.locator('#hd-infra-out'), `${label} final BMC output`).toContainText(/BMC-\d+|PowerEdge|System Information|UNREACHABLE/, { timeout: 35_000 });
      } else {
        await expect(page.locator('#hd-infra-out'), `${label} read output`).not.toHaveText(/^\s*$/);
      }

      await page.locator('#host-overlay [data-action="closeCard"]').click();
      await page.locator('#host-overlay').waitFor({ state: 'hidden' });
    }
  });

  test('safe core device read endpoints return real data', async ({ page }) => {
    const checks = [
      ['/api/infra/pfsense?action=status', body => body.reachable === true && body.auth_failed === false && String(body.output || '').length > 20],
      ['/api/infra/truenas?action=pools', body => body.reachable === true && body.api_available !== false && String(body.output || body.raw || '').length > 5],
      ['/api/switch?action=status', body => body.reachable === true && String(body.output || '').length > 5],
      ['/api/infra/idrac?action=status&target=bmc-10', body => Array.isArray(body.targets) && body.targets.length === 1 && body.targets.every(t => t.reachable === true && String(t.output || '').length > 20)],
      ['/api/infra/idrac?action=status&target=bmc-11', body => Array.isArray(body.targets) && body.targets.length === 1 && body.targets.every(t => t.reachable === true && String(t.output || '').length > 20)]
    ];

    for (const [path, predicate] of checks) {
      const result = await api(page, path);
      expect(result.status, path).toBe(200);
      expect(predicate(result.body), path).toBeTruthy();
    }
  });

  test('terminal sessions open and close without touching power state', async ({ page }) => {
    const opened = [];
    for (const path of [
      '/api/terminal/open?type=vm&target=201&node=pve02&cols=80&rows=24',
      '/api/terminal/open?type=host&target=10.25.255.1&htype=pfsense&cols=80&rows=24'
    ]) {
      const result = await api(page, path, { method: 'POST' });
      expect(result.status, path).toBe(200);
      expect(result.body.ok, path).toBe(true);
      expect(result.body.session, path).toBeTruthy();
      opened.push(result.body.session);
    }

    for (const session of opened) {
      const closed = await api(page, `/api/terminal/close?session=${encodeURIComponent(session)}`, { method: 'POST' });
      expect(closed.status).toBe(200);
      expect(closed.body.ok).toBe(true);
    }
  });

  test('dashboard does not emit page errors during safe navigation', async ({ page }) => {
    const errors = [];
    page.on('pageerror', error => errors.push(String(error)));
    page.on('console', message => {
      if (message.type() === 'error') errors.push(message.text());
    });

    await goFleet(page);
    await page.getByRole('button', { name: 'SYSTEM', exact: true }).click();
    await goFleet(page);
    await page.waitForTimeout(1000);
    await expectNoOperatorWarnings(page);

    expect(errors).toEqual([]);
  });
});

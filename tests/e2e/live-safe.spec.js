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

async function terminalRoundTrip(page, path, input, expected) {
  const opened = await api(page, path, { method: 'POST' });
  expect(opened.status, path).toBe(200);
  expect(opened.body.ok, path).toBe(true);
  expect(opened.body.session, path).toBeTruthy();
  expect(opened.body.ws_nonce, path).toBeTruthy();

  const text = await page.evaluate(async ({ session, nonce, input }) => {
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const ws = new WebSocket(`${proto}//${location.host}/api/terminal/ws?session=${encodeURIComponent(session)}&nonce=${encodeURIComponent(nonce)}`);
    let out = '';
    return await new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        try { ws.close(); } catch {}
        resolve(out);
      }, 20000);
      ws.onerror = () => {
        clearTimeout(timer);
        reject(new Error('terminal websocket failed'));
      };
      ws.onmessage = async event => {
        if (event.data instanceof Blob) {
          out += await event.data.text();
        } else {
          out += String(event.data || '');
        }
      };
      ws.onopen = () => {
        setTimeout(() => {
          try { ws.send(input); } catch {}
        }, 800);
      };
      ws.onclose = () => {
        clearTimeout(timer);
        resolve(out);
      };
    });
  }, { session: opened.body.session, nonce: opened.body.ws_nonce, input });

  const closed = await api(page, `/api/terminal/close?session=${encodeURIComponent(opened.body.session)}`, { method: 'POST' });
  expect(closed.status).toBe(200);
  expect(closed.body.ok).toBe(true);
  expect(text, path).toMatch(expected);
  expect(text, `${path} must not use bootstrap identity after init`).not.toMatch(/freq-ops@/i);
}

test.describe('live dashboard safe E2E', () => {
  test.beforeEach(async ({ page }) => {
    requireLiveCredentials();
    await login(page);
  });

  test('doctor and infra quick are clean', async ({ page }) => {
    const setup = await api(page, '/api/setup/status');
    expect(setup.status).toBe(200);
    expect(setup.body.initialized).toBe(true);
    expect(String(setup.body.reason || ''), JSON.stringify(setup.body, null, 2)).not.toMatch(/partial|stale|setup required|not yet run/i);

    const doctor = await waitForHealthyDoctor(page);
    expect(doctor.status).toBe(200);

    const watchdog = await api(page, '/api/watchdog/health');
    expect(watchdog.status).toBe(200);
    expect(watchdog.body.ok, JSON.stringify(watchdog.body, null, 2)).toBe(true);
    expect(watchdog.body.status, JSON.stringify(watchdog.body, null, 2)).toBe('healthy');
    expect(watchdog.body.errors || 0, JSON.stringify(watchdog.body, null, 2)).toBe(0);

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

  for (const cardCase of [
    { label: 'firewall', button: /STATUS/, expectText: /PFSENSE|states|uptime|interface/i },
    { label: 'switch', button: /STATUS/, expectText: /SWITCH|uptime|version|interface/i },
    { label: 'truenas', button: /SYSTEM/, expectText: /Host|Version|Memory|TrueNAS|truenas/i },
    { label: 'bmc-10', button: /SYSTEM INFO/, expectText: /BMC-10|PowerEdge|System Information/i },
    { label: 'bmc-11', button: /SYSTEM INFO/, expectText: /BMC-11|PowerEdge|System Information/i }
  ]) {
    test(`core system card opens and reads ${cardCase.label}`, async ({ page }) => {
      await goFleet(page);
      const card = page.locator(`.infra-role-card:visible[data-label="${cardCase.label}"]`).first();
      await expect(card).toBeVisible();
      await card.click();
      await page.locator('#host-overlay.open').waitFor();
      await expect(page.locator('#hd-infra-out')).toHaveCount(1);

      const readButton = page.locator('#host-overlay button').filter({ hasText: cardCase.button }).first();
      await expect(readButton, `${cardCase.label} read button`).toBeVisible();
      await readButton.click();

      const out = page.locator('#hd-infra-out');
      await expect(out).toBeVisible();
      await expect(out, `${cardCase.label} readable output`).toContainText(cardCase.expectText, { timeout: 35_000 });

      await page.locator('#host-overlay [data-action="closeCard"]').click();
      await page.locator('#host-overlay').waitFor({ state: 'hidden' });
    });
  }

  test('visible core system cards are clickable', async ({ page }) => {
    await goFleet(page);
    const cards = await page.locator('.infra-role-card:visible').count();
    expect(cards).toBeGreaterThanOrEqual(4);

    for (let i = 0; i < cards; i += 1) {
      const card = page.locator('.infra-role-card:visible').nth(i);
      await card.click();
      await page.locator('#host-overlay.open').waitFor();
      await expect(page.locator('#hd-infra-out')).toHaveCount(1);
      await page.locator('#host-overlay [data-action="closeCard"]').click();
      await page.locator('#host-overlay').waitFor({ state: 'hidden' });
    }
  });

  for (const endpointCase of [
    { name: 'pfSense status', path: '/api/infra/pfsense?action=status', predicate: body => body.reachable === true && body.auth_failed === false && String(body.output || '').length > 20 },
    { name: 'TrueNAS pools', path: '/api/infra/truenas?action=pools', predicate: body => body.reachable === true && body.api_available !== false && String(body.output || body.raw || '').length > 5 },
    { name: 'switch status', path: '/api/switch?action=status', predicate: body => body.reachable === true && String(body.output || '').length > 5 },
    { name: 'bmc-10 status', path: '/api/infra/idrac?action=status&target=bmc-10', predicate: body => Array.isArray(body.targets) && body.targets.length === 1 && body.targets.every(t => t.reachable === true && String(t.output || '').length > 20) },
    { name: 'bmc-11 status', path: '/api/infra/idrac?action=status&target=bmc-11', predicate: body => Array.isArray(body.targets) && body.targets.length === 1 && body.targets.every(t => t.reachable === true && String(t.output || '').length > 20) }
  ]) {
    test(`safe core endpoint returns real data: ${endpointCase.name}`, async ({ page }) => {
      const path = endpointCase.path;
      const result = await api(page, path);
      expect(result.status, path).toBe(200);
      expect(endpointCase.predicate(result.body), `${path}\n${JSON.stringify(result.body, null, 2)}`).toBeTruthy();
    });
  }

  test('truenas alerts render as operator-readable output', async ({ page }) => {
    await goFleet(page);
    const truenasCard = page.locator('.infra-role-card:visible[data-label="truenas"]').first();
    await expect(truenasCard).toBeVisible();
    await truenasCard.click();
    await page.locator('#host-overlay.open').waitFor();

    const alertsButton = page.locator('#host-overlay button:has-text("ALERTS")').first();
    await expect(alertsButton).toBeVisible();
    await alertsButton.click();

    const out = page.locator('#hd-infra-out');
    await expect(out).toBeVisible();
    await expect(out).toContainText(/No active TrueNAS alerts|What it means/, { timeout: 20_000 });
    await expect(out).toContainText(/No active TrueNAS alerts|What to do/, { timeout: 20_000 });
  });

  test('expanded core read actions render readable output without toast spam', async ({ page }) => {
    const cases = [
      { label: 'firewall', buttons: [/RULES/, /NAT/, /STATES/, /INTERFACES/, /ARP TABLE/], expect: /PFSENSE|FILTER RULES|NAT RULES|TOP STATES|INTERFACES|ARP TABLE|IP Address|IP ADDRESS/i },
      { label: 'switch', buttons: [/CDP NEIGHBORS/], expect: /SWITCH|CDP|NEIGHBOR|Device ID|Local Intrfce/i },
      { label: 'truenas', buttons: [/SMART DISKS/, /SNAPSHOTS/, /NETWORK/, /SYSTEM LOG/], expect: /TRUENAS|Disk|Snapshot|Interface|SYSTEM LOG|Raw TrueNAS payload/i },
      { label: 'bmc-10', buttons: [/FIRMWARE/, /LICENSE/, /NETWORK/], expect: /BMC-10|Firmware|License|NIC|Network|Raw BMC-10/i }
    ];

    await goFleet(page);
    for (const item of cases) {
      const card = page.locator(`.infra-role-card:visible[data-label="${item.label}"]`).first();
      await expect(card).toBeVisible();
      await card.click();
      await page.locator('#host-overlay.open').waitFor();
      const out = page.locator('#hd-infra-out');

      for (const buttonText of item.buttons) {
        const btn = page.locator('#host-overlay button').filter({ hasText: buttonText }).first();
        await expect(btn, `${item.label} ${buttonText}`).toBeVisible();
        await btn.click();
        await expect(out, `${item.label} ${buttonText} output`).toContainText(item.expect, { timeout: 45_000 });
        if (item.label === 'firewall' && String(buttonText).includes('INTERFACES')) {
          await expect(out).toContainText(/IP Address/i);
          await expect(out).not.toContainText(/ALL INTERFACES/i);
        }
        await expect(out).not.toContainText(/^\s*\{[\s\S]*\}\s*$/);
      }

      await page.locator('#host-overlay [data-action="closeCard"]').click();
      await page.locator('#host-overlay').waitFor({ state: 'hidden' });
    }

    await expectNoOperatorWarnings(page);
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

  test('network device terminals return real websocket output', async ({ page }) => {
    test.setTimeout(90_000);
    await terminalRoundTrip(
      page,
      '/api/terminal/open?type=host&target=10.25.255.1&htype=pfsense&cols=100&rows=24',
      'hostname\n',
      /pfsense|dc01-admin@pfsense/i
    );
    await terminalRoundTrip(
      page,
      '/api/terminal/open?type=host&target=10.25.255.5&htype=switch&cols=100&rows=24',
      'show version | include uptime\n',
      /uptime is|gigecolo/i
    );
  });

  test('truenas terminal returns real websocket output', async ({ page }) => {
    test.setTimeout(60_000);
    await terminalRoundTrip(
      page,
      '/api/terminal/open?type=host&target=10.25.255.25&htype=truenas&cols=100&rows=24',
      'hostname\n',
      /truenas|freenas|dc01-admin/i
    );
  });

  test('idrac terminal returns real websocket output', async ({ page }) => {
    test.skip(
      process.env.PVE_FREQ_RUN_IDRAC_TERMINAL_E2E !== '1',
      'iDRAC interactive terminal consumes scarce BMC SSH sessions; run explicitly after a cooldown.'
    );
    test.setTimeout(90_000);
    // iDRAC 6/7 controllers keep SSH sessions occupied briefly after
    // read-only racadm calls. The full live suite intentionally exercises
    // BMC buttons immediately before terminal checks, so leave a cooldown
    // before opening the interactive CLP session.
    await page.waitForTimeout(30_000);

    await terminalRoundTrip(
      page,
      '/api/terminal/open?type=host&target=10.25.255.10&htype=idrac&cols=100&rows=24',
      'racadm getsysinfo -s\n',
      /Power Status|CMC|iDRAC|System Model/i
    );
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

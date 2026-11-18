const { test, expect } = require('@playwright/test');
const { liveInputs } = require('./support/terminal-global-setup');

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

async function loginWith(page, credentials) {
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await page.locator('#login-user').fill(credentials.user);
  await page.locator('#login-pass').fill(credentials.password);
  await page.locator('#login-form').evaluate(form => form.requestSubmit());
  await page.locator('#login-overlay').waitFor({ state: 'hidden', timeout: 20_000 });
}

function auditMutations(page) {
  const requests = [];
  page.on('request', request => {
    const method = request.method().toUpperCase();
    if (!['GET', 'HEAD', 'OPTIONS', 'TRACE'].includes(method)) {
      requests.push({ method, path: new URL(request.url()).pathname });
    }
  });
  return requests;
}

async function clickNav(page, name) {
  if (name === 'SETTINGS') {
    await page.locator('[data-view="settings"]').first().click();
  } else {
    await page.getByRole('button', { name, exact: true }).click();
  }
  await page.waitForTimeout(500);
}

async function clickAction(page, action, arg = null) {
  const selector = arg
    ? `[data-action="${action}"][data-arg="${arg}"]`
    : `[data-action="${action}"]`;
  await page.locator(`${selector}:visible`).first().click();
}

async function expectOutput(locator, pattern = /[A-Za-z0-9]/, timeout = 30_000) {
  await expect(locator).toBeVisible({ timeout });
  await expect(locator).toContainText(pattern, { timeout });
  await expect(locator).not.toContainText(/Permission denied|not accessible|Traceback|Unhandled|undefined|null null/i);
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
    const requestOptions = { ...options };
    const method = String(requestOptions.method || 'GET').toUpperCase();
    if (!['GET', 'HEAD', 'OPTIONS', 'TRACE'].includes(method)) {
      const headers = { ...(requestOptions.headers || {}) };
      if (!headers['X-Freq-CSRF']) {
        const verify = await fetch('/api/auth/verify', { credentials: 'same-origin' });
        const session = await verify.json().catch(() => ({}));
        if (session.csrf_token) headers['X-Freq-CSRF'] = session.csrf_token;
      }
      requestOptions.headers = headers;
    }
    if (!requestOptions.credentials) requestOptions.credentials = 'same-origin';
    const response = await fetch(path, requestOptions);
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


test.describe('terminal live owners', () => {
  test('L01 doctor, fleet, system, security, settings, and degradation reads stay mutation-free', async ({ page }) => {
    test.setTimeout(6 * 60 * 1000);
    const credentials = liveInputs().admin;
    await loginWith(page, credentials);
    const mutations = auditMutations(page);

    await test.step('setup, doctor, watchdog, quick truth, cards, and direct device reads are healthy', async () => {
      const setup = await api(page, '/api/setup/status');
      expect(setup.status).toBe(200);
      expect(setup.body.initialized).toBe(true);
      expect(String(setup.body.reason || ''), JSON.stringify(setup.body, null, 2)).not.toMatch(/partial|stale|setup required|not yet run/i);
      await waitForHealthyDoctor(page);

      const watchdog = await api(page, '/api/watchdog/health');
      expect(watchdog.status).toBe(200);
      expect(watchdog.body).toMatchObject({ ok: true, status: 'healthy' });
      expect(watchdog.body.errors || 0).toBe(0);

      const quick = await api(page, '/api/infra/quick');
      expect(quick.status).toBe(200);
      expect(quick.body.probe_status).toBe('ok');
      expect((quick.body.devices || []).length).toBeGreaterThanOrEqual(4);
      for (const device of quick.body.devices || []) {
        expect(device.reachable, `${device.label} should be reachable`).toBeTruthy();
        expect(device.auth_failed, `${device.label} should not auth-fail`).toBeFalsy();
      }

      const cardCases = [
        { label: 'firewall', button: /STATUS/, output: /PFSENSE|states|uptime|interface/i },
        { label: 'switch', button: /STATUS/, output: /SWITCH|uptime|version|interface/i },
        { label: 'truenas', button: /SYSTEM/, output: /Host|Version|Memory|TrueNAS|truenas/i },
        { label: 'bmc-10', button: /SYSTEM INFO/, output: /BMC-10|PowerEdge|System Information/i },
        { label: 'bmc-11', button: /SYSTEM INFO/, output: /BMC-11|PowerEdge|System Information/i }
      ];
      await goFleet(page);
      for (const item of cardCases) {
        const card = page.locator(`.infra-role-card:visible[data-label="${item.label}"]`).first();
        await expect(card).toBeVisible();
        await card.click();
        await page.locator('#host-overlay.open').waitFor();
        const button = page.locator('#host-overlay button').filter({ hasText: item.button }).first();
        await expect(button).toBeVisible();
        await button.click();
        await expectOutput(page.locator('#hd-infra-out'), item.output, 45_000);
        await page.locator('#host-overlay [data-action="closeCard"]').click();
        await page.locator('#host-overlay').waitFor({ state: 'hidden' });
      }

      const visibleCards = await page.locator('.infra-role-card:visible').count();
      expect(visibleCards).toBeGreaterThanOrEqual(4);
      for (let index = 0; index < visibleCards; index += 1) {
        await page.locator('.infra-role-card:visible').nth(index).click();
        await page.locator('#host-overlay.open').waitFor();
        await expect(page.locator('#hd-infra-out')).toHaveCount(1);
        await page.locator('#host-overlay [data-action="closeCard"]').click();
        await page.locator('#host-overlay').waitFor({ state: 'hidden' });
      }

      const endpoints = [
        { path: '/api/infra/pfsense?action=status', valid: body => body.reachable === true && body.auth_failed === false && String(body.output || '').length > 20 },
        { path: '/api/infra/truenas?action=pools', valid: body => body.reachable === true && body.api_available !== false && String(body.output || body.raw || '').length > 5 },
        { path: '/api/switch?action=status', valid: body => body.reachable === true && String(body.output || '').length > 5 },
        { path: '/api/infra/idrac?action=status&target=bmc-10', valid: body => Array.isArray(body.targets) && body.targets.length === 1 && body.targets.every(target => target.reachable === true && String(target.output || '').length > 20) },
        { path: '/api/infra/idrac?action=status&target=bmc-11', valid: body => Array.isArray(body.targets) && body.targets.length === 1 && body.targets.every(target => target.reachable === true && String(target.output || '').length > 20) }
      ];
      for (const endpoint of endpoints) {
        const result = await api(page, endpoint.path);
        expect(result.status, endpoint.path).toBe(200);
        expect(endpoint.valid(result.body), `${endpoint.path}\n${JSON.stringify(result.body, null, 2)}`).toBeTruthy();
      }
    });

    await test.step('expanded core reads and TrueNAS alerts remain operator-readable', async () => {
      await goFleet(page);
      const truenas = page.locator('.infra-role-card:visible[data-label="truenas"]').first();
      await truenas.click();
      await page.locator('#host-overlay.open').waitFor();
      await page.locator('#host-overlay button:has-text("ALERTS")').first().click();
      await expectOutput(page.locator('#hd-infra-out'), /No active TrueNAS alerts|What it means/, 30_000);
      await expect(page.locator('#hd-infra-out')).toContainText(/No active TrueNAS alerts|What to do/);
      await page.locator('#host-overlay [data-action="closeCard"]').click();
      await page.locator('#host-overlay').waitFor({ state: 'hidden' });

      for (const item of [
        { label: 'firewall', buttons: [/RULES/, /NAT/, /STATES/, /INTERFACES/, /ARP TABLE/], output: /PFSENSE|FILTER RULES|NAT RULES|TOP STATES|INTERFACES|ARP TABLE|IP Address/i },
        { label: 'switch', buttons: [/CDP NEIGHBORS/], output: /SWITCH|CDP|NEIGHBOR|Device ID|Local Intrfce/i },
        { label: 'truenas', buttons: [/SMART DISKS/, /SNAPSHOTS/, /NETWORK/, /SYSTEM LOG/], output: /TRUENAS|Disk|Snapshot|Interface|SYSTEM LOG|Raw TrueNAS payload/i },
        { label: 'bmc-10', buttons: [/FIRMWARE/, /LICENSE/, /NETWORK/], output: /BMC-10|Firmware|License|NIC|Network|Raw BMC-10/i }
      ]) {
        const card = page.locator(`.infra-role-card:visible[data-label="${item.label}"]`).first();
        await card.click();
        await page.locator('#host-overlay.open').waitFor();
        for (const text of item.buttons) {
          await page.locator('#host-overlay button').filter({ hasText: text }).first().click();
          await expectOutput(page.locator('#hd-infra-out'), item.output, 45_000);
        }
        await page.locator('#host-overlay [data-action="closeCard"]').click();
        await page.locator('#host-overlay').waitFor({ state: 'hidden' });
      }
      await expectNoOperatorWarnings(page);
    });

    await test.step('System, Security, and Settings read surfaces return useful data', async () => {
      await clickNav(page, 'SYSTEM');
      await clickAction(page, 'runDoctor');
      await expectOutput(page.locator('#diag-out'), /STATUS|passed|healthy|All /i, 45_000);
      const logHost = page.locator('#log-host');
      await expect(logHost).toBeVisible();
      if (await logHost.locator('option').count() > 1) await logHost.selectOption({ index: 1 });
      await clickAction(page, 'fetchLogs');
      await expectOutput(page.locator('#log-out'), /journal|freq|log|systemd|sshd|No logs|-- No entries --/i, 45_000);
      for (const [action, arg, locator, pattern] of [
        ['loadZfs', null, '#zfs-out', /pool|ZFS|No ZFS|not installed/i],
        ['loadBackups', 'list', '#backup-out', /backup|snapshot|No backups|list/i],
        ['loadBackups', 'status', '#backup-out', /status|backup|snapshot|No backups/i],
        ['loadInventory', null, '#inventory-out', /Hosts|VMs|Containers/i],
        ['generateReport', null, '#inventory-out', /fleet|host|vm|container/i]
      ]) {
        await clickAction(page, action, arg);
        await expectOutput(page.locator(locator), pattern, 45_000);
      }
      for (const view of ['hosts', 'vms', 'containers']) {
        await clickAction(page, 'loadInventoryView', view);
        await expectOutput(page.locator('#inventory-out'), new RegExp(view, 'i'), 45_000);
      }
      for (const kind of ['db', 'logs', 'proxy', 'pool', 'setup']) {
        await clickAction(page, 'loadSysInfo', kind);
        await expectOutput(page.locator('#sysinfo-out'), /No |status|routes|pool|setup|healthy|errors|DB|database/i, 45_000);
      }

      await clickNav(page, 'SECURITY');
      await expectOutput(page.locator('#sec-secrets-audit'), /SECRETS AUDIT|LEASES/i, 45_000);
      await expectOutput(page.locator('#sec-comply-status'), /COMPLIANCE|CIS/i, 45_000);
      await clickAction(page, 'loadSecretsLeases');
      await expectOutput(page.locator('#sec-secrets-detail'), /No secret leases|Key|Expires|Status/i, 45_000);
      await clickAction(page, 'loadSecretsScan');
      await expectOutput(page.locator('#sec-secrets-detail'), /No secrets|finding|Last scan|scan/i, 45_000);
      await page.locator('[data-view="sec-compliance"]:visible').first().click();
      await expectOutput(page.locator('#policy-out'), /Last scan|No |Pass|Fail|Score|compliance/i, 45_000);

      await clickNav(page, 'SETTINGS');
      for (const [action, locator, pattern] of [
        ['loadCosts', '#cost-summary', /TOTAL \/ MONTH|TOTAL WATTS|RATE|kWh|No /i],
        ['loadFederation', '#fed-sites', /No sites registered|Site|URL|Status|registered/i],
        ['openApiDocs', '#api-docs-out, #settings-api-out', /api|endpoint|openapi|docs/i],
        ['loadOpenApi', '#api-docs-out', /Endpoints|openapi|paths|version/i],
        ['loadPrometheus', '#api-docs-out', /HELP|TYPE|freq_|python|process/i]
      ]) {
        await clickAction(page, action);
        await expectOutput(page.locator(locator).first(), pattern, 45_000);
      }
      expect((await api(page, '/api/openapi.json')).status).toBe(200);
    });

    await test.step('optional Fleet enrichment degrades without stale loading rows', async () => {
      await page.route('**/api/fleet/ntp', route => route.fulfill({ status: 200, contentType: 'application/json', body: '{}' }));
      await page.route('**/api/fleet/updates', route => route.fulfill({ status: 200, contentType: 'application/json', body: '{}' }));
      await page.route('**/api/infra/quick', route => route.fulfill({ status: 200, contentType: 'application/json', body: '{}' }));
      await page.reload({ waitUntil: 'domcontentloaded' });
      await page.locator('#login-overlay').waitFor({ state: 'hidden', timeout: 20_000 }).catch(() => {});
      await goFleet(page);
      await expect(page.locator('#metrics-cards')).not.toContainText('Loading...');
      await expect(page.locator('#metrics-cards')).toContainText(/PENDING|UNAVAILABLE|PROXMOX NODES/);
    });

    expect(mutations).toEqual([]);
  });

  test('L02 Docker, network, storage, and explicit device terminals allow only terminal session POSTs', async ({ page }) => {
    test.setTimeout(6 * 60 * 1000);
    const credentials = liveInputs().admin;
    await loginWith(page, credentials);
    const mutations = auditMutations(page);

    await test.step('Docker and Network read surfaces return real output', async () => {
      await clickNav(page, 'DOCKER');
      await page.locator('#services-container-cards .crd').first().waitFor({ timeout: 30_000 });
      await clickAction(page, 'loadStackInfo', 'status');
      await expectOutput(page.locator('#stack-info'), /Stacks|No Docker Compose stacks/i);
      await clickAction(page, 'loadStackInfo', 'health');
      await expectOutput(page.locator('#stack-info'), /Containers|No running containers|Healthy/i);
      await clickAction(page, 'switchDockerSub', 'registry');
      await expectOutput(page.locator('#registry-table'), /Container|No containers|Registry/i);
      await clickAction(page, 'switchDockerSub', 'fleet-inv');
      await expectOutput(page.locator('#docker-fleet-table'), /Docker VMs|Container|No Docker VMs|plex/i);

      await clickAction(page, 'switchDockerSub', 'services');
      const plex = page.locator('#services-container-cards .crd').filter({ hasText: /^PLEX/i }).first();
      await expect(plex).toBeVisible();
      await plex.getByRole('button', { name: 'LOGS', exact: true }).click();
      const logs = page.locator('.container-logs-panel:visible, #container-logs:visible').first();
      await expectOutput(logs, /Plex Media Server|ls\.io-init|Critical: libusb_init|Starting Plex/i, 30_000);
      const direct = await api(page, '/api/containers/logs?host=plex&name=plex&lines=5');
      expect(direct.status).toBe(200);
      expect(direct.body.ok).toBe(true);
      expect(direct.body.resolved_host).toBe('plex');
      expect(String(direct.body.output || '').length).toBeGreaterThan(10);

      await clickNav(page, 'FLEET');
      await page.locator('[data-view="network"]:visible').first().click();
      for (const action of ['show', 'facts', 'interfaces', 'vlans', 'mac', 'arp', 'neighbors', 'environment']) {
        await clickAction(page, 'loadSwitchData', action);
        await expectOutput(page.locator('#switch-detail-out'), /switch|vlan|interface|mac|arp|neighbor|environment|uptime|version|No /i, 45_000);
      }
    });

    await test.step('terminal sessions open, return non-bootstrap output, and close', async () => {
      const opened = [];
      for (const path of [
        '/api/terminal/open?type=vm&target=201&node=pve02&cols=80&rows=24',
        '/api/terminal/open?type=host&target=10.25.255.1&htype=pfsense&cols=80&rows=24'
      ]) {
        const result = await api(page, path, { method: 'POST' });
        expect(result.status, path).toBe(200);
        expect(result.body).toMatchObject({ ok: true });
        expect(result.body.session).toBeTruthy();
        expect(result.body.ws_nonce).toBeTruthy();
        opened.push(result.body.session);
      }
      for (const session of opened) {
        const closed = await api(page, `/api/terminal/close?session=${encodeURIComponent(session)}`, { method: 'POST' });
        expect(closed.status).toBe(200);
        expect(closed.body.ok).toBe(true);
      }

      await terminalRoundTrip(page, '/api/terminal/open?type=host&target=10.25.255.1&htype=pfsense&cols=100&rows=24', 'hostname\n', /pfsense|dc01-admin@pfsense/i);
      await terminalRoundTrip(page, '/api/terminal/open?type=host&target=10.25.255.5&htype=switch&cols=100&rows=24', 'show version | include uptime\n', /uptime is|gigecolo/i);
      await terminalRoundTrip(page, '/api/terminal/open?type=host&target=10.25.255.25&htype=truenas&cols=100&rows=24', 'hostname\n', /truenas|freenas|dc01-admin/i);
      await page.waitForTimeout(30_000);
      await terminalRoundTrip(page, '/api/terminal/open?type=host&target=10.25.255.10&htype=idrac&cols=100&rows=24', 'racadm getsysinfo -s\n', /Power Status|CMC|iDRAC|System Model/i);
    });

    expect(mutations.length).toBeGreaterThan(0);
    expect(mutations.every(request => (
      request.method === 'POST' &&
      ['/api/terminal/open', '/api/terminal/close'].includes(request.path)
    )), JSON.stringify(mutations, null, 2)).toBe(true);
  });

  test('L03 live desktop and phone shells stay responsive, grouped, and console-clean', async ({ browser }, testInfo) => {
    test.setTimeout(4 * 60 * 1000);
    const credentials = liveInputs().admin;
    const errors = [];
    const contexts = [];
    const mutationAudits = [];
    const openPage = async viewport => {
      const context = await browser.newContext({
        baseURL: testInfo.project.use.baseURL,
        viewport,
        ignoreHTTPSErrors: true
      });
      contexts.push(context);
      const page = await context.newPage();
      page.on('pageerror', error => errors.push(String(error)));
      page.on('console', message => {
        if (message.type() === 'error') errors.push(message.text());
      });
      return page;
    };

    try {
      const mobile = await openPage({ width: 390, height: 844 });
      await mobile.goto('/', { waitUntil: 'networkidle' });
      const loginGeometry = await mobile.locator('.login-card').evaluate(element => {
        const rect = element.getBoundingClientRect();
        return { left: rect.left, right: rect.right, width: rect.width, viewport: innerWidth };
      });
      expect(loginGeometry.left).toBeGreaterThanOrEqual(0);
      expect(loginGeometry.right).toBeLessThanOrEqual(loginGeometry.viewport);
      expect(loginGeometry.width).toBeGreaterThan(300);
      await loginWith(mobile, credentials);
      mutationAudits.push(auditMutations(mobile));
      await expect(mobile.locator('.mobile-menu-btn')).toBeVisible();
      await mobile.locator('.mobile-menu-btn').click();
      await expect(mobile.locator('#nav-items')).toBeVisible();
      await expect(mobile.getByRole('button', { name: 'FLEET', exact: true })).toBeVisible();
      await expect(mobile.getByRole('button', { name: 'SYSTEM', exact: true })).toBeVisible();
      await mobile.getByRole('button', { name: 'FLEET', exact: true }).click();
      await mobile.locator('#metrics-cards .pve-group').first().waitFor({ timeout: 30_000 });
      await expect(mobile.locator('#fleet-sec-ct')).toBeHidden();
      const mobileOverflow = await mobile.evaluate(() => ({ width: innerWidth, scroll: document.documentElement.scrollWidth }));
      expect(mobileOverflow.scroll).toBeLessThanOrEqual(mobileOverflow.width);

      const shellGeometry = await mobile.evaluate(() => {
        const ids = ['page-title', 'stream-status', 'watchdog-status', 'header-user-btn'];
        const rects = Object.fromEntries(ids.map(id => [id, document.getElementById(id)?.getBoundingClientRect()]));
        const overlaps = (a, b) => a && b && !(a.right <= b.left || b.right <= a.left || a.bottom <= b.top || b.bottom <= a.top);
        return {
          overflow: overlaps(rects['page-title'], rects['stream-status']) || overlaps(rects['page-title'], rects['watchdog-status']) || overlaps(rects['watchdog-status'], rects['header-user-btn']),
          right: Math.max(...ids.map(id => rects[id]?.right || 0)),
          viewport: innerWidth
        };
      });
      expect(shellGeometry.overflow).toBe(false);
      expect(shellGeometry.right).toBeLessThanOrEqual(shellGeometry.viewport);

      const tableGeometry = await mobile.evaluate(() => {
        const host = document.createElement('div');
        host.className = 'section-body';
        host.innerHTML = '<input id="l03-input"><select id="l03-select"><option>proof</option></select><table id="l03-table"><tr><th>Host</th><th>Description</th></tr><tr><td>nexus</td><td>long generated value</td></tr></table>';
        document.querySelector('#fleet-view').prepend(host);
        window._enhanceResponsiveTables(host);
        const table = host.querySelector('table');
        return {
          tableRight: table.getBoundingClientRect().right,
          inputRight: host.querySelector('input').getBoundingClientRect().right,
          selectRight: host.querySelector('select').getBoundingClientRect().right,
          classed: table.classList.contains('responsive-table'),
          label: table.querySelector('td').getAttribute('data-label'),
          viewport: innerWidth
        };
      });
      expect(tableGeometry.tableRight).toBeLessThanOrEqual(tableGeometry.viewport);
      expect(tableGeometry.inputRight).toBeLessThanOrEqual(tableGeometry.viewport);
      expect(tableGeometry.selectRight).toBeLessThanOrEqual(tableGeometry.viewport);
      expect(tableGeometry.classed).toBe(true);
      expect(tableGeometry.label).toBe('Host');

      const desktop = await openPage({ width: 1440, height: 1000 });
      await loginWith(desktop, credentials);
      mutationAudits.push(auditMutations(desktop));
      await goFleet(desktop);
      await expect(desktop.locator('#fleet-sec-ct')).toBeHidden();
      await expect(desktop.locator('.sparkline-row canvas').first()).toBeVisible({ timeout: 20_000 });
      await desktop.evaluate(() => {
        for (let index = 0; index < 8; index += 1) window._renderSparklines();
      });
      const heights = await desktop.locator('.sparkline-row canvas').evaluateAll(elements => elements.map(element => ({
        rect: element.getBoundingClientRect().height,
        style: element.style.height
      })));
      expect(heights.length).toBeGreaterThan(0);
      for (const height of heights) {
        expect(height.rect).toBeLessThanOrEqual(30);
        expect(height.style).toBe('28px');
      }
      const grouped = await desktop.evaluate(() => {
        const cache = window._fleetCache || {};
        if (!cache.fo || !cache.hd || !(cache.fo.pve_nodes || []).length) return { ok: false };
        const node = cache.fo.pve_nodes[0].name;
        window._renderFleetData(cache.fo, cache.hd, null, { containers: [{
          ctid: 7777, name: 'l03-lxc-proof', status: 'running', node,
          cpu: 0.05, maxcpu: 2, mem: 268435456, maxmem: 1073741824,
          mem_pct: 25, disk: 0, maxdisk: 8589934592, uptime: 60,
          tags: 'ui-test', template: 0
        }] });
        return { ok: true, text: document.querySelector('.ct-workload-card')?.innerText || '' };
      });
      expect(grouped.ok).toBe(true);
      expect(grouped.text).toContain('LXC 7777');
      expect(grouped.text).toContain('TERM');
      await clickNav(desktop, 'SYSTEM');
      await goFleet(desktop);
      const desktopOverflow = await desktop.evaluate(() => ({ width: innerWidth, scroll: document.documentElement.scrollWidth }));
      expect(desktopOverflow.scroll).toBeLessThanOrEqual(desktopOverflow.width);
      await expectNoOperatorWarnings(desktop);
      expect(errors).toEqual([]);
      expect(mutationAudits.flat()).toEqual([]);
    } finally {
      await Promise.all(contexts.map(context => context.close()));
    }
  });

  test('L04 real operator reads assignments while admin mutations remain inert', async ({ page }) => {
    test.setTimeout(3 * 60 * 1000);
    const credentials = liveInputs().operator;
    await loginWith(page, credentials);
    const mutations = auditMutations(page);

    const verify = await api(page, '/api/auth/verify');
    expect(verify.status).toBe(200);
    expect(verify.body).toMatchObject({ valid: true, user: credentials.user, role: 'operator' });
    await expect(page.locator('#header-user-name')).toHaveText(credentials.user);
    await expect(page.locator('#header-user-role')).toHaveText('OPERATOR');

    const overview = await api(page, '/api/fleet/overview');
    expect(overview.status).toBe(200);
    expect(overview.body).toBeTruthy();
    const denial = await api(page, '/api/admin/fleet-boundaries');
    expect(denial.status).toBe(403);
    expect(denial.body.error).toMatch(/Requires admin role.*operator/i);

    await clickNav(page, 'SETTINGS');
    await expect(page.locator('#settings-view')).toBeVisible();
    await expect(page.locator('#settings-view')).toContainText('OOC (out of contract)');
    const assignments = page.locator('#lab-assign-list');
    await expect(assignments.locator('.device-assignment-readonly')).toContainText('READ ONLY');
    await expect(assignments.locator('.device-assignment-table tbody tr').first()).toBeVisible();
    await expect(assignments.locator('[data-action="saveDeviceAssignmentRow"]')).toHaveCount(0);
    await expect(assignments.locator('select, input')).toHaveCount(0);
    await expect(page.locator('#fleet-admin-section')).toBeHidden();

    await page.evaluate(() => switchView('sec-hardening'));
    await expect(page.locator('#hardening-role-notice')).toContainText('ADMIN REQUIRED');
    await expect(page.locator('#sec-hardening-view [data-audit]:disabled')).toHaveCount(7);
    await expect(page.locator('#sec-hardening-view [data-action="runSshSweep"]:disabled')).toHaveCount(1);
    await expect(page.locator('#harden-target:disabled')).toHaveCount(1);
    await expect(page.locator('#sec-hardening-view [data-action="hardenAction"]:disabled')).toHaveCount(4);
    await expect(page.locator('#sec-hardening-view [data-action="sshdPanel"]:disabled')).toHaveCount(1);
    const before = await page.evaluate(() => ({
      audit: document.getElementById('audit-c').innerHTML,
      sweep: document.getElementById('sweep-c').innerHTML,
      harden: document.getElementById('harden-c').innerHTML
    }));
    await page.evaluate(() => {
      runAuditCheck('all');
      runSshSweep();
      hardenAction('disable-root');
      sshdPanel('harden-c');
      sshdRestartHost('operator-proof');
      sshdRestartSelected();
      sshdRestartAll();
      _sshdRestart(['operator-proof']);
    });
    expect(await page.evaluate(() => ({
      audit: document.getElementById('audit-c').innerHTML,
      sweep: document.getElementById('sweep-c').innerHTML,
      harden: document.getElementById('harden-c').innerHTML
    }))).toEqual(before);
    await expect(page.locator('#modal-container')).toBeHidden();
    expect(mutations).toEqual([]);
  });
});

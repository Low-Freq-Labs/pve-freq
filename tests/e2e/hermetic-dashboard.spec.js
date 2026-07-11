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

  test('generated Security and System subnav strips stay complete and self-active', async ({ page }) => {
    await page.goto('/');
    const result = await page.evaluate(() => {
      const expected = {
        security: ['security', 'sec-hardening', 'sec-access', 'sec-compliance', 'firewall', 'certs', 'vpn'],
        system: ['tools', 'playbooks', 'gitops', 'chaos', 'dns', 'dr', 'incidents', 'metrics', 'automation', 'plugins']
      };
      return Array.from(document.querySelectorAll('[data-subnav-group]')).map(mount => ({
        group: mount.dataset.subnavGroup,
        active: mount.dataset.subnavActive,
        expected: expected[mount.dataset.subnavGroup],
        views: Array.from(mount.querySelectorAll('.sub-tab')).map(button => button.dataset.view),
        activeViews: Array.from(mount.querySelectorAll('.sub-tab.active-sub')).map(button => button.dataset.view),
        chaosRed: mount.dataset.subnavGroup !== 'system' || mount.querySelector('[data-view="chaos"]').classList.contains('c-red')
      }));
    });
    expect(result).toHaveLength(17);
    for (const strip of result) {
      expect(strip.views).toEqual(strip.expected);
      expect(strip.activeViews).toEqual([strip.active]);
      expect(strip.chaosRed).toBe(true);
    }

    await loginInBrowser(page);
    for (const [topView, views] of [
      ['security', ['security', 'sec-hardening', 'sec-access', 'sec-compliance', 'firewall', 'certs', 'vpn']],
      ['tools', ['tools', 'playbooks', 'gitops', 'chaos', 'dns', 'dr', 'incidents', 'metrics', 'automation', 'plugins']]
    ]) {
      await page.locator(`#nav-items [data-view="${topView}"]`).click();
      let currentView = topView;
      for (const targetView of views) {
        await page.locator(`#${currentView}-view > .sub-tabs > .sub-tab[data-view="${targetView}"]`).click();
        await expect(page.locator(`#${targetView}-view`)).toBeVisible();
        await expect(page.locator(`#${targetView}-view .sub-tab.active-sub`)).toHaveAttribute('data-view', targetView);
        currentView = targetView;
      }
    }
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

  test('Network actions render into the active view instead of hidden Fleet panels', async ({ page }) => {
    let snmpPlanCalls = 0;
    await page.route('**/api/netmon/data', route => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        snapshots: [{
          time: '2026-07-11T17:30:00Z',
          host: 'active-network-proof',
          interfaces: [{ name: 'eth0', rx: '1', tx: '2', errors: '0' }]
        }]
      })
    }));
    await page.route('**/api/netmon/interfaces', route => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        total_interfaces: 1,
        hosts: [{
          host: 'active-interfaces-proof',
          interfaces: [{ name: 'eth0', state: 'up', ips: ['192.0.2.8'], mac: '00:00:5e:00:53:01', mtu: 1500 }]
        }]
      })
    }));
    await page.route('**/api/v1/net/snmp/setup/plan*', route => {
      snmpPlanCalls += 1;
      const label = snmpPlanCalls === 1 ? 'fleet-snmp-proof' : 'network-snmp-proof';
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          credential_ready: true,
          targets: [{
            label,
            ip: '192.0.2.9',
            setup_class: 'linux_snmpd',
            mutation: 'configure',
            current_state: { reachable: true, version: 'v3' },
            caveats: []
          }]
        })
      });
    });
    await page.route('**/api/v1/net/snmp/setup/status', route => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ state: 'never_run' })
    }));
    await loginInBrowser(page);
    await page.locator('#nav-items [data-view="fleet"]').click();
    await expect(page.locator('#fleet-snmp-setup-main')).toContainText('fleet-snmp-proof');
    await page.locator('#subtabs-fleet [data-view="network"]').click();

    await expect(page.locator('#network-view')).toBeVisible();
    await expect(page.locator('#fleet-view')).toBeHidden();
    await page.locator('#network-view [data-action="loadNetmonData"]').click();
    await expect(page.locator('#network-netmon-out')).toContainText('active-network-proof');
    await expect(page.locator('#network-netmon-out')).toBeVisible();
    await expect(page.locator('#fleet-netmon-out')).not.toContainText('active-network-proof');
    await page.locator('#network-view [data-action="loadNetmonInterfaces"]').click();
    await expect(page.locator('#network-netmon-out')).toContainText('active-interfaces-proof');
    await expect(page.locator('#fleet-netmon-out')).not.toContainText('active-interfaces-proof');
    await expect(page.locator('#network-snmp-setup-main')).toContainText('network-snmp-proof');
    await expect(page.locator('#network-snmp-setup-main')).toBeVisible();
    await expect(page.locator('#fleet-snmp-setup-main')).not.toContainText('network-snmp-proof');
  });

  test('expanding a data panel fetches fresh data and stamps only successful responses', async ({ page }) => {
    let netmonRequests = 0;
    await page.route('**/api/netmon/data', route => {
      netmonRequests += 1;
      if (netmonRequests > 1) {
        return route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ error: 'proof failure' }) });
      }
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          snapshots: [{
            time: '2026-07-11T17:40:00Z',
            host: 'expand-freshness-proof',
            interfaces: [{ name: 'eth0', rx: '1', tx: '2', errors: '0' }]
          }]
        })
      });
    });
    await loginInBrowser(page);
    await page.locator('#nav-items [data-view="fleet"]').click();
    await page.locator('#subtabs-fleet [data-view="network"]').click();

    const panel = page.locator('#network-netmon-out').locator('xpath=ancestor::*[contains(concat(" ", normalize-space(@class), " "), " section ")][1]');
    const header = panel.locator(':scope > .section-header');
    await header.click();
    await expect(panel).toHaveClass(/collapsed/);
    expect(netmonRequests).toBe(0);
    await header.click();
    await expect(panel).not.toHaveClass(/collapsed/);
    await expect(page.locator('#network-netmon-out')).toContainText('expand-freshness-proof');
    await expect(panel.locator(':scope > .section-body > .panel-updated')).toHaveText(/^AS OF \d{2}:\d{2}:\d{2}$/);
    const successfulStamp = await panel.locator(':scope > .section-body > .panel-updated').textContent();

    await panel.locator('[data-action="loadNetmonData"]').click();
    await expect.poll(() => netmonRequests).toBe(2);
    await expect(panel.locator(':scope > .section-body > .panel-updated')).toHaveText(successfulStamp);
  });

  test('chaos injection uses the styled non-blocking confirmation flow', async ({ page }) => {
    let runRequests = 0;
    await page.route('**/api/chaos/run?*', route => {
      runRequests += 1;
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ result: { status: 'completed', recovery_time: 3 } })
      });
    });
    await page.route('**/api/chaos/log', route => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ experiments: [] })
    }));
    await loginInBrowser(page);
    await page.locator('#nav-items [data-view="tools"]').click();
    await page.locator('#subtabs-tools [data-view="chaos"]').click();
    await page.locator('#chaos-name').fill('styled-confirm-proof');
    await page.locator('#chaos-type').selectOption('service_restart');
    await page.locator('#chaos-target').evaluate(select => {
      const option = document.createElement('option');
      option.value = 'pve-hermetic';
      option.textContent = 'pve-hermetic';
      select.appendChild(option);
    });
    await page.locator('#chaos-target').selectOption('pve-hermetic');
    await page.locator('#chaos-service').fill('proof-service');
    await page.locator('#chaos-view [data-action="chaosRun"]').click();

    await expect(page.locator('#modal-container')).toBeVisible();
    await expect(page.locator('#modal-container')).toContainText('styled-confirm-proof');
    expect(runRequests).toBe(0);
    await page.locator('#modal-confirm-btn').click();
    await expect.poll(() => runRequests).toBe(1);
    await expect(page.locator('#toast-container')).toContainText('Experiment completed');
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

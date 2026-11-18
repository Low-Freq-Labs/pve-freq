const fs = require('node:fs');
const path = require('node:path');
const { test, expect } = require('@playwright/test');

const USER = 'admin';
const PASS = 'hermetic-dashboard-password';
const F10_PROXY_INVOCATION_IDS = Object.freeze([
  "_ltProxy#1/direct",
  "ltAction#1/confirm-absent",
  "ltAction#1/confirm-YES",
  "gwipeBayWipe#1/confirmAction-accepted"
]);
const F10_PERSISTENCE_ENUMERATOR_IDS = Object.freeze([
  "caches",
  "cookie",
  "indexedDB",
  "localStorage",
  "sessionStorage"
]);


async function loginInBrowser(page, username = USER) {
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await page.locator('#login-user').fill(username);
  await page.locator('#login-pass').fill(PASS);
  await page.locator('#login-form').evaluate(form => form.requestSubmit());
  await page.locator('#login-overlay').waitFor({ state: 'hidden' });
}

test.describe('hermetic dashboard behavior oracle', () => {
  test('H01 auth and security lifecycle owns security headers, CSRF, and logout', async ({ browser }, testInfo) => {
    const context = await browser.newContext({ baseURL: testInfo.project.use.baseURL });
    const page = await context.newPage();
    const commonHeaders = {
      'x-content-type-options': 'nosniff',
      'x-frame-options': 'DENY',
      'referrer-policy': 'strict-origin-when-cross-origin',
      'permissions-policy': 'geolocation=(), microphone=(), camera=(), usb=(), payment=(), accelerometer=(), gyroscope=(), magnetometer=(), interest-cohort=()',
      'content-security-policy': "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; font-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'; object-src 'none'"
    };
    const sessionCookies = async () => (
      await context.cookies()
    ).filter(cookie => cookie.name === 'freq_session');
    const browserFetch = (url, options = {}) => page.evaluate(async ({ url, options }) => {
      const response = await fetch(url, options);
      const text = await response.text();
      let body = null;
      try { body = JSON.parse(text); } catch { body = text; }
      return {
        status: response.status,
        headers: Object.fromEntries(response.headers.entries()),
        body
      };
    }, { url, options });
    const expectRejectedLogin = async (response, status, error) => {
      expect(response.status).toBe(status);
      const body = response.body;
      expect(body.error).toBe(error);
      expect(body.request_id).toEqual(expect.any(String));
      expect(body.request_id).not.toBe('');
      expect(await sessionCookies()).toHaveLength(0);
      expect((await browserFetch('/api/auth/verify')).body).toEqual({ valid: false });
    };

    await page.context().clearCookies();
    let origin;
    const preAuthRequests = [];
    const recordPreAuthRequest = request => preAuthRequests.push(request.url());
    page.on('request', recordPreAuthRequest);

    await test.step('pre-auth cover permits only bootstrap auth truth', async () => {
      const rootResponse = await page.goto('/', { waitUntil: 'networkidle' });
      expect(rootResponse.status()).toBe(200);
      origin = new URL(rootResponse.url()).origin;
      page.off('request', recordPreAuthRequest);

      const apiPaths = preAuthRequests
        .map(url => new URL(url))
        .filter(url => url.origin === origin && url.pathname.startsWith('/api/'))
        .map(url => url.pathname);
      expect([...new Set(apiPaths)].sort()).toEqual(['/api/auth/verify', '/api/setup/status']);
      expect(apiPaths).toContain('/api/auth/verify');
      expect(apiPaths).toContain('/api/setup/status');
      expect(apiPaths.some(pathname => (
        pathname.startsWith('/api/fleet') ||
        pathname.startsWith('/api/health') ||
        pathname.startsWith('/api/events')
      ))).toBe(false);

      await expect(page.locator('#login-overlay')).toBeVisible();
      await expect(page.locator('#login-user')).toBeVisible();
      await expect(page.locator('#login-pass')).toBeVisible();
      await expect(page.locator('#mn-body')).toBeHidden();

      const anonymousFleet = await browserFetch('/api/fleet/overview');
      expect(anonymousFleet.status).toBe(403);
      const body = anonymousFleet.body;
      expect(body.error).toBe('Authentication required');
      expect(body.request_id).toEqual(expect.any(String));
      expect(body.request_id).not.toBe('');
    });

    await test.step('login rejects wrong methods and invalid credentials', async () => {
      await test.step('GET login is rejected', async () => {
        await expectRejectedLogin(
          await browserFetch('/api/auth/login'),
          405,
          'Use POST with JSON body for login'
        );
      });
      for (const row of [
        { name: 'empty username', username: '', password: PASS },
        { name: 'empty password', username: USER, password: '' }
      ]) {
        await test.step(`${row.name} is rejected`, async () => {
          await expectRejectedLogin(
            await browserFetch('/api/auth/login', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ username: row.username, password: row.password })
            }),
            400,
            'Username and password required'
          );
        });
      }
      await test.step('wrong password is rejected', async () => {
        await expectRejectedLogin(
          await browserFetch('/api/auth/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username: USER, password: 'wrong-password' })
          }),
          401,
          'Invalid credentials'
        );
      });
    });

    await test.step('HTML and JSON responses enforce the security policy', async () => {
      const rootResponse = await browserFetch('/');
      const rootHeaders = rootResponse.headers;
      expect(rootResponse.status).toBe(200);
      expect(rootHeaders).toMatchObject(commonHeaders);
      expect(rootHeaders['x-xss-protection']).toBe('1; mode=block');
      expect(rootHeaders['strict-transport-security']).toBe('max-age=31536000; includeSubDomains');
      expect(rootHeaders['access-control-allow-origin']).toBeUndefined();

      const deniedResponse = await browserFetch('/api/fleet/overview');
      const deniedHeaders = deniedResponse.headers;
      expect(deniedResponse.status).toBe(403);
      expect(deniedHeaders).toMatchObject(commonHeaders);
      expect(deniedHeaders['cache-control']).toBe('no-store, no-cache, must-revalidate');
      expect(deniedHeaders.pragma).toBe('no-cache');
      expect(deniedHeaders['strict-transport-security']).toBe('max-age=31536000; includeSubDomains');
      expect(deniedHeaders['access-control-allow-origin']).toBeUndefined();
    });

    let loginBody;
    await test.step('real browser form establishes the cookie session', async () => {
      await page.locator('#login-user').fill(USER);
      await page.locator('#login-pass').fill(PASS);
      const loginResponsePromise = page.waitForResponse(response => (
        new URL(response.url()).pathname === '/api/auth/login' &&
        response.request().method() === 'POST'
      ));
      await page.locator('#login-form').evaluate(form => form.requestSubmit());
      const loginResponse = await loginResponsePromise;
      expect(loginResponse.status()).toBe(200);
      loginBody = await loginResponse.json();
      expect(loginBody).toMatchObject({
        ok: true,
        auth_mode: 'cookie',
        user: USER,
        role: 'admin'
      });
      expect(loginBody.token).toEqual(expect.any(String));
      expect(loginBody.token).not.toBe('');
      expect(loginBody.csrf_token).toEqual(expect.any(String));
      expect(loginBody.csrf_token).not.toBe('');

      const cookies = await context.cookies(origin);
      expect(cookies).toHaveLength(1);
      expect(cookies[0]).toMatchObject({
        name: 'freq_session',
        value: loginBody.token,
        path: '/',
        httpOnly: true,
        sameSite: 'Strict',
        secure: true
      });
      await expect(page.locator('#login-overlay')).toBeHidden();
      await expect(page.locator('#mn-body')).toBeVisible();

      const verifyResponse = await browserFetch('/api/auth/verify');
      expect(verifyResponse.status).toBe(200);
      expect(verifyResponse.body).toMatchObject({
        valid: true,
        user: USER,
        role: 'admin',
        auth_mode: 'cookie',
        csrf_token: loginBody.csrf_token
      });
    });

    await test.step('cookie-authenticated unsafe requests require the exact CSRF token', async () => {
      for (const row of [
        { name: 'missing CSRF header', headers: {} },
        { name: 'wrong CSRF header', headers: { 'X-Freq-CSRF': 'wrong-csrf-token' } }
      ]) {
        await test.step(`${row.name} is rejected`, async () => {
          const response = await browserFetch('/api/hermetic-h01-csrf-probe', {
            method: 'POST',
            headers: row.headers
          });
          expect(response.status).toBe(403);
          const body = response.body;
          expect(body.error).toBe('CSRF token required');
          expect(body.request_id).toEqual(expect.any(String));
          expect(body.request_id).not.toBe('');
        });
      }

      const response = await browserFetch('/api/hermetic-h01-csrf-probe', {
        method: 'POST',
        headers: { 'X-Freq-CSRF': loginBody.csrf_token }
      });
      expect(response.status).toBe(404);
      expect(response.headers['content-type']).toContain('application/json');
      const body = response.body;
      expect(body).toMatchObject({
        error: 'not found',
        path: '/api/hermetic-h01-csrf-probe'
      });
      expect(body.request_id).toEqual(expect.any(String));
      expect(body.request_id).not.toBe('');
    });

    await test.step('real user-menu logout invalidates the session once', async () => {
      const logoutRequests = [];
      page.on('request', request => {
        if (new URL(request.url()).pathname === '/api/auth/logout') logoutRequests.push(request);
      });

      await page.locator('#header-user-btn').click();
      const logoutResponsePromise = page.waitForResponse(response => (
        new URL(response.url()).pathname === '/api/auth/logout' &&
        response.request().method() === 'POST'
      ));
      await page.getByRole('button', { name: 'LOG OUT', exact: true }).click();
      const logoutResponse = await logoutResponsePromise;
      expect(logoutResponse.status()).toBe(200);
      expect(logoutResponse.request().headers()['x-freq-csrf']).toBe(loginBody.csrf_token);

      await expect(page.locator('#login-overlay')).toBeVisible();
      await expect(page.locator('#login-user')).toBeVisible();
      await expect(page.locator('#login-user')).toHaveValue('');
      await expect(page.locator('#login-user')).toBeFocused();
      await expect(page.locator('#login-pass')).toBeVisible();
      await expect(page.locator('#login-pass')).toHaveValue('');
      await expect(page.locator('#mn-body')).toBeHidden();
      await expect(page.locator('#header-user-btn')).toBeHidden();
      expect(await sessionCookies()).toHaveLength(0);
      expect((await browserFetch('/api/auth/verify')).body).toEqual({ valid: false });
      const anonymousFleet = await browserFetch('/api/fleet/overview');
      expect(anonymousFleet.status).toBe(403);
      expect(logoutRequests).toHaveLength(1);
    });
    await context.close();
  });

  test('H02 one view router owns canonical shell, subnav, and history', async ({ browser }, testInfo) => {
    test.setTimeout(60_000);
    const context = await browser.newContext({ baseURL: testInfo.project.use.baseURL });
    const page = await context.newPage();
    const viewIds = [
      'home', 'fleet', 'network', 'docker', 'security', 'sec-hardening',
      'sec-access', 'sec-compliance', 'firewall', 'certs', 'vpn', 'vault',
      'tools', 'playbooks', 'chaos', 'dns', 'dr', 'incidents',
      'metrics', 'automation', 'plugins', 'lab', 'settings', 'infra', 'system'
    ];
    const subnavGroups = {
      fleet: ['fleet', 'network'],
      security: ['security', 'sec-hardening', 'sec-access', 'sec-compliance', 'firewall', 'certs', 'vpn'],
      system: ['tools', 'playbooks', 'chaos', 'dns', 'dr', 'incidents', 'metrics', 'automation', 'plugins']
    };

    const assertShell = async (view, nav, pathname = `/dashboard/${view}`) => {
      await expect(page.locator('#login-overlay')).toBeHidden();
      await expect(page.locator('#mn-body')).toBeVisible();
      await expect(page.locator(`#${view}-view`)).toBeVisible();
      await expect(page).toHaveURL(new RegExp(`${pathname.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}$`));
      const state = await page.evaluate(() => {
        const root = document.querySelector('#dashboard-root');
        const mounts = Array.from(document.querySelectorAll('#dashboard-root [id$="-view"]'));
        return {
          rootCount: document.querySelectorAll('#dashboard-root').length,
          mountIds: mounts.map(mount => mount.id).sort(),
          uniqueMountIds: new Set(mounts.map(mount => mount.id)).size,
          outsideMountIds: Array.from(document.querySelectorAll('[id$="-view"]'))
            .filter(mount => !root.contains(mount))
            .map(mount => mount.id),
          visibleMountIds: mounts
            .filter(mount => getComputedStyle(mount).display !== 'none')
            .map(mount => mount.id),
          activeNav: Array.from(document.querySelectorAll('#nav-items .view-btn.active-view'))
            .map(button => button.dataset.view),
          pathname: location.pathname,
          historyView: history.state && history.state.view
        };
      });
      expect(state).toEqual({
        rootCount: 1,
        mountIds: viewIds.map(id => `${id}-view`).sort(),
        uniqueMountIds: viewIds.length,
        outsideMountIds: [],
        visibleMountIds: [`${view}-view`],
        activeNav: [nav],
        pathname,
        historyView: view
      });
    };

    let initialHistoryLength;
    await test.step('served app and router are the checked-in browser resources', async () => {
      const rootResponse = await page.goto('/dashboard/sec-compliance', { waitUntil: 'domcontentloaded' });
      expect(rootResponse.status()).toBe(200);
      initialHistoryLength = await page.evaluate(() => history.length);
      await expect(page.locator('#login-overlay')).toBeVisible();
      await expect(page.locator('#mn-body')).toBeHidden();

      for (const asset of [
        { url: '/static/js/app.js', file: '../../freq/data/web/js/app.js' },
        { url: '/static/js/router.js', file: '../../freq/data/web/js/router.js' }
      ]) {
        const response = await page.request.get(asset.url);
        expect(response.status()).toBe(200);
        expect(response.headers()['content-type']).toContain('javascript');
        expect(await response.text()).toBe(fs.readFileSync(path.join(__dirname, asset.file), 'utf8'));
      }
      const resources = await page.evaluate(() => (
        performance.getEntriesByType('resource').map(entry => new URL(entry.name).pathname)
      ));
      expect(resources.filter(resource => resource === '/static/js/app.js')).toHaveLength(1);
      expect(resources.filter(resource => resource === '/static/js/router.js')).toHaveLength(1);
      expect(await page.evaluate(() => typeof window.FreqViewRouter?.create)).toBe('function');
    });

    await test.step('direct canonical route survives real login and reveals one shell', async () => {
      await page.locator('#login-user').fill(USER);
      await page.locator('#login-pass').fill(PASS);
      const loginResponsePromise = page.waitForResponse(response => (
        new URL(response.url()).pathname === '/api/auth/login' &&
        response.request().method() === 'POST'
      ));
      await page.locator('#login-form').evaluate(form => form.requestSubmit());
      expect((await loginResponsePromise).status()).toBe(200);
      await assertShell('sec-compliance', 'security');
      expect(await page.evaluate(() => history.length)).toBe(initialHistoryLength);
    });

    await test.step('route topology has no duplicate or stale page islands', async () => {
      await assertShell('sec-compliance', 'security');
      const activeSubnav = page.locator('#sec-compliance-view > .sub-tabs > .sub-tab.active-sub');
      await expect(activeSubnav).toHaveCount(1);
      await expect(activeSubnav).toHaveAttribute('data-view', 'sec-compliance');
    });

    await test.step('generated subnavs stay complete, self-active, and canonical', async () => {
      const strips = await page.evaluate(expected => (
        Array.from(document.querySelectorAll('[data-subnav-group]')).map(mount => ({
          parentView: mount.parentElement.id,
          group: mount.dataset.subnavGroup,
          active: mount.dataset.subnavActive,
          expected: expected[mount.dataset.subnavGroup],
          views: Array.from(mount.querySelectorAll(':scope > .sub-tab')).map(button => button.dataset.view),
          activeViews: Array.from(mount.querySelectorAll(':scope > .sub-tab.active-sub')).map(button => button.dataset.view),
          chaosRed: mount.dataset.subnavGroup !== 'system' || mount.querySelector(':scope > [data-view="chaos"]').classList.contains('c-red')
        }))
      ), subnavGroups);
      // Compare every mount identity against the explicit route contract. A
      // total alone can hide a missing strip replaced by a duplicate elsewhere.
      const expectedMounts = Object.entries(subnavGroups).flatMap(([group, views]) => (
        views.map(view => `${group}:${view}:${view}-view`)
      )).sort();
      expect(strips.map(strip => `${strip.group}:${strip.active}:${strip.parentView}`).sort()).toEqual(expectedMounts);
      for (const strip of strips) {
        expect(strip.views).toEqual(strip.expected);
        expect(strip.activeViews).toEqual([strip.active]);
        expect(strip.chaosRed).toBe(true);
      }

      for (const [group, views] of Object.entries(subnavGroups)) {
        const nav = group === 'system' ? 'tools' : group;
        await page.locator(`#nav-items [data-view="${nav}"]`).click();
        let currentView = views[0];
        await assertShell(currentView, nav);
        for (const targetView of views) {
          await page.locator(`#${currentView}-view > .sub-tabs > .sub-tab[data-view="${targetView}"]`).click();
          await assertShell(targetView, nav);
          const active = page.locator(`#${targetView}-view > .sub-tabs > .sub-tab.active-sub`);
          await expect(active).toHaveCount(1);
          await expect(active).toHaveAttribute('data-view', targetView);
          currentView = targetView;
        }
      }
    });

    await test.step('legacy and invalid paths replace into canonical routes', async () => {
      await page.goto('/dashboard/media', { waitUntil: 'domcontentloaded' });
      const aliasHistoryLength = await page.evaluate(() => history.length);
      await assertShell('docker', 'docker');
      expect(await page.evaluate(() => history.length)).toBe(aliasHistoryLength);

      await page.goto('/dashboard/not-a-view', { waitUntil: 'domcontentloaded' });
      const invalidHistoryLength = await page.evaluate(() => history.length);
      await assertShell('home', 'home');
      expect(await page.evaluate(() => history.length)).toBe(invalidHistoryLength);
    });

    await test.step('click, back, and forward keep one canonical active route', async () => {
      const beforeClicks = await page.evaluate(() => history.length);
      await page.locator('#nav-items [data-view="fleet"]').click();
      await assertShell('fleet', 'fleet');
      expect(await page.evaluate(() => history.length)).toBe(beforeClicks + 1);
      await page.locator('#nav-items [data-view="docker"]').click();
      await assertShell('docker', 'docker');
      expect(await page.evaluate(() => history.length)).toBe(beforeClicks + 2);

      await page.goBack();
      await assertShell('fleet', 'fleet');
      expect(await page.evaluate(() => history.length)).toBe(beforeClicks + 2);
      await page.goForward();
      await assertShell('docker', 'docker');
      expect(await page.evaluate(() => history.length)).toBe(beforeClicks + 2);
    });

    await context.close();
  });

  test('H03 read and freshness behavior owns Network actions, panel stamps, activity dedupe, and Chaos request truth', async ({ page }) => {
    test.setTimeout(90_000);
    const activityCalls = { downloads: 0, streams: 0 };
    let netmonCalls = 0;
    let netmonMode = 'success';
    let netmonLabel = 'active-network-proof';
    let snmpPlanCalls = 0;
    let fleetReadMode = null;
    let fleetReadCalls = 0;
    let pveMetricsCalls = 0;
    let chaosRequest = null;
    const fulfillJson = (route, body, status = 200) => route.fulfill({
      status,
      contentType: 'application/json',
      body: JSON.stringify(body)
    });

    await page.route('**/api/media/downloads', route => {
      activityCalls.downloads += 1;
      return fulfillJson(route, { count: 2, age_seconds: 3 });
    });
    await page.route('**/api/media/streams', route => {
      activityCalls.streams += 1;
      return fulfillJson(route, { count: 1, age_seconds: 3 });
    });
    await page.route('**/api/netmon/data', route => {
      netmonCalls += 1;
      if (netmonMode === 'http-error') {
        return fulfillJson(route, { error: 'transport rejected' }, 503);
      }
      if (netmonMode === 'invalid-json') {
        return route.fulfill({ status: 200, contentType: 'application/json', body: '{not-json' });
      }
      if (netmonMode === 'payload-error') {
        return fulfillJson(route, { error: 'payload rejected' });
      }
      return fulfillJson(route, {
        snapshots: [{
          time: '2026-07-14T23:00:00Z',
          host: netmonLabel,
          interfaces: [{ name: 'eth0', rx: '1', tx: '2', errors: '0' }]
        }]
      });
    });
    await page.route('**/api/netmon/interfaces', route => fulfillJson(route, {
      total_interfaces: 1,
      hosts: [{
        host: 'active-interfaces-proof',
        interfaces: [{
          name: 'eth0', state: 'up', ips: ['192.0.2.8'],
          mac: '00:00:5e:00:53:01', mtu: 1500
        }]
      }]
    }));
    await page.route('**/api/v1/net/snmp/setup/plan*', route => {
      snmpPlanCalls += 1;
      return fulfillJson(route, {
        credential_ready: true,
        targets: [{
          label: snmpPlanCalls === 1 ? 'fleet-snmp-proof' : 'network-snmp-proof',
          ip: '192.0.2.9',
          setup_class: 'linux_snmpd',
          mutation: 'configure',
          current_state: { reachable: true, version: 'v3' },
          caveats: []
        }]
      });
    });
    await page.route('**/api/v1/net/snmp/setup/status', route => fulfillJson(route, { state: 'never_run' }));
    await page.route('**/api/chaos/log', route => fulfillJson(route, { experiments: [] }));
    await page.route('**/api/chaos/run?*', route => {
      chaosRequest = { method: route.request().method(), url: route.request().url() };
      return fulfillJson(route, { result: { status: 'completed', recovery_time: 3 } });
    });
    await page.route('**/api/pve/metrics', route => {
      pveMetricsCalls += 1;
      return fulfillJson(route, {
        nodes: [{
          name: 'pve-hermetic', online: true, cpu_pct: 73, ram_pct: 64,
          cores: 8, ram_used_gb: 5, ram_total_gb: 8, iowait: 4,
          storage_pct: 31, storage_used_gb: 31, storage_total_gb: 100
        }]
      });
    });

    const validFleetPayloads = {
      '/api/fleet/overview': {
        vms: [{
          vmid: 321, name: 'h03-cache-vm', node: 'pve-hermetic', category: 'prod',
          status: 'running', cpu: 2, ram_mb: 2048
        }],
        physical: [], pve_nodes: [{ name: 'pve-hermetic', online: true, state: 'live' }],
        summary: { resource_count: 2, running: 1, stopped: 0 }, probe_status: 'ok'
      },
      '/api/health': {
        hosts: [{
          label: 'pve-hermetic', type: 'pve', status: 'online', state: 'live',
          cores: '8', load: '2', disk: '31%', ram: '5120/8192MB'
        }],
        probe_status: 'ok'
      },
      '/api/media/status': {
        containers: [
          { vm_id: 321, name: 'h03-up', status: 'up' },
          { vmid: 321, name: 'h03-down', status: 'down' }
        ]
      },
      '/api/ct/list': {
        containers: [{ vmid: 401, name: 'h03-stopped-ct', node: 'pve-hermetic', status: 'stopped' }]
      }
    };
    for (const endpoint of Object.keys(validFleetPayloads)) {
      await page.route(`**${endpoint}`, route => {
        if (fleetReadMode === null) return route.continue();
        fleetReadCalls += 1;
        return fulfillJson(
          route,
          fleetReadMode === 'success' ? validFleetPayloads[endpoint] : { error: 'rejected H03 payload' }
        );
      });
    }

    await test.step('initial Home and first Fleet share one activity read per endpoint', async () => {
      await page.addInitScript(() => {
        Object.defineProperty(window, 'EventSource', {
          value: undefined,
          configurable: true
        });
      });
      await page.goto('/', { waitUntil: 'domcontentloaded' });
      await page.evaluate(() => {
        localStorage.setItem('freq_admin_home_widgets', JSON.stringify(['w-fleet-stats']));
      });
      await page.locator('#login-user').fill(USER);
      await page.locator('#login-pass').fill(PASS);
      await page.locator('#login-form').evaluate(form => form.requestSubmit());
      await page.locator('#login-overlay').waitFor({ state: 'hidden' });
      await expect(page.locator('#hw-fleet-stats .st:nth-child(7)')).toContainText('2');
      await expect(page.locator('#hw-fleet-stats .st:nth-child(7)')).toContainText('1');
      await page.evaluate(() => {
        clearInterval(window._healthTimer);
        clearInterval(window._fleetTimer);
        clearInterval(window._activityTimer);
        clearInterval(window._pveMetricsTimer);
        window._pveMetricsTimer = null;
      });
      expect(activityCalls).toEqual({ downloads: 1, streams: 1 });

      await page.locator('#nav-items [data-view="fleet"]').click();
      await expect(page.locator('#metrics-summary .st:nth-child(5)')).toContainText('2');
      await expect(page.locator('#metrics-summary .st:nth-child(5)')).toContainText('1');
      expect(activityCalls).toEqual({ downloads: 1, streams: 1 });
    });

    await page.evaluate(() => {
      const nativeFetch = window.fetch.bind(window);
      window.__h03NetmonFetches = 0;
      window.fetch = function(input, options) {
        const raw = typeof input === 'string' ? input : input.url;
        if (new URL(raw, location.href).pathname === '/api/netmon/data') {
          window.__h03NetmonFetches += 1;
        }
        return nativeFetch(input, options);
      };
    });
    const netmonFetchCount = () => page.evaluate(() => window.__h03NetmonFetches);

    await test.step('real Network reads render only into the visible Network surface', async () => {
      await expect(page.locator('#fleet-snmp-setup-main')).toContainText('fleet-snmp-proof');
      await page.locator('#subtabs-fleet [data-view="network"]').click();
      await expect(page.locator('#network-view')).toBeVisible();
      await expect(page.locator('#fleet-view')).toBeHidden();
      await expect(page.locator('#network-snmp-setup-main')).toContainText('network-snmp-proof');
      await expect(page.locator('#network-snmp-setup-main')).toBeVisible();
      await expect(page.locator('#fleet-snmp-setup-main')).not.toContainText('network-snmp-proof');

      await page.locator('#network-view [data-action="loadNetmonData"]').click();
      await expect(page.locator('#network-netmon-out')).toContainText('active-network-proof');
      await expect(page.locator('#network-netmon-out')).toBeVisible();
      await expect(page.locator('#fleet-netmon-out')).not.toContainText('active-network-proof');
      await page.locator('#network-view [data-action="loadNetmonInterfaces"]').click();
      await expect(page.locator('#network-netmon-out')).toContainText('active-interfaces-proof');
      await expect(page.locator('#fleet-netmon-out')).not.toContainText('active-interfaces-proof');
    });

    await page.evaluate(() => {
      window.__h03Now = Date.parse('2026-07-14T23:10:00.000Z');
      const NativeDate = window.Date;
      window.Date = class extends NativeDate {
        constructor(...args) { super(...(args.length ? args : [window.__h03Now])); }
        static now() { return window.__h03Now; }
      };
    });

    await test.step('panel expansion admits one visible read and rejects off, hidden, and run-only triggers', async () => {
      const beforeCollapse = await netmonFetchCount();
      await page.evaluate(() => {
        document.querySelector('#network-netmon-out').closest('.section').querySelector(':scope > .section-header').click();
      });
      expect(await netmonFetchCount()).toBe(beforeCollapse);
      await expect(page.locator('#network-netmon-out').locator('xpath=ancestor::*[contains(concat(" ", normalize-space(@class), " "), " section ")][1]')).toHaveClass(/collapsed/);

      netmonLabel = 'expand-freshness-proof';
      await page.evaluate(() => {
        document.querySelector('#network-netmon-out').closest('.section').querySelector(':scope > .section-header').click();
      });
      await expect(page.locator('#network-netmon-out')).toContainText('expand-freshness-proof');
      expect(await netmonFetchCount()).toBe(beforeCollapse + 1);

      const noFetchScenario = async scenario => page.evaluate(mode => {
        const panel = document.querySelector('#network-netmon-out').closest('.section');
        const header = panel.querySelector(':scope > .section-header');
        const reads = Array.from(panel.querySelectorAll('[data-action="loadNetmonData"], [data-action="loadNetmonInterfaces"]'));
        if (!panel.classList.contains('collapsed')) header.click();
        if (mode === 'section-off') panel.dataset.expandFetch = 'off';
        if (mode === 'trigger-off') {
          reads[0].dataset.expandFetch = 'off';
          reads[1].hidden = true;
        }
        if (mode === 'hidden') reads.forEach(button => { button.hidden = true; });
        let runOnly = null;
        if (mode === 'run-only') {
          reads.forEach(button => { button.hidden = true; });
          runOnly = document.createElement('button');
          runOnly.dataset.action = 'runH03Probe';
          runOnly.textContent = 'RUN ONLY';
          panel.querySelector(':scope > .section-body').prepend(runOnly);
        }
        const before = window.__h03NetmonFetches;
        header.click();
        const after = window.__h03NetmonFetches;
        delete panel.dataset.expandFetch;
        reads.forEach(button => {
          delete button.dataset.expandFetch;
          button.hidden = false;
        });
        if (runOnly) runOnly.remove();
        return { before, after };
      }, scenario);

      for (const scenario of ['section-off', 'trigger-off', 'hidden', 'run-only']) {
        expect(await noFetchScenario(scenario)).toEqual({
          before: beforeCollapse + 1,
          after: beforeCollapse + 1
        });
      }
    });

    await test.step('only successful parseable panel responses advance the dim accessible stamp', async () => {
      const panel = page.locator('#network-netmon-out').locator('xpath=ancestor::*[contains(concat(" ", normalize-space(@class), " "), " section ")][1]');
      const stamp = panel.locator(':scope > .section-body > .panel-updated');
      await expect(stamp).toHaveAttribute('title', 'Last successful fetch: 2026-07-14T23:10:00.000Z');
      await expect(stamp).toHaveAttribute('role', 'status');
      await expect(stamp).toHaveText(/^AS OF \d{2}:\d{2}:\d{2}$/);
      const visibleLabel = (await stamp.textContent()).replace('AS OF ', '');
      await expect(stamp).toHaveAttribute('aria-label', `Data fetched at ${visibleLabel}`);
      const colors = await stamp.evaluate(element => {
        const probe = document.createElement('span');
        probe.style.color = 'var(--text-dim)';
        document.body.appendChild(probe);
        const result = {
          actual: getComputedStyle(element).color,
          expected: getComputedStyle(probe).color
        };
        probe.remove();
        return result;
      });
      expect(colors.actual).toBe(colors.expected);
      expect(colors.actual).not.toBe('');

      const successfulTitle = await stamp.getAttribute('title');
      const pollButton = page.locator('#network-view [data-action="loadNetmonData"]');
      for (const [mode, now] of [
        ['http-error', '2026-07-14T23:11:00.000Z'],
        ['invalid-json', '2026-07-14T23:12:00.000Z'],
        ['payload-error', '2026-07-14T23:13:00.000Z']
      ]) {
        netmonMode = mode;
        await page.evaluate(value => { window.__h03Now = Date.parse(value); }, now);
        const expectedCall = netmonCalls + 1;
        await pollButton.click();
        await expect.poll(() => netmonCalls).toBe(expectedCall);
        await expect(stamp).toHaveAttribute('title', successfulTitle);
      }
      netmonMode = 'success';
    });

    await test.step('cache-only Fleet renders preserve stamps while verified reads move both together', async () => {
      // Fleet entry also starts a background read. Wait for that verified
      // render before isolating a cache-only render; otherwise its completion
      // can legitimately move the stamp during the cache assertion.
      fleetReadMode = 'success';
      await page.evaluate(() => { window.__h03Now = Date.parse('2026-07-14T23:19:00.000Z'); });
      await page.locator('#nav-items [data-view="fleet"]').click();
      const statsStamp = page.locator('#fleet-sec-stats > .section-body > .panel-updated');
      const cardsStamp = page.locator('#fleet-sec-infra > .section-body > .panel-updated');
      await expect.poll(() => fleetReadCalls).toBe(4);
      await expect(statsStamp).toHaveAttribute('title', 'Last successful fetch: 2026-07-14T23:19:00.000Z');
      const before = await statsStamp.getAttribute('title');
      expect(await cardsStamp.getAttribute('title')).toBe(before);

      await page.evaluate(() => {
        window.__h03Now = Date.parse('2026-07-14T23:20:00.000Z');
        window._renderFleetData(
          window._fleetCache.fo,
          window._fleetCache.hd,
          window._fleetCache.md,
          window._fleetCache.ct,
          false
        );
      });
      await expect(statsStamp).toHaveAttribute('title', before);
      await expect(cardsStamp).toHaveAttribute('title', before);

      fleetReadMode = 'success';
      await page.evaluate(() => {
        window.__h03Now = Date.parse('2026-07-14T23:21:00.000Z');
        window.loadMetricsQuick();
      });
      await expect.poll(() => fleetReadCalls).toBe(8);
      await expect(statsStamp).toHaveAttribute('title', 'Last successful fetch: 2026-07-14T23:21:00.000Z');
      await expect(cardsStamp).toHaveAttribute('title', 'Last successful fetch: 2026-07-14T23:21:00.000Z');

      const nodeCard = page.locator('.pve-node-card[data-host-id="pve-hermetic"]');
      const lxcRow = nodeCard.locator('.pve-node-stat').filter({ hasText: 'LXC' });
      const dockerRow = nodeCard.locator('.pve-node-stat').filter({ hasText: 'DOCKER' });
      await expect(nodeCard).toBeVisible();
      await expect(lxcRow).toContainText(/LXC\s*1\s*TOTAL\s*0\s*RUN\s*1\s*STOP/);
      await expect(dockerRow).toContainText(/DOCKER\s*2\s*TOTAL\s*1\s*UP\s*1\s*DOWN/);

      const expectedRed = await page.evaluate(() => {
        const probe = document.createElement('span');
        probe.style.color = 'var(--red)';
        document.body.appendChild(probe);
        const color = getComputedStyle(probe).color;
        probe.remove();
        return color;
      });
      const lxcStop = lxcRow.locator('strong').nth(2);
      const dockerDown = dockerRow.locator('strong').nth(2);
      await expect.poll(() => lxcStop.evaluate(element => getComputedStyle(element).color)).toBe(expectedRed);
      await expect.poll(() => dockerDown.evaluate(element => getComputedStyle(element).color)).toBe(expectedRed);

      await page.evaluate(() => {
        clearInterval(window._pveMetricsTimer);
        window._pveMetricsTimer = null;
      });
      const metricsBefore = pveMetricsCalls;
      await page.evaluate(() => window._pveMetricsRefresh());
      await expect.poll(() => pveMetricsCalls).toBe(metricsBefore + 1);
      await expect(nodeCard.locator('.pve-util-cpu')).toHaveText('73%');
      await expect(nodeCard.locator('.pve-util-ram')).toHaveText('64%');

      fleetReadMode = 'payload-error';
      await page.evaluate(() => {
        window.__h03Now = Date.parse('2026-07-14T23:22:00.000Z');
        window.loadMetricsQuick();
      });
      await expect.poll(() => fleetReadCalls).toBe(12);
      await expect(statsStamp).toHaveAttribute('title', 'Last successful fetch: 2026-07-14T23:21:00.000Z');
      await expect(cardsStamp).toHaveAttribute('title', 'Last successful fetch: 2026-07-14T23:21:00.000Z');
      await expect(dockerRow).toContainText(/DOCKER\s*2\s*TOTAL\s*1\s*UP\s*1\s*DOWN/);
      await expect.poll(() => dockerDown.evaluate(element => getComputedStyle(element).color)).toBe(expectedRed);
      fleetReadMode = null;
    });

    await test.step('confirmed Chaos request is POST with one encoded duration value', async () => {
      await page.locator('#nav-items [data-view="tools"]').click();
      await page.locator('#subtabs-tools [data-view="chaos"]').click();
      await page.locator('#chaos-name').fill('h03-request-truth');
      await page.locator('#chaos-type').selectOption('service_restart');
      await page.locator('#chaos-target').evaluate(select => {
        const option = document.createElement('option');
        option.value = 'pve-hermetic';
        option.textContent = 'pve-hermetic';
        select.appendChild(option);
      });
      await page.locator('#chaos-target').selectOption('pve-hermetic');
      await page.locator('#chaos-service').fill('proof-service');
      await page.locator('#chaos-duration').evaluate(input => {
        input.type = 'text';
        input.value = '17&injected=1';
      });
      await page.locator('#chaos-view [data-action="chaosRun"]').click();
      await page.locator('#modal-confirm-btn').click();
      await expect.poll(() => chaosRequest).not.toBeNull();

      const url = new URL(chaosRequest.url);
      expect(chaosRequest.method).toBe('POST');
      expect(url.searchParams.getAll('duration')).toEqual(['17&injected=1']);
      expect(url.searchParams.has('injected')).toBe(false);
    });
  });

  test('H04 mutation safety owns session truth, password rotation, destructive confirmation, Chaos sanitization, and method rejection', async ({ browser }, testInfo) => {
    test.setTimeout(90_000);
    const context = await browser.newContext({ baseURL: testInfo.project.use.baseURL });
    const page = await context.newPage();
    const fulfillJson = (route, body, status = 200) => route.fulfill({
      status,
      contentType: 'application/json',
      body: JSON.stringify(body)
    });

    await loginInBrowser(page);
    await page.evaluate(() => {
      clearInterval(window._healthTimer);
      clearInterval(window._fleetTimer);
      clearInterval(window._activityTimer);
    });

    let verifyTruth;
    await test.step('real session truth formats safely in a hostile user menu and exposes password rotation', async () => {
      verifyTruth = await page.evaluate(async () => {
        const response = await fetch('/api/auth/verify');
        return { status: response.status, body: await response.json() };
      });
      expect(verifyTruth.status).toBe(200);
      expect(verifyTruth.body).toMatchObject({
        valid: true,
        user: USER,
        role: 'admin',
        session_age_s: expect.any(Number),
        session_idle_s: expect.any(Number),
        session_ttl_s: expect.any(Number),
        session_timeout_s: expect.any(Number),
        csrf_token: expect.any(String)
      });
      expect(verifyTruth.body.session_age_s).toBeGreaterThanOrEqual(0);
      expect(verifyTruth.body.session_idle_s).toBeGreaterThanOrEqual(0);
      expect(verifyTruth.body.session_ttl_s).toBeGreaterThanOrEqual(0);
      expect(verifyTruth.body.session_ttl_s).toBeLessThanOrEqual(verifyTruth.body.session_timeout_s);
      expect(verifyTruth.body.csrf_token).not.toBe('');

      expect(await page.evaluate(() => [-1, 59, 60, 3600, 3660].map(_formatDuration))).toEqual([
        '0s', '59s', '1m', '1h', '1h 1m'
      ]);
      await page.evaluate(() => {
        window.__h04UserMenuPwned = 0;
        window._currentUser = '<img src=x onerror="window.__h04UserMenuPwned=1">';
        openUserMenu();
      });
      await expect(page.locator('#modal-container')).toBeVisible();
      await expect(page.locator('#modal-container img')).toHaveCount(0);
      expect(await page.evaluate(() => window.__h04UserMenuPwned)).toBe(0);
      await expect(page.locator('#modal-container')).toContainText('<IMG SRC=X ONERROR="WINDOW.__H04USERMENUPWNED=1">');
      const sessionBadge = page.locator('#user-menu-session-badge');
      await expect(sessionBadge).not.toContainText('probing');
      await expect(sessionBadge).toContainText('SESSION AGE');
      await expect(sessionBadge).toContainText('IDLE');
      await expect(sessionBadge).toContainText('EXPIRES IN');
      await expect(page.getByRole('button', { name: 'CHANGE PASSWORD' })).toBeVisible();
    });

    const passwordRequests = [];
    await page.route('**/api/auth/change-password', route => {
      const request = route.request();
      const body = JSON.parse(request.postData() || '{}');
      passwordRequests.push({
        method: request.method(),
        headers: request.headers(),
        body
      });
      if (body.current_password === 'wrong-current') {
        return fulfillJson(route, { error: 'Current password is incorrect' }, 401);
      }
      const purged = body.current_password === 'zero-current' ? 0 : 1;
      return fulfillJson(route, { ok: true, sessions_purged: purged });
    });

    await test.step('password validation, inline errors, CSRF POST, and purge counts preserve the caller session', async () => {
      await page.getByRole('button', { name: 'CHANGE PASSWORD' }).click();
      await expect(page.locator('#cp-current')).toBeVisible();
      await expect(page.locator('#cp-new')).toBeVisible();
      await expect(page.locator('#cp-confirm')).toBeVisible();
      const error = page.locator('#cp-err');
      const submit = page.getByRole('button', { name: 'ROTATE PASSWORD' });
      const submitValues = async (current, password, confirm) => {
        await page.locator('#cp-current').fill(current);
        await page.locator('#cp-new').fill(password);
        await page.locator('#cp-confirm').fill(confirm);
        await submit.click();
      };

      for (const [values, message] of [
        [['', 'abcdefgh', 'abcdefgh'], 'Current password required'],
        [['current', 'short', 'short'], 'New password must be at least 8 characters'],
        [['current', 'abcdefgh', 'abcdefgi'], 'New passwords do not match'],
        [['abcdefgh', 'abcdefgh', 'abcdefgh'], 'New password must differ from current']
      ]) {
        await submitValues(...values);
        await expect(error).toHaveText(message);
        expect(passwordRequests).toHaveLength(0);
      }

      await submitValues('wrong-current', 'new-password-123', 'new-password-123');
      await expect(error).toHaveText('Current password is incorrect');
      await expect(submit).toBeEnabled();
      await expect(page.locator('#login-overlay')).toBeHidden();
      expect(await page.evaluate(() => window._authFailing)).toBe(false);
      expect(passwordRequests).toHaveLength(1);
      expect(passwordRequests[0].method).toBe('POST');
      expect(passwordRequests[0].headers['content-type']).toContain('application/json');
      expect(passwordRequests[0].headers.cookie).toContain('freq_session=');
      expect(passwordRequests[0].headers['x-freq-csrf']).toBe(verifyTruth.body.csrf_token);
      expect(passwordRequests[0].body).toEqual({
        current_password: 'wrong-current',
        password: 'new-password-123'
      });

      await submitValues('zero-current', 'new-password-456', 'new-password-456');
      await expect(page.locator('#modal-container')).toBeHidden();
      await expect(page.locator('#toast-container .toast').last()).toHaveText('Password rotated · 0 stale sessions purged');
      await expect(page.locator('#login-overlay')).toBeHidden();
      expect(passwordRequests).toHaveLength(2);

      await page.evaluate(() => openChangePasswordModal());
      await page.locator('#cp-current').fill('one-current');
      await page.locator('#cp-new').fill('new-password-789');
      await page.locator('#cp-confirm').fill('new-password-789');
      await page.getByRole('button', { name: 'ROTATE PASSWORD' }).click();
      await expect(page.locator('#modal-container')).toBeHidden();
      await expect(page.locator('#toast-container .toast').last()).toHaveText('Password rotated · 1 stale session purged');
      await expect(page.locator('#login-overlay')).toBeHidden();
      expect(passwordRequests).toHaveLength(3);
    });

    const vmRequests = [];
    const gwipeRequests = [];
    const gwipeProxyRequests = [];
    const containerRequests = [];
    await page.route('**/api/vm/destroy?*', route => {
      const request = route.request();
      vmRequests.push({ method: request.method(), url: request.url() });
      return fulfillJson(route, { ok: true });
    });
    await page.route('**/api/gwipe?*', route => {
      const request = route.request();
      gwipeRequests.push({ method: request.method(), url: request.url() });
      if (gwipeRequests.length === 1) {
        return fulfillJson(route, {
          ok: true,
          action: 'wipe-all',
          data: { message: 'WIPE ALL queued' }
        });
      }
      return fulfillJson(route, { error: 'GWIPE station refused' }, 400);
    });
    await page.route('**/api/lab-tool/proxy?*', route => {
      const url = new URL(route.request().url());
      if (url.searchParams.get('tool') === 'gwipe') {
        gwipeProxyRequests.push({ method: route.request().method(), url: route.request().url() });
      }
      return fulfillJson(route, { error: 'read-only proxy is not a mutation route' }, 403);
    });
    await page.route('**/api/containers/action?*', route => {
      containerRequests.push({ method: route.request().method(), url: route.request().url() });
      return fulfillJson(route, { ok: true });
    });

    await test.step('VM and GWIPE require exact text, cancel cleanly, and dispatch one typed POST', async () => {
      await page.evaluate(() => vmDestroy(321));
      let input = page.locator('#destructive-confirm-input');
      let confirm = page.getByRole('button', { name: 'CONFIRM' });
      await expect(confirm).toBeDisabled();
      await input.fill('321-extra');
      await expect(confirm).toBeDisabled();
      await page.getByRole('button', { name: 'Cancel' }).click();
      expect(vmRequests).toHaveLength(0);

      await page.evaluate(() => vmDestroy(321));
      input = page.locator('#destructive-confirm-input');
      confirm = page.getByRole('button', { name: 'CONFIRM' });
      await input.fill('321');
      await expect(confirm).toBeEnabled();
      await confirm.click();
      await expect.poll(() => vmRequests.length).toBe(1);
      const vmUrl = new URL(vmRequests[0].url);
      expect(vmRequests[0].method).toBe('POST');
      expect(vmUrl.pathname).toBe('/api/vm/destroy');
      expect(vmUrl.searchParams.getAll('vmid')).toEqual(['321']);

      await page.evaluate(() => gwipeWipeAll('station-a'));
      input = page.locator('#destructive-confirm-input');
      confirm = page.getByRole('button', { name: 'CONFIRM' });
      await expect(confirm).toBeDisabled();
      await input.fill('WIPE station-a extra');
      await expect(confirm).toBeDisabled();
      await page.getByRole('button', { name: 'Cancel' }).click();
      expect(gwipeRequests).toHaveLength(0);
      expect(gwipeProxyRequests).toHaveLength(0);

      await page.evaluate(() => gwipeWipeAll('station-a'));
      input = page.locator('#destructive-confirm-input');
      await input.fill('WIPE station-a');
      await input.press('Enter');
      await expect.poll(() => gwipeRequests.length).toBe(1);
      await expect(page.locator('#toast-container')).toContainText('WIPE ALL queued');
      const gwipeUrl = new URL(gwipeRequests[0].url);
      expect(gwipeRequests[0].method).toBe('POST');
      expect(gwipeUrl.pathname).toBe('/api/gwipe');
      expect(gwipeUrl.searchParams.getAll('action')).toEqual(['wipe-all']);
      expect(gwipeUrl.searchParams.getAll('confirm')).toEqual(['YES']);
      expect(gwipeProxyRequests).toHaveLength(0);

      const beforeError = gwipeRequests.length;
      await page.evaluate(() => gwipeWipeAll('station-a'));
      input = page.locator('#destructive-confirm-input');
      await input.fill('WIPE station-a');
      await page.getByRole('button', { name: 'CONFIRM' }).click();
      await expect.poll(() => gwipeRequests.length).toBe(beforeError + 1);
      await expect(page.locator('#toast-container')).toContainText('GWIPE station refused');
      expect(gwipeProxyRequests).toHaveLength(0);
    });

    const chaosRequests = [];
    await page.route('**/api/chaos/log', route => fulfillJson(route, { experiments: [] }));
    await page.route('**/api/chaos/run?*', route => {
      chaosRequests.push({ method: route.request().method(), url: route.request().url() });
      return fulfillJson(route, { result: { status: 'completed', recovery_time: 3 } });
    });

    await test.step('hostile Chaos confirmation is inert, cancel is quiet, and confirm sends one POST', async () => {
      await page.locator('#nav-items [data-view="tools"]').click();
      await page.locator('#subtabs-tools [data-view="chaos"]').click();
      const hostile = '<img src=x onerror="window.__h04ChaosPwned=1">';
      await page.locator('#chaos-name').fill(hostile);
      await page.locator('#chaos-type').selectOption('service_restart');
      await page.locator('#chaos-target').evaluate(select => {
        const option = document.createElement('option');
        option.value = 'pve-hermetic';
        option.textContent = 'pve-hermetic';
        select.appendChild(option);
      });
      await page.locator('#chaos-target').selectOption('pve-hermetic');
      await page.evaluate(() => { window.__h04ChaosPwned = 0; });
      await page.locator('#chaos-view [data-action="chaosRun"]').click();
      await expect(page.locator('#modal-container')).toBeVisible();
      await expect(page.locator('#modal-container')).toContainText(hostile);
      await expect(page.locator('#modal-container img')).toHaveCount(0);
      expect(await page.evaluate(() => window.__h04ChaosPwned)).toBe(0);
      expect(chaosRequests).toHaveLength(0);
      await page.getByRole('button', { name: 'Cancel' }).click();
      expect(chaosRequests).toHaveLength(0);

      await page.locator('#chaos-view [data-action="chaosRun"]').click();
      await page.locator('#modal-confirm-btn').click();
      await expect.poll(() => chaosRequests.length).toBe(1);
      expect(chaosRequests[0].method).toBe('POST');
    });

    await test.step('container restart cancels quietly and confirms one encoded POST with honest result', async () => {
      page.once('dialog', dialog => dialog.dismiss());
      await page.evaluate(() => {
        window._cardState.host = 'docker-hermetic';
        window.hdDockerRestart('plex hermetic');
      });
      await page.waitForTimeout(100);
      expect(containerRequests).toHaveLength(0);

      page.once('dialog', dialog => dialog.accept());
      await page.evaluate(() => window.hdDockerRestart('plex hermetic'));
      await expect.poll(() => containerRequests.length).toBe(1);
      await page.waitForTimeout(100);
      expect(containerRequests).toHaveLength(1);
      const request = containerRequests[0];
      const url = new URL(request.url);
      expect(request.method).toBe('POST');
      expect(url.pathname).toBe('/api/containers/action');
      expect(url.searchParams.getAll('host')).toEqual(['docker-hermetic']);
      expect(url.searchParams.getAll('name')).toEqual(['plex hermetic']);
      expect(url.searchParams.getAll('action')).toEqual(['restart']);
      await expect(page.locator('#toast-container .toast').last()).toHaveText('Restarted plex hermetic');
    });

    await test.step('authenticated real mutation route rejects GET', async () => {
      const result = await page.evaluate(async () => {
        const response = await fetch('/api/exec');
        return { status: response.status, body: await response.json() };
      });
      expect(result.status).toBe(405);
      expect(result.body.error).toBe('Fleet exec requires POST');
    });

    await context.close();
  });

  test('H05 operator RBAC keeps reads useful, admin actions inert, and shortcuts out of editing contexts', async ({ browser }, testInfo) => {
    test.setTimeout(120_000);
    const operatorContext = await browser.newContext({ baseURL: testInfo.project.use.baseURL });
    const operatorPage = await operatorContext.newPage();
    const operatorExecRequests = [];
    const operatorHardenRequests = [];
    const operatorAdminRequests = [];
    operatorPage.on('request', request => {
      const pathname = new URL(request.url()).pathname;
      if (pathname === '/api/exec') operatorExecRequests.push(request.method());
      if (pathname === '/api/harden') operatorHardenRequests.push(request.method());
      if (pathname === '/api/admin/fleet-boundaries') operatorAdminRequests.push(request.method());
    });

    await test.step('real operator identity is preserved and the real admin boundary denies it', async () => {
      await loginInBrowser(operatorPage, 'operator');
      await operatorPage.evaluate(() => {
        clearInterval(window._healthTimer);
        clearInterval(window._fleetTimer);
        clearInterval(window._activityTimer);
      });
      const verify = await operatorPage.evaluate(async () => {
        const response = await fetch('/api/auth/verify');
        return { status: response.status, body: await response.json() };
      });
      expect(verify.status).toBe(200);
      expect(verify.body).toMatchObject({ valid: true, user: 'operator', role: 'operator' });
      await expect(operatorPage.locator('#header-user-name')).toHaveText('operator');
      await expect(operatorPage.locator('#header-user-role')).toHaveText('OPERATOR');

      const denial = await operatorPage.evaluate(async () => {
        const response = await fetch('/api/admin/fleet-boundaries');
        return { status: response.status, body: await response.json() };
      });
      expect(denial).toMatchObject({
        status: 403,
        body: { error: 'Requires admin role (you are operator)' }
      });
      expect(operatorAdminRequests).toEqual(['GET']);
      await expect(operatorPage.locator('#login-overlay')).toBeHidden();
      expect(await operatorPage.evaluate(() => window._authFailing)).toBe(false);
    });

    await test.step('operator Settings renders truthful OOC inventory without an admin consumer request', async () => {
      await operatorPage.locator('#nav-items [data-view="settings"]').click();
      await expect(operatorPage.locator('#settings-view')).toBeVisible();
      await expect(operatorPage.locator('#settings-view')).toContainText('OOC (out of contract)');
      const assignments = operatorPage.locator('#lab-assign-list');
      await expect(assignments.locator('.device-assignment-readonly')).toContainText('READ ONLY');
      await expect(assignments.locator('.device-assignment-table tbody tr').first()).toBeVisible();
      await expect(assignments.locator('[data-action="saveDeviceAssignmentRow"]')).toHaveCount(0);
      await expect(assignments.locator('select, input')).toHaveCount(0);
      await expect(operatorPage.locator('#fleet-admin-section')).toBeHidden();
      expect(operatorAdminRequests).toEqual(['GET']);
    });

    await test.step('operator hardening exposes one real read while every command family fails closed before side effects', async () => {
      await operatorPage.evaluate(() => switchView('sec-hardening'));
      await expect(operatorPage.locator('#sec-hardening-view')).toBeVisible();
      const notice = operatorPage.locator('#hardening-role-notice');
      await expect(notice).toBeVisible();
      await expect(notice).toHaveText('ADMIN REQUIRED — Command audits, policy sweep, remediation, and SSHD restart require an admin role. Full Hardening Audit remains available.');
      await expect(operatorPage.locator('#sec-hardening-view [data-audit]:disabled')).toHaveCount(7);
      expect(await operatorPage.locator('#sec-hardening-view [data-audit]').evaluateAll(controls =>
        controls.every(control => control.title === 'Admin role required')
      )).toBe(true);
      await expect(operatorPage.locator('#sec-hardening-view [data-action="runSshSweep"]:disabled')).toHaveCount(1);
      await expect(operatorPage.locator('#harden-target:disabled')).toHaveCount(1);
      await expect(operatorPage.locator('#sec-hardening-view [data-action="hardenAction"]:disabled')).toHaveCount(4);
      await expect(operatorPage.locator('#sec-hardening-view [data-action="sshdPanel"]:disabled')).toHaveCount(1);
      await expect(operatorPage.locator('#sec-hardening-view [data-action="runHarden"]')).toBeEnabled();

      const before = await operatorPage.evaluate(() => ({
        audit: document.getElementById('audit-c').innerHTML,
        sweep: document.getElementById('sweep-c').innerHTML,
        harden: document.getElementById('harden-c').innerHTML
      }));
      await operatorPage.evaluate(() => {
        runAuditCheck('all');
        runSshSweep();
        hardenAction('disable-root');
        sshdPanel('harden-c');
        sshdRestartHost('pve-hermetic');
        sshdRestartSelected();
        sshdRestartAll();
        _sshdRestart(['pve-hermetic']);
      });
      expect(await operatorPage.evaluate(() => ({
        audit: document.getElementById('audit-c').innerHTML,
        sweep: document.getElementById('sweep-c').innerHTML,
        harden: document.getElementById('harden-c').innerHTML
      }))).toEqual(before);
      await expect(operatorPage.locator('#modal-container')).toBeHidden();
      expect(operatorExecRequests).toHaveLength(0);

      const hardenResponsePromise = operatorPage.waitForResponse(response =>
        new URL(response.url()).pathname === '/api/harden'
      );
      await operatorPage.locator('#sec-hardening-view [data-action="runHarden"]').click();
      const hardenResponse = await hardenResponsePromise;
      expect(hardenResponse.status()).toBe(200);
      expect(operatorHardenRequests).toEqual(['GET']);
      await expect(operatorPage.locator('#harden-c table')).toBeVisible();
      await expect(operatorPage.locator('#toast-container')).toContainText('Hardening audit complete');
      expect(operatorExecRequests).toHaveLength(0);
      await expect(operatorPage.locator('#login-overlay')).toBeHidden();
      expect(await operatorPage.evaluate(() => window._authFailing)).toBe(false);
      const verify = await operatorPage.evaluate(async () => {
        const response = await fetch('/api/auth/verify');
        return { status: response.status, body: await response.json() };
      });
      expect(verify).toMatchObject({ status: 200, body: { valid: true, user: 'operator', role: 'operator' } });
    });

    await test.step('operator help and 1-6 shortcuts resolve to the six truthful top-level destinations', async () => {
      await operatorPage.locator('body').click({ position: { x: 4, y: 4 } });
      await operatorPage.keyboard.type('?');
      const help = operatorPage.locator('#shortcuts-modal');
      await expect(help).toBeVisible();
      await expect(help).toContainText('1-6');
      await expect(help).toContainText('Home / Fleet / Docker / Certificates / System / Settings');
      await operatorPage.keyboard.press('Escape');
      await expect(help).toBeHidden();

      for (const destination of [
        { key: '1', view: 'home', nav: 'home', title: 'HOME' },
        { key: '2', view: 'fleet', nav: 'fleet', title: 'FLEET' },
        { key: '3', view: 'docker', nav: 'docker', title: 'DOCKER' },
        { key: '4', view: 'certs', nav: 'security', title: 'SECURITY' },
        { key: '5', view: 'tools', nav: 'tools', title: 'SYSTEM' },
        { key: '6', view: 'settings', nav: 'settings', title: 'SETTINGS' }
      ]) {
        await operatorPage.keyboard.press(destination.key);
        await expect(operatorPage.locator(`#${destination.view}-view`)).toBeVisible();
        await expect(operatorPage.locator(`#nav-items [data-view="${destination.nav}"]`)).toHaveClass(/active-view/);
        await expect(operatorPage.locator('#page-title')).toHaveText(destination.title);
        await expect.poll(() => new URL(operatorPage.url()).pathname).toBe(`/dashboard/${destination.view}`);
      }
    });

    await test.step('editing focus suppresses shortcuts and an admin can target remediation but cancel without dispatch', async () => {
      await operatorPage.evaluate(() => {
        const probes = document.createElement('div');
        probes.id = 'h05-editing-probes';
        probes.innerHTML = '<input id="h05-input"><textarea id="h05-textarea"></textarea><select id="h05-select"><option>one</option></select><div id="h05-editable" contenteditable="true">editable</div>';
        document.body.appendChild(probes);
      });
      for (const selector of ['#h05-input', '#h05-textarea', '#h05-select', '#h05-editable']) {
        await operatorPage.locator(selector).focus();
        await operatorPage.keyboard.type('?');
        await operatorPage.keyboard.press('1');
        await operatorPage.keyboard.press('5');
        await expect(operatorPage.locator('#settings-view')).toBeVisible();
        await expect(operatorPage.locator('#shortcuts-modal')).toBeHidden();
        await expect.poll(() => new URL(operatorPage.url()).pathname).toBe('/dashboard/settings');
      }

      const adminContext = await browser.newContext({ baseURL: testInfo.project.use.baseURL });
      const adminPage = await adminContext.newPage();
      const adminExecRequests = [];
      adminPage.on('request', request => {
        if (new URL(request.url()).pathname === '/api/exec') adminExecRequests.push(request.method());
      });
      await loginInBrowser(adminPage);
      await adminPage.evaluate(() => {
        clearInterval(window._healthTimer);
        clearInterval(window._fleetTimer);
        clearInterval(window._activityTimer);
        switchView('sec-hardening');
      });
      await expect(adminPage.locator('#sec-hardening-view')).toBeVisible();
      await expect(adminPage.locator('#hardening-role-notice')).toBeHidden();
      await expect(adminPage.locator('#sec-hardening-view [data-audit]:enabled')).toHaveCount(7);
      await expect(adminPage.locator('#sec-hardening-view [data-action="runSshSweep"]')).toBeEnabled();
      await expect(adminPage.locator('#harden-target')).toBeEnabled();
      await expect(adminPage.locator('#sec-hardening-view [data-action="hardenAction"]:enabled')).toHaveCount(4);
      await expect(adminPage.locator('#sec-hardening-view [data-action="sshdPanel"]')).toBeEnabled();
      await expect(adminPage.locator('#sec-hardening-view [data-action="runHarden"]')).toBeEnabled();

      await adminPage.locator('#sec-hardening-view [data-action="hardenAction"][data-arg="disable-root"]').click();
      await expect(adminPage.locator('#toast-container')).toContainText('Select a hardening target');
      await expect(adminPage.locator('#modal-container')).toBeHidden();
      expect(adminExecRequests).toHaveLength(0);

      const target = adminPage.locator('#harden-target');
      await expect(target.locator('option[value="pve-hermetic"]')).toHaveCount(1);
      await target.focus();
      await adminPage.keyboard.press('5');
      await expect(adminPage.locator('#sec-hardening-view')).toBeVisible();
      await expect.poll(() => new URL(adminPage.url()).pathname).toBe('/dashboard/sec-hardening');
      await target.selectOption('pve-hermetic');
      await adminPage.locator('#sec-hardening-view [data-action="hardenAction"][data-arg="disable-root"]').click();
      await expect(adminPage.locator('#modal-container')).toBeVisible();
      await expect(adminPage.locator('#modal-container')).toContainText('PVE-HERMETIC');
      expect(adminExecRequests).toHaveLength(0);
      await adminPage.getByRole('button', { name: 'Cancel' }).click();
      await expect(adminPage.locator('#modal-container')).toBeHidden();
      expect(adminExecRequests).toHaveLength(0);

      const hostUpdateUrls = [];
      let unknownDeviceType = 'unknown';
      const fulfillJson = (route, body) => route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(body)
      });
      await adminPage.route('**/api/admin/fleet-boundaries', route => fulfillJson(route, {
        tiers: {}, categories: {}, physical: {}, core_physical: {}, lab_physical: {}, pve_nodes: {},
        hosts: [
          { ip: '192.0.2.40', label: 'new-unknown', type: unknownDeviceType, groups: '', vmid: 4040, managed: false, all_ips: ['192.0.2.40'] },
          { ip: '192.0.2.41', label: 'existing-explicit', type: 'docker', groups: 'media,prod', vmid: 4041, managed: true, all_ips: ['192.0.2.41'] }
        ]
      }));
      await adminPage.route('**/api/fleet/overview', route => fulfillJson(route, { vms: [], physical: [], pve_nodes: [] }));
      await adminPage.route('**/api/health', route => fulfillJson(route, { hosts: [], probe_status: 'ok' }));
      await adminPage.route('**/api/admin/hosts/update?*', route => {
        hostUpdateUrls.push(route.request().url());
        const url = new URL(route.request().url());
        return fulfillJson(route, {
          ok: true,
          label: url.searchParams.get('label'),
          type: url.searchParams.get('type'),
          groups: url.searchParams.get('groups'),
          managed: url.searchParams.get('managed') === 'true'
        });
      });

      await test.step('Unknown inventory remains undecided until an explicit assignment', async () => {
        await adminPage.evaluate(() => {
          switchView('settings');
          _loadLabAssignments();
        });
        const assignments = adminPage.locator('#lab-assign-list');
        const unknown = assignments.locator('#hg-new-unknown').locator('xpath=ancestor::tr');
        const explicit = assignments.locator('#hg-existing-explicit').locator('xpath=ancestor::tr');
        await expect(unknown).toBeVisible();
        await expect(unknown.locator('[aria-label="Device type"]')).toHaveValue('unknown');
        await expect(unknown.locator('[aria-label="Device management mode"]')).toHaveValue('false');
        await expect(unknown.locator('[aria-label="Device groups"]')).toHaveValue('');
        const unknownAssignment = unknown.locator('[aria-label="Device assignment"]');
        await expect(unknownAssignment).toHaveValue('');
        await expect(unknownAssignment.locator('option:checked')).toHaveText('CHOOSE');
        await expect(unknownAssignment.locator('option:checked')).toBeDisabled();

        await expect(explicit.locator('[aria-label="Device groups"]')).toHaveValue('media,prod');
        await expect(explicit.locator('[aria-label="Device assignment"]')).toHaveValue('prod');

        await unknown.locator('[placeholder="new-unknown"]').fill('New Unknown');
        await unknown.locator('[data-action="saveDeviceAssignmentRow"]').click();
        await expect.poll(() => hostUpdateUrls.length).toBe(1);
        let update = new URL(hostUpdateUrls[0]);
        expect(update.searchParams.get('label')).toBe('new-unknown');
        expect(update.searchParams.get('display_name')).toBe('New Unknown');
        expect(update.searchParams.get('groups')).toBe('');
        expect(update.searchParams.get('groups')).not.toBe('prod');

        // Hold the post-save inventory read while another row is edited.
        // A background replacement must not erase that explicit draft.
        let releaseAssignmentRefresh;
        const assignmentRefreshGate = new Promise(resolve => { releaseAssignmentRefresh = resolve; });
        let heldAssignmentRefreshes = 0;
        await adminPage.route('**/api/admin/fleet-boundaries', async route => {
          heldAssignmentRefreshes += 1;
          await assignmentRefreshGate;
          return route.fallback();
        });
        await explicit.locator('[placeholder="existing-explicit"]').fill('Existing Explicit');
        await explicit.locator('[data-action="saveDeviceAssignmentRow"]').click();
        await expect.poll(() => hostUpdateUrls.length).toBe(2);
        update = new URL(hostUpdateUrls[1]);
        expect(update.searchParams.get('label')).toBe('existing-explicit');
        expect(update.searchParams.get('groups')).toBe('media,prod');

        await expect(unknown).toBeVisible();
        await expect.poll(() => heldAssignmentRefreshes).toBeGreaterThan(0);
        await unknown.locator('[aria-label="Device assignment"]').selectOption('prod');
        await unknown.locator('[placeholder="new-unknown"]').fill('Draft during refresh');
        const oldUnknownRow = await unknown.elementHandle();
        unknownDeviceType = 'linux';
        releaseAssignmentRefresh();
        await expect.poll(() => oldUnknownRow.evaluate(row => row.isConnected)).toBe(false);
        await expect(unknown.locator('[aria-label="Device assignment"]')).toHaveValue('prod');
        await expect(unknown.locator('[placeholder="new-unknown"]')).toHaveValue('Draft during refresh');
        await expect(unknown.locator('[aria-label="Device type"]')).toHaveValue('linux');
        await unknown.locator('[data-action="saveDeviceAssignmentRow"]').click();
        await expect.poll(() => hostUpdateUrls.length).toBe(3);
        update = new URL(hostUpdateUrls[2]);
        expect(update.searchParams.get('label')).toBe('new-unknown');
        expect(update.searchParams.get('groups')).toBe('prod');
      });
      await adminContext.close();
    });

    await operatorContext.close();
  });

  test('H10 responsive shell contains current routes and owns local overflow', async ({ browser }, testInfo) => {
    test.setTimeout(60_000);
    const profiles = [
      { name: 'desktop', width: 1440, height: 1000 },
      { name: 'tablet', width: 820, height: 1180 },
      { name: 'phone', width: 390, height: 844 }
    ];

    async function horizontalTruth(page, rootSelector) {
      return page.evaluate((selector) => {
        const viewport = document.documentElement.clientWidth;
        const root = document.querySelector(selector);
        if (!root) return { missing: selector };
        const rootBox = root.getBoundingClientRect();
        const visible = (element) => {
          const style = getComputedStyle(element);
          const box = element.getBoundingClientRect();
          return style.display !== 'none' && style.visibility !== 'hidden' && box.width > 0 && box.height > 0;
        };
        const scrollOwner = (element) => {
          for (let node = element; node && node !== document.body; node = node.parentElement) {
            const style = getComputedStyle(node);
            if (/^(auto|scroll)$/.test(style.overflowX) && node.scrollWidth > node.clientWidth + 1) {
              const box = node.getBoundingClientRect();
              return box.left >= -1 && box.right <= viewport + 1;
            }
          }
          return false;
        };
        const escaped = [];
        root.querySelectorAll('button, input:not([type="hidden"]), select, textarea, a[href], .section, .crd, .host-card, .infra-role-card').forEach((element) => {
          if (!visible(element)) return;
          const box = element.getBoundingClientRect();
          if ((box.left < -1 || box.right > viewport + 1) && !scrollOwner(element)) {
            escaped.push({
              tag: element.tagName,
              id: element.id,
              text: (element.textContent || '').trim().slice(0, 60),
              box: [Math.round(box.left), Math.round(box.right)]
            });
          }
        });
        return {
          documentOverflow: document.documentElement.scrollWidth - viewport,
          rootBox: [Math.round(rootBox.left), Math.round(rootBox.right), viewport],
          escaped
        };
      }, rootSelector);
    }

    for (const profile of profiles) {
      const context = await browser.newContext({
        baseURL: testInfo.project.use.baseURL,
        viewport: { width: profile.width, height: profile.height }
      });
      const page = await context.newPage();

      await test.step(`${profile.name} pre-auth shell is contained`, async () => {
        await page.goto('/', { waitUntil: 'domcontentloaded' });
        await expect(page.locator('#login-overlay')).toBeVisible();
        await expect(page.locator('.login-card')).toBeVisible();
        const geometry = await page.locator('.login-card').evaluate((card) => {
          const box = card.getBoundingClientRect();
          return {
            viewport: document.documentElement.clientWidth,
            documentOverflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
            box: [box.left, box.right]
          };
        });
        expect(geometry.documentOverflow).toBeLessThanOrEqual(1);
        expect(geometry.box[0]).toBeGreaterThanOrEqual(-1);
        expect(geometry.box[1]).toBeLessThanOrEqual(geometry.viewport + 1);
      });

      await test.step(`${profile.name} authenticated global shell is contained`, async () => {
        await page.locator('#login-user').fill(USER);
        await page.locator('#login-pass').fill(PASS);
        await page.locator('#login-form').evaluate((form) => form.requestSubmit());
        await page.locator('#login-overlay').waitFor({ state: 'hidden' });
        await page.evaluate(() => {
          clearInterval(window._healthTimer);
          clearInterval(window._fleetTimer);
          clearInterval(window._activityTimer);
        });
        await expect(page.locator('#mn-body')).toBeVisible();
        await expect(page.locator('.mn-header')).toBeVisible();
        await expect(page.locator('#header-user-btn')).toBeVisible();

        if (profile.width <= 768) {
          await expect(page.locator('.mobile-menu-btn')).toBeVisible();
          await page.locator('.mobile-menu-btn').click();
          await expect(page.locator('#nav-items')).toBeVisible();
        } else {
          await expect(page.locator('#nav-items')).toBeVisible();
        }
        for (const selector of ['.mn-header', '#nav-items', '#mn-body']) {
          const truth = await horizontalTruth(page, selector);
          expect(truth.missing).toBeUndefined();
          expect(truth.documentOverflow).toBeLessThanOrEqual(1);
          expect(truth.rootBox[0]).toBeGreaterThanOrEqual(-1);
          expect(truth.rootBox[1]).toBeLessThanOrEqual(truth.rootBox[2] + 1);
          expect(truth.escaped).toEqual([]);
        }
        if (profile.width <= 768) await page.locator('.mobile-menu-btn').click();
      });

      const topology = await page.evaluate(() => ({
        views: window.VIEW_IDS.slice(),
        viewToNav: Object.assign({}, window.VIEW_TO_NAV),
        groups: Object.fromEntries(Object.entries(window.SUBNAV_GROUPS).map(([group, items]) => [
          group,
          items.map((item) => item.view)
        ])),
        missingMounts: window.VIEW_IDS.filter((view) => !document.getElementById(`${view}-view`))
      }));
      expect(topology.views.length).toBeGreaterThan(0);
      expect(new Set(topology.views).size).toBe(topology.views.length);
      expect(topology.missingMounts).toEqual([]);

      await test.step(`${profile.name} current route loop stays contained`, async () => {
        const routeTruths = await page.evaluate((views) => views.map((nextView) => {
            const expectedNav = window.VIEW_TO_NAV[nextView] || nextView;
            window.switchView(nextView);
            const viewport = document.documentElement.clientWidth;
            const root = document.getElementById(`${nextView}-view`);
            const visible = (element) => {
              const style = getComputedStyle(element);
              const box = element.getBoundingClientRect();
              return style.display !== 'none' && style.visibility !== 'hidden' && box.width > 0 && box.height > 0;
            };
            const scrollOwner = (element) => {
              for (let node = element; node && node !== document.body; node = node.parentElement) {
                const style = getComputedStyle(node);
                if (/^(auto|scroll)$/.test(style.overflowX) && node.scrollWidth > node.clientWidth + 1) {
                  const box = node.getBoundingClientRect();
                  return box.left >= -1 && box.right <= viewport + 1;
                }
              }
              return false;
            };
            const escaped = [];
            root.querySelectorAll('button, input:not([type="hidden"]), select, textarea, a[href], .section, .crd, .host-card, .infra-role-card').forEach((element) => {
              if (!visible(element)) return;
              const box = element.getBoundingClientRect();
              if ((box.left < -1 || box.right > viewport + 1) && !scrollOwner(element)) {
                escaped.push({
                  tag: element.tagName,
                  id: element.id,
                  text: (element.textContent || '').trim().slice(0, 60),
                  box: [Math.round(box.left), Math.round(box.right)]
                });
              }
            });
            const rootBox = root.getBoundingClientRect();
            const subnav = root.querySelector(':scope > [data-subnav-group]');
            let subnavTruth = null;
            if (subnav) {
              const box = subnav.getBoundingClientRect();
              subnavTruth = {
                group: subnav.dataset.subnavGroup,
                count: subnav.querySelectorAll('.sub-tab').length,
                current: subnav.querySelector('.sub-tab[aria-current="page"]')?.dataset.view || '',
                box: [box.left, box.right, viewport],
                hiddenOverflow: subnav.scrollWidth - subnav.clientWidth,
                escaped: Array.from(subnav.querySelectorAll('.sub-tab')).filter((button) => {
                  const child = button.getBoundingClientRect();
                  return child.left < box.left - 1 || child.right > box.right + 1;
                }).map((button) => button.dataset.view)
              };
            }
            return {
              view: nextView,
              path: location.pathname,
              rootVisible: visible(root),
              activeNav: document.querySelector(`#nav-items [data-view="${expectedNav}"]`)?.getAttribute('aria-current') || '',
              activeNavCount: document.querySelectorAll('#nav-items [aria-current="page"]').length,
              documentOverflow: document.documentElement.scrollWidth - viewport,
              rootBox: [Math.round(rootBox.left), Math.round(rootBox.right), viewport],
              escaped,
              subnav: subnavTruth
            };
          }), topology.views);

        for (const routeTruth of routeTruths) {
          const view = routeTruth.view;
          expect(routeTruth.path).toBe(`/dashboard/${view}`);
          expect(routeTruth.rootVisible).toBe(true);
          expect(routeTruth.activeNav).toBe('page');
          expect(routeTruth.activeNavCount).toBe(1);
          expect(routeTruth.documentOverflow).toBeLessThanOrEqual(1);
          expect(routeTruth.rootBox[0]).toBeGreaterThanOrEqual(-1);
          expect(routeTruth.rootBox[1]).toBeLessThanOrEqual(routeTruth.rootBox[2] + 1);
          expect(routeTruth.escaped).toEqual([]);

          if (routeTruth.subnav) {
            expect(topology.groups[routeTruth.subnav.group]).toContain(view);
            expect(routeTruth.subnav.count).toBe(topology.groups[routeTruth.subnav.group].length);
            expect(routeTruth.subnav.current).toBe(view);
            expect(routeTruth.subnav.box[0]).toBeGreaterThanOrEqual(-1);
            expect(routeTruth.subnav.box[1]).toBeLessThanOrEqual(routeTruth.subnav.box[2] + 1);
            expect(routeTruth.subnav.hiddenOverflow).toBeLessThanOrEqual(1);
            expect(routeTruth.subnav.escaped).toEqual([]);
          }
        }
      });

      await test.step(`${profile.name} wide tables and controls stay locally usable`, async () => {
        await page.evaluate(() => window.switchView('security'));
        await expect(page.locator('#security-view')).toBeVisible();
        const host = page.locator('#security-view .section-body').first();
        await expect(host).toBeVisible();
        await host.evaluate((sectionBody) => {
          const probe = document.createElement('div');
          probe.id = 'h10-overflow-probe';
          const headers = Array.from({ length: 10 }, (_, index) => `<th>VeryLongHeader${index}</th>`).join('');
          const cells = Array.from({ length: 10 }, (_, index) => `<td>unbreakable-value-${index}-xxxxxxxxxx</td>`).join('');
          probe.innerHTML = `<table id="h10-wide-table"><thead><tr>${headers}</tr></thead><tbody><tr>${cells}</tr></tbody></table>` +
            '<div id="h10-control-rail" class="form-row"><input aria-label="Long proof input" value="long-control-value-xxxxxxxxxxxxxxxx"><select aria-label="Long proof select"><option>long-option-value-xxxxxxxxxxxxxxxx</option></select><button class="fleet-btn">LONG CONTROL ACTION</button></div>';
          sectionBody.prepend(probe);
        });
        await expect(page.locator('#h10-wide-table')).toHaveClass(/responsive-table/);

        const controlTruth = await horizontalTruth(page, '#h10-control-rail');
        expect(controlTruth.documentOverflow).toBeLessThanOrEqual(1);
        expect(controlTruth.rootBox[0]).toBeGreaterThanOrEqual(-1);
        expect(controlTruth.rootBox[1]).toBeLessThanOrEqual(controlTruth.rootBox[2] + 1);
        expect(controlTruth.escaped).toEqual([]);

        if (profile.width > 480) {
          const tableTruth = await page.locator('#h10-wide-table').evaluate((table) => {
            const box = table.getBoundingClientRect();
            const style = getComputedStyle(table);
            table.scrollLeft = 120;
            return {
              documentOverflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
              box: [box.left, box.right, document.documentElement.clientWidth],
              display: style.display,
              overflow: style.overflowX,
              client: table.clientWidth,
              scroll: table.scrollWidth,
              scrollLeft: table.scrollLeft
            };
          });
          expect(tableTruth.documentOverflow).toBeLessThanOrEqual(1);
          expect(tableTruth.box[0]).toBeGreaterThanOrEqual(-1);
          expect(tableTruth.box[1]).toBeLessThanOrEqual(tableTruth.box[2] + 1);
          expect(tableTruth.display).toBe('block');
          expect(tableTruth.overflow).toBe('auto');
          expect(tableTruth.scroll).toBeGreaterThan(tableTruth.client + 1);
          expect(tableTruth.scrollLeft).toBeGreaterThan(0);
        } else {
          const mobileTableTruth = await page.locator('#h10-wide-table').evaluate((table) => {
            const box = table.getBoundingClientRect();
            return {
              box: [box.left, box.right, document.documentElement.clientWidth],
              documentOverflow: document.documentElement.scrollWidth - document.documentElement.clientWidth
            };
          });
          expect(mobileTableTruth.documentOverflow).toBeLessThanOrEqual(1);
          expect(mobileTableTruth.box[0]).toBeGreaterThanOrEqual(-1);
          expect(mobileTableTruth.box[1]).toBeLessThanOrEqual(mobileTableTruth.box[2] + 1);
        }
      });

      if (profile.width === 390) {
        await test.step('phone Fleet core, PVE, workload, and control grids stay contained', async () => {
          const fleetTruth = await page.evaluate(() => {
            window.switchView('fleet');
            const cards = document.getElementById('metrics-cards');
            const pveNodes = [{ name: 'pve-h10', online: true, detail: '16 cores 64GB responsive proof' }];
            const health = {
              'pve-h10': { state: 'live', status: 'online', cores: '16', load: '4', disk: '20%', ram: '4096/16384MB' }
            };
            const vms = {
              'pve-h10': [{ vmid: 910, name: 'responsive-workload-with-a-long-name', status: 'running', cpu: 2, ram_mb: 4096 }]
            };
            const nodeData = window._buildPveNodeData(pveNodes, health, vms, {}, {}, {});
            nodeData['pve-h10'].rows = window._pveWorkloadRow(
              'VM', 'responsive-workload-with-a-long-name', 910, 'running', '25%', '4GB', 'PROD', 'var(--purple-light)'
            );
            nodeData['pve-h10'].workloadCount = 1;
            window._pveExpandedNodes['pve-h10'] = true;
            const infraCards = [0, 1, 2].map((index) =>
              `<article class="infra-role-card"><h3>responsive-core-system-${index}-with-long-label</h3><button class="fleet-btn">OPEN SYSTEM ${index}</button></article>`
            ).join('');
            cards.innerHTML = window._assembleFleetOutput(infraCards, nodeData, pveNodes);
            const viewport = document.documentElement.clientWidth;
            const escaped = [];
            document.querySelectorAll('#metrics-cards .infra-role-card, #metrics-cards .pve-node-card, #metrics-cards .pve-node-summary, #metrics-cards .pve-node-metrics, #metrics-cards .pve-workload-row, #metrics-cards button').forEach((element) => {
              const style = getComputedStyle(element);
              const box = element.getBoundingClientRect();
              if (style.display === 'none' || box.width === 0 || box.height === 0) return;
              if (box.left < -1 || box.right > viewport + 1) {
                escaped.push({ selector: element.className, box: [Math.round(box.left), Math.round(box.right)] });
              }
            });
            return {
              documentOverflow: document.documentElement.scrollWidth - viewport,
              coreCards: document.querySelectorAll('#metrics-cards .core-systems-grid > .infra-role-card').length,
              coreTracks: getComputedStyle(document.querySelector('#metrics-cards .core-systems-grid')).gridTemplateColumns.trim().split(/\s+/).length,
              pveCards: document.querySelectorAll('#metrics-cards .pve-node-card').length,
              summaryTracks: getComputedStyle(document.querySelector('#metrics-cards .pve-node-summary')).gridTemplateColumns.trim().split(/\s+/).length,
              metricTracks: getComputedStyle(document.querySelector('#metrics-cards .pve-node-metrics')).gridTemplateColumns.trim().split(/\s+/).length,
              workloads: document.querySelectorAll('#metrics-cards .pve-workload-row').length,
              workloadTracks: getComputedStyle(document.querySelector('#metrics-cards .pve-workload-row')).gridTemplateColumns.trim().split(/\s+/).length,
              escaped
            };
          });
          expect(fleetTruth.documentOverflow).toBeLessThanOrEqual(1);
          expect(fleetTruth.coreCards).toBe(3);
          expect(fleetTruth.coreTracks).toBe(1);
          expect(fleetTruth.pveCards).toBe(1);
          expect(fleetTruth.summaryTracks).toBe(2);
          expect(fleetTruth.metricTracks).toBe(1);
          expect(fleetTruth.workloads).toBe(1);
          expect(fleetTruth.workloadTracks).toBe(2);
          expect(fleetTruth.escaped).toEqual([]);
        });
      }

      await context.close();
    }
  });

  test('H11 operator truth keeps setup, doctor, watchdog, cache, and stream degradation honest', async ({ page }) => {
    test.setTimeout(90_000);
    const cleanSetup = {
      first_run: false,
      initialized: true,
      setup_health: 'configured',
      pve_nodes_configured: true,
      hosts_configured: true,
      ssh_key_exists: true,
      ssh_key_readable: true
    };
    const liveHealth = {
      hosts: [{ label: 'pve-hermetic', type: 'pve', state: 'live', status: 'healthy' }],
      probe_state: 'live',
      probe_status: 'ok',
      age_seconds: 2
    };
    const liveFleet = {
      pve_nodes: [{ name: 'pve-hermetic', state: 'live', online: true }],
      vms: [],
      physical: [],
      summary: { resource_count: 1, total_vms: 0, running: 0, stopped: 0 },
      fleet_state: 'live',
      probe_status: 'ok',
      stale: false,
      age_seconds: 2
    };
    let setupPlan = { status: 200, body: {
      first_run: false, initialized: false, setup_health: 'init-failed',
      setup_reason: 'Operator VM contract failed: unexpected out-of-contract PVE VM 106',
      dashboard_accounts_configured: true, dashboard_passwords_configured: true,
      pve_nodes_configured: false, hosts_configured: false,
      ssh_key_exists: false, ssh_key_readable: false
    } };
    let doctorPlan = {
      status: 200,
      body: {
        status: 'unhealthy', passed: 8, failed: 1, warnings: 1,
        checks: [
          { name: 'service-user', status: 'fail' },
          { name: 'cache-age', status: 'warn' }
        ]
      }
    };
    let watchdogPlan = { status: 501, body: { watchdog_installed: false } };
    let healthPlan = liveHealth;
    let fleetPlan = liveFleet;
    const fulfillJson = (route, status, body) => route.fulfill({
      status,
      contentType: 'application/json',
      body: JSON.stringify(body)
    });

    await page.route('**/api/auth/login', route => fulfillJson(route, 200, {
      user: USER, role: 'admin', username: USER
    }));
    await page.route('**/api/setup/status', route => fulfillJson(route, setupPlan.status, setupPlan.body));
    await page.route('**/api/doctor', route => fulfillJson(route, doctorPlan.status, doctorPlan.body));
    await page.route('**/api/watchdog/health', route => {
      if (watchdogPlan.abort) return route.abort('failed');
      return fulfillJson(route, watchdogPlan.status, watchdogPlan.body);
    });
    await page.route('**/api/health', route => fulfillJson(route, 200, healthPlan));
    await page.route('**/api/fleet/overview', route => fulfillJson(route, 200, fleetPlan));
    await page.addInitScript(() => {
      Object.defineProperty(window, 'EventSource', { value: undefined, configurable: true });
      localStorage.setItem('freq_admin_home_widgets', JSON.stringify(['w-fleet-stats']));
    });

    const waitForHealthRefresh = async () => {
      await page.evaluate(() => window._silentHealthRefresh());
      await expect.poll(() => page.evaluate(() => window._healthInFlight)).toBe(false);
    };
    const waitForFleetRefresh = async () => {
      await page.evaluate(() => window._silentFleetRefresh());
      await expect.poll(() => page.evaluate(() => window._fleetInFlight)).toBe(false);
    };

    await test.step('pre-auth incomplete setup stays visible and post-auth truth layers', async () => {
      await page.goto('/', { waitUntil: 'domcontentloaded' });
      await expect(page.locator('#login-setup-banner')).toBeVisible();
      await expect(page.locator('#login-setup-banner')).toContainText('LOGIN AVAILABLE');
      await expect(page.locator('#login-setup-banner')).toContainText('SETUP ATTENTION');
      await expect(page.locator('#login-setup-banner')).toContainText('out-of-contract PVE VM 106');
    });

    await test.step('post-auth doctor failure names failing checks without hiding setup truth', async () => {
      await page.locator('#login-user').fill(USER);
      await page.locator('#login-pass').fill(PASS);
      await page.locator('#login-form').evaluate(form => form.requestSubmit());
      await page.locator('#login-overlay').waitFor({ state: 'hidden' });
      await page.evaluate(() => {
        clearInterval(window._healthTimer);
        clearInterval(window._fleetTimer);
        clearInterval(window._activityTimer);
        clearInterval(window._watchdogHeaderTimer);
        clearInterval(window._doctorProbeTimer);
      });
      await expect(page.locator('#operator-truth-banner')).toBeVisible();
      await expect(page.locator('#operator-truth-text')).toContainText('DOCTOR: FAILING');
      await expect(page.locator('#operator-truth-text')).toContainText('service-user');
      await expect(page.locator('#operator-truth-text')).toContainText('cache-age');
      await expect(page.locator('#operator-truth-text')).toContainText('LOGIN AVAILABLE');
      await expect(page.locator('#operator-truth-text')).toContainText('SETUP ATTENTION');
      await expect(page.locator('#operator-truth-text')).toContainText('out-of-contract PVE VM 106');
    });

    await test.step('structured monitoring doctor is rendered, not blank legacy output', async () => {
      await page.evaluate(() => window.fleetTool('monitoring'));
      await page.evaluate(() => window.switchMonitoring('mondoctor'));
      await page.evaluate(() => window.monRunDoctor());
      await expect(page.locator('#mon-doc-out')).toContainText('STATUS: UNHEALTHY');
      await expect(page.locator('#mon-doc-out')).toContainText('service-user');
      await expect(page.locator('#mon-doc-out')).toContainText('cache-age');
    });

    await test.step('watchdog states stay inline, distinct, and never create toast noise', async () => {
      const cases = [
        {
          plan: { status: 501, body: { watchdog_installed: false } },
          text: 'Watchdog: not installed', green: false
        },
        {
          plan: { status: 503, body: { watchdog_down: true } },
          text: 'Watchdog: daemon not reachable', green: false
        },
        {
          plan: { status: 200, body: { status: 'degraded', hosts: 3, errors: 1, pending_count: 0 } },
          text: 'Watchdog: degraded · 3 hosts observed', green: false
        },
        {
          plan: { status: 200, body: { status: 'healthy', hosts: 3, errors: 0, pending_count: 0 } },
          text: 'Watchdog: healthy · 3 hosts observed', green: true
        },
        {
          plan: { abort: true },
          text: 'Watchdog: status unavailable', green: false
        }
      ];
      for (const entry of cases) {
        watchdogPlan = entry.plan;
        await page.evaluate(() => window.refreshWatchdogHeader());
        await expect(page.locator('#watchdog-status')).toContainText(entry.text);
        const visualStyle = await page.locator('#watchdog-status .watchdog-label').getAttribute('style');
        if (entry.green) expect(visualStyle).toContain('var(--green)');
        else expect(visualStyle).not.toContain('var(--green)');
      }
      expect(await page.locator('#toast-container').innerText()).not.toMatch(/watchdog/i);
    });

    await test.step('one resolver merges every state field, cache flag, and structural empty law', async () => {
      const matrix = await page.evaluate(() => {
        if (typeof _resolveProbeTruth !== 'function') throw new Error('real product resolver unavailable');
        const cases = [
          ['health-live', { hosts: [{ state: 'live', status: 'healthy' }], probe_status: 'ok' }, 'health'],
          ['health-recovering', { hosts: [{ state: 'recovering', status: 'healthy' }], probe_status: 'ok' }, 'health'],
          ['health-canonical-hard', { hosts: [{ state: 'live' }], probe_status: 'ok', probe_state: 'auth_failed' }, 'health'],
          ['health-canonical-live-legacy-error', { hosts: [{ state: 'live' }], probe_state: 'live', probe_status: 'error', probe_error: 'new error' }, 'health'],
          ['health-legacy-hard', { hosts: [{ state: 'live' }], probe_status: 'error', probe_state: 'live', probe_reason: 'prior healthy', probe_error: 'new refresh failed' }, 'health'],
          ['health-disk-stale', { hosts: [], probe_state: 'live', probe_status: 'ok', from_disk_cache: true }, 'health'],
          ['health-all-stale', { hosts: [{ state: 'stale', status: 'stale' }], probe_status: 'ok' }, 'health'],
          ['health-warming', { hosts: [], probe_status: 'pending' }, 'health'],
          ['health-empty', { hosts: [] }, 'health'],
          ['fleet-age-stale', { pve_nodes: [{ state: 'live' }], fleet_state: 'live', probe_status: 'ok', stale: true }, 'fleet'],
          ['fleet-all-stale', { pve_nodes: [{ state: 'stale', online: false }], probe_status: 'ok' }, 'fleet'],
          ['fleet-warming', { pve_nodes: [], probe_status: 'loading', _loading: true, stale: true }, 'fleet'],
          ['fleet-empty-live', { pve_nodes: [], fleet_state: 'live', probe_status: 'ok' }, 'fleet'],
          ['fleet-hard', { pve_nodes: [{ state: 'live' }], fleet_state: 'auth_failed', probe_status: 'ok' }, 'fleet']
          ,['fleet-state-only-live', { pve_nodes: [{ state: 'live' }], probe_status: 'ok' }, 'fleet']
          ,['fleet-state-only-recovering', { pve_nodes: [{ state: 'recovering' }], probe_status: 'ok' }, 'fleet']
          ,['fleet-node-hard-over-online', { pve_nodes: [{ state: 'auth_failed', online: true }], probe_status: 'ok' }, 'fleet']
          ,['fleet-node-stale-over-offline', { pve_nodes: [{ state: 'stale', online: false }], probe_status: 'ok' }, 'fleet']
          ,['fleet-online-fallback', { pve_nodes: [{ online: true }], probe_status: 'ok' }, 'fleet']
          ,['fleet-offline-fallback', { pve_nodes: [{ online: false }], probe_status: 'ok' }, 'fleet']
        ];
        return Object.fromEntries(cases.map(([name, payload, kind]) => [name, _resolveProbeTruth(payload, kind)]));
      });
      expect(matrix['health-live'].state).toBe('live');
      expect(matrix['health-recovering'].state).toBe('live');
      expect(matrix['health-canonical-hard']).toMatchObject({ state: 'hard', token: 'auth_failed' });
      expect(matrix['health-legacy-hard']).toMatchObject({ state: 'hard', token: 'error' });
      expect(matrix['health-legacy-hard'].reason).toBe('new refresh failed');
      expect(matrix['health-canonical-live-legacy-error'].state).toBe('hard');
      expect(matrix['health-disk-stale'].state).toBe('stale');
      expect(matrix['health-all-stale'].state).toBe('stale');
      expect(matrix['health-warming'].state).toBe('warming');
      expect(matrix['health-empty']).toMatchObject({ state: 'hard', token: 'empty' });
      expect(matrix['fleet-age-stale'].state).toBe('stale');
      expect(matrix['fleet-all-stale'].state).toBe('stale');
      expect(matrix['fleet-warming'].state).toBe('warming');
      expect(matrix['fleet-empty-live']).toMatchObject({ state: 'hard', token: 'empty' });
      expect(matrix['fleet-hard']).toMatchObject({ state: 'hard', token: 'auth_failed' });
      expect(matrix['fleet-state-only-live'].state).toBe('live');
      expect(matrix['fleet-state-only-recovering'].state).toBe('live');
      expect(matrix['fleet-node-hard-over-online'].state).toBe('hard');
      expect(matrix['fleet-node-stale-over-offline'].state).toBe('stale');
      expect(matrix['fleet-online-fallback'].state).toBe('live');
      expect(matrix['fleet-offline-fallback'].state).toBe('hard');
    });

    await test.step('hard health fails closed while stale and warming remain visible non-green metadata', async () => {
      await page.evaluate(() => {
        window._saveHomeWidgetConfig(['w-fleet-stats']);
        window.showView('home');
        window.loadHome();
      });
      await expect(page.locator('#sse-conn-status')).toHaveCount(1);
      healthPlan = liveHealth;
      await waitForHealthRefresh();
      const stamp = page.locator('#fleet-sec-stats .panel-updated');
      await expect(stamp).toHaveCount(1);
      const successfulReadTitle = await stamp.getAttribute('title');
      expect(successfulReadTitle).toMatch(/^Last successful fetch:/);

      healthPlan = {
        hosts: [{ label: 'pve-hermetic', type: 'pve', state: 'live', status: 'healthy' }],
        probe_status: 'ok', probe_state: 'auth_failed', probe_reason: 'credential rejected'
      };
      await waitForHealthRefresh();
      await waitForHealthRefresh();
      await expect(page.locator('#operator-truth-text')).toContainText('API DEGRADED');
      await expect(page.locator('#operator-truth-text')).toContainText('credential rejected');
      await expect(page.locator('#operator-truth-text')).toContainText('SETUP ATTENTION');
      await expect(page.locator('#operator-truth-text')).toContainText('DOCTOR: FAILING');
      await expect(page.locator('#sse-conn-status')).toHaveText('AUTH FAILED');

      healthPlan = { hosts: [], probe_status: 'ok', probe_state: 'live', from_disk_cache: true };
      await waitForHealthRefresh();
      await expect(page.locator('#operator-truth-text')).not.toContainText('API DEGRADED');
      await expect(page.locator('#sse-conn-status')).toHaveText('STALE');
      await expect(stamp).toHaveAttribute('title', successfulReadTitle);

      healthPlan = { hosts: [], probe_status: 'pending' };
      await waitForHealthRefresh();
      await expect(page.locator('#operator-truth-text')).not.toContainText('API DEGRADED');
      await expect(page.locator('#sse-conn-status')).toHaveText('CACHE WARMING');
      await expect(stamp).toHaveAttribute('title', successfulReadTitle);
    });

    await test.step('fleet empty/hard failures escalate and actual live recovery clears them', async () => {
      fleetPlan = { ...liveFleet, stale: true, age_seconds: 180 };
      await waitForFleetRefresh();
      await expect(page.locator('#operator-truth-text')).not.toContainText('API DEGRADED');
      await expect(page.locator('#sse-conn-status')).toHaveText('STALE');

      fleetPlan = {
        pve_nodes: [], vms: [], physical: [], summary: {},
        probe_status: 'loading', _loading: true, stale: true
      };
      await waitForFleetRefresh();
      await expect(page.locator('#operator-truth-text')).not.toContainText('API DEGRADED');
      await expect(page.locator('#sse-conn-status')).toHaveText('CACHE WARMING');

      fleetPlan = {
        pve_nodes: [{ name: 'pve-hermetic', state: 'auth_failed', online: true }],
        vms: [], physical: [], summary: {}, fleet_state: 'live', probe_status: 'ok',
        probe_error: 'credential rejected'
      };
      await waitForFleetRefresh();
      await waitForFleetRefresh();
      await expect(page.locator('#operator-truth-text')).toContainText('credential rejected');
      await expect(page.locator('#operator-truth-text')).not.toContainText('every PVE node offline');

      fleetPlan = liveFleet;
      await waitForFleetRefresh();
      await expect(page.locator('#operator-truth-text')).not.toContainText('API DEGRADED');

      fleetPlan = {
        pve_nodes: [{ name: 'pve-hermetic', state: 'live', online: true }],
        vms: [], physical: [], summary: {}, fleet_state: 'live', fleet_reason: 'prior fleet healthy', probe_status: 'error',
        probe_error: 'PVE transport failed'
      };
      await waitForFleetRefresh();
      await waitForFleetRefresh();
      await expect(page.locator('#operator-truth-text')).toContainText('API DEGRADED');
      await expect(page.locator('#operator-truth-text')).toContainText('PVE transport failed');

      fleetPlan = {
        pve_nodes: [], vms: [], physical: [], summary: {}, probe_status: 'ok',
        fleet_reason: 'prior fleet healthy'
      };
      await waitForFleetRefresh();
      await waitForFleetRefresh();
      await expect(page.locator('#operator-truth-text')).toContainText('no PVE nodes in payload');
      await expect(page.locator('#operator-truth-text')).not.toContainText('prior fleet healthy');
      await expect(page.locator('#sse-conn-status')).toHaveText('PROBE FAILED');

      fleetPlan = liveFleet;
      healthPlan = liveHealth;
      await waitForFleetRefresh();
      await waitForHealthRefresh();
      await expect(page.locator('#operator-truth-text')).not.toContainText('API DEGRADED');
      await expect(page.locator('#operator-truth-text')).toContainText('DOCTOR: FAILING');
    });

    await test.step('stream badge distinguishes waiting, reconnecting cached, dead, fresh, and stale', async () => {
      await page.evaluate(() => {
        window._lastStreamEventTs = 0;
        window._renderStreamStatus('live');
      });
      await expect(page.locator('#stream-status')).toHaveText('LIVE WAITING');
      await expect(page.locator('#stream-status')).toHaveClass(/s-live/);

      await page.evaluate(() => window._renderStreamStatus('cached'));
      await expect(page.locator('#stream-status')).toHaveText('CACHED');
      await expect(page.locator('#stream-status')).toHaveClass(/s-cached/);

      await page.evaluate(() => window._renderStreamStatus('dead'));
      await expect(page.locator('#stream-status')).toHaveText('STREAM DEAD');
      await expect(page.locator('#stream-status')).toHaveClass(/s-dead/);

      await page.evaluate(() => {
        window._lastStreamEventTs = Date.now() - window.STREAM_STALE_AFTER_MS - 1000;
        window._renderStreamStatus('live');
      });
      await expect(page.locator('#stream-status')).toContainText('LIVE STALE');
      await expect(page.locator('#stream-status')).toHaveClass(/s-cached/);

      await page.evaluate(() => window._markStreamEvent());
      await expect(page.locator('#stream-status')).toContainText('LIVE now');
      await expect(page.locator('#stream-status')).toHaveClass(/s-live/);
    });
  });

  test('H12 terminal behavior owns nonce-bound output, rejection, cleanup, and mutation isolation', async ({ page }) => {
    test.setTimeout(45_000);

    const terminalRequests = [];
    const forbiddenMutationRequests = [];
    page.on('request', request => {
      if (request.method() !== 'POST') return;
      const pathname = new URL(request.url()).pathname;
      if (pathname.startsWith('/api/terminal/')) {
        terminalRequests.push({ method: request.method(), pathname, url: request.url() });
      }
      if (pathname.endsWith('/power') || pathname.endsWith('/destroy') || pathname === '/api/containers/action') {
        forbiddenMutationRequests.push({ method: request.method(), pathname, url: request.url() });
      }
    });

    const terminalBuffer = () => page.evaluate(() => {
      if (!window._termXterm) return '';
      const buffer = window._termXterm.buffer.active;
      const lines = [];
      for (let index = 0; index < buffer.length; index += 1) {
        const line = buffer.getLine(index);
        if (line) lines.push(line.translateToString(true));
      }
      return lines.join('\n');
    });
    const sessionTruth = () => page.evaluate(async () => {
      const response = await fetch('/api/terminal/sessions');
      return { status: response.status, headers: Object.fromEntries(response.headers), body: await response.json() };
    });
    const closeThroughUi = async expectedCloseCount => {
      const responsePromise = page.waitForResponse(response => {
        const request = response.request();
        return request.method() === 'POST' && new URL(response.url()).pathname === '/api/terminal/close';
      });
      await page.locator('#terminal-overlay').getByRole('button', { name: 'CLOSE', exact: true }).click();
      const response = await responsePromise;
      expect(response.status()).toBe(200);
      expect(response.headers()['access-control-allow-origin']).toBeUndefined();
      await expect(page.locator('#terminal-overlay')).toBeHidden();
      expect(terminalRequests.filter(request => request.pathname === '/api/terminal/close')).toHaveLength(expectedCloseCount);
      await expect.poll(async () => (await sessionTruth()).body.count).toBe(0);
    };

    await loginInBrowser(page);
    await page.locator('#nav-items [data-view="fleet"]').click();
    await expect(page.locator('#fleet-view')).toBeVisible();
    await page.locator('#term-type').selectOption('node');
    const target = page.locator('#term-target');
    await expect(target.locator('option[value="192.0.2.10"]')).toHaveCount(1);
    await target.selectOption('192.0.2.10');

    let firstOpen;
    await test.step('valid nonce carries real PTY output and explicit close reaches zero sessions', async () => {
      const openResponsePromise = page.waitForResponse(response => {
        const request = response.request();
        return request.method() === 'POST' && new URL(response.url()).pathname === '/api/terminal/open';
      });
      await page.getByRole('button', { name: /OPEN TERMINAL/ }).click();
      const response = await openResponsePromise;
      expect(response.status()).toBe(200);
      expect(response.headers()['access-control-allow-origin']).toBeUndefined();
      firstOpen = await response.json();
      expect(firstOpen.session).toEqual(expect.any(String));
      expect(firstOpen.session.length).toBeGreaterThan(16);
      expect(firstOpen.ws_nonce).toEqual(expect.any(String));
      expect(firstOpen.ws_nonce.length).toBeGreaterThan(16);
      await expect.poll(() => page.evaluate(() => Boolean(
        window._termSocket && window._termSocket.readyState === WebSocket.OPEN
      ))).toBe(true);
      const terminalPath = new URL(page.url()).pathname;
      expect(terminalPath).toBe('/dashboard/fleet');
      await page.locator('#terminal-overlay').getByRole('button', { name: 'COPY', exact: true }).focus();
      await page.keyboard.press('1');
      await expect.poll(() => new URL(page.url()).pathname).toBe(terminalPath);
      await expect(page.locator('#fleet-view')).toBeVisible();
      await page.locator('#terminal-container').click();
      await page.keyboard.type('h12-output-proof');
      await page.keyboard.press('Enter');
      await expect.poll(terminalBuffer).toContain('h12-output-proof');
      await expect.poll(terminalBuffer).toContain('HERMETIC TERMINAL OUTPUT');
      await expect.poll(() => new URL(page.url()).pathname).toBe(terminalPath);
      await expect(page.locator('#fleet-view')).toBeVisible();
      await expect(page.locator('#home-view')).toBeHidden();

      const active = await sessionTruth();
      expect(active.status).toBe(200);
      expect(active.headers['access-control-allow-origin']).toBeUndefined();
      expect(active.body.count).toBe(1);
      expect(active.body.sessions).toHaveLength(1);
      await closeThroughUi(1);
    });

    let rejectedOpen;
    await page.route('**/api/terminal/open?*', async route => {
      const backendResponse = await route.fetch();
      const actual = await backendResponse.json();
      rejectedOpen = actual;
      const headers = { ...backendResponse.headers() };
      delete headers['content-length'];
      delete headers['content-encoding'];
      await route.fulfill({
        status: backendResponse.status(),
        headers,
        contentType: 'application/json',
        body: JSON.stringify({ ...actual, ws_nonce: `${actual.ws_nonce}-corrupted` })
      });
    });

    await test.step('corrupted nonce fails visibly but authenticated CLOSE still cleans the session', async () => {
      const openResponsePromise = page.waitForResponse(response => {
        const request = response.request();
        return request.method() === 'POST' && new URL(response.url()).pathname === '/api/terminal/open';
      });
      await page.getByRole('button', { name: /OPEN TERMINAL/ }).click();
      const response = await openResponsePromise;
      expect(response.status()).toBe(200);
      expect(response.headers()['access-control-allow-origin']).toBeUndefined();
      const browserPayload = await response.json();
      expect(rejectedOpen.session).toEqual(expect.any(String));
      expect(rejectedOpen.ws_nonce).toEqual(expect.any(String));
      expect(rejectedOpen.session).not.toBe(firstOpen.session);
      expect(rejectedOpen.ws_nonce).not.toBe(firstOpen.ws_nonce);
      expect(browserPayload.session).toBe(rejectedOpen.session);
      expect(browserPayload.ws_nonce).toBe(`${rejectedOpen.ws_nonce}-corrupted`);

      await expect.poll(terminalBuffer).toContain('Connection failed');
      await expect.poll(async () => (await sessionTruth()).body.count).toBe(1);
      await closeThroughUi(2);
    });

    await page.unroute('**/api/terminal/open?*');
    expect(terminalRequests.filter(request => request.pathname === '/api/terminal/open')).toHaveLength(2);
    expect(terminalRequests.filter(request => request.pathname === '/api/terminal/close')).toHaveLength(2);
    expect(forbiddenMutationRequests).toEqual([]);
  });

  test('H13 lab-tool proxy requests keep vault credentials out of browser request surfaces', async ({ page, context }) => {
    test.setTimeout(45_000);

    const appSource = fs.readFileSync(path.resolve(__dirname, '../../freq/data/web/js/app.js'), 'utf8');
    const derivePersistenceRoots = source => {
      const roots = new Set();
      if (/\b(?:localStorage)\s*(?:\.\s*(?:setItem|removeItem|clear)\s*\(|\[[^\]]+\]\s*=)/.test(source)) roots.add('localStorage');
      if (/\b(?:sessionStorage)\s*(?:\.\s*(?:setItem|removeItem|clear)\s*\(|\[[^\]]+\]\s*=)/.test(source)) roots.add('sessionStorage');
      if (/\bdocument\s*(?:\.\s*cookie|\[[^\]]+\])\s*=/.test(source)) roots.add('cookie');
      if (/\bindexedDB\s*\./.test(source)) roots.add('indexedDB');
      if (/\bcaches\s*\./.test(source)) roots.add('caches');
      return [...roots].sort();
    };
    const activePersistenceRoots = derivePersistenceRoots(appSource);
    expect(activePersistenceRoots.length).toBeGreaterThan(0);
    expect(activePersistenceRoots.every(root => F10_PERSISTENCE_ENUMERATOR_IDS.includes(root))).toBe(true);

    const persistenceEnumerators = {
      localStorage: async () => page.evaluate(() => Object.keys(localStorage).sort().map(key => [key, localStorage.getItem(key)])),
      sessionStorage: async () => page.evaluate(() => Object.keys(sessionStorage).sort().map(key => [key, sessionStorage.getItem(key)])),
      cookie: async () => ({
        document: await page.evaluate(() => document.cookie),
        context: (await context.cookies()).map(cookie => ({ name: cookie.name, value: cookie.value }))
      }),
      indexedDB: async () => page.evaluate(async () => {
        if (typeof indexedDB.databases !== 'function') throw new Error('indexedDB.databases is required for F10 enumeration');
        const databases = await indexedDB.databases();
        const result = [];
        for (const row of databases) {
          if (!row.name) continue;
          const database = await new Promise((resolve, reject) => {
            const request = indexedDB.open(row.name);
            request.onerror = () => reject(request.error);
            request.onsuccess = () => resolve(request.result);
          });
          try {
            const stores = [...database.objectStoreNames];
            for (const storeName of stores) {
              const transaction = database.transaction(storeName, 'readonly');
              const store = transaction.objectStore(storeName);
              const [keys, values] = await Promise.all([
                new Promise((resolve, reject) => {
                  const request = store.getAllKeys();
                  request.onerror = () => reject(request.error);
                  request.onsuccess = () => resolve(request.result);
                }),
                new Promise((resolve, reject) => {
                  const request = store.getAll();
                  request.onerror = () => reject(request.error);
                  request.onsuccess = () => resolve(request.result);
                })
              ]);
              result.push({ database: row.name, store: storeName, keys, values });
            }
          } finally {
            database.close();
          }
        }
        return result;
      }),
      caches: async () => page.evaluate(async () => {
        const result = [];
        for (const cacheName of await caches.keys()) {
          const cache = await caches.open(cacheName);
          for (const request of await cache.keys()) {
            const response = await cache.match(request);
            result.push({
              cache: cacheName,
              request: { url: request.url, headers: Object.fromEntries(request.headers.entries()) },
              response: response ? {
                headers: Object.fromEntries(response.headers.entries()),
                body: await response.clone().text()
              } : null
            });
          }
        }
        return result;
      })
    };
    expect(Object.keys(persistenceEnumerators).sort()).toEqual([...F10_PERSISTENCE_ENUMERATOR_IDS].sort());
    const activeEnumerators = Object.fromEntries(activePersistenceRoots.map(root => [root, persistenceEnumerators[root]]));
    expect(Object.keys(activeEnumerators).sort()).toEqual(activePersistenceRoots);

    await loginInBrowser(page);

    const networkRequests = [];
    await page.route('**/api/lab-tool/proxy?*', async route => {
      const request = route.request();
      networkRequests.push({
        url: request.url(),
        method: request.method(),
        headers: request.headers(),
        postData: request.postData()
      });
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ ok: true, message: 'H13 proxy response' })
      });
    });

    const configResponseSecret = 'H13_CONFIG_RESPONSE_SECRET_MUST_NOT_POPULATE_DOM';
    const configRequests = [];
    await page.route('**/api/lab-tool/config?*', async route => {
      configRequests.push(route.request().url());
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          host: 'h13-configured-host.invalid',
          key_set: true,
          key: configResponseSecret
        })
      });
    });

    await test.step('saved config projects presence, leaves the key field blank, and auto-connects', async () => {
      const observation = await page.evaluate(async secret => {
        const prefix = 'h13-config-';
        const install = (suffix, type) => {
          const input = document.createElement('input');
          input.id = `${prefix}${suffix}`;
          if (type) input.type = type;
          document.body.appendChild(input);
          return input;
        };
        const host = install('lt-host');
        const key = install('lt-key', 'password');
        const status = document.createElement('div');
        status.id = `${prefix}lt-conn-status`;
        document.body.appendChild(status);
        LAB_TOOLS.push({
          id: 'h13-config-owner',
          name: 'H13 config owner',
          connectEndpoint: 'status',
          refreshInterval: 0
        });
        try {
          await ltLoad('h13-config-owner', prefix);
          return {
            host: host.value,
            key: key.value,
            keySet: key.dataset.keySet,
            status: status.textContent,
            secretInDom: document.documentElement.innerHTML.includes(secret)
          };
        } finally {
          LAB_TOOLS = LAB_TOOLS.filter(tool => tool.id !== 'h13-config-owner');
          host.remove();
          key.remove();
          status.remove();
        }
      }, configResponseSecret);
      expect(observation).toEqual({
        host: 'h13-configured-host.invalid',
        key: '',
        keySet: 'true',
        status: 'Connected',
        secretInDom: false
      });
      expect(configRequests).toHaveLength(1);
      expect(new URL(configRequests[0]).searchParams.get('tool')).toBe('h13-config-owner');
      expect(networkRequests).toHaveLength(1);
      const proxyUrl = new URL(networkRequests[0].url);
      expect(Object.fromEntries(proxyUrl.searchParams.entries())).toEqual({
        tool: 'h13-config-owner',
        endpoint: 'status'
      });
      expect(JSON.stringify(networkRequests[0])).not.toContain(configResponseSecret);
    });

    await test.step('an unsaved key remains a save-only value and dispatches no proxy request', async () => {
      const observation = await page.evaluate(() => {
        const prefix = 'h13-unsaved-';
        const host = document.createElement('input');
        host.id = `${prefix}lt-host`;
        host.value = 'h13-unsaved-host.invalid';
        document.body.appendChild(host);
        const key = document.createElement('input');
        key.id = `${prefix}lt-key`;
        key.type = 'password';
        key.value = 'H13_PENDING_REPLACEMENT_KEY';
        key.dataset.keySet = 'false';
        document.body.appendChild(key);
        const status = document.createElement('div');
        status.id = `${prefix}lt-conn-status`;
        document.body.appendChild(status);
        try {
          ltConnect('gwipe', prefix);
          return { key: key.value, keySet: key.dataset.keySet, status: status.textContent };
        } finally {
          host.remove();
          key.remove();
          status.remove();
        }
      });
      expect(observation).toEqual({
        key: 'H13_PENDING_REPLACEMENT_KEY',
        keySet: 'false',
        status: 'Save the API key before connecting'
      });
      expect(networkRequests).toHaveLength(1);
    });
    await page.unroute('**/api/lab-tool/config?*');
    networkRequests.length = 0;

    const cdp = await context.newCDPSession(page);
    await cdp.send('Debugger.enable');
    const authFetchObject = await cdp.send('Runtime.evaluate', { expression: '_authFetch' });
    expect(authFetchObject.result.objectId).toEqual(expect.any(String));
    const breakpoint = await cdp.send('Debugger.setBreakpointOnFunctionCall', {
      objectId: authFetchObject.result.objectId
    });
    const authFetchEntries = [];
    let debuggerFailure = null;
    cdp.on('Debugger.paused', async event => {
      try {
        const callFrameId = event.callFrames[0].callFrameId;
        const [urlResult, optionsResult] = await Promise.all([
          cdp.send('Debugger.evaluateOnCallFrame', { callFrameId, expression: 'url', returnByValue: true }),
          cdp.send('Debugger.evaluateOnCallFrame', { callFrameId, expression: 'opts', returnByValue: true })
        ]);
        const url = urlResult.result.value;
        if (typeof url === 'string' && url.includes('/api/lab-tool/proxy')) {
          authFetchEntries.push({ url, options: optionsResult.result.value || null });
        }
      } catch (error) {
        debuggerFailure = String(error);
      } finally {
        await cdp.send('Debugger.resume').catch(error => { debuggerFailure = debuggerFailure || String(error); });
      }
    });

    const installInputs = async (prefix, host, key) => page.evaluate(({ prefix, host, key }) => {
      window.__h13InputReads = window.__h13InputReads || {};
      const nativeValue = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value');
      const install = (suffix, value, label) => {
        const input = document.createElement('input');
        input.id = `${prefix}${suffix}`;
        nativeValue.set.call(input, value);
        Object.defineProperty(input, 'value', {
          configurable: true,
          get() {
            const stack = new Error().stack || '';
            if (!stack.includes('Streamer.captureSnapshot')) {
              window.__h13InputReads[prefix][label] += 1;
            }
            return nativeValue.get.call(this);
          },
          set(next) { nativeValue.set.call(this, next); }
        });
        document.body.appendChild(input);
      };
      document.getElementById(`${prefix}lt-host`)?.remove();
      document.getElementById(`${prefix}lt-key`)?.remove();
      window.__h13InputReads[prefix] = { host: 0, key: 0 };
      install('lt-host', host, 'host');
      install('lt-key', key, 'key');
    }, { prefix, host, key });

    const inputReads = prefix => page.evaluate(prefix => ({ ...window.__h13InputReads[prefix] }), prefix);
    const collectPersistence = async () => {
      const result = {};
      for (const [root, enumerate] of Object.entries(activeEnumerators)) result[root] = await enumerate();
      return result;
    };
    const browserSurfaces = async () => page.evaluate(() => ({
      documentUrl: document.URL,
      historyState: history.state,
      performanceResources: performance.getEntriesByType('resource').map(entry => entry.name)
    }));
    const encodedForms = value => {
      const encoded = encodeURIComponent(value);
      return [...new Set([value, encoded, encoded.toLowerCase()])];
    };
    const leakLabels = (labelled, sentinels) => {
      const needles = sentinels.flatMap(encodedForms);
      return Object.entries(labelled)
        .filter(([, value]) => needles.some(needle => JSON.stringify(value).includes(needle)))
        .map(([label]) => label)
        .sort();
    };
    const waitForCapture = async (networkBefore, cdpBefore) => {
      await expect.poll(() => networkRequests.length).toBe(networkBefore + 1);
      await expect.poll(() => authFetchEntries.length).toBe(cdpBefore + 1);
      expect(debuggerFailure).toBeNull();
    };

    const invocationAdapters = {
      '_ltProxy#1/direct': async row => {
        await page.evaluate(() => new Promise(resolve => {
          window.__h13TrapReads = { host: 0, key: 0 };
          _ltProxy('scope-probe', 'GET', 'status', resolve);
        }));
        return page.evaluate(() => ({ ...window.__h13TrapReads }));
      },
      'ltAction#1/confirm-absent': async row => {
        await installInputs(row.prefix, row.host, row.key);
        await page.evaluate(prefix => {
          window.__h13InputReads[prefix] = { host: 0, key: 0 };
          ltAction('gwipe', 'status', prefix, false);
        }, row.prefix);
        return inputReads(row.prefix);
      },
      'ltAction#1/confirm-YES': async row => {
        await installInputs(row.prefix, row.host, row.key);
        await page.evaluate(prefix => {
          window.__h13InputReads[prefix] = { host: 0, key: 0 };
          ltAction('gwipe', 'status', prefix, true);
        }, row.prefix);
        return inputReads(row.prefix);
      },
      'gwipeBayWipe#1/confirmAction-accepted': async row => {
        await installInputs(row.prefix, row.host, row.key);
        await page.evaluate(prefix => {
          window.__h13InputReads[prefix] = { host: 0, key: 0 };
          gwipeBayWipe('sda', prefix);
        }, row.prefix);
        await expect.poll(() => page.evaluate(() => {
          const modal = document.getElementById('modal-container');
          return Boolean(modal && getComputedStyle(modal).display !== 'none');
        })).toBe(true);
        await page.evaluate(() => document.getElementById('modal-confirm-btn').click());
        return inputReads(row.prefix);
      }
    };
    expect(Object.keys(invocationAdapters).sort()).toEqual([...F10_PROXY_INVOCATION_IDS].sort());

    await test.step('gwipeBayWipe#1 cancel is zero-read and zero-request', async () => {
      const row = {
        prefix: 'h13-cancel-',
        host: 'h13-cancel-host.example/?#&',
        key: 'h13-cancel-key/%?#&'
      };
      await installInputs(row.prefix, row.host, row.key);
      const networkBefore = networkRequests.length;
      const cdpBefore = authFetchEntries.length;
      await page.evaluate(prefix => {
        window.__h13InputReads[prefix] = { host: 0, key: 0 };
        gwipeBayWipe('sda', prefix);
      }, row.prefix);
      await expect.poll(() => page.evaluate(() => {
        const modal = document.getElementById('modal-container');
        return Boolean(modal && getComputedStyle(modal).display !== 'none');
      })).toBe(true);
      await page.evaluate(() => {
        const cancel = document.querySelector('#modal-container .modal-actions .btn:not(#modal-confirm-btn)');
        if (!cancel || cancel.textContent !== 'Cancel') throw new Error('H13 cancel control is missing');
        cancel.click();
      });
      await page.waitForTimeout(50);
      expect(networkRequests).toHaveLength(networkBefore);
      expect(authFetchEntries).toHaveLength(cdpBefore);
      expect(await inputReads(row.prefix)).toEqual({ host: 0, key: 0 });
    });

    const rows = [
      {
        id: '_ltProxy#1/direct', prefix: 'h13-proxy-',
        host: 'h13-proxy-host.example/?#&', key: 'h13-proxy-key/%?#&',
        expected: { tool: 'scope-probe', endpoint: 'status' }
      },
      {
        id: 'ltAction#1/confirm-absent', prefix: 'h13-action-no-',
        host: 'h13-action-no-host.example/?#&', key: 'h13-action-no-key/%?#&',
        expected: { tool: 'gwipe', method: 'POST', endpoint: 'status' }
      },
      {
        id: 'ltAction#1/confirm-YES', prefix: 'h13-action-yes-',
        host: 'h13-action-yes-host.example/?#&', key: 'h13-action-yes-key/%?#&',
        expected: { tool: 'gwipe', method: 'POST', endpoint: 'status', confirm: 'YES' }
      },
      {
        id: 'gwipeBayWipe#1/confirmAction-accepted', prefix: 'h13-wipe-',
        host: 'h13-wipe-host.example/?#&', key: 'h13-wipe-key/%?#&',
        expected: { tool: 'gwipe', method: 'POST', endpoint: 'bays/sda/wipe', confirm: 'YES' }
      }
    ];

    for (const row of rows) {
      await test.step(row.id, async () => {
        const networkBefore = networkRequests.length;
        const cdpBefore = authFetchEntries.length;
        const reads = await invocationAdapters[row.id](row);
        await waitForCapture(networkBefore, cdpBefore);
        const network = networkRequests[networkBefore];
        const entry = authFetchEntries[cdpBefore];
        const url = new URL(network.url);
        const entryUrl = new URL(entry.url, page.url());
        const persistence = await collectPersistence();
        const browser = await browserSurfaces();
        const leaks = leakLabels({
          cdpUrl: entry.url,
          cdpOptions: entry.options,
          networkUrl: network.url,
          networkHeaders: network.headers,
          networkBody: network.postData,
          persistence,
          browser
        }, [row.host, row.key]);

        expect.soft(reads, `${row.id} credential value reads`).toEqual({ host: 0, key: 0 });
        expect.soft(leaks, `${row.id} credential surface leaks`).toEqual([]);
        expect.soft(network.method, `${row.id} method`).toBe('GET');
        expect.soft(url.pathname, `${row.id} path`).toBe('/api/lab-tool/proxy');
        expect.soft(entryUrl.pathname, `${row.id} CDP path`).toBe('/api/lab-tool/proxy');
        expect.soft(Object.fromEntries(url.searchParams.entries()), `${row.id} query`).toEqual(row.expected);
        expect.soft(url.searchParams.getAll('host'), `${row.id} host query`).toEqual([]);
        expect.soft(url.searchParams.getAll('key'), `${row.id} key query`).toEqual([]);
        expect.soft(entryUrl.hash, `${row.id} CDP fragment`).toBe('');
        expect.soft(url.hash, `${row.id} network fragment`).toBe('');

        const forbiddenApplicationHeaders = new Set(['key', 'x-api-key', 'x-lab-host', 'x-lab-key']);
        for (const [name, value] of Object.entries(network.headers)) {
          const lower = name.toLowerCase();
          if (lower === 'host') {
            expect.soft(value, `${row.id} standard Host authority`).toBe(url.host);
          } else {
            expect.soft(forbiddenApplicationHeaders.has(lower), `${row.id} application header ${name}`).toBe(false);
          }
        }
      });
    }

    expect(networkRequests).toHaveLength(4);
    expect(authFetchEntries).toHaveLength(4);
    expect(debuggerFailure).toBeNull();
    await cdp.send('Debugger.removeBreakpoint', { breakpointId: breakpoint.breakpointId });
    await cdp.detach();
  });

});


test('H14 template visibility follows metadata across topology, VM lists and counts', async ({ page }) => {
  const vms = [
    { vmid: 9050, name: 'ordinary-high', category: 'prod', template: false },
    { vmid: 120, name: 'template-low', category: 'templates' },
    { vmid: 121, name: 'template-flag', template: 1 },
    { vmid: 9200, name: 'unknown-high' },
    { vmid: 120, name: 'ordinary-other-estate', category: 'templates', template: 0, node: 'other-node' }
  ].map(v => ({ node: 'fixture-node', status: 'running', cpu: 2, ram_mb: 2048, ...v }));
  const pveNodes = ['fixture-node', 'other-node'].map(name => ({ name, online: true, state: 'live' }));
  const overview = { vms, pve_nodes: pveNodes, physical: [], summary: {}, probe_status: 'ok' };
  const topology = {
    pve_count: 2,
    nodes: [
      ...pveNodes.map(n => ({ id: n.name, type: 'pve', label: n.name })),
      ...vms.map(v => ({ ...v, id: v.node + ':vm:' + v.vmid, type: 'vm', label: v.name }))
    ],
    links: vms.map(v => ({ source: v.node, target: v.node + ':vm:' + v.vmid }))
  };
  await page.route('**/api/vms', route => route.fulfill({ json: { vms } }));
  await page.route('**/api/fleet/overview', route => route.fulfill({ json: overview }));
  await page.route('**/api/topology', route => route.fulfill({ json: topology }));
  await loginInBrowser(page);
  await page.evaluate(() => switchView('fleet'));
  await expect(page.locator('#metrics-cards')).toContainText('ordinary-high');
  for (const show of [false, true, false]) {
    await page.evaluate(({ show, overview }) => {
      saveSetting('showTemplates', show);
      _initFleetData(overview);
      _renderFleetData(overview, { hosts: [] }, { containers: [] }, { containers: [] }, false);
      loadTopology();
      // Mount the real overview widget through its registry loader.
      let mount = document.getElementById('h14-overview');
      if (!mount) { mount = document.createElement('div'); mount.id = 'h14-overview'; document.body.appendChild(mount); }
      WIDGET_REGISTRY.find(w => w.id === 'w-fleet-overview').loader(mount);
      let stats = document.getElementById('h14-stats');
      if (!stats) { stats = document.createElement('div'); stats.id = 'h14-stats'; document.body.appendChild(stats); }
      WIDGET_REGISTRY.find(w => w.id === 'w-fleet-stats').loader(stats);
    }, { show, overview });
    await expect(page.locator('#topo-info')).toHaveText(`2 PVE nodes, ${show ? 5 : 3} VMs`);
    for (const name of ['ordinary-high', 'unknown-high', 'ordinary-other-estate']) {
      await expect(page.locator('#topo-svg')).toContainText(name);
      await expect(page.locator('#metrics-cards')).toContainText(name);
    }
    for (const name of ['template-low', 'template-flag']) {
      for (const selector of ['#topo-svg', '#metrics-cards']) {
        if (show) await expect(page.locator(selector)).toContainText(name);
        else await expect(page.locator(selector)).not.toContainText(name);
      }
    }
    await expect(page.locator('#h14-overview #hw-vms')).toContainText(`${show ? 5 : 3} VMs`);
    await expect(page.locator('#h14-stats .st:nth-child(5) .stat-big-green')).toHaveText(show ? '5/5' : '3/3');
    const names = await page.evaluate(() => PROD_VMS.map(v => v.label).sort());
    expect(names).toEqual(vms.filter(v => show || !['template-low', 'template-flag'].includes(v.name)).map(v => v.name).sort());
  }
});


test('H15 missing presentation asset reports a visible startup failure', async ({ page }) => {
  const failures = [];
  page.on('pageerror', error => failures.push(error.message));
  await page.route('**/static/js/presentation.js*', route => route.abort());
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await expect(page.getByRole('alert').filter({ hasText: 'Dashboard assets could not load.' })).toBeVisible();
  expect(failures).toContain('Required presentation asset is unavailable');
});


test('H16 config backup availability never claims an artifact from connectivity or config reads', async ({ page }) => {
  let connectivity = 0;
  let configReads = 0;
  const downloads = [];
  page.on('download', download => downloads.push(download.suggestedFilename()));
  await page.route('**/api/fleet/connectivity', route => {
    connectivity++;
    return route.fulfill({ json: { reachable: 3, total: 3 } });
  });
  await page.route('**/api/config', route => {
    configReads++;
    return route.fulfill({ json: { hosts: [], marker: 'H16_NOT_A_BACKUP_ARTIFACT' } });
  });
  await loginInBrowser(page);
  await page.evaluate(() => switchView('system'));
  await page.waitForLoadState('networkidle');
  const beforeConnectivity = connectivity;
  await page.locator('[data-action="runBackup"]').click();
  await expect(page.locator('#backup-c')).toContainText('No backup was created.');
  await expect(page.locator('#backup-c')).toContainText('not implemented');
  await expect(page.locator('#toast-container')).not.toContainText('Backup snapshot complete');
  expect(connectivity).toBe(beforeConnectivity);
  await page.evaluate(() => { switchView('fleet'); fleetTool('backup'); });
  await page.locator('.bk-tab[data-bktab="bkexport"]').click();
  await expect(page.locator('#bk-exp-out')).toContainText('No backup was created.');
  await expect(page.locator('#bk-form').getByRole('button', { name: 'EXPORT UNAVAILABLE' })).toBeDisabled();
  const beforeConfig = configReads;
  // A stale caller cannot bypass the visible unavailable state.
  await page.evaluate(() => bkExportConfig());
  await expect(page.locator('#bk-exp-out')).not.toContainText('H16_NOT_A_BACKUP_ARTIFACT');
  await expect(page.locator('#bk-exp-out')).toContainText('users, vault secrets or guest disks');
  expect(configReads).toBe(beforeConfig);
  expect(downloads).toEqual([]);
});


test('H17 generated tool tabs navigate with mouse and keyboard under CSP', async ({ page }) => {
  test.setTimeout(90_000);
  await loginInBrowser(page);
  await page.evaluate(() => switchView('fleet'));
  const writes = [];
  page.on('request', request => {
    const pathname = new URL(request.url()).pathname;
    if (!['GET', 'HEAD'].includes(request.method()) && pathname !== '/api/ui/event') writes.push(pathname);
  });
  const groups = [
    ['vmmgmt', 'vm', ['vmlist', 'vmcreate', 'vmclone', 'vmmigrate', 'vmresize', 'vmadddisk', 'vmtag', 'vmrollback']],
    ['monitoring', 'mon', ['monhealth', 'mondoctor', 'monjournal', 'monwatch']],
    ['network', 'net', ['netvlan', 'netdns', 'netping', 'netports']],
    ['backup', 'bk', ['bkstatus', 'bkschedule', 'bksnapshot', 'bkexport', 'bkrestore']],
    ['usermgmt', 'um', ['newuser', 'passwd', 'sshkey', 'promote']],
    ['fleetops', 'fo', ['deepscan', 'ntp', 'updates', 'sshd', 'exec']]
  ];
  for (const [tool, prefix, ids] of groups) {
    await page.evaluate(tool => fleetTool(tool), tool);
    const buttons = page.locator(`.${prefix}-tab`);
    expect(await buttons.evaluateAll((els, prefix) => els.map(el => el.getAttribute(`data-${prefix}tab`)), prefix)).toEqual(ids);
    for (let step = 0; step < ids.length; step++) {
      const index = (step + 1) % ids.length;
      const button = buttons.nth(index);
      if (index % 2) { await button.focus(); await button.press('Enter'); }
      else await button.click();
      await expect(button).toHaveClass(/active-view/);
      await expect(page.locator(`.${prefix}-tab.active-view`)).toHaveCount(1);
      await expect(page.locator(`#${prefix}-subtitle`)).toHaveText(ids[index] === 'newuser' ? 'NEW FLEET USER' : await button.innerText());
      await expect(page.locator(`#${prefix}-form`)).not.toBeEmpty();
      expect(await button.getAttribute('onclick')).toBeNull();
      expect(await button.getAttribute('data-legacy-onclick')).toBeNull();
    }
  }
  const last = page.locator('.fo-tab').last();
  await last.click();
  await last.evaluate(el => {
    window.__h17Called = 0;
    window.__h17Trap = () => { window.__h17Called++; };
    el.dataset.tabGroup = '__h17Trap';
    el.dataset.tabId = 'exec';
  });
  await last.click();
  expect(await page.evaluate(() => window.__h17Called)).toBe(0);
  await expect(page.locator('#fo-subtitle')).toHaveText('FLEET EXEC');
  await last.evaluate(el => { el.dataset.tabGroup = 'switchFleetOps'; el.dataset.tabId = 'vmcreate'; });
  await last.press('Enter');
  await expect(page.locator('#fo-subtitle')).toHaveText('FLEET EXEC');
  expect(writes).toEqual([]);
});

const { test, expect } = require('@playwright/test');

const USER = process.env.PVE_FREQ_USER;
const PASS = process.env.PVE_FREQ_PASS;

function requireLiveCredentials() {
  test.skip(!USER || !PASS, 'Set PVE_FREQ_USER and PVE_FREQ_PASS for live dashboard UI polish tests.');
}

async function login(page) {
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await page.locator('#login-user').fill(USER);
  await page.locator('#login-pass').fill(PASS);
  await page.locator('#login-form').evaluate(form => form.requestSubmit());
  await page.locator('#login-overlay').waitFor({ state: 'hidden', timeout: 20_000 });
}

async function openFleet(page) {
  await page.getByRole('button', { name: 'FLEET', exact: true }).click();
  await page.locator('#metrics-cards .pve-group').first().waitFor({ timeout: 30_000 });
}

async function openFleetMobile(page) {
  const fleetButton = page.getByRole('button', { name: 'FLEET', exact: true });
  if (!(await fleetButton.isVisible().catch(() => false))) {
    await page.locator('.mobile-menu-btn').click();
  }
  await fleetButton.click();
  await page.locator('#metrics-cards .pve-group').first().waitFor({ timeout: 30_000 });
}

test.describe('UI polish regressions', () => {
  test('mobile login card stays inside the viewport', async ({ browser }) => {
    requireLiveCredentials();
    const context = await browser.newContext({ viewport: { width: 390, height: 844 }, ignoreHTTPSErrors: true });
    const page = await context.newPage();
    await page.goto('/', { waitUntil: 'networkidle' });

    const geom = await page.locator('.login-card').evaluate((el) => {
      const r = el.getBoundingClientRect();
      return {
        left: r.left,
        right: r.right,
        width: r.width,
        viewport: window.innerWidth,
      };
    });

    expect(geom.left).toBeGreaterThanOrEqual(0);
    expect(geom.right).toBeLessThanOrEqual(geom.viewport);
    expect(geom.width).toBeGreaterThan(300);
    await context.close();
  });

  test('Fleet keeps LXC grouped with PVE nodes and sparklines pinned', async ({ page }) => {
    requireLiveCredentials();
    await login(page);
    await openFleet(page);

    await expect(page.locator('#fleet-sec-ct')).toBeHidden();
    await page.reload({ waitUntil: 'domcontentloaded' });
    await page.locator('#login-overlay').waitFor({ state: 'hidden', timeout: 20_000 }).catch(() => {});
    await openFleet(page);
    await page.waitForTimeout(1_000);
    await expect(page.locator('#fleet-sec-ct')).toBeHidden();

    await expect(page.locator('.sparkline-row canvas').first()).toBeVisible({ timeout: 20_000 });
    await page.evaluate(() => {
      for (let i = 0; i < 8; i += 1) {
        if (window._renderSparklines) window._renderSparklines();
      }
    });

    const canvasHeights = await page.locator('.sparkline-row canvas').evaluateAll((els) =>
      els.map((el) => ({
        rectHeight: el.getBoundingClientRect().height,
        styleHeight: el.style.height,
      }))
    );
    expect(canvasHeights.length).toBeGreaterThan(0);
    for (const h of canvasHeights) {
      expect(h.rectHeight).toBeLessThanOrEqual(30);
      expect(h.styleHeight).toBe('28px');
    }

    const synthetic = await page.evaluate(() => {
      const fo = window._fleetCache && window._fleetCache.fo;
      const hd = window._fleetCache && window._fleetCache.hd;
      if (!fo || !fo.pve_nodes || !fo.pve_nodes.length || !window._renderFleetData) {
        return { ok: false, reason: 'fleet cache/render unavailable' };
      }
      const node = fo.pve_nodes[0].name;
      window._renderFleetData(fo, hd, null, {
        containers: [{
          ctid: 7777,
          name: 'ui-lxc-proof',
          status: 'running',
          node,
          cpu: 0.05,
          maxcpu: 2,
          mem: 268435456,
          maxmem: 1073741824,
          mem_pct: 25,
          disk: 0,
          maxdisk: 8589934592,
          uptime: 60,
          tags: 'ui-test',
          template: 0,
        }],
      });
      return {
        ok: true,
        ctCards: document.querySelectorAll('.ct-workload-card').length,
        cardText: document.querySelector('.ct-workload-card')?.innerText || '',
      };
    });

    expect(synthetic.ok, synthetic.reason).toBe(true);
    expect(synthetic.ctCards).toBe(1);
    expect(synthetic.cardText).toContain('LXC 7777');
    expect(synthetic.cardText).toContain('TERM');
  });

  test('mobile global nav remains available after login', async ({ browser }) => {
    requireLiveCredentials();
    const context = await browser.newContext({ viewport: { width: 390, height: 844 }, ignoreHTTPSErrors: true });
    const page = await context.newPage();
    await login(page);

    await expect(page.locator('.mobile-menu-btn')).toBeVisible();
    await page.locator('.mobile-menu-btn').click();
    await expect(page.locator('#nav-items')).toBeVisible();
    await expect(page.getByRole('button', { name: 'FLEET', exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: 'SYSTEM', exact: true })).toBeVisible();

    const header = await page.evaluate(() => {
      const title = document.querySelector('#page-title')?.getBoundingClientRect();
      const stream = document.querySelector('#stream-status')?.getBoundingClientRect();
      const watchdog = document.querySelector('#watchdog-status')?.getBoundingClientRect();
      const user = document.querySelector('#header-user-btn')?.getBoundingClientRect();
      if (!title || !stream || !watchdog || !user) return { overlap: false, viewport: window.innerWidth };
      const overlaps = (a, b) => !(a.right <= b.left || b.right <= a.left || a.bottom <= b.top || b.bottom <= a.top);
      return {
        viewport: window.innerWidth,
        overlap: overlaps(title, stream) || overlaps(title, watchdog) || overlaps(watchdog, user) || overlaps(stream, user),
        titleTop: title.top,
        streamTop: stream.top,
        watchdogRight: watchdog.right,
        streamRight: stream.right,
        userRight: user.right,
      };
    });
    expect(header.overlap).toBe(false);
    expect(header.watchdogRight).toBeLessThanOrEqual(header.viewport);
    expect(header.streamRight).toBeLessThanOrEqual(header.viewport);
    expect(header.userRight).toBeLessThanOrEqual(header.viewport);

    await context.close();
  });

  test('mobile tables and controls stay inside dark shell', async ({ browser }) => {
    requireLiveCredentials();
    const context = await browser.newContext({ viewport: { width: 390, height: 844 }, ignoreHTTPSErrors: true });
    const page = await context.newPage();
    await login(page);

    const geom = await page.evaluate(() => {
      const host = document.createElement('div');
      host.className = 'section-body ui-polish-proof';
      host.innerHTML = `
        <input id="ui-proof-input" placeholder="proof">
        <select id="ui-proof-select"><option>proof</option></select>
        <table id="ui-proof-table"><thead><tr>
          <th>Very Long Header One</th><th>Very Long Header Two</th><th>Very Long Header Three</th>
        </tr></thead><tbody><tr>
          <td>alpha-alpha-alpha-alpha</td><td>beta-beta-beta-beta</td><td>gamma-gamma-gamma-gamma</td>
        </tr></tbody></table>`;
      document.querySelector('#home-view').prepend(host);
      if (window._enhanceResponsiveTables) window._enhanceResponsiveTables(host);
      const table = document.querySelector('#ui-proof-table');
      const bare = document.createElement('table');
      bare.id = 'ui-proof-bare-table';
      bare.innerHTML = '<tr><th>Host</th><th>Watts</th><th>Description</th></tr><tr><td>nexus</td><td>125W</td><td>Long generated settings/plugin value</td></tr>';
      host.appendChild(bare);
      const input = document.querySelector('#ui-proof-input');
      const select = document.querySelector('#ui-proof-select');
      if (window._enhanceResponsiveTables) window._enhanceResponsiveTables(host);
      const tr = table.getBoundingClientRect();
      const br = bare.getBoundingClientRect();
      const ir = input.getBoundingClientRect();
      const sr = select.getBoundingClientRect();
      const inputStyle = getComputedStyle(input);
      const selectStyle = getComputedStyle(select);
      return {
        viewport: window.innerWidth,
        tableLeft: tr.left,
        tableRight: tr.right,
        inputRight: ir.right,
        selectRight: sr.right,
        inputBg: inputStyle.backgroundColor,
        selectBg: selectStyle.backgroundColor,
        inputColor: inputStyle.color,
        tableClassed: table.classList.contains('responsive-table'),
        firstLabel: table.querySelector('td')?.getAttribute('data-label') || '',
        bareRight: br.right,
        bareClassed: bare.classList.contains('responsive-table'),
        bareLabel: bare.querySelector('td')?.getAttribute('data-label') || '',
      };
    });

    expect(geom.tableLeft).toBeGreaterThanOrEqual(0);
    expect(geom.tableRight).toBeLessThanOrEqual(geom.viewport);
    expect(geom.inputRight).toBeLessThanOrEqual(geom.viewport);
    expect(geom.selectRight).toBeLessThanOrEqual(geom.viewport);
    expect(geom.inputBg).not.toBe('rgb(255, 255, 255)');
    expect(geom.selectBg).not.toBe('rgb(255, 255, 255)');
    expect(geom.inputColor).not.toBe('rgb(0, 0, 0)');
    expect(geom.tableClassed).toBe(true);
    expect(geom.firstLabel).toBe('Very Long Header One');
    expect(geom.bareRight).toBeLessThanOrEqual(geom.viewport);
    expect(geom.bareClassed).toBe(true);
    expect(geom.bareLabel).toBe('Host');

    await context.close();
  });

  test('Fleet optional enrichment degrades without stale loading rows', async ({ page }) => {
    requireLiveCredentials();
    const consoleErrors = [];
    page.on('console', msg => {
      if (msg.type() === 'error') consoleErrors.push(msg.text());
    });
    await page.route('**/api/fleet/ntp', route => route.fulfill({ status: 200, contentType: 'application/json', body: '{}' }));
    await page.route('**/api/fleet/updates', route => route.fulfill({ status: 200, contentType: 'application/json', body: '{}' }));
    await page.route('**/api/infra/quick', route => route.fulfill({ status: 200, contentType: 'application/json', body: '{}' }));

    await login(page);
    await openFleet(page);
    await page.waitForTimeout(500);

    await expect(page.locator('#metrics-cards')).not.toContainText('Loading...');
    await expect(page.locator('#metrics-cards')).toContainText(/PENDING|UNAVAILABLE|PROXMOX NODES/);
    expect(consoleErrors.filter(text => /forEach|_renderFleetData error|infra quick error/.test(text))).toEqual([]);
  });
});

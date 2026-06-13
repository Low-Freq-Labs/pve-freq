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
});

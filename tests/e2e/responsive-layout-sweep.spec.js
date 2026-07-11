const { test, expect } = require('@playwright/test');

const USER = process.env.PVE_FREQ_USER;
const PASS = process.env.PVE_FREQ_PASS;

function requireLiveCredentials() {
  test.skip(!USER || !PASS, 'Set PVE_FREQ_USER and PVE_FREQ_PASS for live dashboard responsive sweep.');
}

const VIEWPORTS = [
  { name: 'desktop-1440x1000', width: 1440, height: 1000 },
  { name: 'wide-short-1980x900', width: 1980, height: 900 },
  { name: 'wide-1920x1080', width: 1920, height: 1080 },
  { name: 'laptop-1366x768', width: 1366, height: 768 },
  { name: 'narrow-desktop-1100x820', width: 1100, height: 820 },
  { name: 'tablet-820x1180', width: 820, height: 1180 },
  { name: 'phone-390x844', width: 390, height: 844 }
];

const MAIN_VIEWS = ['HOME', 'FLEET', 'DOCKER', 'MEDIA', 'SECURITY', 'SYSTEM', 'LAB', 'SETTINGS'];
const FLEET_SUBVIEWS = ['topology', 'capacity', 'network', 'fleet'];
const DOCKER_SUBVIEWS = ['all', 'registry', 'compose', 'fleet-inv', 'services'];
const SECURITY_VIEWS = ['sec-hardening', 'sec-access', 'sec-vault', 'sec-compliance', 'firewall', 'certs', 'vpn', 'security'];
const SYSTEM_VIEWS = ['playbooks', 'gitops', 'chaos', 'dns', 'dr', 'incidents', 'metrics', 'automation', 'plugins', 'tools'];

async function login(page) {
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await page.locator('#login-user').fill(USER);
  await page.locator('#login-pass').fill(PASS);
  await page.locator('#login-form').evaluate(form => form.requestSubmit());
  await page.locator('#login-overlay').waitFor({ state: 'hidden', timeout: 20_000 });
}

async function clickMainView(page, name) {
  const viewMap = {
    HOME: 'home',
    FLEET: 'fleet',
    DOCKER: 'docker',
    MEDIA: 'media',
    SECURITY: 'security',
    SYSTEM: 'tools',
    LAB: 'lab',
    SETTINGS: 'settings'
  };
  const view = viewMap[name];
  const navButton = page.locator(`#nav-items [data-view="${view}"]`).first();
  if (!(await navButton.isVisible().catch(() => false))) {
    const menu = page.locator('[data-action="toggleNavItems"]').first();
    if (await menu.isVisible().catch(() => false)) {
      await menu.click();
    }
  }
  if (name === 'SETTINGS') {
    await page.locator('[data-view="settings"]').first().click();
  } else if (view) {
    await page.locator(`#nav-items [data-view="${view}"]:visible`).first().click();
  } else {
    await page.getByRole('button', { name, exact: true }).click();
  }
  await page.waitForTimeout(900);
}

async function clickDataView(page, view) {
  await page.locator(`[data-view="${view}"]:visible`).first().click();
  await page.waitForTimeout(900);
}

async function clickDockerSub(page, arg) {
  await page.locator(`[data-action="switchDockerSub"][data-arg="${arg}"]:visible`).first().click();
  await page.waitForTimeout(700);
}

async function assertLayoutClean(page, label) {
  await page.waitForFunction(() => {
    const visible = el => {
      const style = getComputedStyle(el);
      if (style.display === 'none' || style.visibility === 'hidden' || Number(style.opacity) === 0) return false;
      const rect = el.getBoundingClientRect();
      return rect.width > 0 && rect.height > 0 && rect.bottom > 0 && rect.right > 0 && rect.top < innerHeight && rect.left < innerWidth;
    };
    return Array.from(document.querySelectorAll('#dashboard-root .skeleton')).filter(visible).length === 0;
  }, { timeout: 8_000 }).catch(() => {});

  const result = await page.evaluate(() => {
    const vw = document.documentElement.clientWidth;
    const bodyOverflow = document.documentElement.scrollWidth - vw;
    const visible = el => {
      const style = getComputedStyle(el);
      if (style.display === 'none' || style.visibility === 'hidden' || Number(style.opacity) === 0) return false;
      const rect = el.getBoundingClientRect();
      return rect.width > 0 && rect.height > 0 && rect.bottom > 0 && rect.right > 0 && rect.top < innerHeight && rect.left < innerWidth;
    };
    const clipSelectors = [
      '.st', '.host-card', '.infra-role-card', '.crd', '.fleet-btn', '.sub-tab',
      '.section-header h3', '.metric-val', '.metric-label', '.host-meta', '.role-label',
      '.badge', '.input', '.input-primary', '.fleet-filter-input'
    ];
    const clipped = [];
    for (const selector of clipSelectors) {
      for (const el of document.querySelectorAll(selector)) {
        if (!visible(el)) continue;
        const rect = el.getBoundingClientRect();
        if (rect.left < -2 || rect.right > vw + 2) {
          clipped.push({ selector, text: (el.textContent || '').trim().slice(0, 80), box: [Math.round(rect.left), Math.round(rect.right), vw] });
          continue;
        }
        if (el.scrollWidth > el.clientWidth + 3 && !el.closest('table, .exec-out, pre, code, textarea, #log-out, #go-diff-content')) {
          clipped.push({ selector, text: (el.textContent || '').trim().slice(0, 80), scroll: [el.scrollWidth, el.clientWidth] });
        }
      }
    }
    const stuckSkeletons = Array.from(document.querySelectorAll('#dashboard-root .skeleton'))
      .filter(visible)
      .slice(0, 8)
      .map(el => {
        const rect = el.getBoundingClientRect();
        return { box: [Math.round(rect.width), Math.round(rect.height)], parent: el.parentElement && el.parentElement.id };
      });
    return { bodyOverflow, clipped: clipped.slice(0, 12), stuckSkeletons };
  });

  expect(result.bodyOverflow, `${label}: body horizontal overflow`).toBeLessThanOrEqual(2);
  expect(result.clipped, `${label}: clipped visible UI`).toEqual([]);
  expect(result.stuckSkeletons, `${label}: visible skeletons after settle`).toEqual([]);
}

test.describe('responsive layout sweep', () => {
  for (const viewport of VIEWPORTS) {
    test(`${viewport.name}: main pages and nested tabs stay contained`, async ({ page }) => {
      requireLiveCredentials();
      test.setTimeout(180_000);
      await page.setViewportSize({ width: viewport.width, height: viewport.height });
      await login(page);

      for (const view of MAIN_VIEWS) {
        await clickMainView(page, view);
        await assertLayoutClean(page, `${viewport.name} ${view}`);
      }

      await clickMainView(page, 'FLEET');
      for (const view of FLEET_SUBVIEWS) {
        await clickDataView(page, view);
        await assertLayoutClean(page, `${viewport.name} fleet/${view}`);
      }

      await clickMainView(page, 'DOCKER');
      for (const sub of DOCKER_SUBVIEWS) {
        await clickDockerSub(page, sub);
        await assertLayoutClean(page, `${viewport.name} docker/${sub}`);
      }

      await clickMainView(page, 'SECURITY');
      for (const view of SECURITY_VIEWS) {
        await clickDataView(page, view);
        await assertLayoutClean(page, `${viewport.name} security/${view}`);
      }

      await clickMainView(page, 'SYSTEM');
      for (const view of SYSTEM_VIEWS) {
        await clickDataView(page, view);
        await assertLayoutClean(page, `${viewport.name} system/${view}`);
      }
    });
  }
});

test('fleet activity endpoints are not duplicated during initial home/fleet render', async ({ page }) => {
  requireLiveCredentials();
  const hits = { downloads: 0, streams: 0 };
  page.on('request', request => {
    const url = request.url();
    if (/\/api\/media\/downloads(?:\?|$)/.test(url)) hits.downloads += 1;
    if (/\/api\/media\/streams(?:\?|$)/.test(url)) hits.streams += 1;
  });

  await login(page);
  await page.waitForTimeout(2500);
  await clickMainView(page, 'FLEET');
  await page.locator('#metrics-summary .st').first().waitFor({ timeout: 30_000 });
  await page.waitForTimeout(2500);

  expect(hits.downloads, 'downloads endpoint calls across home boot + first fleet render').toBeLessThanOrEqual(1);
  expect(hits.streams, 'streams endpoint calls across home boot + first fleet render').toBeLessThanOrEqual(1);
});

// Fictional normalized request ports exercise only the original browser consumer.
// These checks do not establish HTTP/auth/provider or installed-demo acceptance.
const path = require('node:path');
const { test, expect } = require('@playwright/test');
const source = path.resolve(__dirname, '../../freq/data/web/js/pve-inventory.js');
const observedAt = '2026-11-13T12:00:00Z';
const attacker = '<img src=x onerror="globalThis.attackerRan=true">';

function host(id, name) {
  return {
    id, label: id, endpoint: `${id}.invalid:8006`, state: 'observed', observedAt,
    nodes: [{ id: 'node/same-node', name: 'same-node', status: 'online', cpu: '12%', memory: '1 GiB / 8 GiB', disk: null }],
    guests: [{ id: 'same-node/qemu/101', vmid: 101, name, type: 'qemu', node: 'same-node', status: 'running', cpu: '5%', memory: '512 MiB', disk: null }]
  };
}
function observed() {
  return { state: 'observed', observedAt, hosts: [host('alpha', 'guest-alpha'), host('beta', attacker)] };
}
function largePartialReport() {
  const alpha = host('alpha', 'unused');
  alpha.nodes = ['node-west', 'node-east'].map(name => ({ id: name, name }));
  alpha.guests = Array.from({ length: 43 }, (_, index) => ({
    vmid: 7000 + index, name: index === 42 ? 'guest-[literal]' : `guest-${index}`,
    node: index < 20 ? 'node-west' : 'node-east', type: index % 2 ? 'lxc' : 'qemu'
  }));
  return { state: 'partial', observedAt, hosts: [alpha, {
    id: 'beta', label: 'beta', endpoint: 'beta.invalid:8006', state: 'unavailable', observedAt: null,
    error: 'The configured endpoint could not be read.', nodes: [], guests: []
  }] };
}
async function mount(page) {
  await page.setContent('<main><div id="pve-inventory-report"></div></main>');
  await page.addScriptTag({ path: source });
  await page.evaluate(() => {
    window.syntheticCurrent = true;
    window.syntheticRequests = [];
    window.syntheticView = FreqPveInventory.create({
      root: document.querySelector('#pve-inventory-report'),
      isCurrent: () => window.syntheticCurrent,
      request: signal => new Promise((resolve, reject) => {
        window.syntheticRequests.push({ signal, resolve, reject });
      })
    });
    void window.syntheticView.load();
  });
  await expect.poll(() => page.evaluate(() => window.syntheticRequests.length)).toBe(1);
}
async function reply(page, index, report) {
  await page.evaluate(({ index, report }) => window.syntheticRequests[index].resolve(report), { index, report });
}
async function requests(page, count) {
  await expect.poll(() => page.evaluate(() => window.syntheticRequests.length)).toBe(count);
}

test.beforeEach(async ({ context }) => {
  // No navigation or fetch is necessary; block all accidental network attempts.
  await context.route('**/*', route => route.abort('blockedbyclient'));
});

test('synthetic consumer renders scoped duplicate IDs and literal text; keyboard details receive focus', async ({ page }) => {
  await mount(page);
  await reply(page, 0, observed());
  const root = page.locator('#pve-inventory-report');
  await expect(root).toHaveAttribute('data-state', 'ready');
  await expect(page.getByRole('heading', { name: 'PVE inventory', exact: true })).toBeVisible();
  await expect(root.locator('[data-inventory-kind="node"]')).toHaveCount(2);
  await expect(root.locator('[data-inventory-kind="guest"]')).toHaveCount(2);
  const alpha = root.locator('.pve-inventory-host').filter({ has: page.getByRole('heading', { name: 'alpha', exact: true }) });
  const beta = root.locator('.pve-inventory-host').filter({ has: page.getByRole('heading', { name: 'beta', exact: true }) });
  await expect(alpha.locator('[data-inventory-kind="guest"]')).toContainText('101');
  await expect(beta.locator('[data-inventory-kind="guest"]')).toContainText('101');
  await expect(beta.locator('[data-inventory-kind="guest"]')).toContainText(attacker);
  await expect(root.locator('img, script, iframe')).toHaveCount(0);
  expect(await page.evaluate(() => window.attackerRan)).toBeUndefined();
  const button = alpha.getByRole('button', { name: 'Details for guest-alpha', exact: true });
  await button.focus();
  await page.keyboard.press('Enter');
  const details = root.locator('[data-inventory-detail]');
  await expect(details.getByRole('heading', { name: 'guest-alpha', exact: true })).toBeFocused();
  await expect(details).toContainText('alpha');
  await expect(button).toHaveAttribute('aria-expanded', 'true');
  await beta.getByRole('button', { name: 'Details for ' + attacker, exact: true }).click();
  await expect(details).toContainText('beta');
  await expect(details.getByRole('heading', { name: attacker, exact: true })).toBeFocused();
  await expect(button).toHaveAttribute('aria-expanded', 'false');
  await expect(details).toContainText('Unknown');
  await expect(root.getByRole('status')).toContainText('Observed:');
});

test('synthetic refresh clears previous details and observations but preserves configured endpoints on failure', async ({ page }) => {
  await mount(page);
  await reply(page, 0, observed());
  await page.getByRole('button', { name: 'Details for guest-alpha', exact: true }).click();
  await page.getByRole('button', { name: 'Refresh inventory', exact: true }).click();
  await requests(page, 2);
  const root = page.locator('#pve-inventory-report');
  await expect(root).toHaveAttribute('data-state', 'loading');
  await expect(root.locator('[data-inventory-kind]')).toHaveCount(0);
  await expect(root).not.toContainText('guest-alpha');
  await expect(root).toContainText('alpha.invalid:8006');
  await page.evaluate(() => window.syntheticRequests[1].reject(new Error('synthetic private exception must not appear')));
  await expect(root).toHaveAttribute('data-state', 'unavailable');
  await expect(root).toContainText('alpha.invalid:8006');
  await expect(root).toContainText('beta.invalid:8006');
  await expect(root).not.toContainText('private exception');
  await expect(root.locator('[data-inventory-kind]')).toHaveCount(0);
  await expect(root.locator('[data-inventory-detail]')).not.toContainText('guest-alpha');
  await expect(page.getByRole('button', { name: 'Refresh inventory', exact: true })).toBeEnabled();
});

test('synthetic held responses cannot publish after disposal, navigation or logout', async ({ page }) => {
  for (const reason of ['dispose', 'navigation', 'logout']) {
    await mount(page);
    await page.evaluate(reason => {
      if (reason === 'dispose') window.syntheticView.dispose();
      else window.syntheticCurrent = false; // Parent route/session authority retires.
    }, reason);
    await reply(page, 0, observed());
    await expect(page.locator('#pve-inventory-report > section')).toHaveCount(0);
    expect(await page.evaluate(() => window.syntheticRequests[0].signal.aborted)).toBe(true);
    await page.evaluate(() => window.syntheticView.load());
    expect(await page.evaluate(() => window.syntheticRequests.length)).toBe(1);
    await expect(page.locator('#pve-inventory-report')).not.toContainText('guest-alpha');
  }
});

test('synthetic timeout discards late success; retries show partial then empty observations', async ({ page }) => {
  await page.clock.install();
  await mount(page);
  await page.clock.fastForward(20_001);
  const root = page.locator('#pve-inventory-report');
  await expect(root).toHaveAttribute('data-state', 'unavailable');
  expect(await page.evaluate(() => window.syntheticRequests[0].signal.aborted)).toBe(true);
  await reply(page, 0, observed());
  await expect(root.locator('[data-inventory-kind]')).toHaveCount(0);
  await page.getByRole('button', { name: 'Refresh inventory', exact: true }).click();
  await requests(page, 2);
  const partial = observed();
  partial.state = 'partial';
  partial.hosts[1] = { id: 'beta', label: 'beta', endpoint: 'beta.invalid:8006', state: 'unavailable', observedAt: null,
    error: 'The configured endpoint could not be read.', nodes: [], guests: [] };
  await reply(page, 1, partial);
  await expect(root).toHaveAttribute('data-state', 'partial');
  await expect(root.locator('[data-inventory-kind="guest"]')).toHaveCount(1);
  await expect(root).toContainText('beta.invalid:8006');
  await expect(root).toContainText('The configured endpoint could not be read.');
  await page.getByRole('button', { name: 'Refresh inventory', exact: true }).click();
  await requests(page, 3);
  await reply(page, 2, { state: 'observed', observedAt, hosts: [] });
  await expect(root).toHaveAttribute('data-state', 'empty');
  await expect(root).toContainText('No PVE endpoints are configured.');
  await expect(root.locator('[data-inventory-kind]')).toHaveCount(0);
  await expect(root).not.toContainText('guest-alpha');
});

test('synthetic 43-guest filter matches source, name, node, VMID, type and literal brackets without requests', async ({ page }) => {
  await mount(page);
  await reply(page, 0, largePartialReport());
  const root = page.locator('#pve-inventory-report'), filter = page.getByRole('searchbox', { name: 'Filter inventory' });
  const count = root.locator('.pve-inventory-filter-summary');
  const guests = root.locator('[data-inventory-kind="guest"]:visible');
  await expect(count).toHaveText('Showing 43 of 43 guest rows and 2 of 2 node rows.');
  await filter.fill('GUEST-17');
  await expect(guests).toHaveCount(1);
  await page.getByRole('button', { name: 'Details for guest-17', exact: true }).click();
  await filter.fill('node-west');
  await expect(guests).toHaveCount(20);
  await expect(count).toHaveText('Showing 20 of 43 guest rows and 1 of 2 node rows.');
  await expect(root.locator('[data-inventory-detail] h3')).toHaveText('guest-17');
  await filter.fill('7042');
  await expect(guests).toHaveCount(1);
  await expect(root.locator('[data-inventory-detail] h3')).toHaveText('Select a node, VM or container');
  await expect(root.locator('[data-inventory-detail] dt')).toHaveCount(0);
  await filter.fill('[literal]');
  await expect(guests).toHaveCount(1);
  await expect(guests).toContainText('guest-[literal]');
  await filter.fill('lxc');
  await expect(guests).toHaveCount(21);
  await filter.fill('ALPHA.INVALID');
  await expect(guests).toHaveCount(43);
  await filter.fill('no-such-guest');
  await expect(guests).toHaveCount(0);
  await expect(count).toContainText('No inventory rows match this filter.');
  await expect(root).toHaveAttribute('data-state', 'partial');
  await expect(root.getByText('The configured endpoint could not be read.', { exact: true })).toBeVisible();
  await expect(root.getByText('Endpoint: beta.invalid:8006', { exact: true })).toBeVisible();
  expect(await page.evaluate(() => window.syntheticRequests.length)).toBe(1);
});

test('synthetic filter survives refresh while unavailable observations stay distinct from no matches', async ({ page }) => {
  await mount(page);
  await reply(page, 0, largePartialReport());
  const root = page.locator('#pve-inventory-report'), filter = page.getByRole('searchbox', { name: 'Filter inventory' });
  const count = root.locator('.pve-inventory-filter-summary');
  await filter.fill('7031');
  await page.getByRole('button', { name: 'Refresh inventory', exact: true }).click();
  await requests(page, 2);
  await expect(root).toHaveAttribute('data-state', 'loading');
  await expect(count).toContainText('No current inventory rows to filter.');
  await reply(page, 1, largePartialReport());
  await expect(filter).toHaveValue('7031');
  await expect(root.locator('[data-inventory-kind="guest"]:visible')).toHaveCount(1);
  await expect(count).toHaveText('Showing 1 of 43 guest rows and 1 of 2 node rows.');
  await page.getByRole('button', { name: 'Refresh inventory', exact: true }).click();
  await requests(page, 3);
  await page.evaluate(() => window.syntheticRequests[2].reject(new Error('synthetic unavailable port')));
  await expect(root).toHaveAttribute('data-state', 'unavailable');
  await expect(filter).toHaveValue('7031');
  await expect(count).toContainText('No current inventory rows to filter.');
  await expect(count).not.toContainText('No inventory rows match');
  await expect(root.getByText('Endpoint: beta.invalid:8006', { exact: true })).toBeVisible();
  await expect(root.locator('[data-inventory-kind]')).toHaveCount(0);
});

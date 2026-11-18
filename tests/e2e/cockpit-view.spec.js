// Original consumer + fictional normalized ports only; no server/provider claim.
const path = require('node:path');
const { test, expect } = require('@playwright/test');
const source = path.resolve(__dirname, '../../freq/data/web/js/pve-inventory.js');
function report() {
  const host = (id, name) => ({ id, label: id, endpoint: id + '.invalid:8006', state: 'observed',
    observedAt: '2026-11-13T12:00:00Z',
    nodes: [{ id: id + '/same-node', node: 'same-node', name: 'same-node', status: 'online',
      cpu: id === 'alpha' ? '12%' : null, memory: '1 GiB / 8 GiB', disk: null, uptime: '120 seconds' }],
    guests: [{ id: id + '/same-node/qemu/5000', vmid: 5000, type: 'qemu', node: 'same-node', name,
      status: 'running', cpu: '5%', memory: '512 MiB', disk: null, maxcpu: 2, uptime: '60 seconds', template: false },
    { id: id + '/same-node/lxc/9500', vmid: 9500, type: 'lxc', node: 'same-node', name: id + '-lab-template',
      status: null, cpu: null, memory: null, disk: null, maxcpu: null, template: true }] });
  return { state: 'observed', observedAt: '2026-11-13T12:00:00Z',
    hosts: [host('alpha', 'hq-pve1'), host('beta', '<img src=x onerror="globalThis.attacked=true">')] };
}
async function mount(page) {
  await page.setContent('<main><div id="pve-inventory-report"></div></main>');
  await page.addScriptTag({ path: source });
  await page.evaluate(() => {
    window.syntheticCurrent = true;
    window.syntheticPorts = [];
    window.syntheticCockpit = FreqPveInventory.create({ root: document.querySelector('#pve-inventory-report'),
      isCurrent: () => window.syntheticCurrent,
      request: signal => new Promise((resolve, reject) => { window.syntheticPorts.push({ signal, resolve, reject }); }) });
    void window.syntheticCockpit.load();
  });
  await expect.poll(() => page.evaluate(() => window.syntheticPorts.length)).toBe(1);
}
async function reply(page, index, data) {
  await page.evaluate(({ index, data }) => window.syntheticPorts[index].resolve(data), { index, data });
}
function sourceBox(page, name) {
  return page.locator('.pve-inventory-host').filter({ has: page.getByRole('heading', { name, exact: true }) });
}
async function detailValue(page, label, text) {
  await expect(page.locator('[data-inventory-detail] dt').filter({ hasText: new RegExp('^' + label + '$') })
    .locator('xpath=following-sibling::dd[1]')).toHaveText(text);
}
test.beforeEach(async ({ context }) => {
  await context.route('**/*', route => route.abort('blockedbyclient'));
});

test('synthetic cockpit preserves source identity, VM/LXC/lab/template rows and observed versus unknown metrics', async ({ page }) => {
  const network = []; page.on('request', request => network.push(request.method()));
  await mount(page); await reply(page, 0, report());
  await expect(page.locator('#pve-inventory-report')).toHaveAttribute('data-state', 'ready');
  await expect(page.locator('.cockpit-node-group')).toHaveCount(2);
  await expect(page.locator('[data-inventory-kind="guest"]')).toHaveCount(4);
  const alpha = sourceBox(page, 'alpha'), beta = sourceBox(page, 'beta');
  await expect(alpha.locator('.pve-node-metrics')).toContainText('12%');
  await expect(beta.locator('.pve-node-metrics')).toContainText('Unknown');
  await expect(alpha.locator('[data-inventory-kind="guest"]').filter({ hasText: 'alpha-lab-template' })).toContainText('LXC');
  await expect(alpha.locator('[data-inventory-kind="guest"]').filter({ hasText: 'alpha-lab-template' })).toContainText('Template');
  await expect(alpha.locator('[data-inventory-kind="guest"]').filter({ hasText: 'alpha-lab-template' })).toContainText('Unknown');
  await expect(alpha.locator('[data-inventory-kind="guest"]').filter({ hasText: 'alpha-lab-template' })).not.toContainText('STOPPED');
  for (const name of ['alpha', 'beta']) {
    await sourceBox(page, name).locator('[data-inventory-kind="guest"]').first().getByRole('button', { name: /^Details for / }).click();
    await detailValue(page, 'Source', name);
    await detailValue(page, 'Node', 'same-node');
    await detailValue(page, 'ID', '5000');
  }
  await expect(page.locator('img, iframe')).toHaveCount(0);
  expect(await page.evaluate(() => window.attacked)).toBeUndefined();
  expect(network).toEqual([]);
  await page.evaluate(() => window.syntheticCockpit.dispose());
});

test('synthetic cockpit groups collapse locally; keyboard resource tabs expose disabled operations without network effects', async ({ page }) => {
  const network = []; page.on('request', request => network.push(request.method()));
  await mount(page); await reply(page, 0, report());
  const alpha = sourceBox(page, 'alpha');
  await alpha.getByRole('button', { name: 'Collapse guests for same-node', exact: true }).click();
  await expect(alpha.locator('[data-inventory-kind="guest"]').first()).toBeHidden();
  await alpha.getByRole('button', { name: 'Expand guests for same-node', exact: true }).click();
  await expect(alpha.locator('[data-inventory-kind="guest"]').first()).toBeVisible();
  const search = page.getByRole('searchbox', { name: 'Filter inventory', exact: true });
  await search.fill('hq-pve1');
  await expect(page.locator('[data-inventory-kind="guest"]:visible')).toHaveCount(1);
  const trigger = alpha.getByRole('button', { name: 'Details for hq-pve1', exact: true });
  await trigger.focus(); await page.keyboard.press('Enter');
  const details = page.locator('[data-inventory-detail]');
  await expect(details.getByRole('heading', { name: 'hq-pve1', exact: true })).toBeFocused();
  await detailValue(page, 'Guest', 'hq-pve1');
  const tabs = details.getByRole('tablist', { name: 'Resource details' });
  await tabs.getByRole('tab', { name: 'Overview', exact: true }).focus();
  for (const tab of ['Console', 'Network', 'Hardware', 'Snapshots', 'Backups']) {
    await page.keyboard.press('ArrowRight');
    await expect(tabs.getByRole('tab', { name: tab, exact: true })).toBeFocused();
    await expect(tabs.getByRole('tab', { name: tab, exact: true })).toHaveAttribute('aria-selected', 'true');
    await expect(details.getByRole('tabpanel')).toBeVisible();
    if (tab === 'Console') await expect(details.getByRole('tabpanel')).toContainText('No console session');
    if (tab === 'Network') await expect(details.getByRole('tabpanel')).toContainText('Unknown');
  }
  await page.keyboard.press('Home');
  await expect(tabs.getByRole('tab', { name: 'Overview', exact: true })).toBeFocused();
  for (const label of ['Start', 'Stop', 'Open shell', 'IP controls']) await expect(details.getByRole('button', { name: label, exact: true })).toBeDisabled();
  await details.locator('button:disabled').evaluateAll(buttons => buttons.forEach(button => button.click()));
  await search.fill('[');
  await expect(page.locator('[data-inventory-kind="guest"]:visible')).toHaveCount(0);
  await expect(page.locator('#pve-inventory-report')).toHaveAttribute('data-state', 'ready');
  await search.fill('');
  await expect(page.locator('[data-inventory-kind="guest"]:visible')).toHaveCount(4);
  expect(await page.evaluate(() => window.syntheticPorts.length)).toBe(1);
  expect(network).toEqual([]);
  await page.evaluate(() => window.syntheticCockpit.dispose());
});

test('synthetic held refresh cannot publish resources after session retirement or disposal', async ({ page }) => {
  for (const reason of ['session-retired', 'disposed']) {
    await mount(page); await reply(page, 0, report());
    await sourceBox(page, 'alpha').getByRole('button', { name: 'Details for hq-pve1', exact: true }).click();
    await page.getByRole('button', { name: 'Refresh inventory', exact: true }).click();
    await expect.poll(() => page.evaluate(() => window.syntheticPorts.length)).toBe(2);
    await expect(page.locator('[data-inventory-kind]')).toHaveCount(0);
    await page.evaluate(reason => {
      if (reason === 'disposed') window.syntheticCockpit.dispose();
      else { window.syntheticCurrent = false; window.syntheticCockpit.load(); }
    }, reason);
    await reply(page, 1, report());
    await expect(page.locator('#pve-inventory-report > section')).toHaveCount(0);
    expect(await page.evaluate(() => window.syntheticPorts[1].signal.aborted)).toBe(true);
    await expect(page.locator('#pve-inventory-report')).not.toContainText('hq-pve1');
  }
});

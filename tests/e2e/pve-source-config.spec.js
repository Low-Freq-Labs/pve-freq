// Synthetic request ports for the original consumer only. No HTTP server,
// credentials, provider connection or installed-demo acceptance is exercised.
const path = require('node:path');
const { test, expect } = require('@playwright/test');
const source = path.resolve(__dirname, '../../freq/data/web/js/pve-source-config.js');
const empty = { addresses: [], token_principal: null, ca_configured: false };
const saved = { addresses: ['pve-example.invalid'], token_principal: 'observer@pve!demo', ca_configured: true };
const fictionalSecret = 'fictional-consumer-test-secret';

async function mount(page) {
  await page.setContent('<main><div id="pve-host-configuration"></div></main>');
  await page.addScriptTag({ path: source });
  await page.evaluate(() => {
    window.syntheticCurrent = true;
    window.syntheticPorts = [];
    window.syntheticSaved = 0;
    window.syntheticConfig = FreqPveSourceConfig.create({
      root: document.querySelector('#pve-host-configuration'),
      isCurrent: () => window.syntheticCurrent,
      request: (method, payload, signal) => new Promise((resolve, reject) => {
        window.syntheticPorts.push({ method, payload, signal, resolve, reject });
      }),
      onSaved: () => { window.syntheticSaved++; },
    });
    void window.syntheticConfig.load();
  });
  await ports(page, 1);
}
async function ports(page, count) {
  await expect.poll(() => page.evaluate(() => window.syntheticPorts.length)).toBe(count);
}
async function reply(page, index, data) {
  await page.evaluate(({ index, data }) => window.syntheticPorts[index].resolve(data), { index, data });
}
async function draft(page) {
  await page.getByLabel('PVE addresses', { exact: true }).fill('pve-example.invalid');
  await page.getByLabel('API token ID', { exact: true }).fill('observer@pve!demo');
  await page.getByLabel('API token secret', { exact: true }).fill(fictionalSecret);
  await page.getByLabel('Trusted CA certificate (optional)', { exact: true }).fill('fictional-ca-bundle');
}
async function submit(page) {
  await page.getByRole('button', { name: 'Save PVE source configuration', exact: true }).click();
}
test.beforeEach(async ({ context }) => {
  await context.route('**/*', route => route.abort('blockedbyclient'));
});

test('synthetic source configuration: empty GET, exact create payload, immediate secret clearing and one success callback', async ({ page }) => {
  await mount(page);
  expect(await page.evaluate(() => window.syntheticPorts[0].method)).toBe('GET');
  await reply(page, 0, empty);
  await expect(page.getByLabel('API token secret', { exact: true })).toHaveAttribute('type', 'password');
  await expect(page.getByLabel('API token secret', { exact: true })).toHaveAttribute('autocomplete', 'off');
  await draft(page);
  await submit(page);
  await expect(page.getByLabel('API token secret', { exact: true })).toHaveValue('');
  await ports(page, 2);
  expect(await page.evaluate(() => ({ method: window.syntheticPorts[1].method, payload: window.syntheticPorts[1].payload }))).toEqual({
    method: 'POST', payload: { addresses: ['pve-example.invalid'], token_id: 'observer@pve!demo',
      token_secret: fictionalSecret, ca_pem: 'fictional-ca-bundle' },
  });
  await expect(page.getByRole('button', { name: 'Save PVE source configuration', exact: true })).toBeDisabled();
  await page.locator('form').evaluate(form => form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })));
  expect(await page.evaluate(() => window.syntheticPorts.length)).toBe(2);
  await reply(page, 1, { ...saved, ok: true });
  await expect(page.locator('#pve-host-configuration form')).toHaveCount(0);
  await expect(page.getByRole('status')).toContainText('Configuration saved.');
  await expect(page.getByRole('status')).toContainText('Inventory is being refreshed to check the PVE connection');
  expect(await page.evaluate(() => window.syntheticSaved)).toBe(1);
  expect(await page.evaluate(() => window.syntheticPorts[1].payload.token_secret)).toBe('');
  await page.evaluate(() => window.syntheticConfig.dispose());
});

test('synthetic configured GET exposes literal source text and no mutation controls', async ({ page }) => {
  await mount(page);
  const malicious = '<img src=x onerror="globalThis.syntheticAttack=true">';
  await reply(page, 0, { ...saved, addresses: [malicious] });
  const root = page.locator('#pve-host-configuration');
  await expect(root).toContainText(malicious);
  await expect(root).toContainText('observer@pve!demo');
  await expect(root).toContainText('Trusted CA certificate: Configured');
  await expect(root.locator('form, input, textarea, img, script, iframe')).toHaveCount(0);
  expect(await page.evaluate(() => window.syntheticAttack)).toBeUndefined();
  await page.getByRole('button', { name: 'Refresh source configuration', exact: true }).click();
  await ports(page, 2);
  expect(await page.evaluate(() => window.syntheticPorts.map(port => port.method))).toEqual(['GET', 'GET']);
  await reply(page, 1, saved);
  await expect(root).toContainText('pve-example.invalid');
  expect(await page.evaluate(() => window.syntheticSaved)).toBe(0);
  await page.evaluate(() => window.syntheticConfig.dispose());
});

test('synthetic source configuration omits an unused CA for system-trusted HTTPS', async ({ page }) => {
  await mount(page);
  await reply(page, 0, empty);
  await draft(page);
  await page.getByLabel('Trusted CA certificate (optional)', { exact: true }).fill('');
  await submit(page);
  await ports(page, 2);
  expect(await page.evaluate(() => Object.hasOwn(window.syntheticPorts[1].payload, 'ca_pem'))).toBe(false);
  await reply(page, 1, { ...saved, ca_configured: false, ok: true });
  await expect(page.getByRole('status')).toContainText('Configuration saved.');
  await expect(page.locator('#pve-host-configuration')).toContainText('Trusted CA certificate: Not configured');
  await page.evaluate(() => window.syntheticConfig.dispose());
});

test('synthetic ambiguous failure, timeout and retired held POST cannot retry or publish late success', async ({ page }) => {
  await page.clock.install();
  for (const outcome of ['failure', 'timeout', 'dispose', 'retired']) {
    await mount(page);
    await reply(page, 0, empty);
    await draft(page);
    await submit(page);
    await ports(page, 2);
    if (outcome === 'failure') {
      await page.evaluate(() => window.syntheticPorts[1].reject(new Error('fictional sensitive exception')));
      await expect(page.getByRole('status')).toContainText('could not be confirmed');
      await expect(page.locator('#pve-host-configuration')).not.toContainText('fictional sensitive exception');
    } else if (outcome === 'timeout') {
      await page.clock.fastForward(20_001);
      await expect(page.getByRole('status')).toContainText('timed out');
    } else if (outcome === 'dispose') {
      await page.evaluate(() => window.syntheticConfig.dispose());
    } else {
      await page.evaluate(() => { window.syntheticCurrent = false; window.syntheticConfig.load(); });
    }
    await expect(page.locator('#pve-host-configuration form')).toHaveCount(0);
    // These retained request ports deliberately never settle on timeout/dispose:
    // cleanup must clear the handed-off object without relying on finally().
    expect(await page.evaluate(() => window.syntheticPorts[1].payload.token_secret)).toBe('');
    expect(await page.evaluate(() => window.syntheticPorts[1].payload.ca_pem)).toBe('');
    await reply(page, 1, { ...saved, ok: true });
    expect(await page.evaluate(() => window.syntheticSaved)).toBe(0);
    await expect(page.locator('#pve-host-configuration')).not.toContainText('Configuration saved.');
    if (outcome === 'failure' || outcome === 'timeout') {
      await page.getByRole('button', { name: 'Refresh source configuration', exact: true }).click();
      await ports(page, 3);
      expect(await page.evaluate(() => window.syntheticPorts[2].method)).toBe('GET');
      await expect(page.locator('#pve-host-configuration form')).toHaveCount(0);
      await reply(page, 2, empty);
      await expect(page.getByRole('button', { name: 'Save PVE source configuration', exact: true })).toBeVisible();
    }
    await page.evaluate(() => window.syntheticConfig.dispose());
  }
});

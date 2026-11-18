// Original workspace UI with local-only state. No provider/auth/server coverage.
const path = require('node:path');
const { test, expect } = require('@playwright/test');
const source = path.resolve(__dirname, '../../freq/data/web/js/cockpit-workspaces.js');
const workspaces = [
  ['network', 'Network & topology', ['Overview', 'Switches', 'VLANs', 'Interfaces', 'Map']],
  ['storage', 'Storage & NAS', ['Overview', 'Pools', 'Datasets', 'Shares', 'Snapshots']],
  ['security', 'Security & firewall', ['Overview', 'Rules', 'Interfaces', 'NAT', 'Logs']],
  ['docker', 'Docker & containers', ['Overview', 'Services', 'Containers', 'Registry', 'Volumes', 'Logs']],
  ['media', 'Media services', ['Overview', 'Services', 'Containers', 'Registry', 'Logs']],
  ['tools', 'System & tools', ['Overview', 'Automation', 'Diagnostics', 'Activity', 'Backups']],
  ['vault', 'Vault', ['Overview', 'Credentials', 'Certificates', 'Access']],
  ['settings', 'Settings', ['Overview', 'Connections', 'Users', 'Notifications', 'About']],
];
test.beforeEach(async ({ context }) => {
  await context.route('**/*', route => route.abort('blockedbyclient'));
});
for (const [view, title, sections] of workspaces) {
  test(`synthetic ${view} workspace provides shaped sections with unavailable operation controls`, async ({ page }) => {
    const network = []; page.on('request', request => network.push(request.method()));
    await page.setContent('<main><div id="workspace"></div></main>');
    await page.addScriptTag({ path: source });
    await page.evaluate(view => {
      window.syntheticCurrent = true; window.syntheticNavigations = [];
      window.syntheticWorkspace = FreqCockpitWorkspaces.create({ root: document.querySelector('#workspace'), view,
        isCurrent: () => window.syntheticCurrent, onNavigate: target => window.syntheticNavigations.push(target) });
    }, view);
    const root = page.locator('#workspace');
    await expect(root.getByRole('heading', { name: title, exact: true, level: 2 })).toBeVisible();
    await expect(root.locator('.cockpit-workspace-status')).toContainText('Not connected yet');
    const tabs = root.getByRole('group', { name: title + ' sections', exact: true });
    for (const section of sections) {
      await tabs.getByRole('button', { name: section, exact: true }).click();
      await expect(tabs.getByRole('button', { name: section, exact: true })).toHaveAttribute('aria-pressed', 'true');
      await expect(tabs.locator('[aria-pressed="true"]')).toHaveCount(1);
      const body = root.locator('.cockpit-workspace-content');
      await expect(body.getByRole('heading').first()).toBeVisible();
      await expect(body).toContainText(/not observed|not been observed|unavailable|No .*observed|No .*session|not connected|Not connected/i);
      const controls = body.locator('[data-action-unavailable="true"]');
      expect(await controls.count()).toBeGreaterThan(0);
      expect(await controls.evaluateAll(buttons => buttons.every(button => button.tagName === 'BUTTON' && button.disabled))).toBe(true);
      await controls.evaluateAll(buttons => buttons.forEach(button => button.click()));
      if (view === 'network' && section === 'Map') await expect(body.locator('.cockpit-map')).toContainText('relationships are observed');
      if (view === 'storage' && section === 'Shares') await expect(body.getByRole('table')).toContainText('SMB and NFS shares have not been observed');
      if (view === 'security' && section === 'Rules') await expect(body.getByRole('table')).toContainText('No firewall rules have been observed');
    }
    expect(network).toEqual([]);
    expect(await page.evaluate(() => window.syntheticNavigations)).toEqual([]);
    await root.getByRole('button', { name: '← Fleet inventory', exact: true }).click();
    expect(await page.evaluate(() => window.syntheticNavigations)).toEqual(['fleet']);
    await page.evaluate(() => { window.syntheticCurrent = false; });
    await tabs.getByRole('button').first().click();
    await expect(root.locator('.cockpit-workspace')).toHaveCount(0);
  });
}

const { test, expect } = require('@playwright/test');

const USER = 'admin';
const PASS = 'hermetic-dashboard-password';

async function login(page) {
  await page.goto('/');
  await page.locator('#login-user').fill(USER);
  await page.locator('#login-pass').fill(PASS);
  await page.locator('#login-form').evaluate(form => form.requestSubmit());
  await page.locator('#login-overlay').waitFor({ state: 'hidden' });
}

test.describe('operator-facing truth', () => {
  test('hardening remediation requires an explicit host or fleet target', async ({ page }) => {
    let execRequests = 0;
    page.on('request', request => {
      if (new URL(request.url()).pathname === '/api/exec') execRequests += 1;
    });

    await login(page);
    await page.evaluate(() => window.switchView('sec-hardening'));
    const target = page.locator('#harden-target');
    await expect(target.locator('option[value="pve-hermetic"]')).toHaveCount(1);

    await page.getByRole('button', { name: 'DISABLE ROOT SSH' }).click();
    await expect(page.locator('#toast-container')).toContainText('Select a hardening target');
    await expect(page.locator('#modal-container')).toBeHidden();
    expect(execRequests).toBe(0);

    await target.selectOption('pve-hermetic');
    await page.getByRole('button', { name: 'DISABLE ROOT SSH' }).click();
    await expect(page.locator('#modal-container')).toBeVisible();
    await expect(page.locator('#modal-container')).toContainText('PVE-HERMETIC');
    expect(execRequests).toBe(0);
  });

  test('shortcut help names the exact implemented key map', async ({ page }) => {
    await login(page);
    await page.keyboard.type('?');
    const help = page.locator('#shortcuts-modal');
    await expect(help).toBeVisible();
    await expect(help).toContainText('1-6');
    await expect(help).toContainText('Home / Fleet / Docker / Certificates / System / Settings');
    await expect(help).not.toContainText('1-8');
  });
});

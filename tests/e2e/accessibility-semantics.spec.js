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

test.describe('dashboard accessibility semantics', () => {
  test('visible form controls have explicit programmatic names on every view', async ({ page }) => {
    await login(page);
    const views = ['home', 'fleet', 'network', 'docker', 'security', 'vault', 'tools', 'lab', 'infra', 'system', 'settings'];

    for (const view of views) {
      await page.evaluate(next => window.switchView(next), view);
      await page.waitForTimeout(50);
      const unnamed = await page.locator('input:not([type="hidden"]), select, textarea').evaluateAll(controls =>
        controls.filter(control => {
          const style = getComputedStyle(control);
          if (style.display === 'none' || style.visibility === 'hidden' || control.closest('[hidden], .d-none')) return false;
          return !control.labels?.length && !control.getAttribute('aria-label') && !control.getAttribute('aria-labelledby') && !control.title;
        }).map(control => `#${control.id || control.tagName.toLowerCase()}`)
      );
      expect(unnamed, `${view} has unnamed visible form controls`).toEqual([]);
    }
  });

  test('symbol-only close controls expose names and work from the keyboard', async ({ page }) => {
    await login(page);
    await page.evaluate(() => window.openUserMenu());

    const close = page.getByRole('button', { name: 'Close session dialog' });
    await expect(close).toBeVisible();
    await close.focus();
    await page.keyboard.press('Enter');
    await expect(page.locator('#modal-container')).toBeHidden();
  });
});

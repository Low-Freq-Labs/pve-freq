const { test, expect } = require('@playwright/test');

const USER = 'admin';
const PASS = 'hermetic-dashboard-password';

async function switchView(page, view) {
  await page.evaluate(next => window.switchView(next), view);
  await page.waitForTimeout(250);
}

test.describe('dashboard accessibility semantics', () => {
  test('H09 accessibility semantics owns landmarks, controls, tables, dialogs, and announcements', async ({ page }) => {
    test.setTimeout(150_000);
    await test.step('authentication errors are announced before one successful login', async () => {
      await page.route('**/api/v1/net/snmp/setup/plan*', route => route.fulfill({
        json: {
          schema_version: 1,
          credential_ready: true,
          targets: [
            { label: 'pve01', ip: '192.0.2.10', setup_class: 'linux_snmpd', mutation: 'configure', caveats: [] },
            { label: 'edge & core', ip: '192.0.2.11', setup_class: 'cisco_ios_snmpv3', mutation: 'configure', caveats: [] }
          ]
        }
      }));
      await page.route('**/api/v1/net/snmp/setup/status', route => route.fulfill({
        json: { state: 'never_run', results: [], summary: { total: 0 } }
      }));
      await page.goto('/');
      await page.locator('#login-user').fill(USER);
      await page.locator('#login-pass').fill('wrong-password');
      await page.locator('#login-form').evaluate(form => form.requestSubmit());
      const loginError = page.locator('#login-error');
      await expect(loginError).toHaveRole('alert');
      await expect(loginError).toHaveText('Invalid credentials');
      await expect(loginError).toBeVisible();

      await page.locator('#login-pass').fill(PASS);
      await page.locator('#login-form').evaluate(form => form.requestSubmit());
      await page.locator('#login-overlay').waitFor({ state: 'hidden' });
    });

    const primary = page.getByRole('navigation', { name: 'Primary' });
    await test.step('landmarks and initial current navigation follow the real router', async () => {
      await expect(page.getByRole('main')).toBeVisible();
      await expect(primary).toBeVisible();
      await expect(primary.getByRole('button', { name: 'HOME', exact: true })).toHaveAttribute('aria-current', 'page');
      await expect(primary.locator('[aria-current="page"]')).toHaveCount(1);
    });

    await test.step('registered views preserve route, control-name, and table semantics in one traversal', async () => {
      const views = await page.evaluate(() => window.VIEW_IDS.slice());
      expect(views.length, 'VIEW_IDS must be nonempty').toBeGreaterThan(0);
      expect(new Set(views).size, 'VIEW_IDS must be unique').toBe(views.length);
      const tableViews = new Set(['fleet', 'security', 'dr', 'incidents', 'infra']);
      const seenTableViews = [];

      for (const view of views) {
        const mount = page.locator(`#${view}-view`);
        await expect(mount, `${view} needs exactly one registered mount`).toHaveCount(1);
        await switchView(page, view);
        await expect(mount, `${view} registered mount needs to render`).toBeVisible();
        const snmpTargets = mount.locator('.snmp-target-check:visible');
        if (view === 'network') {
          await expect(snmpTargets, 'fixture-backed SNMP target rows need to render').toHaveCount(2);
        }

        if (view === 'security') {
          await expect(primary.getByRole('button', { name: 'SECURITY', exact: true })).toHaveAttribute('aria-current', 'page');
          await expect(primary.locator('[aria-current="page"]')).toHaveCount(1);
          const securityNav = page.locator('#security-view > [data-subnav-group="security"]');
          await expect(securityNav).toHaveRole('navigation');
          await expect(securityNav).toHaveAccessibleName('security sections');
          await expect(securityNav.getByRole('button', { name: 'Overview' })).toHaveAttribute('aria-current', 'page');
        }
        if (view === 'certs') {
          await expect(primary.getByRole('button', { name: 'SECURITY', exact: true })).toHaveAttribute('aria-current', 'page');
          const certsNav = page.locator('#certs-view > [data-subnav-group="security"]');
          await expect(certsNav.getByRole('button', { name: 'Certs' })).toHaveAttribute('aria-current', 'page');
          await expect(certsNav.locator('[aria-current="page"]')).toHaveCount(1);
        }

        const controls = mount.locator('button:visible, input:not([type="hidden"]):visible, select:visible, textarea:visible, a[href]:visible');
        const ids = await controls.evaluateAll((elements, currentView) => elements.map((element, index) => {
          const id = `${currentView}-${index}`;
          element.setAttribute('data-h09-control', id);
          return id;
        }), view);
        for (let index = 0; index < ids.length; index += 1) {
          const control = page.locator(`[data-h09-control="${ids[index]}"]`);
          const title = await control.getAttribute('title');
          if (title) await control.evaluate(element => element.removeAttribute('title'));
          await expect(control, `${view} control ${index} needs a non-title accessible name`).toHaveAccessibleName(/\S/);
          if (title) await control.evaluate((element, value) => element.setAttribute('title', value), title);
        }
        for (let index = 0; index < await snmpTargets.count(); index += 1) {
          const target = snmpTargets.nth(index);
          const key = await target.inputValue();
          await expect(target).toHaveAccessibleName(`Select SNMP target ${key || 'target'}`);
        }

        if (tableViews.has(view)) {
          const table = mount.locator('table:visible').first();
          await expect(table, `${view} needs a rendered table`).toBeVisible();
          await expect(table).toHaveRole('table');
          const headers = table.getByRole('columnheader');
          const count = await headers.count();
          expect(count, `${view} needs native column headers`).toBeGreaterThan(0);
          for (let index = 0; index < count; index += 1) {
            await expect(headers.nth(index), `${view} header ${index} needs a name`).toHaveAccessibleName(/\S/);
          }
          seenTableViews.push(view);
        }
      }
      expect(new Set(seenTableViews)).toEqual(tableViews);
    });

    await test.step('managed dialogs name themselves, contain focus, and restore invokers', async () => {
      const userButton = page.locator('#header-user-btn');
      await userButton.click();
      const session = page.getByRole('dialog', { name: 'Session' });
      await expect(session).toBeVisible();
      const sessionClose = session.getByRole('button', { name: 'Close session dialog' });
      await expect(sessionClose).toBeFocused();
      await page.keyboard.press('Shift+Tab');
      await expect(session.getByRole('button', { name: 'LOG OUT' })).toBeFocused();
      await page.keyboard.press('Tab');
      await expect(sessionClose).toBeFocused();
      await page.keyboard.press('Escape');
      await expect(session).toBeHidden();
      await expect(userButton).toBeFocused();

      await userButton.click();
      await expect(sessionClose).toBeFocused();
      await page.keyboard.press('Enter');
      await expect(session).toBeHidden();
      await expect(userButton).toBeFocused();

      await userButton.focus();
      await page.evaluate(() => window.confirmAction('Confirm semantic proof', () => {}));
      const confirm = page.getByRole('dialog', { name: 'Confirm Action' });
      await expect(confirm.getByRole('button', { name: 'Confirm', exact: true })).toBeFocused();
      await page.keyboard.press('Tab');
      await expect(confirm.getByRole('button', { name: 'Cancel' })).toBeFocused();
      await page.keyboard.press('Escape');
      await expect(confirm).toBeHidden();
      await expect(userButton).toBeFocused();

      const home = primary.getByRole('button', { name: 'HOME', exact: true });
      await home.focus();
      await page.keyboard.press('Control+k');
      const search = page.getByRole('dialog', { name: 'Global search' });
      await expect(search).toBeVisible();
      await expect(page.locator('#search-input')).toBeFocused();
      await page.keyboard.press('Shift+Tab');
      await expect(page.locator('#search-input')).toBeFocused();
      await page.keyboard.press('Escape');
      await expect(search).toBeHidden();
      await expect(home).toBeFocused();

      await page.keyboard.press('?');
      const shortcuts = page.getByRole('dialog', { name: 'Keyboard Shortcuts' });
      await expect(shortcuts).toBeVisible();
      await expect(shortcuts).toBeFocused();
      await page.keyboard.press('Tab');
      await expect(shortcuts).toBeFocused();
      await shortcuts.click({ position: { x: 2, y: 2 } });
      await expect(shortcuts).toBeHidden();
      await expect(home).toBeFocused();
      await page.keyboard.press('?');
      await expect(shortcuts).toBeVisible();
      await page.keyboard.press('Escape');
      await expect(shortcuts).toBeHidden();
      await expect(home).toBeFocused();
    });

    await test.step('password and toast errors are announced with visible exact text', async () => {
      await page.locator('#header-user-btn').click();
      await page.getByRole('button', { name: 'CHANGE PASSWORD' }).click();
      const passwordDialog = page.getByRole('dialog', { name: 'Change Password' });
      await passwordDialog.getByRole('button', { name: 'ROTATE PASSWORD' }).click();
      const passwordError = passwordDialog.locator('#cp-err');
      await expect(passwordError).toHaveRole('alert');
      await expect(passwordError).toHaveText('Current password required');
      await expect(passwordError).toBeVisible();
      await passwordDialog.getByRole('button', { name: 'Close password dialog' }).click();

      await page.evaluate(() => {
        window.toast('semantic error proof', 'error');
        window.toast('semantic success proof', 'success');
      });
      const errorToast = page.locator('#toast-container .toast').filter({ hasText: 'semantic error proof' });
      const successToast = page.locator('#toast-container .toast').filter({ hasText: 'semantic success proof' });
      await expect(errorToast).toHaveRole('alert');
      await expect(successToast).toHaveRole('status');
      await expect(errorToast).toHaveText('semantic error proof');
      await expect(successToast).toHaveText('semantic success proof');
      await expect(errorToast).toBeVisible();
      await expect(successToast).toBeVisible();
    });
  });
});

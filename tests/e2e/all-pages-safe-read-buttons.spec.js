const { test, expect } = require('@playwright/test');

const USER = process.env.PVE_FREQ_USER;
const PASS = process.env.PVE_FREQ_PASS;

function requireLiveCredentials() {
  test.skip(!USER || !PASS, 'Set PVE_FREQ_USER and PVE_FREQ_PASS for live dashboard E2E tests.');
}

async function login(page) {
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await page.locator('#login-user').fill(USER);
  await page.locator('#login-pass').fill(PASS);
  await page.locator('#login-form').evaluate(form => form.requestSubmit());
  await page.locator('#login-overlay').waitFor({ state: 'hidden', timeout: 20_000 });
}

async function clickNav(page, name) {
  if (name === 'SETTINGS') {
    await page.locator('[data-view="settings"]').first().click();
  } else {
    await page.getByRole('button', { name, exact: true }).click();
  }
  await page.waitForTimeout(500);
}

async function clickAction(page, action, arg = null) {
  const selector = arg
    ? `[data-action="${action}"][data-arg="${arg}"]`
    : `[data-action="${action}"]`;
  await page.locator(`${selector}:visible`).first().click();
}

async function expectOutput(locator, pattern = /[A-Za-z0-9]/, timeout = 30_000) {
  await expect(locator).toBeVisible({ timeout });
  await expect(locator).toContainText(pattern, { timeout });
  await expect(locator).not.toContainText(/Permission denied|not accessible|Traceback|Unhandled|undefined|null null/i);
}

async function api(page, path, options = {}) {
  return await page.evaluate(async ({ path, options }) => {
    const response = await fetch(path, options);
    let body = null;
    try {
      body = await response.json();
    } catch {
      body = await response.text();
    }
    return { status: response.status, body };
  }, { path, options });
}

test.describe('all-page safe read buttons', () => {
  test.beforeEach(async ({ page }) => {
    requireLiveCredentials();
    await login(page);
  });

  test('Docker read buttons render real output', async ({ page }) => {
    await clickNav(page, 'DOCKER');
    await page.locator('#services-container-cards .crd').first().waitFor({ timeout: 30_000 });

    await clickAction(page, 'loadStackInfo', 'status');
    await expectOutput(page.locator('#stack-info'), /Stacks|No Docker Compose stacks/i);

    await clickAction(page, 'loadStackInfo', 'health');
    await expectOutput(page.locator('#stack-info'), /Containers|No running containers|Healthy/i);

    await clickAction(page, 'switchDockerSub', 'registry');
    await expectOutput(page.locator('#registry-table'), /Container|No containers|Registry/i);

    await clickAction(page, 'switchDockerSub', 'fleet-inv');
    await expectOutput(page.locator('#docker-fleet-table'), /Docker VMs|Container|No Docker VMs|plex/i);
  });

  test('System/tools read buttons render real output', async ({ page }) => {
    test.setTimeout(180_000);
    await clickNav(page, 'SYSTEM');

    await clickAction(page, 'runDoctor');
    await expectOutput(page.locator('#diag-out'), /STATUS|passed|healthy|All /i, 45_000);

    const logHost = page.locator('#log-host');
    await expect(logHost).toBeVisible({ timeout: 30_000 });
    const logOptions = await logHost.locator('option').count();
    if (logOptions > 1) {
      await logHost.selectOption({ index: 1 });
    }
    await clickAction(page, 'fetchLogs');
    await expectOutput(page.locator('#log-out'), /journal|freq|log|systemd|sshd|No logs|-- No entries --/i, 45_000);

    await clickAction(page, 'loadZfs');
    await expectOutput(page.locator('#zfs-out'), /pool|ZFS|No ZFS|not installed/i, 45_000);

    await clickAction(page, 'loadBackups', 'list');
    await expectOutput(page.locator('#backup-out'), /backup|snapshot|No backups|list/i, 45_000);

    await clickAction(page, 'loadBackups', 'status');
    await expectOutput(page.locator('#backup-out'), /status|backup|snapshot|No backups/i, 45_000);

    await clickAction(page, 'loadInventory');
    await expectOutput(page.locator('#inventory-out'), /Hosts|VMs|Containers/i, 45_000);

    for (const view of ['hosts', 'vms', 'containers']) {
      await clickAction(page, 'loadInventoryView', view);
      await expectOutput(page.locator('#inventory-out'), new RegExp(view, 'i'), 45_000);
    }

    await clickAction(page, 'generateReport');
    await expectOutput(page.locator('#inventory-out'), /fleet|host|vm|container/i, 45_000);

    for (const kind of ['db', 'logs', 'proxy', 'pool', 'setup']) {
      await clickAction(page, 'loadSysInfo', kind);
      await expectOutput(page.locator('#sysinfo-out'), /No |status|routes|pool|setup|healthy|errors|DB|database/i, 45_000);
    }
  });

  test('Security read buttons render real output', async ({ page }) => {
    test.setTimeout(120_000);
    await clickNav(page, 'SECURITY');

    await expectOutput(page.locator('#sec-secrets-audit'), /SECRETS AUDIT|LEASES/i, 45_000);
    await expectOutput(page.locator('#sec-comply-status'), /COMPLIANCE|CIS/i, 45_000);

    await clickAction(page, 'loadSecretsLeases');
    await expectOutput(page.locator('#sec-secrets-detail'), /No secret leases|Key|Expires|Status/i, 45_000);
    await clickAction(page, 'loadSecretsScan');
    await expectOutput(page.locator('#sec-secrets-detail'), /No secrets|finding|Last scan|scan/i, 45_000);

    await page.locator('[data-view="sec-compliance"]:visible').first().click();
    await expectOutput(page.locator('#policy-out'), /Last scan|No |Pass|Fail|Score|compliance/i, 45_000);
  });

  test('Network read buttons render real output', async ({ page }) => {
    await clickNav(page, 'FLEET');
    await page.locator('[data-view="network"]:visible').first().click();

    for (const action of ['show', 'facts', 'interfaces', 'vlans', 'mac', 'arp', 'neighbors', 'environment']) {
      await clickAction(page, 'loadSwitchData', action);
      await expectOutput(page.locator('#switch-detail-out'), /switch|vlan|interface|mac|arp|neighbor|environment|uptime|version|No /i, 45_000);
    }
  });

  test('Settings read buttons render real output', async ({ page }) => {
    test.setTimeout(120_000);
    await clickNav(page, 'SETTINGS');

    await clickAction(page, 'loadCosts');
    await expectOutput(page.locator('#cost-summary'), /TOTAL \/ MONTH|TOTAL WATTS|RATE|kWh|No /i, 45_000);

    await clickAction(page, 'loadFederation');
    await expectOutput(page.locator('#fed-sites'), /No sites registered|Site|URL|Status|registered/i, 45_000);

    await clickAction(page, 'openApiDocs');
    await expectOutput(page.locator('#api-docs-out, #settings-api-out').first(), /api|endpoint|openapi|docs/i, 45_000);

    await clickAction(page, 'loadOpenApi');
    await expectOutput(page.locator('#api-docs-out'), /Endpoints|openapi|paths|version/i, 45_000);

    await clickAction(page, 'loadPrometheus');
    await expectOutput(page.locator('#api-docs-out'), /HELP|TYPE|freq_|python|process/i, 45_000);

    const openapi = await api(page, '/api/openapi.json');
    expect(openapi.status).toBe(200);
    expect(openapi.body).toBeTruthy();
  });
});

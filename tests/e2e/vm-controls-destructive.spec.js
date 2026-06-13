const { test, expect } = require('@playwright/test');

const USER = process.env.PVE_FREQ_USER;
const PASS = process.env.PVE_FREQ_PASS;
const RUN = process.env.PVE_FREQ_RUN_VM_CONTROL_E2E === '1';
const TARGET_VMID = Number(process.env.PVE_FREQ_TEST_VMID || '6000');
const SOURCE_TEMPLATE = process.env.PVE_FREQ_TEMPLATE_VMID ? Number(process.env.PVE_FREQ_TEMPLATE_VMID) : 0;
const TEST_NAME = process.env.PVE_FREQ_TEST_VM_NAME || `e2e-freq-controls-${TARGET_VMID}`;
const TEST_PREFIX = 'e2e-freq-controls-';
const RENAMED_NAME = `${TEST_NAME}-renamed`;
const CHANGED_VMID = Number(process.env.PVE_FREQ_TEST_CHANGED_VMID || String(TARGET_VMID + 1));
const TEST_SERVICE = process.env.PVE_FREQ_TEST_SERVICE || 'cron';
const TEST_STORAGE = process.env.PVE_FREQ_TEST_STORAGE || '';

function requireDestructiveLive() {
  test.skip(!RUN, 'Set PVE_FREQ_RUN_VM_CONTROL_E2E=1 to run destructive VM-control acceptance.');
  test.skip(!USER || !PASS, 'Set PVE_FREQ_USER and PVE_FREQ_PASS.');
  test.skip(!Number.isInteger(TARGET_VMID) || TARGET_VMID < 6000 || TARGET_VMID > 6099, 'PVE_FREQ_TEST_VMID must be 6000-6099.');
  test.skip(!Number.isInteger(CHANGED_VMID) || CHANGED_VMID < 6000 || CHANGED_VMID > 6099 || CHANGED_VMID === TARGET_VMID, 'PVE_FREQ_TEST_CHANGED_VMID must be a different 6000-6099 VMID.');
}

async function login(page) {
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await page.locator('#login-user').fill(USER);
  await page.locator('#login-pass').fill(PASS);
  await page.locator('#login-form').evaluate(form => form.requestSubmit());
  await page.locator('#login-overlay').waitFor({ state: 'hidden', timeout: 20_000 });
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

async function findVm(page, vmid) {
  const result = await api(page, '/api/vms');
  expect(result.status).toBe(200);
  return (result.body.vms || []).find(vm => Number(vm.vmid) === Number(vmid)) || null;
}

function assertTestVm(vm, label = 'test VM') {
  expect(vm, `${label} must exist`).toBeTruthy();
  expect(Number(vm.vmid), `${label} VMID must stay in disposable range`).toBeGreaterThanOrEqual(6000);
  expect(Number(vm.vmid), `${label} VMID must stay in disposable range`).toBeLessThanOrEqual(6099);
  expect(String(vm.name || ''), `${label} name must carry ${TEST_PREFIX} prefix before destructive action`).toMatch(new RegExp(`^${TEST_PREFIX}`));
  return vm;
}

async function waitForVm(page, vmid, predicate, label) {
  let last = null;
  for (let i = 0; i < 30; i += 1) {
    last = await findVm(page, vmid);
    if (last && predicate(last)) return last;
    await page.waitForTimeout(2_000);
  }
  throw new Error(`${label} did not settle for VM ${vmid}: ${JSON.stringify(last)}`);
}

async function destroyIfPresent(page, vmid) {
  const existing = await findVm(page, vmid);
  if (!existing) return;
  assertTestVm(existing, `cleanup target ${vmid}`);
  const stopped = await api(page, `/api/vm/power?vmid=${vmid}&action=stop`, { method: 'POST' });
  expect([200, 404, 409, 502]).toContain(stopped.status);
  const destroyed = await api(page, `/api/vm/destroy?vmid=${vmid}`, { method: 'POST' });
  expect(destroyed.status, JSON.stringify(destroyed.body, null, 2)).toBe(200);
  await expect.poll(async () => (await findVm(page, vmid)) === null, { timeout: 60_000 }).toBe(true);
}

async function resolveTemplate(page) {
  if (SOURCE_TEMPLATE) return SOURCE_TEMPLATE;
  const result = await api(page, '/api/vms');
  expect(result.status).toBe(200);
  const templates = (result.body.vms || [])
    .filter(vm => vm.category === 'templates' && Number(vm.vmid) >= 9000 && Number(vm.vmid) <= 9009)
    .sort((a, b) => Number(a.vmid) - Number(b.vmid));
  expect(templates.length, 'expected at least one 9000-9009 template from init discovery').toBeGreaterThan(0);
  return Number(templates[0].vmid);
}

async function acceptConfirm(page) {
  await expect(page.locator('#modal-container')).toBeVisible({ timeout: 10_000 });
  await page.locator('#modal-confirm-btn:visible').click();
}

async function openTestVmCard(page, vmid) {
  const card = page.locator(`.host-card[data-vmid="${vmid}"]`);
  for (let attempt = 0; attempt < 8; attempt += 1) {
    await page.getByRole('button', { name: 'FLEET', exact: true }).click();
    await page.locator('.host-card').first().waitFor({ timeout: 30_000 });
    const toggles = page.locator('[data-action="togglePveGroup"]');
    const count = await toggles.count();
    for (let i = 0; i < count; i += 1) {
      const toggle = toggles.nth(i);
      if (await toggle.isVisible()) {
        await toggle.click();
      }
    }
    if (await card.count()) break;
    await page.reload({ waitUntil: 'domcontentloaded' });
    await page.locator('#login-overlay').waitFor({ state: 'hidden', timeout: 20_000 }).catch(() => {});
    await page.waitForTimeout(2_000);
  }
  await expect(card, `VM card ${vmid}`).toBeVisible({ timeout: 30_000 });
  await card.click();
  await page.locator('#host-overlay.open').waitFor();
  await expect(page.locator('#host-overlay #hd-title')).toContainText(new RegExp(TEST_PREFIX, 'i'));
}

test.describe('destructive VM control acceptance', () => {
  test.setTimeout(10 * 60 * 1000);

  test.beforeEach(async ({ page }) => {
    requireDestructiveLive();
    await login(page);
  });

  test('sandbox clone exercises VM controls and host tools without touching owned VMs', async ({ page }) => {
    await destroyIfPresent(page, TARGET_VMID);
    await destroyIfPresent(page, CHANGED_VMID);

    const template = await resolveTemplate(page);
    const cloneParams = new URLSearchParams({
      vmid: String(template),
      newid: String(TARGET_VMID),
      name: TEST_NAME,
      full: '1'
    });
    if (TEST_STORAGE) cloneParams.set('storage', TEST_STORAGE);
    const clone = await api(page, `/api/vm/clone?${cloneParams}`, { method: 'POST' });
    expect(clone.status, JSON.stringify(clone.body, null, 2)).toBe(200);
    expect(clone.body.ok, JSON.stringify(clone.body, null, 2)).toBe(true);

    let vm = await waitForVm(page, TARGET_VMID, candidate => candidate.name === TEST_NAME, 'clone');
    assertTestVm(vm, 'cloned VM');
    expect(vm.category, JSON.stringify(vm, null, 2)).toBe('sandbox');
    expect(vm.allowed_actions).toEqual(expect.arrayContaining(['start', 'stop', 'snapshot', 'resize', 'migrate', 'configure', 'destroy']));

    await openTestVmCard(page, TARGET_VMID);

    await page.locator('#vm-new-name').fill(RENAMED_NAME);
    await page.locator(`[data-legacy-onclick="_vmRename(${TARGET_VMID})"]`).click();
    await acceptConfirm(page);
    await expect(page.locator('#vm-ctrl-out')).toContainText(/Renamed/i, { timeout: 30_000 });
    vm = assertTestVm(await waitForVm(page, TARGET_VMID, candidate => candidate.name === RENAMED_NAME, 'rename'), 'renamed VM');

    const tag = await api(page, `/api/vm/tag?vmid=${TARGET_VMID}&tags=e2e,freq-test`, { method: 'POST' });
    expect(tag.status, JSON.stringify(tag.body, null, 2)).toBe(200);
    expect(tag.body.ok, JSON.stringify(tag.body, null, 2)).toBe(true);

    await page.locator(`[data-legacy-onclick="_vmToggleResize(${TARGET_VMID})"]`).click();
    await page.locator('#vm-rz-cores').selectOption('1');
    await page.locator('#vm-rz-ram').selectOption('1024');
    await page.locator(`[data-legacy-onclick="_vmDoResize(${TARGET_VMID})"]`).click();
    await acceptConfirm(page);
    await expect(page.locator('#vm-ctrl-out')).toContainText(/Resized|Error:/i, { timeout: 45_000 });
    await expect(page.locator('#vm-ctrl-out')).not.toContainText(/Error:/i);

    const diskParams = new URLSearchParams({ vmid: String(TARGET_VMID), size: '1G' });
    if (TEST_STORAGE) diskParams.set('storage', TEST_STORAGE);
    const addDisk = await api(page, `/api/vm/add-disk?${diskParams}`, { method: 'POST' });
    expect(addDisk.status, JSON.stringify(addDisk.body, null, 2)).toBe(200);
    expect(addDisk.body.ok, JSON.stringify(addDisk.body, null, 2)).toBe(true);
    expect(addDisk.body.storage, JSON.stringify(addDisk.body, null, 2)).toBeTruthy();

    const snapName = `e2e-${Date.now()}`;
    const snap = await api(page, `/api/vm/snapshot?vmid=${TARGET_VMID}&name=${snapName}`, { method: 'POST' });
    expect(snap.status, JSON.stringify(snap.body, null, 2)).toBe(200);
    expect(snap.body.ok, JSON.stringify(snap.body, null, 2)).toBe(true);

    const snaps = await api(page, `/api/vm/snapshots?vmid=${TARGET_VMID}`);
    expect(snaps.status, JSON.stringify(snaps.body, null, 2)).toBe(200);
    expect(JSON.stringify(snaps.body)).toContain(snapName);

    const delSnap = await api(page, `/api/vm/delete-snapshot?vmid=${TARGET_VMID}&name=${snapName}`, { method: 'POST' });
    expect(delSnap.status, JSON.stringify(delSnap.body, null, 2)).toBe(200);
    expect(delSnap.body.ok, JSON.stringify(delSnap.body, null, 2)).toBe(true);

    await page.locator('#vm-new-id').fill(String(CHANGED_VMID));
    await page.locator(`[data-legacy-onclick="_vmChangeId(${TARGET_VMID})"]`).click();
    await acceptConfirm(page);
    await expect.poll(async () => (await findVm(page, TARGET_VMID)) === null, { timeout: 120_000 }).toBe(true);
    vm = assertTestVm(await waitForVm(page, CHANGED_VMID, candidate => candidate.name === RENAMED_NAME, 'change-id'), 'changed-id VM');

    const start = await api(page, `/api/vm/power?vmid=${TARGET_VMID}&action=start`, { method: 'POST' });
    expect(start.status, 'old VMID must not start after change-id').toBe(404);

    const startChanged = await api(page, `/api/vm/power?vmid=${CHANGED_VMID}&action=start`, { method: 'POST' });
    expect(startChanged.status, JSON.stringify(startChanged.body, null, 2)).toBe(200);
    expect(startChanged.body.ok, JSON.stringify(startChanged.body, null, 2)).toBe(true);
    vm = assertTestVm(await waitForVm(page, CHANGED_VMID, candidate => candidate.status === 'running', 'start'), 'running changed-id VM');

    await openTestVmCard(page, CHANGED_VMID);

    const stopButton = page.locator('#host-overlay button').filter({ hasText: 'STOP' }).first();
    await expect(stopButton).toBeVisible({ timeout: 30_000 });
    await stopButton.click();
    vm = assertTestVm(await waitForVm(page, CHANGED_VMID, candidate => candidate.status !== 'running', 'ui stop'), 'stopped changed-id VM');

    await page.locator('#host-overlay [data-action="closeCard"]').click();
    await page.locator('#host-overlay').waitFor({ state: 'hidden' });

    const startAgain = await api(page, `/api/vm/power?vmid=${CHANGED_VMID}&action=start`, { method: 'POST' });
    expect(startAgain.status, JSON.stringify(startAgain.body, null, 2)).toBe(200);
    expect(startAgain.body.ok, JSON.stringify(startAgain.body, null, 2)).toBe(true);
    vm = assertTestVm(await waitForVm(page, CHANGED_VMID, candidate => candidate.status === 'running', 'restart for host tools'), 'restarted changed-id VM');

    await openTestVmCard(page, CHANGED_VMID);

    const terminalButton = page.locator('#host-overlay button').filter({ hasText: /TERMINAL/ }).first();
    await expect(terminalButton).toBeVisible({ timeout: 30_000 });

    await page.locator('#host-overlay button').filter({ hasText: 'RUN CMD' }).first().click();
    await page.locator('#hd-cmd').fill('hostname');
    await page.locator('#hd-cmd').press('Enter');
    const execOut = page.locator('#hd-exec-out');
    await expect(execOut).not.toContainText(/Running:/, { timeout: 30_000 });
    await expect(execOut).not.toContainText(/No hosts matched|Permission denied|auth failed|unreachable|Error:/i);
    await expect(execOut).toContainText(/\S/);

    await page.locator('#host-overlay button').filter({ hasText: 'LOGS' }).first().click();
    await expect(page.locator('#hd-exec-out')).not.toContainText(/No hosts matched|Host not found|Permission denied|auth failed|unreachable|^Error:/i, { timeout: 30_000 });

    await page.locator('#host-overlay button').filter({ hasText: 'DIAGNOSE' }).first().click();
    await expect(page.locator('#hd-exec-out')).not.toContainText(/No hosts matched|Host not found|Permission denied|auth failed|unreachable|^Error:/i, { timeout: 45_000 });

    page.once('dialog', dialog => dialog.accept(TEST_SERVICE));
    await page.locator('#host-overlay button').filter({ hasText: 'RESTART SVC' }).first().click();
    await page.locator('#modal-confirm-btn').click();
    await expect(page.locator('#hd-exec-out')).toContainText(/active|completed|restart/i, { timeout: 45_000 });

    const stop = await api(page, `/api/vm/power?vmid=${CHANGED_VMID}&action=stop`, { method: 'POST' });
    expect(stop.status, JSON.stringify(stop.body, null, 2)).toBe(200);
    expect(stop.body.ok, JSON.stringify(stop.body, null, 2)).toBe(true);

    await destroyIfPresent(page, CHANGED_VMID);
  });
});

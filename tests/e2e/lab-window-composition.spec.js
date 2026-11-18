// Synthetic source composition only: the actual extracted application join and
// real child controllers/panels run against an in-memory original-auth port.
// No original HTTP/authentication/provider qualification or native action proof.
const fs = require('node:fs');
const path = require('node:path');
const {test, expect} = require('@playwright/test');
const web = path.resolve(__dirname, '../../freq/data/web/js');
const app = fs.readFileSync(path.join(web, 'app.js'), 'utf8');
const start = app.indexOf('function _loadRegisteredLab(){');
const end = app.indexOf('\nfunction _loadFleetOverviewMedia()', start);
if (start < 0 || end <= start) throw Error('Original registered lab join could not be extracted');
const originalJoin = app.slice(start, end);
const DOCUMENT = 'http://localhost/', WINDOW = '/api/lab/window', GUEST = '/api/lab/guest', POWER = '/api/lab/power';
const NOW = '2026-11-13T12:00:00Z', END = '2026-11-13T12:15:00Z';
const CONFIG = 'a'.repeat(64), POLICY = 'b'.repeat(64), FIRST = 'c'.repeat(64), SECOND = 'd'.repeat(64), OP = '1'.repeat(32);
function metadata(revision = FIRST, overrides = {}) {
  return {schema: 'pve-freq-lab-window-v1', target: {ref: 'fixed-synthetic-target', configuration_revision: CONFIG,
    estate: 'synthetic-estate', source: 'synthetic-provider.invalid', node: 'synthetic-node', kind: 'qemu', vmid: 120, name: 'synthetic-guest'},
  policy: {enabled: true, revision: POLICY, duration_seconds: 900, audience: 'original_session'},
  window: revision ? {ref: revision === FIRST ? 'synthetic-window-first' : 'synthetic-window-second', state: 'active',
    registration_revision: revision, qualified_at: NOW, expires_at: END, error: null} : null,
  busy: false, can_request: !revision, reason: null, ...overrides};
}
function guest(revision = FIRST, state = 'running', targetPatch = {}) {
  return {schema: 'pve-freq-lab-guest-view-v1', target: {ref: 'fixed-synthetic-target', registration_revision: revision,
    estate: 'synthetic-estate', source: 'synthetic-provider.invalid', node: 'synthetic-node', kind: 'qemu', vmid: 120,
    name: 'synthetic-guest', qualified_at: NOW, expires_at: END, ...targetPatch},
  capabilities: {lab_only: true, actions: ['start', 'shutdown']}, observation: {state, observed_at: NOW}, busy: false, operation: null};
}
function operation(terminal = false) {
  return {schema: 'pve-freq-lab-operation-view-v1', operation: {ref: OP, target_ref: 'fixed-synthetic-target',
    registration_revision: FIRST, retired: false, action: 'shutdown', expected_state: 'running',
    phase: terminal ? 'succeeded' : 'acknowledged', acknowledgement: 'received',
    task: {state: terminal ? 'succeeded' : 'running', exit: terminal ? 'OK' : null},
    observation: {state: terminal ? 'stopped' : 'running', observed_at: NOW}, error: null, created_at: NOW, updated_at: NOW}};
}
const button = (page, name) => page.getByRole('button', {name, exact: true});
async function mount(page, role = 'admin') {
  await page.evaluate(() => { if (window._registeredLabController) window._registeredLabController.dispose(); });
  await page.setContent('<main><h1>SYNTHETIC COMPOSITION — NO NATIVE ACTIONS</h1><div id="registered-lab-view">' +
    '<div id="lab-window-workspace"><p id="unowned-window">Unowned window sibling</p></div>' +
    '<section id="registered-lab-workspace"><p id="unowned-power">Unowned power sibling</p></section></div><div id="elsewhere"></div></main>');
  await page.evaluate(role => {
    window._registeredLabController = null; window._currentView = 'registered-lab'; window._currentRole = role;
    window._browserSessionActive = true; window._startupReadSequence = 1;
    window.ports = []; window.networkAttempts = []; window.cleanups = [];
    window._captureFleetPollAuth = () => {
      const sequence = window._startupReadSequence, role = window._currentRole;
      return () => window._browserSessionActive === true && sequence === window._startupReadSequence && role === window._currentRole;
    };
    window._onViewCleanup = callback => window.cleanups.push(callback);
    window._withCsrfHeader = headers => ({...headers, 'X-CSRF-Token': 'synthetic-port-only'});
    window._authFetch = (route, options) => {
      if (options.dispatchCurrent && options.dispatchCurrent() !== true) return Promise.reject(Error('synthetic-dispatch-refused'));
      return new Promise((resolve, reject) => {
        window.ports.push({route, method: options.method, payload: options.body ? JSON.parse(options.body) : null,
          signal: options.signal, credentials: options.credentials, cache: options.cache, redirect: options.redirect,
          readCurrent: options.readCurrent, dispatchCurrent: options.dispatchCurrent, resolve, reject, answered: false});
      });
    };
    window.fetch = (...args) => { window.networkAttempts.push(String(args[0])); throw Error('network forbidden'); };
    window.XMLHttpRequest = function () { window.networkAttempts.push('xhr'); throw Error('network forbidden'); };
    window.WebSocket = function () { window.networkAttempts.push('websocket'); throw Error('network forbidden'); };
  }, role);
  for (const file of ['lab-window-panel.js', 'lab-window-controller.js', 'registered-lab-panel.js', 'registered-lab-controller.js'])
    await page.addScriptTag({path: path.join(web, file)});
  await page.addScriptTag({content: originalJoin});
  await page.evaluate(() => _loadRegisteredLab());
}
async function pending(page, route, method = 'GET') {
  const find = () => page.evaluate(({route, method}) => window.ports.findIndex(call => call.route === route && call.method === method && !call.answered && !call.signal.aborted), {route, method});
  await expect.poll(find).toBeGreaterThanOrEqual(0); return find();
}
async function reply(page, index, data, status = 200) {
  await page.evaluate(({index, data, status}) => {
    const call = window.ports[index]; call.answered = true;
    call.resolve({status, headers: {get: name => name.toLowerCase() === 'content-type' ? 'application/json' : null}, json: async () => data});
  }, {index, data, status});
}
async function serve(page, route, data, status = 200, method = 'GET') { const index = await pending(page, route, method); await reply(page, index, data, status); return index; }
async function count(page, route, method = 'GET') { return page.evaluate(({route, method}) => window.ports.filter(call => call.route === route && call.method === method).length, {route, method}); }
async function connect(page, meta = metadata(), observed = guest()) {
  await serve(page, WINDOW, meta); await serve(page, GUEST, observed);
}
test.beforeEach(async ({page, context}) => {
  page.externalAttempts = [];
  page.on('request', request => { if (request.url() !== DOCUMENT) page.externalAttempts.push(request.url()); });
  await context.route('**/*', route => route.request().url() === DOCUMENT && route.request().resourceType() === 'document' ?
    route.fulfill({contentType: 'text/html', body: '<!doctype html><title>Synthetic lab composition</title>'}) : route.abort('blockedbyclient'));
  await page.goto(DOCUMENT);
  expect(await page.evaluate(() => isSecureContext && Function.prototype.toString.call(crypto.randomUUID).includes('[native code]'))).toBe(true);
  await page.clock.install({time: new Date(NOW)});
});
test.afterEach(async ({page}) => {
  expect(await page.evaluate(() => window.networkAttempts || [])).toEqual([]);
  expect(page.externalAttempts).toEqual([]);
  expect(await page.evaluate(() => (window.ports || []).every(call => call.credentials === 'same-origin' && call.cache === 'no-store' && call.redirect === 'error' &&
    (call.route === '/api/lab/window' || call.route === '/api/lab/guest' || call.route === '/api/lab/power' || /^\/api\/lab\/operations\/[a-f0-9]{32}$/.test(call.route))))).toBe(true);
  await page.evaluate(() => { if (window._registeredLabController) window._registeredLabController.dispose(); });
});

test('synthetic original join starts guest read after confirmed window and requires exact effective revision and dates', async ({page}) => {
  for (const mismatch of ['revision', 'dates', 'none']) {
    await mount(page); expect(await count(page, GUEST)).toBe(0);
    const firstWindow = await serve(page, WINDOW, metadata());
    const freshGuest = await pending(page, GUEST); expect(freshGuest).toBeGreaterThan(firstWindow);
    await expect(button(page, 'Shut down')).toBeDisabled();
    await reply(page, freshGuest, mismatch === 'revision' ? guest(SECOND) : mismatch === 'dates' ?
      guest(FIRST, 'running', {qualified_at: '2026-11-13T11:59:59Z', expires_at: '2026-11-13T12:14:59Z'}) : guest());
    await expect(page.locator('[data-lab-target]')).toContainText('synthetic-guest');
    if (mismatch === 'none') await expect(button(page, 'Shut down')).toBeEnabled();
    else await expect(button(page, 'Shut down')).toBeDisabled();
    expect(await count(page, POWER, 'POST')).toBe(0);
  }
});

test('synthetic manual policy fallback requires exact configured revision', async ({page}) => {
  for (const revision of [FIRST, CONFIG]) {
    await mount(page);
    await connect(page, metadata(null, {policy: {enabled: false, revision: null, duration_seconds: 900, audience: 'original_session'},
      can_request: false, reason: 'policy_disabled'}), guest(revision));
    await expect(page.locator('[data-lab-target]')).toContainText('synthetic-guest');
    if (revision === CONFIG) await expect(button(page, 'Shut down')).toBeEnabled(); else await expect(button(page, 'Shut down')).toBeDisabled();
  }
});

test('synthetic viewer reads configured metadata without any restricted guest request or logout', async ({page}) => {
  await mount(page, 'viewer'); await serve(page, WINDOW, metadata(null, {can_request: false}));
  await expect(page.locator('[data-lab-window-target]')).toContainText('synthetic-guest');
  await expect(button(page, 'Request lab window')).toBeDisabled(); await expect(button(page, 'Shut down')).toBeDisabled();
  expect(await count(page, GUEST)).toBe(0); expect(await count(page, POWER, 'POST')).toBe(0);
  expect(await page.evaluate(() => window._browserSessionActive)).toBe(true);
});

test('synthetic lost window click stays unknown while current own-session grant plus fresh guest can enable power', async ({page}) => {
  await mount(page); await connect(page, metadata(null), guest(CONFIG));
  await expect(button(page, 'Request lab window')).toBeEnabled(); await button(page, 'Request lab window').click();
  const post = await pending(page, WINDOW, 'POST');
  await page.evaluate(index => { const call = window.ports[index]; call.answered = true; call.reject(Error('synthetic lost acknowledgement')); }, post);
  await expect(page.locator('[data-lab-window-facts]')).toContainText('Unknown outcome');
  await button(page, 'Refresh window status').click(); const read = await serve(page, WINDOW, metadata());
  const fresh = await pending(page, GUEST); expect(fresh).toBeGreaterThan(read);
  await expect(button(page, 'Shut down')).toBeDisabled();
  await reply(page, fresh, guest()); await expect(button(page, 'Shut down')).toBeEnabled();
  await expect(page.locator('[data-lab-window-facts]')).toContainText('Unknown outcome');
  await expect(button(page, 'Request lab window')).toBeDisabled();
  expect(await count(page, WINDOW, 'POST')).toBe(1); expect(await count(page, POWER, 'POST')).toBe(0);
});

test('synthetic changed grant preserves original unsettled power attempt then admits only a new post-metadata guest read', async ({page}) => {
  await mount(page); await connect(page); await expect(button(page, 'Shut down')).toBeEnabled();
  await button(page, 'Shut down').click(); await serve(page, POWER, operation(), 202, 'POST');
  await button(page, 'Refresh window status').click(); const newerWindow = await serve(page, WINDOW, metadata(SECOND));
  expect(await count(page, GUEST)).toBe(1); await expect(button(page, 'Start')).toBeDisabled();
  await page.clock.runFor(2001);
  const originalTask = await pending(page, '/api/lab/operations/' + OP);
  await reply(page, originalTask, operation(true));
  const oldConsumersRead = await pending(page, GUEST); expect(oldConsumersRead).toBeGreaterThan(newerWindow);
  await reply(page, oldConsumersRead, guest(SECOND, 'stopped'));
  const replacementRead = await pending(page, GUEST); expect(replacementRead).toBeGreaterThan(oldConsumersRead);
  await expect(button(page, 'Start')).toBeDisabled();
  await reply(page, replacementRead, guest(SECOND, 'stopped')); await expect(button(page, 'Start')).toBeEnabled();
  expect(await count(page, POWER, 'POST')).toBe(1); expect(await count(page, WINDOW, 'POST')).toBe(0);
  await expect(page.locator('#unowned-power')).toHaveText('Unowned power sibling');
});

test('synthetic reload recovers an original power task and refreshes cached busy metadata once without qualification or loops', async ({page}) => {
  for (const remainsBusy of [false, true]) {
    await mount(page);
    await serve(page, WINDOW, metadata(FIRST, {busy: true, can_request: false, reason: 'target_busy'}));
    const recovered = guest();
    recovered.busy = true;
    recovered.operation = {ref: OP, target_ref: 'fixed-synthetic-target', registration_revision: FIRST,
      retired: false, action: 'shutdown', phase: 'acknowledged'};
    await serve(page, GUEST, recovered);
    await serve(page, '/api/lab/operations/' + OP, operation());
    await expect(button(page, 'Start')).toBeDisabled();
    expect(await count(page, WINDOW)).toBe(1);
    await page.clock.runFor(2001);
    await serve(page, '/api/lab/operations/' + OP, operation(true));
    const currentGuest = await pending(page, GUEST);
    expect(await count(page, WINDOW)).toBe(1);
    await reply(page, currentGuest, guest(FIRST, 'stopped'));
    const safeRead = await pending(page, WINDOW);
    expect(safeRead).toBeGreaterThan(currentGuest);
    expect(await count(page, WINDOW)).toBe(2);
    await expect(button(page, 'Start')).toBeDisabled();
    await reply(page, safeRead, metadata(FIRST, {busy: remainsBusy, can_request: false, reason: remainsBusy ? 'target_busy' : null}));
    if (remainsBusy) await expect(button(page, 'Start')).toBeDisabled();
    else await expect(button(page, 'Start')).toBeEnabled();
    const before = await page.evaluate(() => window.ports.length);
    await page.clock.runFor(5000);
    expect(await count(page, WINDOW)).toBe(2);
    expect(await count(page, GUEST)).toBe(2);
    expect(await page.evaluate(() => window.ports.length)).toBe(before);
    expect(await count(page, WINDOW, 'POST')).toBe(0);
    expect(await count(page, POWER, 'POST')).toBe(0);
    expect(await page.evaluate(() => window.ports.filter(call => call.route.startsWith('/api/lab/operations/')).every(call => call.route === '/api/lab/operations/' + '1'.repeat(32)))).toBe(true);
  }
});

for (const mode of ['detach-reinsert', 'session-change', 'route-departure']) {
  test('synthetic composite permanently retires held metadata on ' + mode, async ({page}) => {
    await mount(page); const held = await pending(page, WINDOW);
    await page.evaluate(mode => {
      if (mode === 'detach-reinsert') { const root = document.querySelector('#lab-window-workspace'), parent = root.parentNode; root.remove(); parent.prepend(root); }
      if (mode === 'session-change') window._startupReadSequence++;
      if (mode === 'route-departure') { window._currentView = 'fleet'; window.cleanups.forEach(callback => callback()); }
    }, mode);
    await reply(page, held, metadata());
    await expect(page.locator('.lab-window-shell')).toHaveCount(0);
    expect(await count(page, GUEST)).toBe(0); expect(await count(page, WINDOW, 'POST')).toBe(0);
    await expect(page.locator('#unowned-window')).toHaveText('Unowned window sibling');
    await expect(page.locator('#unowned-power')).toHaveText('Unowned power sibling');
  });
}

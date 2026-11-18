// Synthetic exact-metadata HTTP ports; no original HTTP/session/provider/window
// qualification or native action is exercised. Initial GET needs no live grant.
const path = require('node:path');
const { test, expect } = require('@playwright/test');
const web = path.resolve(__dirname, '../../freq/data/web/js');
const DOCUMENT = 'http://localhost/', WINDOW = '/api/lab/window';
const NOW = '2026-11-13T12:00:00Z';
const CONFIG = 'a'.repeat(64), POLICY = 'b'.repeat(64), EFFECTIVE = 'c'.repeat(64);
const controls = page => ({ request: page.getByRole('button', { name: 'Request lab window', exact: true }),
  refresh: page.getByRole('button', { name: 'Refresh window status', exact: true }) });
function metadata(patch = {}) {
  return { schema: 'pve-freq-lab-window-v1', target: {
    ref: 'configured-synthetic-target', configuration_revision: CONFIG, estate: 'synthetic-lab', source: 'synthetic-lab.invalid',
    node: 'synthetic-node', kind: 'qemu', vmid: 120, name: 'synthetic-window-guest'
  }, policy: { enabled: true, revision: POLICY, duration_seconds: 900, audience: 'original_session' },
  window: null, busy: false, can_request: true, reason: null, ...patch };
}
function activeWindow(patch = {}) {
  return { ref: 'synthetic-window-a', state: 'active', registration_revision: EFFECTIVE,
    qualified_at: NOW, expires_at: '2026-11-13T12:15:00Z', error: null, ...patch };
}
function active(patch = {}) { return metadata({ window: activeWindow(), can_request: false, ...patch }); }
async function mount(page, admin = true, eligible = true) {
  await page.evaluate(() => { if (window.controller) window.controller.dispose(); });
  await page.clock.setSystemTime(new Date(NOW));
  await page.setContent('<main><h1>SYNTHETIC WINDOW CONTROLLER PORTS — NO NATIVE QUALIFICATION</h1>' +
    '<div id="root"><p id="unowned">Unowned sibling remains</p></div><div id="other-parent"></div></main>');
  await page.evaluate(({ admin, eligible }) => {
    window.current = true; window.admin = admin; window.localPowerSafe = eligible;
    window.calls = []; window.grants = []; window.stateChanges = []; window.readSettled = []; window.networkAttempts = [];
    window.fetch = (...args) => { window.networkAttempts.push(String(args[0])); return Promise.reject(Error('network forbidden')); };
    window.XMLHttpRequest = function () { window.networkAttempts.push('xhr'); throw Error('network forbidden'); };
    window.WebSocket = function () { window.networkAttempts.push('websocket'); throw Error('network forbidden'); };
  }, { admin, eligible });
  await page.addScriptTag({ path: path.join(web, 'lab-window-panel.js') });
  await page.addScriptTag({ path: path.join(web, 'lab-window-controller.js') });
  await page.evaluate(() => {
    window.controller = FreqLabWindowController.create({ root: document.querySelector('#root'),
      isCurrent: () => { if (window.current === 'throw') throw Error('retired'); return window.current; },
      isAdmin: () => window.admin, canRequest: () => window.localPowerSafe,
      onStateChange: (...args) => window.stateChanges.push(JSON.parse(JSON.stringify(args))),
      onReadSettled: value => window.readSettled.push(value),
      onGrant: grant => window.grants.push(JSON.parse(JSON.stringify(grant))),
      request: (method, route, payload, signal) => new Promise((resolve, reject) => {
        window.calls.push({ method, route, payload: payload == null ? payload : JSON.parse(JSON.stringify(payload)), signal, resolve, reject, answered: false });
      })
    });
    void window.controller.load();
  });
}
async function pending(page, method) {
  const find = () => page.evaluate(method => window.calls.findIndex(call => call.method === method && !call.answered && !call.signal.aborted), method);
  await expect.poll(find).toBeGreaterThanOrEqual(0); return find();
}
async function reply(page, index, data, status = 200) {
  await page.evaluate(({ index, data, status }) => { const call = window.calls[index]; call.answered = true; call.resolve({ status, data }); }, { index, data, status });
}
async function serve(page, method, data, status = 200) { const index = await pending(page, method); await reply(page, index, data, status); return index; }
async function load(page) { await page.evaluate(() => { void window.controller.load(); }); }
async function posts(page) { return page.evaluate(() => window.calls.filter(call => call.method === 'POST').map(call => call.payload)); }
async function unresolved(page) { return page.evaluate(() => window.controller.hasUnresolvedSubmission()); }
async function grant(page) { return page.evaluate(() => window.controller.getGrant()); }
async function requestWindow(page) {
  await serve(page, 'GET', metadata());
  await controls(page).request.click(); return pending(page, 'POST');
}
test.beforeEach(async ({ page, context }) => {
  page.windowFixtureRequests = [];
  page.on('request', request => { if (request.url() !== DOCUMENT) page.windowFixtureRequests.push(request.url()); });
  await context.route('**/*', route => {
    const request = route.request();
    if (request.url() === DOCUMENT && request.method() === 'GET' && request.resourceType() === 'document')
      return route.fulfill({ contentType: 'text/html', body: '<!doctype html><title>Synthetic window controller</title>' });
    return route.abort('blockedbyclient');
  });
  await page.goto(DOCUMENT);
  expect(await page.evaluate(() => isSecureContext && Function.prototype.toString.call(crypto.randomUUID).includes('[native code]'))).toBe(true);
  await page.clock.install({ time: new Date(NOW) });
});
test.afterEach(async ({ page }) => {
  expect(await page.evaluate(() => window.networkAttempts || [])).toEqual([]); expect(page.windowFixtureRequests).toEqual([]);
  expect(await page.evaluate(() => (window.calls || []).every(call => call.route === '/api/lab/window' && ['GET', 'POST'].includes(call.method)))).toBe(true);
  await page.evaluate(() => { if (window.controller) window.controller.dispose(); });
});

test('synthetic inactive metadata permits one exact four-string intent and independent GET confirmation before grant', async ({ page }) => {
  await mount(page);
  const post = await requestWindow(page), payload = (await posts(page))[0];
  expect(Object.keys(payload).sort()).toEqual(['configuration_revision', 'policy_revision', 'request_key', 'target_ref']);
  expect(Object.values(payload).every(value => typeof value === 'string')).toBe(true);
  expect(payload).toMatchObject({ target_ref: 'configured-synthetic-target', configuration_revision: CONFIG, policy_revision: POLICY });
  expect(payload.request_key).toMatch(/^[\x21-\x7e]{1,128}$/);
  for (const value of Object.values(payload)) await expect(page.locator('#root')).not.toContainText(value);
  await expect(controls(page).request).toBeDisabled(); expect(await unresolved(page)).toBe(true);
  await controls(page).request.evaluate(button => { button.click(); button.dispatchEvent(new MouseEvent('click', { bubbles: true })); });
  expect(await posts(page)).toHaveLength(1);
  await reply(page, post, active(), 201);
  await pending(page, 'GET');
  expect(await grant(page)).toBeNull(); expect(await page.evaluate(() => window.grants)).toEqual([]);
  expect(await page.evaluate(() => window.readSettled.length)).toBe(1);
  expect(await page.evaluate(() => window.readSettled.some(read => read.ok && read.metadata?.window?.state === 'active'))).toBe(false);
  await serve(page, 'GET', active());
  await expect.poll(() => grant(page)).toEqual({ ref: 'configured-synthetic-target', revision: EFFECTIVE, startsAt: NOW, expiresAt: '2026-11-13T12:15:00Z' });
  expect(await unresolved(page)).toBe(false);
  expect(await page.evaluate(() => window.grants)).toHaveLength(1);
  const confirmed = await page.evaluate(() => window.readSettled.filter(read => read.ok && read.metadata?.window?.state === 'active'));
  expect(confirmed).toHaveLength(1); expect(confirmed[0].metadata).toEqual(active());
  expect(JSON.stringify(confirmed)).not.toContain(payload.request_key);
  await page.evaluate(() => {
    const publicCopy = window.readSettled.find(read => read.metadata?.window?.state === 'active');
    try { publicCopy.metadata.target.ref = 'mutated-public-copy'; publicCopy.metadata.window.registration_revision = 'd'.repeat(64); } catch (_) {}
  });
  expect(await grant(page)).toMatchObject({ ref: 'configured-synthetic-target', revision: EFFECTIVE });
  const before = await page.evaluate(() => window.calls.length);
  await page.clock.fastForward(6001); expect(await page.evaluate(() => window.calls.length)).toBe(before);
});

test('synthetic metadata is readable for every role; private admin and local-power guards remain authoritative', async ({ page }) => {
  for (const label of ['viewer', 'operator', 'admin', 'protected']) {
    const privileged = ['admin', 'protected'].includes(label);
    await mount(page, privileged); await serve(page, 'GET', metadata({ can_request: privileged }));
    await expect(page.locator('[data-lab-window-target]')).toContainText('synthetic-window-guest');
    if (privileged) await expect(controls(page).request).toBeEnabled(); else await expect(controls(page).request).toBeDisabled();
    expect(await posts(page)).toEqual([]); expect(await grant(page)).toBeNull();
  }
  for (const [admin, safe] of [[false, true], ['true', true], [true, false], [true, 'true']]) {
    await mount(page, admin, safe); await serve(page, 'GET', metadata()); await expect(controls(page).request).toBeDisabled();
  }
});

test('synthetic missing policy/target, unknown busy, invalid schema and malformed binding never admit requests or grants', async ({ page }) => {
  for (const data of [
    metadata({ target: null, policy: { enabled: false, revision: null, duration_seconds: 900, audience: 'original_session' }, can_request: false }),
    metadata({ policy: { enabled: false, revision: null, duration_seconds: 900, audience: 'original_session' }, can_request: false }),
    metadata({ busy: null, can_request: false }), metadata({ busy: true, can_request: false }), metadata({ schema: 'wrong' }),
    metadata({ target: { ...metadata().target, configuration_revision: 'invalid' } }),
    metadata({ policy: { ...metadata().policy, duration_seconds: 901 } }),
    metadata({ policy: { ...metadata().policy, audience: 'all_sessions' } }),
    metadata({ unexpected: 'not-an-exact-DTO' }), metadata({ can_request: 'true' }),
    metadata({ reason: '<script>not_a_fixed_code</script>' })
  ]) {
    await mount(page); await serve(page, 'GET', data); await expect(controls(page).request).toBeDisabled();
    expect(await grant(page)).toBeNull(); expect(await posts(page)).toEqual([]);
  }
  await mount(page); await pending(page, 'GET');
  await expect(controls(page).request).toBeDisabled(); await load(page);
  expect(await page.evaluate(() => window.calls.length)).toBe(1);
});

test('synthetic initial active GET may grant but future, expired, invalid UTC or overlong windows never grant early', async ({ page }) => {
  await mount(page); await serve(page, 'GET', active());
  await expect.poll(() => grant(page)).not.toBeNull(); expect(await posts(page)).toEqual([]);
  await page.evaluate(() => { window.admin = false; }); expect(await grant(page)).toBeNull();
  await mount(page); await serve(page, 'GET', active({ window: activeWindow({
    qualified_at: '2026-11-13T12:00:00+00:00', expires_at: '2026-11-13T12:15:00+00:00'
  }) }));
  await expect.poll(() => grant(page)).not.toBeNull();
  for (const window of [
    activeWindow({ qualified_at: '2026-11-13T12:01:00Z', expires_at: '2026-11-13T12:16:00Z' }),
    activeWindow({ state: 'expired', qualified_at: '2026-11-13T11:30:00Z', expires_at: '2026-11-13T11:45:00Z' }),
    activeWindow({ qualified_at: '2026-02-30T12:00:00Z' }), activeWindow({ qualified_at: '2026-11-13T12:00:00+01:00' }),
    activeWindow({ expires_at: 'not-a-date' }), activeWindow({ expires_at: '2026-11-13T12:15:01Z' }),
    activeWindow({ registration_revision: null })
  ]) {
    await mount(page); await serve(page, 'GET', active({ window }));
    expect(await grant(page)).toBeNull(); expect(await page.evaluate(() => window.grants)).toEqual([]); expect(await posts(page)).toEqual([]);
  }
  await mount(page); await serve(page, 'GET', active()); await expect.poll(() => grant(page)).not.toBeNull();
  const before = await page.evaluate(() => window.calls.length);
  await page.clock.fastForward(900001);
  expect(await grant(page)).toBeNull(); expect(await posts(page)).toEqual([]);
  expect(await page.evaluate(() => window.calls.length)).toBe(before);
});

test('synthetic lost, malformed or HTTP-error submission stays unresolved despite busy-false refresh, with no retry or new key', async ({ page }) => {
  for (const failure of ['lost', 'malformed', 'http-error', 'timeout']) {
    await mount(page); const post = await requestWindow(page), key = (await posts(page))[0].request_key;
    if (failure === 'lost') await page.evaluate(index => { window.calls[index].answered = true; window.calls[index].reject(Error('synthetic lost reply')); }, post);
    else if (failure === 'timeout') await page.clock.fastForward(20001);
    else await reply(page, post, failure === 'malformed' ? { schema: 'wrong' } : { error: 'unavailable' }, failure === 'malformed' ? 201 : 503);
    await expect.poll(() => unresolved(page)).toBe(true); await expect(controls(page).request).toBeDisabled();
    await load(page); await serve(page, 'GET', metadata());
    expect(await unresolved(page)).toBe(true); expect(await grant(page)).toBeNull();
    await expect(controls(page).request).toBeDisabled();
    await load(page); await serve(page, 'GET', active());
    await expect.poll(() => grant(page)).toMatchObject({ ref: 'configured-synthetic-target', revision: EFFECTIVE });
    expect(await unresolved(page)).toBe(true);
    expect(await page.evaluate(() => window.grants)).toHaveLength(1);
    await expect(controls(page).request).toBeDisabled();
    const facts = page.locator('[data-lab-window-facts]');
    await expect(facts.getByText('Request status', { exact: true }).locator('xpath=following-sibling::dd[1]')).toHaveText('Unknown outcome');
    await expect(facts.getByText('Pending work', { exact: true }).locator('xpath=following-sibling::dd[1]')).toHaveText('None reported');
    // This independent session grant is not attributed to the lost click: a
    // second read of that latest ref must not clear its unknown-outcome latch.
    await load(page); await serve(page, 'GET', active());
    expect(await unresolved(page)).toBe(true); expect(await page.evaluate(() => window.grants)).toHaveLength(1);
    await page.clock.fastForward(30001);
    expect(await posts(page)).toHaveLength(1); expect((await posts(page))[0].request_key).toBe(key);
  }
});

test('synthetic known preparing reference recovers and same-ref committed bindings cannot change', async ({ page }) => {
  const preparing = active({ window: activeWindow({ state: 'preparing', registration_revision: null, qualified_at: null, expires_at: null }) });
  await mount(page); const post = await requestWindow(page); await reply(page, post, preparing, 202);
  await serve(page, 'GET', preparing); expect(await unresolved(page)).toBe(true); expect(await grant(page)).toBeNull();
  await load(page); await serve(page, 'GET', active());
  await expect.poll(() => grant(page)).not.toBeNull(); expect(await unresolved(page)).toBe(false); expect(await posts(page)).toHaveLength(1);
  for (const patch of [
    { target: { ...metadata().target, ref: 'different-target' } },
    { target: { ...metadata().target, configuration_revision: 'd'.repeat(64) } },
    { policy: { ...metadata().policy, revision: 'e'.repeat(64) } },
    { window: activeWindow({ registration_revision: 'f'.repeat(64) }) },
    { window: activeWindow({ qualified_at: '2026-11-13T11:59:59Z', expires_at: '2026-11-13T12:14:59Z' }) },
    { window: activeWindow({ expires_at: '2026-11-13T12:14:59Z' }) }
  ]) {
    await mount(page); await reply(page, await requestWindow(page), active(), 201);
    await serve(page, 'GET', active(patch));
    expect(await grant(page)).toBeNull(); expect(await page.evaluate(() => window.grants)).toEqual([]);
    await expect(controls(page).request).toBeDisabled(); expect(await posts(page)).toHaveLength(1);
  }
});

test('synthetic known active POST acknowledgement survives failed current-window reads without granting or retrying', async ({ page }) => {
  await mount(page); const post = await requestWindow(page), key = (await posts(page))[0].request_key;
  await reply(page, post, active(), 201);
  await serve(page, 'GET', { error: 'qualification_unavailable' }, 503);
  await expect(page.locator('[data-lab-window-facts]')).toContainText('Acknowledged');
  expect(await unresolved(page)).toBe(false); expect(await grant(page)).toBeNull();
  expect(await page.evaluate(() => window.grants)).toEqual([]);
  expect(await page.evaluate(() => window.stateChanges.at(-1)[0])).toEqual({ pending: false, unknown: false, loading: false });
  expect(await page.evaluate(() => window.readSettled.at(-1))).toEqual({ ok: false, metadata: null });
  await expect(controls(page).request).toBeDisabled();
  await load(page); await serve(page, 'GET', { schema: 'malformed-current-window' });
  await expect(page.locator('[data-lab-window-facts]')).toContainText('Acknowledged');
  expect(await unresolved(page)).toBe(false); expect(await grant(page)).toBeNull();
  expect(await page.evaluate(() => window.grants)).toEqual([]);
  expect(await posts(page)).toHaveLength(1); expect((await posts(page))[0].request_key).toBe(key);
  await load(page); await serve(page, 'GET', active());
  await expect.poll(() => grant(page)).toMatchObject({ ref: 'configured-synthetic-target', revision: EFFECTIVE });
  expect(await page.evaluate(() => window.grants)).toHaveLength(1);
  expect(await posts(page)).toHaveLength(1); expect((await posts(page))[0].request_key).toBe(key);
});

test('synthetic preparing POST followed by failed current-window read remains unknown and unresolved', async ({ page }) => {
  await mount(page); const post = await requestWindow(page), key = (await posts(page))[0].request_key;
  const preparing = active({ window: activeWindow({ state: 'preparing', registration_revision: null, qualified_at: null, expires_at: null }) });
  await reply(page, post, preparing, 202);
  await serve(page, 'GET', { error: 'qualification_unavailable' }, 503);
  await expect(page.locator('[data-lab-window-facts]')).toContainText('Unknown outcome');
  expect(await unresolved(page)).toBe(true); expect(await grant(page)).toBeNull();
  expect(await page.evaluate(() => window.grants)).toEqual([]);
  expect(await page.evaluate(() => window.stateChanges.at(-1)[0])).toEqual({ pending: false, unknown: true, loading: false });
  expect(await page.evaluate(() => window.readSettled.at(-1))).toEqual({ ok: false, metadata: null });
  await expect(controls(page).request).toBeDisabled();
  expect(await posts(page)).toHaveLength(1); expect((await posts(page))[0].request_key).toBe(key);
});

test('synthetic current other-tab grant is authoritative without relabeling a known earlier click', async ({ page }) => {
  for (const preparing of [true, false]) {
    await mount(page); const post = await requestWindow(page), key = (await posts(page))[0].request_key;
    const postWindow = preparing ? activeWindow({ state: 'preparing', registration_revision: null, qualified_at: null, expires_at: null }) : activeWindow();
    await reply(page, post, active({ window: postWindow }), preparing ? 202 : 201);
    const currentOtherTab = active({ window: activeWindow({ ref: 'current-other-tab-window', registration_revision: 'd'.repeat(64) }) });
    await serve(page, 'GET', currentOtherTab);
    await expect.poll(() => grant(page)).toMatchObject({ ref: 'configured-synthetic-target', revision: 'd'.repeat(64) });
    // A received active acknowledgement remains known; a preparing click whose
    // own final result was replaced by another tab remains unresolved.
    expect(await unresolved(page)).toBe(preparing);
    await load(page); await serve(page, 'GET', currentOtherTab);
    expect(await unresolved(page)).toBe(preparing);
    expect(await page.evaluate(() => window.grants)).toHaveLength(1);
    await expect(controls(page).request).toBeDisabled();
    expect(await posts(page)).toHaveLength(1); expect((await posts(page))[0].request_key).toBe(key);
    await expect(page.locator('#root')).not.toContainText('current-other-tab-window');
  }
});

test('synthetic exact definitive error-only refusals read fresh metadata without an unknown-submission latch or automatic retry', async ({ page }) => {
  const refusals = [[400, 'invalid_request'], [404, 'not_found'], [405, 'method_not_allowed'],
    ...['https_required', 'authentication_required', 'same_origin_required', 'csrf_required', 'role_required'].map(code => [403, code]),
    ...['registration_changed', 'policy_changed', 'request_conflict', 'qualification_busy', 'target_busy'].map(code => [409, code])];
  for (const [status, code] of refusals) {
    await mount(page); const post = await requestWindow(page), key = (await posts(page))[0].request_key;
    await reply(page, post, { error: code }, status);
    await pending(page, 'GET');
    expect(await unresolved(page)).toBe(false); expect(await grant(page)).toBeNull();
    await serve(page, 'GET', metadata());
    expect(await unresolved(page)).toBe(false); expect(await grant(page)).toBeNull();
    await expect(page.locator('[data-lab-window-facts]').getByText('Request status', { exact: true }).locator('xpath=following-sibling::dd[1]')).toHaveText('Refused');
    await expect(controls(page).request).toBeEnabled();
    await page.clock.fastForward(1001);
    expect(await posts(page)).toHaveLength(1); expect((await posts(page))[0].request_key).toBe(key);
  }
});

test('synthetic wrong-status, extra-field and unknown errors remain uncertain and never expose raw details', async ({ page }) => {
  const privateText = 'PRIVATE_PROVIDER_DETAIL <img src=x onerror=alert(1)>';
  for (const [status, data] of [[503, { error: 'invalid_request' }], [409, { error: 'unrecognized_code' }],
    [400, { error: 'invalid_request', extra: true }], [200, { error: 'invalid_request' }], [503, { error: privateText }]]) {
    await mount(page); await reply(page, await requestWindow(page), data, status);
    await expect.poll(() => unresolved(page)).toBe(true); expect(await grant(page)).toBeNull();
    await expect(controls(page).request).toBeDisabled();
    await expect(page.locator('#root')).not.toContainText(privateText); await expect(page.locator('#root img')).toHaveCount(0);
    await page.clock.fastForward(1001); expect(await posts(page)).toHaveLength(1);
    expect(await page.evaluate(() => window.calls.filter(call => call.method === 'GET').length)).toBe(1);
  }
});

test('synthetic session_retired from original GET or POST permanently disposes without recovery reads or grants', async ({ page }) => {
  for (const phase of ['GET', 'POST']) {
    await mount(page); const held = phase === 'POST' ? await requestWindow(page) : await pending(page, 'GET');
    const before = await page.evaluate(() => ({ calls: window.calls.length, reads: window.readSettled.length }));
    await reply(page, held, { error: 'session_retired' }, 403);
    await expect(page.locator('#root .lab-window-shell')).toHaveCount(0);
    expect(await grant(page)).toBeNull(); expect(await page.evaluate(() => window.grants)).toEqual([]);
    await load(page); await page.clock.fastForward(30001);
    expect(await page.evaluate(() => window.calls.length)).toBe(before.calls);
    expect(await page.evaluate(() => window.readSettled.length)).toBe(before.reads);
    expect(await posts(page)).toHaveLength(phase === 'POST' ? 1 : 0);
    await expect(page.locator('#unowned')).toHaveText('Unowned sibling remains');
  }
});

test('synthetic rejected original window permits only a later explicit intent with a distinct native key', async ({ page }) => {
  await mount(page);
  const first = await requestWindow(page), firstKey = (await posts(page))[0].request_key;
  const rejected = metadata({ window: activeWindow({ state: 'rejected', registration_revision: null, qualified_at: null, expires_at: null }) });
  await reply(page, first, rejected, 409); await serve(page, 'GET', rejected);
  expect(await unresolved(page)).toBe(false); expect(await grant(page)).toBeNull();
  await expect(controls(page).request).toBeEnabled();
  await page.clock.fastForward(1001); expect(await posts(page)).toHaveLength(1);
  await controls(page).request.click(); await pending(page, 'POST');
  const payloads = await posts(page);
  expect(payloads).toHaveLength(2); expect(payloads[1].request_key).not.toBe(firstKey);
  expect(payloads[1]).toMatchObject({ target_ref: 'configured-synthetic-target', configuration_revision: CONFIG, policy_revision: POLICY });
});

test('synthetic held responses after session/route retirement or root loss cannot publish grants or submit new requests', async ({ page }) => {
  for (const phase of ['GET', 'POST']) for (const reason of ['auth', 'route', 'throw', 'dispose', 'detach-reinsert', 'replace']) {
    await mount(page);
    const held = phase === 'POST' ? await requestWindow(page) : await pending(page, 'GET');
    await page.evaluate(reason => {
      const root = document.querySelector('#root'); window.retiredRoot = root;
      if (reason === 'dispose') window.controller.dispose();
      else if (reason === 'detach-reinsert') { const parent = root.parentNode, next = root.nextSibling; root.remove(); parent.insertBefore(root, next); }
      else if (reason === 'replace') root.replaceWith(Object.assign(document.createElement('div'), { id: 'root' }));
      else window.current = reason === 'throw' ? 'throw' : false;
    }, reason);
    const before = await page.evaluate(() => ({ calls: window.calls.length, states: window.stateChanges.length }));
    await reply(page, held, active(), phase === 'POST' ? 201 : 200);
    expect(await grant(page)).toBeNull(); expect(await page.evaluate(() => window.grants)).toEqual([]);
    await load(page); await page.clock.fastForward(920001);
    expect(await page.evaluate(() => window.calls.length)).toBe(before.calls);
    expect(await page.evaluate(() => window.stateChanges.length)).toBe(before.states);
    expect(await posts(page)).toHaveLength(phase === 'POST' ? 1 : 0);
    expect(await page.evaluate(() => window.retiredRoot.querySelector('#unowned').textContent)).toBe('Unowned sibling remains');
  }
});

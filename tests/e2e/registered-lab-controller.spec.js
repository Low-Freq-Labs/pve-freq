// Synthetic HTTP-port consumer checks only. No original server, registration,
// operation admission, provider task or live infrastructure is exercised.
const path = require('node:path');
const { test, expect } = require('@playwright/test');
const web = path.resolve(__dirname, '../../freq/data/web/js');
const NOW = '2026-11-13T12:00:00Z';
const REV = 'a'.repeat(64), OP = 'b'.repeat(32);
const GUEST = '/api/lab/guest', POWER = '/api/lab/power', ORIGINAL = '/api/lab/operations/' + OP;
const DOCUMENT = 'http://localhost/';

function guest(patch = {}) {
  return { schema: 'pve-freq-lab-guest-view-v1', target: {
    ref: 'registered-lab-a', registration_revision: REV, estate: 'synthetic-lab', source: 'lab.invalid',
    node: 'node-a', kind: 'qemu', vmid: 120, name: 'synthetic-lab-guest',
    qualified_at: '2026-11-13T11:59:00Z', expires_at: '2026-11-13T12:10:00Z'
  }, capabilities: { lab_only: true, actions: ['start', 'shutdown'] },
  observation: { state: 'stopped', observed_at: NOW }, busy: false, operation: null, ...patch };
}
function operation(patch = {}) {
  return { schema: 'pve-freq-lab-operation-view-v1', operation: {
    ref: OP, target_ref: 'registered-lab-a', registration_revision: REV, retired: false,
    action: 'start', expected_state: 'stopped', phase: 'acknowledged', acknowledgement: 'received',
    task: { state: 'running', exit: null }, observation: { state: 'unknown', observed_at: null },
    error: null, created_at: NOW, updated_at: NOW, ...patch
  } };
}
function fact(page, label, target = false) {
  return page.locator(target ? '[data-lab-target]' : '[data-lab-operation]')
    .getByText(label, { exact: true }).locator('xpath=following-sibling::dd[1]');
}
async function mount(page, admission) {
  await page.evaluate(() => { if (window.syntheticController) window.syntheticController.dispose(); });
  await page.setContent('<main><div id="root"><p id="unowned">Unowned sibling</p></div><div id="new-parent"></div></main>');
  await page.evaluate(() => {
    window.syntheticCurrent = true;
    window.portCalls = [];
    window.forbiddenNetwork = [];
    window.fetch = (...args) => { window.forbiddenNetwork.push(String(args[0])); return Promise.reject(Error('network forbidden')); };
  });
  await page.addScriptTag({ path: path.join(web, 'registered-lab-panel.js') });
  await page.addScriptTag({ path: path.join(web, 'registered-lab-controller.js') });
  await page.evaluate(admission => {
    const options = {
      root: document.querySelector('#root'),
      isCurrent: () => { if (window.syntheticCurrent === 'throw') throw Error('retired'); return window.syntheticCurrent; },
      request: (method, route, payload, signal) => new Promise((resolve, reject) => {
        window.portCalls.push({ method, route, payload: payload == null ? payload : JSON.parse(JSON.stringify(payload)), signal, resolve, reject, answered: false });
      })
    };
    if (admission !== undefined) {
      window.syntheticAdmission = admission;
      options.maySubmit = () => {
        if (window.syntheticAdmission === 'dispose') { window.syntheticController.dispose(); return true; }
        if (window.syntheticAdmission === 'throw') throw Error('admission unavailable');
        return window.syntheticAdmission;
      };
    }
    window.syntheticController = FreqRegisteredLabController.create(options);
    void window.syntheticController.load();
  }, admission);
}
async function pending(page, method, route) {
  const find = () => page.evaluate(({ method, route }) => window.portCalls.findIndex(call => !call.answered && call.method === method && call.route === route && !call.signal.aborted), { method, route });
  await expect.poll(find).toBeGreaterThanOrEqual(0);
  return find();
}
async function reply(page, index, data, status = 200) {
  await page.evaluate(({ index, data, status }) => {
    const call = window.portCalls[index]; call.answered = true; call.resolve({ status, data });
  }, { index, data, status });
}
async function serve(page, method, route, data, status = 200) {
  const index = await pending(page, method, route); await reply(page, index, data, status); return index;
}
async function posts(page) { return page.evaluate(() => window.portCalls.filter(call => call.method === 'POST').map(call => call.payload)); }
async function start(page) {
  await serve(page, 'GET', GUEST, guest());
  await expect(page.getByRole('button', { name: 'Shut down', exact: true })).toBeDisabled();
  await page.getByRole('button', { name: 'Start', exact: true }).click();
  return pending(page, 'POST', POWER);
}
test.beforeEach(async ({ page, context }) => {
  page.syntheticRequests = [];
  page.on('request', request => { if (request.url() !== DOCUMENT) page.syntheticRequests.push(request.url()); });
  await context.route('**/*', route => {
    const request = route.request();
    // A fictional document gives native crypto.randomUUID its required secure
    // origin. Fulfilled in memory; all other URLs are aborted, never forwarded.
    if (request.url() === DOCUMENT && request.method() === 'GET' && request.resourceType() === 'document')
      return route.fulfill({ status: 200, contentType: 'text/html', body: '<!doctype html><title>Synthetic registered lab consumer</title>' });
    return route.abort('blockedbyclient');
  });
  await page.goto(DOCUMENT);
  expect(await page.evaluate(() => ({ secure: window.isSecureContext,
    native: Function.prototype.toString.call(window.crypto.randomUUID).includes('[native code]')
  }))).toEqual({ secure: true, native: true });
  await page.clock.install({ time: new Date(NOW) });
});
test.afterEach(async ({ page }) => {
  expect(await page.evaluate(() => window.forbiddenNetwork || [])).toEqual([]);
  expect(page.syntheticRequests).toEqual([]);
  await page.evaluate(() => { if (window.syntheticController) window.syntheticController.dispose(); });
});

test('synthetic valid capabilities enable only correct action; one trusted intent sends exactly five strings once', async ({ page }) => {
  await mount(page);
  const post = await start(page);
  const payload = (await posts(page))[0];
  expect(Object.keys(payload).sort()).toEqual(['action', 'expected_state', 'registration_revision', 'request_key', 'target_ref']);
  expect(Object.values(payload).every(value => typeof value === 'string')).toBe(true);
  expect(payload).toMatchObject({ target_ref: 'registered-lab-a', registration_revision: REV, action: 'start', expected_state: 'stopped' });
  expect(payload.request_key).toMatch(/^[\x21-\x7e]{1,128}$/);
  await expect(page.getByRole('button', { name: 'Start', exact: true })).toBeDisabled();
  await expect(page.getByRole('button', { name: 'Shut down', exact: true })).toBeDisabled();
  await page.getByRole('button', { name: 'Start', exact: true }).evaluate(button => {
    button.click(); button.dispatchEvent(new MouseEvent('click', { bubbles: true }));
  });
  await reply(page, post, operation(), 202);
  await expect(fact(page, 'Submission acknowledgement')).toHaveText('Acknowledged');
  await expect(fact(page, 'Provider task observation')).toHaveText('Running');
  await expect(fact(page, 'Current guest observation', true)).not.toHaveText('Running');
  expect(await posts(page)).toHaveLength(1);
});

test('synthetic original-operation polling preserves historical terminal facts until an independent fresh guest read', async ({ page }) => {
  await mount(page);
  const post = await start(page);
  await reply(page, post, operation(), 202);
  await page.clock.fastForward(2001);
  await serve(page, 'GET', ORIGINAL, operation({ phase: 'succeeded', task: { state: 'succeeded', exit: 'OK' }, observation: { state: 'running', observed_at: NOW } }));
  await expect(fact(page, 'Provider task observation')).toHaveText('Success');
  await expect(fact(page, 'Operation guest observation')).toHaveText('Running');
  await expect(fact(page, 'Current guest observation', true)).not.toHaveText('Running');
  await page.evaluate(() => { void window.syntheticController.load(); });
  await serve(page, 'GET', GUEST, guest({ observation: { state: 'running', observed_at: NOW } }));
  await expect(fact(page, 'Current guest observation', true)).toHaveText('Running');
  await expect(page.getByRole('button', { name: 'Start', exact: true })).toBeDisabled();
  await expect(page.getByRole('button', { name: 'Shut down', exact: true })).toBeEnabled();
  await page.getByRole('button', { name: 'Shut down', exact: true }).click();
  await pending(page, 'POST', POWER);
  const payloads = await posts(page);
  expect(payloads).toHaveLength(2);
  expect(payloads[1]).toMatchObject({ action: 'shutdown', expected_state: 'running' });
  expect(payloads[1].request_key).not.toBe(payloads[0].request_key);
});

test('synthetic lost, malformed and HTTP-error POST responses retain uncertainty without automatic retry or replacement key', async ({ page }) => {
  for (const failure of ['lost', 'malformed', 'http-error']) {
    await mount(page);
    const post = await start(page), originalKey = (await posts(page))[0].request_key;
    if (failure === 'lost') await page.evaluate(index => {
      window.portCalls[index].answered = true; window.portCalls[index].reject(Error('synthetic lost response'));
    }, post);
    else await reply(page, post, failure === 'malformed' ? { schema: 'wrong' } : { error: 'store_unavailable' }, failure === 'malformed' ? 202 : 503);
    await expect(page.getByRole('button', { name: 'Start', exact: true })).toBeDisabled();
    await expect(page.locator('.registered-lab-panel')).toContainText(/unknown|unconfirmed|uncertain/i);
    await page.clock.fastForward(61_000);
    expect(await posts(page)).toHaveLength(1);
    expect((await posts(page))[0].request_key).toBe(originalKey);
    await page.evaluate(() => { void window.syntheticController.load(); });
    await serve(page, 'GET', GUEST, guest());
    await expect(page.getByRole('button', { name: 'Start', exact: true })).toBeDisabled();
    expect(await posts(page)).toHaveLength(1);
  }
});

test('synthetic GET guest recovery reads only the retained original operation reference', async ({ page }) => {
  await mount(page);
  const recovery = { ref: OP, target_ref: 'registered-lab-a', registration_revision: REV, retired: false, action: 'start', phase: 'running' };
  await serve(page, 'GET', GUEST, guest({ busy: true, operation: recovery }));
  await page.clock.fastForward(2001);
  await serve(page, 'GET', ORIGINAL, operation());
  await expect(fact(page, 'Submission acknowledgement')).toHaveText('Acknowledged');
  expect(await posts(page)).toEqual([]);
  const routes = await page.evaluate(() => window.portCalls.map(call => call.route));
  expect(routes.every(route => route === GUEST || route === ORIGINAL)).toBe(true);
  await expect(page.getByRole('button', { name: 'Start', exact: true })).toBeDisabled();
});

test('synthetic invalid schema, state, busy or capability/window never enables actions', async ({ page }) => {
  for (const invalid of [
    guest({ schema: 'wrong' }), guest({ busy: true }), guest({ observation: { state: 'unknown', observed_at: null } }),
    guest({ capabilities: { lab_only: false, actions: ['start'] } }),
    guest({ capabilities: { lab_only: true, actions: [] } }),
    guest({ target: { ...guest().target, registration_revision: 'invalid-revision' } }),
    guest({ target: { ...guest().target, expires_at: '2026-11-13T11:59:59Z' } })
  ]) {
    await mount(page); await serve(page, 'GET', GUEST, invalid);
    await expect(page.getByRole('button', { name: 'Start', exact: true })).toBeDisabled();
    await expect(page.getByRole('button', { name: 'Shut down', exact: true })).toBeDisabled();
    expect(await posts(page)).toEqual([]);
  }
  await mount(page); await serve(page, 'GET', GUEST, guest({ target: { ...guest().target, expires_at: '2026-11-13T12:00:03Z' } }));
  await expect(page.getByRole('button', { name: 'Start', exact: true })).toBeEnabled();
  await page.clock.fastForward(3001);
  await expect(page.getByRole('button', { name: 'Start', exact: true })).toBeDisabled();
});

test('synthetic mismatched or retired operation cannot join current target or admit a new action', async ({ page }) => {
  for (const patch of [{ registration_revision: 'c'.repeat(64) }, { target_ref: 'different' }, { target_ref: null, retired: true }]) {
    await mount(page);
    await reply(page, await start(page), operation(patch), 202);
    await expect(page.locator('[data-lab-operation]')).not.toContainText('Acknowledged');
    await expect(page.getByRole('button', { name: 'Start', exact: true })).toBeDisabled();
    expect(await posts(page)).toHaveLength(1);
  }
  await mount(page); await reply(page, await start(page), operation(), 202);
  await page.clock.fastForward(2001);
  await serve(page, 'GET', ORIGINAL, operation({ ref: 'd'.repeat(32), task: { state: 'succeeded', exit: 'OK' } }));
  await expect(fact(page, 'Provider task observation')).not.toHaveText('Success');
  await expect(page.getByRole('button', { name: 'Start', exact: true })).toBeDisabled();
});

// Synthetic original-session witness; expiry withdraws new dispatch only.
for (const held of ['POST', 'GET']) {
  test(`synthetic expiry preserves held ${held}, original reads and historical facts without a new intent`, async ({ page }) => {
    await mount(page);
    const witness = guest({ target: { ...guest().target, expires_at: '2026-11-13T12:00:03Z' } });
    await serve(page, 'GET', GUEST, witness);
    await page.getByRole('button', { name: 'Start', exact: true }).click();
    const post = await pending(page, 'POST', POWER);
    const originalPayload = (await posts(page))[0];
    let heldIndex = post;
    if (held === 'GET') {
      await reply(page, post, operation(), 202);
      await page.clock.fastForward(2001);
      heldIndex = await pending(page, 'GET', ORIGINAL);
      await page.clock.fastForward(1001);
    } else await page.clock.fastForward(3002);
    expect(await page.evaluate(index => portCalls[index].signal.aborted, heldIndex)).toBe(false);
    await expect(page.locator('[data-lab-target]')).toContainText('synthetic-lab-guest');
    await expect(page.getByRole('button', { name: 'Start', exact: true })).toBeDisabled();
    await expect(page.getByRole('button', { name: 'Shut down', exact: true })).toBeDisabled();
    await reply(page, heldIndex, operation(), held === 'POST' ? 202 : 200);
    await expect(fact(page, 'Submission acknowledgement')).toHaveText('Acknowledged');
    await expect(fact(page, 'Provider task observation')).toHaveText('Running');
    await page.clock.fastForward(2001);
    await serve(page, 'GET', ORIGINAL, operation({ phase: 'succeeded', task: { state: 'succeeded', exit: 'OK' },
      observation: { state: 'running', observed_at: '2026-11-13T12:00:05Z' } }));
    await expect(fact(page, 'Provider task observation')).toHaveText('Success');
    await expect(fact(page, 'Current guest observation', true)).not.toHaveText('Running');
    await serve(page, 'GET', GUEST, { ...witness, capabilities: { lab_only: true, actions: [] },
      observation: { state: 'running', observed_at: '2026-11-13T12:00:05Z' } });
    await expect(fact(page, 'Current guest observation', true)).toHaveText('Running');
    await expect(fact(page, 'Provider task observation')).toHaveText('Success');
    await expect(fact(page, 'Operation guest observation')).toHaveText('Running');
    expect(await page.evaluate(() => syntheticController.getCurrentBinding())).toEqual({ ref: witness.target.ref,
      revision: REV, startsAt: witness.target.qualified_at, expiresAt: witness.target.expires_at });
    for (const name of ['Start', 'Shut down']) {
      const button = page.getByRole('button', { name, exact: true });
      await expect(button).toBeDisabled();
      await button.evaluate(button => { button.click(); button.dispatchEvent(new MouseEvent('click', { bubbles: true })); });
    }
    const settledCalls = await page.evaluate(() => portCalls.length);
    await page.clock.fastForward(65_000);
    expect(await page.evaluate(() => portCalls.length)).toBe(settledCalls);
    expect(await posts(page)).toEqual([originalPayload]);
    expect(await page.evaluate(() => portCalls.filter(call => call.method === 'GET' && call.route.includes('/operations/')).map(call => call.route)))
      .toEqual(held === 'GET' ? [ORIGINAL, ORIGINAL] : [ORIGINAL]);
  });
}

test('synthetic acknowledgement timeout and bounded poll loss pause observation without cancelling or resubmitting', async ({ page }) => {
  await mount(page);
  const post = await start(page);
  await page.clock.fastForward(20_001);
  await expect(page.locator('.registered-lab-panel')).toContainText(/unknown|unconfirmed|uncertain/i);
  expect(await page.evaluate(index => window.portCalls[index].signal.aborted, post)).toBe(true);
  await reply(page, post, operation(), 202);
  await expect(page.locator('[data-lab-operation]')).not.toContainText('Acknowledged');
  expect(await posts(page)).toHaveLength(1);
  await mount(page); await reply(page, await start(page), operation(), 202);
  await page.clock.fastForward(2001);
  const poll = await pending(page, 'GET', ORIGINAL);
  await reply(page, poll, { error: 'unavailable' }, 503);
  await expect(fact(page, 'Submission acknowledgement')).toHaveText('Acknowledged');
  await expect(fact(page, 'Provider task observation')).toHaveText('Running');
  await expect(fact(page, 'Current guest observation', true)).toHaveText('Unknown');
  const paused = await page.evaluate(() => window.portCalls.length);
  await page.clock.fastForward(6001);
  expect(await page.evaluate(() => window.portCalls.length)).toBe(paused);
  await mount(page);
  await serve(page, 'GET', GUEST, guest({ target: { ...guest().target,
    expires_at: await page.evaluate(() => new Date(Date.now() + 3000).toISOString()) } }));
  await page.getByRole('button', { name: 'Start', exact: true }).click();
  await reply(page, await pending(page, 'POST', POWER), operation(), 202);
  // Cross expiry while answering bounded original reads; no cancel/new POST.
  for (let index = 0; index < 32; index++) {
    await page.clock.fastForward(2001);
    await page.evaluate(dto => window.portCalls.forEach(call => {
      if (!call.answered && call.method === 'GET' && call.route.includes('/operations/') && !call.signal.aborted) {
        call.answered = true; call.resolve({ status: 200, data: dto });
      }
    }), operation());
  }
  const before = await page.evaluate(() => window.portCalls.length);
  const reads = await page.evaluate(() => window.portCalls.filter(call => call.method === 'GET' && call.route.includes('/operations/')).length);
  expect(reads).toBeGreaterThan(2); // Reads continued beyond the 3-second dispatch window.
  expect(reads).toBeLessThanOrEqual(30);
  await page.clock.fastForward(20_000);
  expect(await page.evaluate(() => window.portCalls.length)).toBe(before);
  expect(await posts(page)).toHaveLength(1);
  await expect(page.locator('.registered-lab-panel')).not.toContainText(/cancelled|canceled/i);
});

test('synthetic held guest response after auth retirement, navigation or disposal cannot publish or act; timers stop', async ({ page }) => {
  for (const reason of ['auth', 'navigation', 'dispose', 'moved-root', 'throw']) {
    await mount(page);
    const held = await pending(page, 'GET', GUEST);
    await page.evaluate(reason => {
      if (reason === 'dispose') window.syntheticController.dispose();
      else if (reason === 'moved-root') document.querySelector('#new-parent').append(document.querySelector('#root'));
      else window.syntheticCurrent = reason === 'throw' ? 'throw' : false;
    }, reason);
    await reply(page, held, guest());
    await expect(page.locator('#root')).not.toContainText('synthetic-lab-guest');
    expect(await posts(page)).toEqual([]);
    const before = await page.evaluate(() => window.portCalls.length);
    await page.clock.fastForward(65_000);
    expect(await page.evaluate(() => window.portCalls.length)).toBe(before);
    await expect(page.locator('#unowned')).toHaveText('Unowned sibling');
  }
});

test('synthetic held POST response after retirement cannot publish acknowledgement or create a second intent', async ({ page }) => {
  for (const reason of ['auth', 'navigation', 'dispose']) {
    await mount(page);
    const held = await start(page);
    await page.evaluate(reason => {
      if (reason === 'dispose') window.syntheticController.dispose();
      else window.syntheticCurrent = false;
    }, reason);
    await reply(page, held, operation(), 202);
    await expect(page.locator('#root')).not.toContainText('Acknowledged');
    await expect(page.locator('#root')).not.toContainText(OP);
    await page.evaluate(() => { void window.syntheticController.load(); });
    await page.clock.fastForward(65_000);
    expect(await posts(page)).toHaveLength(1);
    expect(await page.evaluate(index => window.portCalls[index].signal.aborted, held)).toBe(true);
    expect(await page.evaluate(() => window.portCalls.filter(call => call.route.includes('/operations/')).length)).toBe(0);
    await expect(page.locator('#unowned')).toHaveText('Unowned sibling');
  }
});

// The protected manifest accepts both canonical UTC spellings and the API
// deliberately preserves its qualification strings.
test('synthetic UTC offset qualification agrees with the public manifest projection', async ({ page }) => {
  await mount(page);
  const dto = guest();
  dto.target.qualified_at = dto.target.qualified_at.replace('Z', '+00:00');
  dto.target.expires_at = dto.target.expires_at.replace('Z', '+00:00');
  await serve(page, 'GET', GUEST, dto);
  await expect(page.getByRole('button', { name: 'Start', exact: true })).toBeEnabled();
  await expect(page.getByRole('button', { name: 'Shut down', exact: true })).toBeDisabled();
  expect(await posts(page)).toEqual([]);
});


test('synthetic original-owner admission gate blocks stale enabled power controls and preserves unresolved attempts', async ({ page }) => {
  await mount(page, false); await serve(page, 'GET', GUEST, guest());
  await expect(page.getByRole('button', { name: 'Start', exact: true })).toBeDisabled();
  expect(await page.evaluate(() => syntheticController.getCurrentBinding())).toEqual({ ref: 'registered-lab-a', revision: REV,
    startsAt: '2026-11-13T11:59:00Z', expiresAt: '2026-11-13T12:10:00Z' });
  expect(await page.evaluate(() => syntheticController.hasUnsettledAttempt())).toBe(false);
  await page.evaluate(() => { syntheticAdmission = true; syntheticController.refreshEligibility(); });
  await expect(page.getByRole('button', { name: 'Start', exact: true })).toBeEnabled();
  await page.evaluate(() => { syntheticAdmission = false; });
  await page.getByRole('button', { name: 'Start', exact: true }).click();
  expect(await posts(page)).toHaveLength(0);
  await page.evaluate(() => { syntheticAdmission = true; syntheticController.refreshEligibility(); });
  await page.getByRole('button', { name: 'Start', exact: true }).click();
  const post = await pending(page, 'POST', POWER);
  expect(await page.evaluate(() => syntheticController.hasUnsettledAttempt())).toBe(true);
  await page.evaluate(index => { const call = portCalls[index]; call.answered = true; call.reject(Error('fictional lost acknowledgement')); }, post);
  await expect(fact(page, 'Current guest observation', true)).toHaveText('Unknown');
  await page.getByRole('button', { name: 'Refresh status', exact: true }).click();
  await serve(page, 'GET', GUEST, guest({ busy: false, operation: null }));
  expect(await page.evaluate(() => syntheticController.hasUnsettledAttempt())).toBe(true);
  expect(await posts(page)).toHaveLength(1);
});

test('synthetic admission callback retirement cannot dispatch a power request', async ({ page }) => {
  await mount(page, true); await serve(page, 'GET', GUEST, guest());
  await expect(page.getByRole('button', { name: 'Start', exact: true })).toBeEnabled();
  await page.evaluate(() => { syntheticAdmission = 'dispose'; });
  await page.getByRole('button', { name: 'Start', exact: true }).click();
  expect(await posts(page)).toHaveLength(0);
  expect(await page.evaluate(() => syntheticController.getCurrentBinding())).toBeNull();
  expect(await page.evaluate(() => syntheticController.hasUnsettledAttempt())).toBe(true);
});

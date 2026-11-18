// Fictional internal display models, original panel and actual local styles.
// No HTTP/native/data contract, registration, operation or window is exercised.
const path = require('node:path');
const { test, expect } = require('@playwright/test');
const web = path.resolve(__dirname, '../../freq/data/web');
const hostile = '<img src=x onerror="window.hostileExecuted=true">';
const names = { request: 'Request lab window', refresh: 'Refresh window status' };
const target = () => ({ name: 'synthetic-window-guest', source: 'synthetic-lab.invalid', node: 'synthetic-node', kind: 'qemu', vmid: 120 });
const windowTime = () => ({ startsAt: '2026-11-13T11:45:00Z', expiresAt: '2026-11-13T12:00:00Z' });
const eligible = patch => ({ windowState: 'inactive', requestState: 'none', target: target(), window: null,
  isAdmin: true, requestEligible: true, exclusion: 'none', ...patch });
const request = page => page.getByRole('button', { name: names.request, exact: true });
const refresh = page => page.getByRole('button', { name: names.refresh, exact: true });
async function render(page, model) { await page.evaluate(model => window.windowPanel.render(model), model); }
async function mount(page, callbacks = true) {
  await page.evaluate(() => { if (window.windowPanel) window.windowPanel.dispose(); });
  await page.setContent('<main id="synthetic-stage" style="width:100%;max-width:1100px;min-width:0;margin:16px auto;padding:16px">' +
    '<h1 style="font-size:16px;margin-bottom:16px;overflow-wrap:anywhere">SYNTHETIC LAB WINDOW DISPLAY — NO HTTP OR NATIVE ACTION</h1>' +
    '<div id="fixture-root"><p id="unowned">Unowned sibling remains</p></div><div id="other-parent"></div></main>');
  await page.addStyleTag({ path: path.join(web, 'css/app.css') });
  await page.addStyleTag({ path: path.join(web, 'css/lab-window-panel.css') });
  await page.evaluate(() => {
    window.fixtureCurrent = true;
    window.retiredRoot = null;
    window.requestGate = true;
    window.refreshGate = true;
    window.gateBehavior = null;
    window.calls = { request: [], refresh: [] };
    window.portAttempts = [];
    window.timerAttempts = 0;
    window.fetch = () => { window.portAttempts.push('fetch'); return Promise.reject(Error('forbidden synthetic port')); };
    window.XMLHttpRequest = function () { window.portAttempts.push('xhr'); throw Error('forbidden synthetic port'); };
    window.WebSocket = function () { window.portAttempts.push('websocket'); throw Error('forbidden synthetic port'); };
    if (!window.savedTimeout) window.savedTimeout = window.setTimeout;
    window.setTimeout = function (...args) { window.timerAttempts++; return window.savedTimeout(...args); };
  });
  await page.addScriptTag({ path: path.join(web, 'js/lab-window-panel.js') });
  await page.evaluate(callbacks => {
    const options = { root: document.querySelector('#fixture-root'),
      isCurrent: () => { if (window.fixtureCurrent === 'throw') throw Error('retired'); return window.fixtureCurrent; }
    };
    if (callbacks) {
      options.canRequest = () => {
        if (window.gateBehavior === 'retire') window.fixtureCurrent = false;
        if (window.gateBehavior === 'dispose') window.windowPanel.dispose();
        if (window.gateBehavior === 'detach-reinsert') {
          const root = document.querySelector('#fixture-root'), parent = root.parentNode, next = root.nextSibling;
          root.remove(); parent.insertBefore(root, next);
        }
        if (window.gateBehavior === 'render') window.windowPanel.render({ windowState: 'loading', requestState: 'none', target: null, window: null,
          isAdmin: true, requestEligible: false, exclusion: 'none' });
        return window.requestGate;
      };
      options.onRequest = (...args) => window.calls.request.push(args.length);
      options.canRefresh = () => window.refreshGate;
      options.onRefresh = (...args) => window.calls.refresh.push(args.length);
    }
    window.windowPanel = FreqLabWindowPanel.create(options);
  }, callbacks);
}
test.beforeEach(async ({ page, context }) => {
  page.fixtureNetwork = [];
  page.on('request', event => page.fixtureNetwork.push(event.url()));
  await context.route('**/*', route => route.abort('blockedbyclient'));
});
test.afterEach(async ({ page }) => {
  expect(await page.evaluate(() => window.portAttempts || [])).toEqual([]);
  expect(await page.evaluate(() => window.timerAttempts || 0)).toBe(0);
  expect(page.fixtureNetwork).toEqual([]);
  await page.evaluate(() => { if (window.windowPanel) window.windowPanel.dispose(); });
});

test('synthetic role, exclusion and state gates refuse forged eligibility and absent private ports', async ({ page }) => {
  await mount(page, false); await render(page, eligible());
  await expect(request(page)).toBeDisabled(); await expect(refresh(page)).toBeDisabled();
  await page.evaluate(() => {
    window.windowPanel.dispose();
    window.windowPanel = FreqLabWindowPanel.create({ root: document.querySelector('#fixture-root'), isCurrent: () => true,
      onRequest: () => window.calls.request.push(0), onRefresh: () => window.calls.refresh.push(0) });
  });
  await render(page, eligible()); await expect(request(page)).toBeDisabled(); await expect(refresh(page)).toBeDisabled();
  await mount(page);
  const blocked = [
    { isAdmin: false }, { isAdmin: 'true' }, { requestEligible: false }, { requestEligible: 'true' },
    { target: null }, { exclusion: 'busy' }, { exclusion: 'uncertain' },
    ...['pending', 'unknown', 'acknowledged'].map(requestState => ({ requestState })),
    ...['loading', 'unavailable', 'not_configured'].map(windowState => ({ windowState, target: null })),
    ...['active', 'future'].map(windowState => ({ windowState, window: windowTime() }))
  ];
  for (const patch of blocked) {
    await render(page, eligible(patch)); await expect(request(page)).toBeDisabled();
  }
  await page.evaluate(() => { window.requestGate = 'true'; });
  await render(page, eligible()); await expect(request(page)).toBeDisabled();
  await page.evaluate(() => { window.requestGate = true; });
  for (const model of [eligible(), eligible({ requestState: 'refused' }), eligible({ windowState: 'expired', window: windowTime() })]) {
    await render(page, model); await expect(request(page)).toBeEnabled();
  }
  expect(await page.evaluate(() => window.calls)).toEqual({ request: [], refresh: [] });
});

test('synthetic literal target fields remain text and invalid finite UTC windows clear previous facts', async ({ page }) => {
  await mount(page);
  await render(page, eligible({ windowState: 'active', target: { ...target(), name: hostile, source: hostile, node: hostile }, window: windowTime() }));
  const root = page.locator('#fixture-root');
  await expect(root).toContainText(hostile);
  await expect(root.locator('img, script, svg, iframe')).toHaveCount(0);
  expect(await page.evaluate(() => window.hostileExecuted)).toBeUndefined();
  for (const window of [null, { startsAt: 'not-a-date', expiresAt: windowTime().expiresAt },
    { startsAt: '2026-02-30T11:00:00Z', expiresAt: windowTime().expiresAt },
    { startsAt: '2026-11-13T11:00:00+01:00', expiresAt: windowTime().expiresAt },
    { startsAt: windowTime().expiresAt, expiresAt: windowTime().startsAt },
    { startsAt: windowTime().startsAt, expiresAt: windowTime().startsAt }]) {
    await render(page, eligible({ windowState: 'active', window }));
    await expect(root).not.toContainText('synthetic-window-guest');
    await expect(root).not.toContainText(hostile);
    await expect(request(page)).toBeDisabled();
  }
  await render(page, eligible({ windowState: 'expired', window: { startsAt: '2026-11-13T11:00:00+00:00', expiresAt: '2026-11-13T12:00:00+00:00' } }));
  await expect(root).toContainText('synthetic-window-guest');
  await expect(request(page)).toBeEnabled();
  for (const invalid of [eligible({ target: null }), eligible({ target: { ...target(), vmid: 0 } }),
    eligible({ target: { ...target(), name: 'x'.repeat(4096) } }), eligible({ target: { ...target(), source: 'line\nbreak' } })]) {
    await render(page, invalid); await expect(root).not.toContainText('synthetic-window-guest'); await expect(request(page)).toBeDisabled();
  }
  for (const windowState of ['active', 'expired', 'future']) {
    for (const invalid of [{ target: null, window: windowTime() }, { target: target(), window: null }]) {
      await render(page, eligible({ windowState, ...invalid }));
      await expect(root).not.toContainText('synthetic-window-guest'); await expect(request(page)).toBeDisabled();
    }
  }
});

test('synthetic trusted request consumes one intent per render, without accepting script clicks or callback arguments', async ({ page }) => {
  await mount(page); await render(page, eligible());
  await request(page).evaluate(button => { button.click(); button.dispatchEvent(new MouseEvent('click', { bubbles: true })); });
  expect(await page.evaluate(() => window.calls.request)).toEqual([]);
  await request(page).click();
  expect(await page.evaluate(() => window.calls.request)).toEqual([0]);
  await expect(request(page)).toBeDisabled();
  await request(page).evaluate(button => { button.disabled = false; });
  await request(page).click();
  expect(await page.evaluate(() => window.calls.request)).toEqual([0]);
  await render(page, eligible()); await request(page).click();
  expect(await page.evaluate(() => window.calls.request)).toEqual([0, 0]);
  await render(page, eligible());
  await page.evaluate(() => { window.requestGate = false; });
  await request(page).click();
  expect(await page.evaluate(() => window.calls.request)).toEqual([0, 0]);
});

test('synthetic eligibility callbacks that render, dispose or retire cannot reuse the earlier click', async ({ page }) => {
  for (const behavior of ['render', 'dispose', 'retire', 'detach-reinsert']) {
    await mount(page); await render(page, eligible());
    await page.evaluate(behavior => { window.gateBehavior = behavior; }, behavior);
    await request(page).click();
    expect(await page.evaluate(() => window.calls.request)).toEqual([]);
  }
});

test('synthetic stable controls retain keyboard focus across display updates; refresh is privately gated', async ({ page }) => {
  await mount(page); await render(page, eligible());
  await request(page).focus(); await request(page).evaluate(button => { window.originalRequest = button; });
  await render(page, eligible({ target: { ...target(), name: 'updated-synthetic-guest' } }));
  await expect(request(page)).toBeFocused();
  expect(await request(page).evaluate(button => button === window.originalRequest)).toBe(true);
  await refresh(page).focus(); await render(page, eligible()); await expect(refresh(page)).toBeFocused();
  await refresh(page).evaluate(button => { button.click(); button.dispatchEvent(new MouseEvent('click', { bubbles: true })); });
  expect(await page.evaluate(() => window.calls.refresh)).toEqual([]);
  await page.keyboard.press('Enter'); expect(await page.evaluate(() => window.calls.refresh)).toEqual([0]);
  await page.evaluate(() => { window.refreshGate = false; }); await refresh(page).click();
  expect(await page.evaluate(() => window.calls.refresh)).toEqual([0]);
  await render(page, eligible()); await expect(refresh(page)).toBeDisabled();
  await page.evaluate(() => { window.refreshGate = 'true'; }); await render(page, eligible()); await expect(refresh(page)).toBeDisabled();
});

test('synthetic retirement, root replacement and detach/reinsert revoke owned controls while preserving siblings', async ({ page }) => {
  for (const reason of ['false', 'throw', 'dispose', 'detach', 'move', 'replace', 'detach-reinsert']) {
    await mount(page); await render(page, eligible());
    await page.evaluate(reason => {
      const root = document.querySelector('#fixture-root'); window.retiredRoot = root;
      if (reason === 'false') window.fixtureCurrent = false;
      if (reason === 'throw') window.fixtureCurrent = 'throw';
      if (reason === 'dispose') window.windowPanel.dispose();
      if (reason === 'detach') root.remove();
      if (reason === 'move') document.querySelector('#other-parent').append(root);
      if (reason === 'replace') root.replaceWith(Object.assign(document.createElement('div'), { id: 'fixture-root' }));
      if (reason === 'detach-reinsert') { const parent = root.parentNode, next = root.nextSibling; root.remove(); parent.insertBefore(root, next); }
    }, reason);
    await render(page, eligible());
    expect(await page.evaluate(() => window.calls)).toEqual({ request: [], refresh: [] });
    await render(page, eligible());
    expect(await page.evaluate(() => Array.from(window.retiredRoot.children).filter(child => child.id !== 'unowned').length)).toBe(0);
    expect(await page.evaluate(() => window.retiredRoot.querySelector('#unowned').textContent)).toBe('Unowned sibling remains');
  }
});

test('synthetic original styles fit desktop and phone widths with literal long facts', async ({ page }, testInfo) => {
  await mount(page);
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
    await render(page, eligible({ windowState: 'active', requestState: 'acknowledged', window: windowTime(), target: {
      ...target(), name: 'synthetic-window-guest-' + 'long-name-'.repeat(7), source: 'lab-' + 'x'.repeat(90) + '.invalid'
    } }));
    await expect(request(page)).toBeVisible(); await expect(refresh(page)).toBeVisible();
    const geometry = await page.evaluate(() => ({ viewport: innerWidth, client: document.documentElement.clientWidth,
      document: document.documentElement.scrollWidth, buttonRects: Array.from(document.querySelectorAll('#fixture-root button')).map(button => {
        const box = button.getBoundingClientRect(); return { left: box.left, right: box.right, height: box.height };
      }) }));
    expect(geometry.viewport).toBe(width); expect(geometry.document).toBeLessThanOrEqual(geometry.client);
    expect(geometry.buttonRects.every(box => box.left >= 0 && box.right <= geometry.client && box.height >= 24)).toBe(true);
    await page.screenshot({ path: testInfo.outputPath('synthetic-lab-window-panel-' + width + '.png'), fullPage: true });
    await testInfo.attach('synthetic-geometry-' + width, { body: JSON.stringify(geometry), contentType: 'application/json' });
  }
});

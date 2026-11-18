// Fictional normalized models test only the original display consumer.
// No registration, operation admission, auth, task or provider API is exercised.
const path = require('node:path');
const { test, expect } = require('@playwright/test');
const source = path.resolve(__dirname, '../../freq/data/web/js/registered-lab-panel.js');
const observedAt = '2026-11-13T12:00:00Z';
const hostile = '<img src=x onerror="globalThis.attackerRan=true">';

function ready() {
  return { registrationState: 'ready', target: {
    ref: 'registered-branch-a', revision: 7, source: 'lab-branch.invalid', node: 'lab-node',
    kind: 'qemu', vmid: 6101, name: 'lab-guest', state: 'stopped', observedAt
  }, operation: null };
}
function operation(model, patch = {}) {
  return { ...model, operation: {
    ref: 'operation-a', targetRef: model.target.ref, registrationRevision: model.target.revision,
    action: 'start', phase: 'terminal', ack: 'acknowledged', taskState: 'success',
    observedState: 'stopped', observedAt, ...patch
  } };
}
async function render(page, model) {
  await page.evaluate(model => window.syntheticPanel.render(model), model);
}
async function mount(page) {
  await page.setContent('<main><div id="root"><p id="unowned">Unowned sibling remains</p></div><div id="other-root"></div></main>');
  await page.evaluate(() => {
    window.syntheticCurrent = true;
    window.detachedRoot = null;
    window.syntheticNetworkCalls = [];
    window.syntheticLegacyCalls = [];
    window.fetch = (...args) => { window.syntheticNetworkCalls.push(String(args[0])); return Promise.reject(Error('network forbidden')); };
    document.addEventListener('click', event => {
      const action = event.target.closest('[data-action],[onclick],[data-view]');
      if (action) window.syntheticLegacyCalls.push(action.outerHTML);
    });
  });
  await page.addScriptTag({ path: source });
  await page.evaluate(() => {
    window.syntheticPanel = FreqRegisteredLabPanel.create({
      root: document.querySelector('#root'),
      isCurrent: () => { if (window.syntheticCurrent === 'throw') throw Error('retired'); return window.syntheticCurrent; }
    });
  });
}

test.beforeEach(async ({ context }) => {
  await context.route('**/*', route => route.abort('blockedbyclient'));
});

test('synthetic registered target identity is literal and operation cannot follow equal VMID onto another target', async ({ page }) => {
  await mount(page);
  const model = ready();
  model.target.name = hostile;
  await render(page, operation(model));
  const target = page.locator('[data-lab-target]');
  await expect(target).toContainText(hostile);
  await expect(target).toContainText('lab-branch.invalid');
  await expect(target).toContainText('6101');
  await expect(page.locator('#root img, #root script, #root iframe')).toHaveCount(0);
  expect(await page.evaluate(() => window.attackerRan)).toBeUndefined();
  const physical = operation(model);
  physical.target = { ...model.target, ref: 'registered-physical-b', revision: 8,
    source: 'physical.invalid', node: 'physical-node', kind: 'lxc', name: 'physical-same-vmid' };
  await render(page, physical);
  await expect(target).toContainText('physical.invalid');
  await expect(target).toContainText('physical-node');
  await expect(target).toContainText('6101');
  await expect(page.locator('#root')).not.toContainText(hostile);
  await expect(page.locator('[data-lab-operation]')).not.toContainText('operation-a');
});

test('synthetic acknowledgement, task result and observed power state remain separate facts', async ({ page }) => {
  await mount(page);
  await render(page, operation(ready()));
  const result = page.locator('[data-lab-operation]');
  await expect(result).toContainText('operation-a');
  const fact = label => result.getByText(label, { exact: true }).locator('xpath=following-sibling::dd[1]');
  await expect(fact('Submission acknowledgement')).toHaveText('Acknowledged');
  await expect(fact('Provider task observation')).toHaveText('Success');
  await expect(fact('Operation guest observation')).toHaveText('Stopped');
  await expect(fact('Operation observed at')).toHaveText(observedAt);
  await expect(result).not.toContainText(/started successfully|operation succeeded|guest is running/i);
  await render(page, operation(ready(), { ack: 'unknown', taskState: 'unknown', observedState: 'unknown', observedAt: null }));
  await expect(result).not.toContainText(/acknowledged|stopped|success/i);
  await expect(fact('Submission acknowledgement')).toHaveText('Unknown');
  await expect(fact('Provider task observation')).toHaveText('Unknown');
  await expect(fact('Operation guest observation')).toHaveText('Unknown');
  await expect(fact('Operation observed at')).toHaveText('Unknown');
});

test('synthetic mismatched operation registration revision or target reference discards previous facts', async ({ page }) => {
  await mount(page);
  for (const mismatch of [{ targetRef: 'different-target' }, { registrationRevision: 6 }]) {
    await render(page, operation(ready()));
    await expect(page.locator('[data-lab-operation]')).toContainText('operation-a');
    await render(page, operation(ready(), mismatch));
    await expect(page.locator('[data-lab-operation]')).not.toContainText('operation-a');
    await expect(page.locator('[data-lab-operation]')).not.toContainText(/acknowledged|success/i);
    await expect(page.locator('[data-lab-target]')).toContainText('lab-branch.invalid');
  }
});

test('synthetic registration transitions remove target and operation facts instead of showing stale or zero values', async ({ page }) => {
  await mount(page);
  for (const registrationState of ['loading', 'unavailable', 'none', 'expired']) {
    await render(page, operation(ready()));
    await expect(page.locator('[data-lab-target]')).toContainText('lab-branch.invalid');
    await render(page, { registrationState, target: null, operation: null });
    await expect(page.locator('#root')).not.toContainText('lab-branch.invalid');
    await expect(page.locator('#root')).not.toContainText('operation-a');
    await expect(page.locator('#root')).not.toContainText('6101');
    await expect(page.locator('#root')).not.toContainText(/acknowledged|success|stopped|running/i);
    await expect(page.locator('#root')).not.toContainText(/\bVMID\s*:?\s*0\b/);
    await expect(page.locator('#unowned')).toHaveText('Unowned sibling remains');
  }
});

test('synthetic retired, detached or moved root cannot publish and cleanup preserves unowned siblings', async ({ page }) => {
  for (const reason of ['false', 'throw', 'dispose', 'detach', 'move']) {
    await mount(page);
    await render(page, operation(ready()));
    await expect(page.locator('#root > .lab-panel-shell')).toHaveCount(1);
    await page.evaluate(reason => {
      const root = document.querySelector('#root');
      if (reason === 'false') window.syntheticCurrent = false;
      if (reason === 'throw') window.syntheticCurrent = 'throw';
      if (reason === 'dispose') window.syntheticPanel.dispose();
      if (reason === 'detach') { root.remove(); window.detachedRoot = root; }
      if (reason === 'move') document.querySelector('#other-root').append(root);
    }, reason);
    await render(page, operation(ready()));
    expect(await page.evaluate(() => {
      const root = window.detachedRoot || document.querySelector('#root');
      return root.querySelectorAll('.lab-panel-shell, [data-lab-target], [data-lab-operation]').length;
    })).toBe(0);
    expect(await page.evaluate(() => {
      const root = window.detachedRoot || document.querySelector('#root');
      return root.querySelector('#unowned').textContent;
    })).toBe('Unowned sibling remains');
    await page.evaluate(() => window.syntheticPanel.dispose());
  }
});

test('synthetic display controls stay native-disabled and programmatic clicks gain no request or legacy action', async ({ page }) => {
  const networkRequests = [];
  page.on('request', request => networkRequests.push(request.url()));
  await mount(page);
  for (const model of [ready(), operation(ready()), { registrationState: 'none', target: null, operation: null }]) {
    await render(page, model);
    for (const name of ['Start', 'Shut down']) {
      const control = page.getByRole('button', { name, exact: true });
      await expect(control).toBeDisabled();
      await control.evaluate(button => { button.click(); button.dispatchEvent(new MouseEvent('click', { bubbles: true })); });
    }
    await expect(page.locator('.registered-lab-panel [data-action], .registered-lab-panel [onclick], .registered-lab-panel [data-view]')).toHaveCount(0);
  }
  expect(await page.evaluate(() => window.syntheticNetworkCalls)).toEqual([]);
  expect(await page.evaluate(() => window.syntheticLegacyCalls)).toEqual([]);
  expect(networkRequests).toEqual([]);
});

async function mountCallbacks(page) {
  await mount(page);
  await page.evaluate(() => {
    window.syntheticPanel.dispose();
    window.callbackActions = [];
    window.callbackRefreshes = 0;
    window.actionAllowed = true;
    window.refreshAllowed = true;
    window.syntheticPanel = FreqRegisteredLabPanel.create({
      root: document.querySelector('#root'), isCurrent: () => window.syntheticCurrent === true,
      canAct: action => action === 'start' ? window.actionAllowed : false,
      onAction: action => window.callbackActions.push(action),
      canRefresh: () => window.refreshAllowed,
      onRefresh: () => window.callbackRefreshes++
    });
  });
  await render(page, ready());
}

test('synthetic panel callbacks require trusted current-owned click and literal private action eligibility', async ({ page }) => {
  await mountCallbacks(page);
  const start = page.getByRole('button', { name: 'Start', exact: true });
  await expect(start).toBeEnabled();
  await expect(page.getByRole('button', { name: 'Shut down', exact: true })).toBeDisabled();
  await start.evaluate(button => { button.click(); button.dispatchEvent(new MouseEvent('click', { bubbles: true })); });
  expect(await page.evaluate(() => window.callbackActions)).toEqual([]);
  await start.click();
  expect(await page.evaluate(() => window.callbackActions)).toEqual(['start']);
  await page.evaluate(() => { window.actionAllowed = false; });
  await start.click();
  expect(await page.evaluate(() => window.callbackActions)).toEqual(['start']);
  await page.evaluate(() => { window.actionAllowed = 'true'; });
  await render(page, ready());
  await expect(start).toBeDisabled();
  await page.evaluate(() => { window.actionAllowed = true; });
  await render(page, ready());
  await start.evaluate(button => { window.oldStart = button; });
  await render(page, ready());
  await page.evaluate(() => {
    window.oldStart.id = 'stale-start'; document.querySelector('#other-root').append(window.oldStart);
  });
  await page.locator('#stale-start').click();
  expect(await page.evaluate(() => window.callbackActions)).toEqual(['start']);
  await page.evaluate(() => { window.syntheticCurrent = false; });
  await page.locator('#root').getByRole('button', { name: 'Start', exact: true }).click();
  expect(await page.evaluate(() => window.callbackActions)).toEqual(['start']);
  await expect(page.locator('#root > .lab-panel-shell')).toHaveCount(0);
});

test('synthetic refresh callback is trusted, privately gated and disabled during loading', async ({ page }) => {
  await mountCallbacks(page);
  const refresh = page.getByRole('button', { name: 'Refresh status', exact: true });
  await expect(refresh).toBeEnabled();
  await refresh.evaluate(button => { button.click(); button.dispatchEvent(new MouseEvent('click', { bubbles: true })); });
  expect(await page.evaluate(() => window.callbackRefreshes)).toBe(0);
  await refresh.click();
  expect(await page.evaluate(() => window.callbackRefreshes)).toBe(1);
  await page.evaluate(() => { window.refreshAllowed = false; });
  await refresh.click();
  expect(await page.evaluate(() => window.callbackRefreshes)).toBe(1);
  await page.evaluate(() => { window.refreshAllowed = true; });
  await render(page, { ...ready(), loading: true });
  await expect(refresh).toBeDisabled();
  await render(page, ready());
  await expect(refresh).toBeEnabled();
  await refresh.evaluate(button => { window.oldRefresh = button; });
  await render(page, ready());
  await page.evaluate(() => window.oldRefresh.dispatchEvent(new MouseEvent('click', { bubbles: true })));
  expect(await page.evaluate(() => window.callbackRefreshes)).toBe(1);
  await page.evaluate(() => window.syntheticPanel.dispose());
  await expect(page.locator('#root > .lab-panel-shell')).toHaveCount(0);
});


test('synthetic expired target retains matching task facts but refuses forged private action eligibility', async ({ page }) => {
  await mount(page);
  await page.evaluate(() => {
    syntheticPanel.dispose();
    window.expiredActionCalls = [];
    window.syntheticPanel = FreqRegisteredLabPanel.create({ root: document.querySelector('#root'),
      isCurrent: () => true, canAct: () => true, onAction: action => expiredActionCalls.push(action) });
  });
  const expired = operation(ready());
  expired.registrationState = 'expired';
  await render(page, expired);
  await expect(page.locator('[data-lab-target]')).toContainText('lab-guest');
  await expect(page.locator('[data-lab-target]')).toContainText('lab-branch.invalid');
  const facts = page.locator('[data-lab-operation]');
  await expect(facts).toContainText('operation-a');
  await expect(facts.getByText('Submission acknowledgement', { exact: true }).locator('xpath=following-sibling::dd[1]')).toHaveText('Acknowledged');
  await expect(facts.getByText('Provider task observation', { exact: true }).locator('xpath=following-sibling::dd[1]')).toHaveText('Success');
  for (const name of ['Start', 'Shut down']) {
    const button = page.getByRole('button', { name, exact: true });
    await expect(button).toBeDisabled();
    await button.evaluate(button => { button.click(); button.dispatchEvent(new MouseEvent('click', { bubbles: true })); });
  }
  expect(await page.evaluate(() => expiredActionCalls)).toEqual([]);
  expect(await page.evaluate(() => syntheticNetworkCalls)).toEqual([]);
});

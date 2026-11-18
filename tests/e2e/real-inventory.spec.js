const fs = require('node:fs');
const path = require('node:path');
const { test, expect } = require('@playwright/test');

const expected = process.env.PVE_FREQ_DEMO_EXPECT || 'observed';
const requireFilter = process.env.PVE_FREQ_DEMO_REQUIRE_FILTER === '1';
const expectCockpit = process.env.PVE_FREQ_EXPECT_COCKPIT === '1';
const syntheticProvider = process.env.PVE_FREQ_DEMO_SYNTHETIC === '1';
function credentials() {
  const user = process.env.PVE_FREQ_DEMO_USER;
  const file = process.env.PVE_FREQ_DEMO_PASSWORD_FILE;
  if (!user || !file || !path.isAbsolute(file)) throw new Error('Explicit demo user and absolute private password file required');
  const stat = fs.lstatSync(file);
  if (!stat.isFile() || (stat.mode & 0o077)) throw new Error('Password must be a private regular file');
  const password = fs.readFileSync(file, 'utf8').replace(/(?:\r\n|\n)$/, '');
  if (!password) throw new Error('Password file must not be empty');
  return { user, password };
}

// Keep the product response mapping here, independently of DOM counts.
function inventoryRows(body) {
  expect(body).toMatchObject({ schema: 1, read_only: true });
  expect(Array.isArray(body.sources)).toBe(true);
  const nodes = [];
  const guests = [];
  for (const source of body.sources) {
    expect(typeof source.source).toBe('string');
    expect(Array.isArray(source.nodes) && Array.isArray(source.guests)).toBe(true);
    for (const row of source.nodes) nodes.push({ ...row, source: source.source });
    for (const row of source.guests) guests.push({ ...row, source: source.source });
  }
  return { nodes, guests };
}

test(`${syntheticProvider ? 'SYNTHETIC PROVIDER / ' : ''}actual-server inventory: ${expected === 'populated' ? 'POSITIVE populated demo' : 'observed/negative journey (' + expected + '), no positive-demo claim'}`, async ({ page }, testInfo) => {
  const mutations = [];
  const responses = [];
  const browserErrors = [];
  const apiServerErrors = [];
  let browserApiRequests = 0;
  const cockpitEvidence = { required: expectCockpit, verified: false, workspaces: [] };
  cockpitEvidence.resources = { verified: false, observedKinds: [], checkedKinds: [], targets: [] };
  let inventoryRequests = 0;
  const filterEvidence = { required: requireFilter, verified: false,
    browserRead: { inventoryMethod: 'GET', noExtraBrowserInventoryGetVerified: false,
      designatedLabCarrierVerified: false },
    limitation: 'Browser inventory GET counts only; independent provider calls and held-response behavior are not observed by this journey.' };
  const origin = new URL(testInfo.project.use.baseURL).origin;
  const isInventory = response => new URL(response.url()).origin === origin &&
    new URL(response.url()).pathname === '/api/pve/inventory' && response.request().method() === 'GET';
  page.on('request', request => {
    if (new URL(request.url()).origin === origin && new URL(request.url()).pathname.startsWith('/api/')) browserApiRequests++;
    if (new URL(request.url()).origin === origin && new URL(request.url()).pathname === '/api/pve/inventory' && request.method() === 'GET') inventoryRequests++;
    if (!['GET', 'HEAD', 'OPTIONS'].includes(request.method())) {
      mutations.push({ method: request.method(), path: new URL(request.url()).pathname });
    }
  });
  page.on('response', response => {
    if (isInventory(response)) responses.push(response);
    const url = new URL(response.url());
    if (url.origin === origin && url.pathname.startsWith('/api/') && response.status() >= 500) {
      apiServerErrors.push({ method: response.request().method(), path: url.pathname, status: response.status() });
    }
  });
  page.on('pageerror', () => browserErrors.push('Uncaught browser exception; message withheld'));
  const verify = () => page.evaluate(async () => {
    const response = await fetch('/api/auth/verify', { credentials: 'same-origin' });
    const body = await response.json();
    return { status: response.status, valid: body.valid, user: body.user };
  });
  const cockpitRow = (report, record, kind) => {
    const host = report.locator('.pve-inventory-host').filter({ has: page.getByRole('heading', { name: record.source, exact: true }) });
    const candidates = host.locator(`[data-inventory-kind="${kind}"]`);
    return kind === 'node' ? candidates.filter({ has: page.getByRole('heading', { name: record.name || record.node, exact: true }) }) :
      candidates.filter({ has: page.getByText(`ID ${record.vmid} · ${record.node}`, { exact: true }) })
        .filter({ has: page.getByText(record.type === 'qemu' ? 'VM' : 'LXC', { exact: true }) });
  };
  const checkResourceWorkspaces = async (report, rows) => {
    const evidence = cockpitEvidence.resources;
    evidence.observedKinds = ['qemu', 'lxc'].filter(kind => rows.guests.some(guest => guest.type === kind));
    if (!rows.guests.length) return;
    const beforeApi = browserApiRequests, beforeInventory = inventoryRequests;
    const initialState = await report.getAttribute('data-state');
    for (const kind of evidence.observedKinds) {
      const target = rows.guests.find(guest => guest.type === kind);
      await cockpitRow(report, target, 'guest').getByRole('button', { name: /^Details for / }).click();
      const detail = report.locator('[data-inventory-detail]');
      for (const [label, value] of [['Source', target.source], ['Endpoint', target.source], ['Node', target.node],
        ['Type', target.type], ['ID', target.vmid], ['Guest', target.name || String(target.vmid)]]) {
        await expect(detail.locator('dt').filter({ hasText: new RegExp('^' + label + '$') })
          .locator('xpath=following-sibling::dd[1]')).toHaveText(String(value));
      }
      const tabs = detail.getByRole('tablist', { name: 'Resource details' });
      const selected = async name => {
        const tab = tabs.getByRole('tab', { name, exact: true });
        await expect(tab).toHaveAttribute('aria-selected', 'true');
        await expect(tab).toBeFocused();
        expect(await tabs.getByRole('tab').evaluateAll(items => items.filter(item => item.tabIndex === 0).length)).toBe(1);
        expect(await tabs.getByRole('tab').evaluateAll(items => items.every(item => item.tabIndex ===
          (item.getAttribute('aria-selected') === 'true' ? 0 : -1)))).toBe(true);
        expect(await tab.evaluate(item => item.tabIndex)).toBe(0);
        await expect(tabs.locator('[aria-selected="true"]')).toHaveCount(1);
        await expect(detail.getByRole('tabpanel', { name, exact: true })).toBeVisible();
        const operations = detail.locator('button.cockpit-action');
        expect(await operations.count(), 'Resource workspace exposes its unavailable operations').toBeGreaterThan(0);
        expect(await operations.evaluateAll(items => items.every(item => item.disabled))).toBe(true);
        await operations.evaluateAll(items => items.forEach(item => item.click()));
      };
      await tabs.getByRole('tab', { name: 'Overview', exact: true }).focus();
      await selected('Overview');
      for (const name of ['Console', 'Network', 'Hardware', 'Snapshots', 'Backups']) {
        await page.keyboard.press('ArrowRight');
        await selected(name);
        if (name === 'Console') await expect(detail.getByRole('tabpanel')).toContainText('No console session is connected');
        if (name === 'Snapshots' || name === 'Backups') await expect(detail.getByRole('tabpanel')).toContainText('have not been read');
      }
      for (const [key, name] of [['Home', 'Overview'], ['End', 'Backups'], ['ArrowRight', 'Overview'], ['ArrowLeft', 'Backups'], ['Home', 'Overview']]) {
        await page.keyboard.press(key); await selected(name);
      }
      evidence.checkedKinds.push(kind);
      evidence.targets.push({ source: target.source, node: target.node, type: target.type, vmid: target.vmid,
        name: target.name === undefined ? null : target.name });
    }
    expect(evidence.checkedKinds).toEqual(evidence.observedKinds);
    if (rows.nodes.length) {
      const node = rows.nodes[0], nodeRow = cockpitRow(report, node, 'node');
      const group = nodeRow.locator('xpath=ancestor::section[contains(@class,"cockpit-node-group")]');
      const returnedGuests = rows.guests.filter(guest => guest.source === node.source && guest.node === node.node).length;
      const beforeVisible = await report.locator('[data-inventory-kind="guest"]:visible').count();
      await expect(group.locator('[data-inventory-kind="guest"]')).toHaveCount(returnedGuests);
      const collapse = group.getByRole('button', { name: 'Collapse guests for ' + (node.name || node.node), exact: true });
      await collapse.click();
      await expect(group.getByRole('button', { name: 'Expand guests for ' + (node.name || node.node), exact: true })).toHaveAttribute('aria-expanded', 'false');
      await expect(group.locator('[data-inventory-kind="guest"]:visible')).toHaveCount(0);
      await expect(report.locator('[data-inventory-kind="guest"]:visible')).toHaveCount(beforeVisible - returnedGuests);
      await expect(nodeRow).toBeVisible();
      await group.getByRole('button', { name: 'Expand guests for ' + (node.name || node.node), exact: true }).click();
      await expect(group.getByRole('button', { name: 'Collapse guests for ' + (node.name || node.node), exact: true })).toHaveAttribute('aria-expanded', 'true');
      await expect(group.locator('[data-inventory-kind="guest"]:visible')).toHaveCount(returnedGuests);
      await expect(report.locator('[data-inventory-kind="guest"]:visible')).toHaveCount(beforeVisible);
      await expect(nodeRow).toBeVisible();
      evidence.firstNodeGroupCollapseExpand = { source: node.source, node: node.node, returnedGuests, verified: true };
    }
    await expect(report).toHaveAttribute('data-state', initialState);
    expect(browserApiRequests, 'Resource tabs and group toggles issue no extra browser API requests').toBe(beforeApi);
    expect(inventoryRequests, 'Resource tabs and group toggles issue no EXTRA BROWSER inventory GET').toBe(beforeInventory);
    evidence.extraBrowserApiRequests = browserApiRequests - beforeApi;
    evidence.extraBrowserInventoryGets = inventoryRequests - beforeInventory;
    evidence.verified = true;
  };
  const checkFilter = async (report, rows) => {
    expect(rows.guests.length, 'Filter journey requires an actual observed guest').toBeGreaterThan(0);
    await expect(report).toHaveAttribute('data-state', /^(ready|partial)$/);
    const initialState = await report.getAttribute('data-state');
    const carrierIndex = rows.guests.findIndex(guest => guest.source === 'pve01.dc01.lowfreqlabs.com' &&
      guest.node === 'pve01' && guest.type === 'qemu' && guest.vmid === 5000 && guest.name === 'hq-pve1');
    const targetIndex = carrierIndex >= 0 ? carrierIndex : 0;
    const target = rows.guests[targetIndex];
    const query = String(target.vmid);
    const fields = row => [row.source, row.node, row.name, row.type, row.vmid]
      .filter(value => value !== null && value !== undefined).map(String).map(value => value.toLowerCase());
    const matches = (row, text) => fields(row).some(value => value.includes(text.toLowerCase()));
    const matchingGuests = rows.guests.filter(row => matches(row, query)).length;
    const matchingNodes = rows.nodes.filter(row => matches(row, query)).length;
    const visibleNodes = text => rows.nodes.filter(node => matches(node, text) ||
      (expectCockpit && rows.guests.some(guest => guest.source === node.source && guest.node === node.node && matches(guest, text)))).length;
    const before = inventoryRequests;
    const errors = report.locator('.pve-inventory-error');
    const errorText = await errors.allTextContents();
    const assertErrorsPreserved = async () => {
      await expect(errors).toHaveCount(errorText.length);
      for (let index = 0; index < errorText.length; index++) {
        await expect(errors.nth(index)).toBeVisible();
        await expect(errors.nth(index)).toHaveText(errorText[index]);
        await expect(errors.nth(index).locator('xpath=ancestor::section[contains(@class,"pve-inventory-host")]')).toBeVisible();
      }
      await expect(report).toHaveAttribute('data-state', initialState);
    };
    const search = report.getByRole('searchbox', { name: 'Filter inventory', exact: true });
    await search.fill(query);
    await expect(report.locator('[data-inventory-kind="guest"]:visible')).toHaveCount(matchingGuests);
    await expect(report.locator('[data-inventory-kind="node"]:visible')).toHaveCount(visibleNodes(query));
    await expect(report.locator('[data-inventory-kind="guest"][hidden]')).toHaveCount(rows.guests.length - matchingGuests);
    await expect(report.locator('[data-inventory-kind="node"][hidden]')).toHaveCount(rows.nodes.length - visibleNodes(query));
    const summary = report.locator('.pve-inventory-filter-summary');
    await expect(summary).toContainText(`Showing ${matchingGuests} of ${rows.guests.length} guest rows and ${expectCockpit ? visibleNodes(query) : matchingNodes} of ${rows.nodes.length} node rows`);
    await assertErrorsPreserved();
    const row = expectCockpit ? cockpitRow(report, target, 'guest') : report.locator('[data-inventory-kind="guest"]').nth(targetIndex);
    await expect(row).toBeVisible();
    const details = row.getByRole('button', { name: /^Details for / });
    await details.focus();
    await page.keyboard.press('Enter');
    const detailRegion = report.locator('[data-inventory-detail]');
    const identityFields = [[expectCockpit ? 'Source' : 'Host', target.source], ['Node', target.node], ['Type', target.type],
      ['ID', target.vmid], ['Guest', target.name || String(target.vmid)]];
    if (expectCockpit) identityFields.push(['Endpoint', target.source]);
    for (const [label, value] of identityFields) {
      await expect(detailRegion.locator('dt').filter({ hasText: new RegExp('^' + label + '$') })
        .locator('xpath=following-sibling::dd[1]')).toHaveText(String(value));
    }
    await expect(detailRegion.getByRole('heading', { name: String(target.name || target.vmid), exact: true })).toBeFocused();
    // '[' must be treated as a literal substring, never a regular expression.
    const metacharGuests = rows.guests.filter(row => matches(row, '[')).length;
    const metacharNodes = rows.nodes.filter(row => matches(row, '[')).length;
    await search.fill('[');
    await expect(report.locator('[data-inventory-kind="guest"]:visible')).toHaveCount(metacharGuests);
    await expect(report.locator('[data-inventory-kind="node"]:visible')).toHaveCount(visibleNodes('['));
    await expect(summary).toContainText(`Showing ${metacharGuests} of ${rows.guests.length} guest rows and ${expectCockpit ? visibleNodes('[') : metacharNodes} of ${rows.nodes.length} node rows`);
    await assertErrorsPreserved();
    let absent = 'inventory-absent-literal-check';
    while ([...rows.nodes, ...rows.guests].some(row => matches(row, absent))) absent += 'x';
    await search.fill(absent);
    await expect(report.locator('[data-inventory-kind]:visible')).toHaveCount(0);
    await expect(report).toHaveAttribute('data-state', initialState);
    await expect(summary).toContainText(`Showing 0 of ${rows.guests.length} guest rows and 0 of ${rows.nodes.length} node rows`);
    await expect(report).toContainText(/No[^\n.]*match/i);
    await assertErrorsPreserved();
    await search.fill('');
    await expect(report.locator('[data-inventory-kind="guest"]:visible')).toHaveCount(rows.guests.length);
    await expect(report.locator('[data-inventory-kind="node"]:visible')).toHaveCount(rows.nodes.length);
    await assertErrorsPreserved();
    expect(inventoryRequests, 'Local filtering must issue no EXTRA BROWSER inventory GET').toBe(before);
    filterEvidence.verified = true;
    filterEvidence.browserRead.noExtraBrowserInventoryGetVerified = true;
    filterEvidence.browserRead.designatedLabCarrierVerified = carrierIndex >= 0;
    filterEvidence.selection = carrierIndex >= 0 ? 'designated lab carrier acceptance' : 'generic observed guest acceptance';
    filterEvidence.selectedIdentity = { source: target.source, node: target.node,
      type: target.type, vmid: target.vmid, name: target.name === undefined ? null : target.name };
    filterEvidence.reportStatePreserved = initialState;
    filterEvidence.matchingGuests = matchingGuests;
    filterEvidence.matchingNodes = matchingNodes;
    filterEvidence.visibleNodeContext = visibleNodes(query);
    filterEvidence.extraBrowserInventoryGetsDuringFiltering = inventoryRequests - before;
    filterEvidence.literalMetacharacterVerified = true;
    filterEvidence.metacharacterMatchingGuests = metacharGuests;
    filterEvidence.metacharacterMatchingNodes = metacharNodes;
    filterEvidence.keyboardDetailsVerified = true;
    filterEvidence.absentLiteralVerified = true;
  };
  const checkReport = async (response, initial = false) => {
    const report = page.locator('#pve-inventory-report');
    await expect(report).toBeVisible();
    await expect(report.getByRole('heading', { name: 'PVE inventory', exact: true })).toBeVisible();
    await expect(report.locator('.pve-inventory')).toHaveAttribute('aria-busy', 'false');
    const status = response.status();
    let rows = { nodes: [], guests: [] };
    let document;
    if (status === 200) {
      document = await response.json();
      rows = inventoryRows(document);
    }
    expect(Array.isArray(rows.nodes) && Array.isArray(rows.guests), 'Original API inventory arrays').toBe(true);
    await expect(report).toHaveAttribute('data-state', /^(ready|observed|partial|empty|unavailable)$/);
    const state = await report.getAttribute('data-state');
    if (status !== 200) expect(state).toBe('unavailable');
    if (document && document.state === 'unavailable') expect(state).toBe('unavailable');
    if (document && document.state === 'unconfigured') expect(state).toBe('empty');
    if (document && document.state === 'partial') expect(state).toBe('partial');
    if (expected === 'populated') {
      expect(status).toBe(200);
      expect(rows.nodes.length, 'Positive demo requires actual nodes').toBeGreaterThan(0);
      expect(rows.guests.length, 'Positive demo requires actual guests').toBeGreaterThan(0);
      expect(['ready', 'observed', 'partial']).toContain(state);
    }
    if (expected === 'empty') {
      expect(status).toBe(200);
      expect(rows.nodes.length + rows.guests.length).toBe(0);
      expect(['ok', 'unconfigured']).toContain(document.state);
      expect(['empty', 'ready']).toContain(state);
    }
    if (expected === 'unavailable') expect(state).toBe('unavailable');
    for (const [kind, records] of [['node', rows.nodes], ['guest', rows.guests]]) {
      const displayed = report.locator(`[data-inventory-kind="${kind}"]`);
      await expect(displayed).toHaveCount(records.length);
      for (let index = 0; index < records.length; index++) {
        const record = records[index];
        const row = expectCockpit ? cockpitRow(report, record, kind) : displayed.nth(index);
        const identity = kind === 'guest' ? record.vmid : (record.name || record.node);
        expect(identity !== undefined && identity !== null, 'Original record has display identity').toBe(true);
        await expect(row).toContainText(String(identity));
        if (record.name) await expect(row).toContainText(String(record.name));
        await expect(row.locator('xpath=ancestor::section[contains(@class,"pve-inventory-host")]')).toContainText(record.source);
        if (kind === 'guest' && record.node) await expect(row).toContainText(record.node);
        if (kind === 'guest' && record.type) await expect(row).toContainText(expectCockpit ? ({ qemu: 'VM', lxc: 'LXC' }[record.type]) : record.type);
      }
      if (records.length) {
        await (expectCockpit ? cockpitRow(report, records[0], kind) : displayed.first()).getByRole('button', { name: /^Details for / }).click();
        await expect(report.locator('[data-inventory-detail]')).toBeVisible();
        const firstIdentity = kind === 'guest' ? records[0].vmid : (records[0].name || records[0].node);
        await expect(report.locator('[data-inventory-detail]')).toContainText(String(firstIdentity));
        if (records[0].node) await expect(report.locator('[data-inventory-detail]')).toContainText(records[0].node);
        if (expectCockpit) {
          for (const label of ['Source', 'Endpoint']) await expect(report.locator('[data-inventory-detail] dt')
            .filter({ hasText: new RegExp('^' + label + '$') }).locator('xpath=following-sibling::dd[1]')).toHaveText(records[0].source);
          for (const label of ['Start', 'Stop', 'Open shell', 'IP controls']) await expect(report.locator('[data-inventory-detail]')
            .getByRole('button', { name: label, exact: true })).toBeDisabled();
        }
      }
    }
    if (initial && expectCockpit) await checkResourceWorkspaces(report, rows);
    if (initial && requireFilter) await checkFilter(report, rows);
    return { status, state, nodes: rows.nodes.length, guests: rows.guests.length,
      sources: document ? document.sources.map(source => ({ state: source.state,
        nodes: source.nodes.length, guests: source.guests.length })) : [] };
  };
  let authenticated = false;
  const observations = [];
  const checkCockpitNavigation = async () => {
    const primary = page.getByRole('navigation', { name: 'Primary' });
    const homeResponse = page.waitForResponse(isInventory);
    await primary.locator('[data-view="home"]').click();
    const homeBody = await (await homeResponse).json();
    const homeRows = inventoryRows(homeBody);
    const home = page.locator('#home-view #home-widgets .pve-cockpit');
    await expect(home).toBeVisible();
    await expect(home).toHaveAttribute('aria-busy', 'false');
    await expect(home.locator('[data-inventory-kind="node"]')).toHaveCount(homeRows.nodes.length);
    await expect(home.locator('[data-inventory-kind="guest"]')).toHaveCount(homeRows.guests.length);
    if (homeRows.nodes.length) await expect(home.locator('.cockpit-node-group').first()).toBeVisible();
    cockpitEvidence.homeOriginalReadVerified = true;
    const beforeWorkspaces = inventoryRequests;
    const workspaces = [
      ['network', 'topology', 'Network & topology'], ['storage', 'nas', 'Storage & NAS'],
      ['pve-firewall', 'security', 'Security & firewall'], ['docker', 'docker', 'Docker & containers'],
      ['security', 'security', 'Security & firewall'], ['vault', 'vault', 'Vault'],
      ['tools', 'tools', 'System & tools'], ['settings', 'settings', 'Settings'],
    ];
    for (const [view, workspace, title] of workspaces) {
      await primary.locator(`[data-view="${view}"]`).click();
      const mounted = page.locator(`.cockpit-workspace[data-workspace="${workspace}"]:visible`);
      await expect(mounted.getByRole('heading', { name: title, exact: true, level: 2 })).toBeVisible();
      const sections = mounted.getByRole('group', { name: title + ' sections', exact: true });
      const buttons = sections.getByRole('button');
      for (let index = 0; index < await buttons.count(); index++) {
        await buttons.nth(index).click();
        await expect(buttons.nth(index)).toHaveAttribute('aria-pressed', 'true');
        const operations = mounted.locator('[data-action-unavailable="true"]');
        expect(await operations.count(), 'Visible management surface exposes unavailable controls').toBeGreaterThan(0);
        expect(await operations.evaluateAll(controls => controls.every(control => control.disabled))).toBe(true);
        await operations.evaluateAll(controls => controls.forEach(control => control.click()));
      }
      cockpitEvidence.workspaces.push(view);
    }
    expect(inventoryRequests, 'Local workspace navigation issues no EXTRA BROWSER inventory GET').toBe(beforeWorkspaces);
    const fleetResponse = page.waitForResponse(isInventory);
    await primary.locator('[data-view="fleet"]').click();
    observations.push(await checkReport(await fleetResponse));
    await page.setViewportSize({ width: 390, height: 844 });
    try {
      const menu = page.getByRole('button', { name: 'Menu', exact: true });
      await expect(menu).toBeVisible();
      await expect(primary).toBeHidden();
      await menu.click();
      await expect(menu).toHaveAttribute('aria-expanded', 'true');
      await expect(primary).toBeVisible();
      const beforeNetwork = inventoryRequests;
      await primary.locator('[data-view="network"]').click();
      const network = page.locator('.cockpit-workspace[data-workspace="topology"]:visible');
      await expect(network).toBeVisible();
      await expect(page).toHaveURL(new URL('/dashboard/network', origin).href);
      await page.reload({ waitUntil: 'domcontentloaded' });
      await expect(network).toBeVisible();
      expect(await verify()).toMatchObject({ status: 200, valid: true });
      await expect(page).toHaveURL(new URL('/dashboard/network', origin).href);
      if (!(await primary.isVisible())) await menu.click();
      await expect(primary).toBeVisible();
      await expect(menu).toHaveAttribute('aria-expanded', 'true');
      await expect(primary.locator('[data-view="network"]')).toHaveAttribute('aria-current', 'page');
      expect(inventoryRequests, 'Preview deep-route reload issues no EXTRA BROWSER inventory GET').toBe(beforeNetwork);
      const phoneFleet = page.waitForResponse(isInventory);
      await primary.locator('[data-view="fleet"]').click();
      observations.push(await checkReport(await phoneFleet));
      expect(await page.evaluate(() => document.documentElement.scrollWidth), 'Actual phone cockpit fits the 390px viewport').toBeLessThanOrEqual(390);
      if (syntheticProvider) await page.evaluate(() => {
        const label = document.createElement('p'); label.textContent = 'SYNTHETIC PROVIDER — ORIGINAL LOCAL SERVER'; document.body.prepend(label);
      });
      await page.evaluate(() => window.scrollTo(0, 0));
      await page.screenshot({ path: testInfo.outputPath('actual-cockpit-phone.png'), fullPage: true,
        mask: [page.locator('input[type="password"]')] });
      cockpitEvidence.phoneMenuNavigationVerified = true;
      cockpitEvidence.networkAuthenticatedDeepReloadVerified = true;
      cockpitEvidence.networkDeepReloadExtraBrowserInventoryGets = 0;
    } finally { await page.setViewportSize({ width: 1440, height: 1000 }); }
    cockpitEvidence.verified = true;
  };
  try {
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    if (!(await verify()).valid) {
      try {
        const login = credentials();
        await expect(page.locator('#login-overlay')).toBeVisible();
        await page.locator('#login-user').fill(login.user);
        await page.locator('#login-pass').fill(login.password);
        const [response] = await Promise.all([
          page.waitForResponse(response => new URL(response.url()).pathname === '/api/auth/login' && response.request().method() === 'POST'),
          page.locator('#login-pass').press('Enter'),
        ]);
        if (response.status() !== 200) throw new Error('Login rejected');
        await expect(page.locator('#login-overlay')).toBeHidden();
        await page.locator('#login-pass').evaluate(input => { input.value = ''; });
      } catch {
        await page.close().catch(() => {});
        throw new Error('Credential entry or sign-in failed; credential details withheld');
      }
    }
    authenticated = true;
    expect(await verify()).toMatchObject({ status: 200, valid: true });
    if (expectCockpit) {
      const home = page.locator('#home-view #home-widgets');
      await expect(home.locator('.pve-cockpit')).toBeVisible();
      await expect(home.locator('.pve-cockpit')).toHaveAttribute('aria-busy', 'false');
      const settledState = expected === 'populated' ? /^(ready|partial)$/ : expected === 'empty' ? /^(ready|empty)$/ :
        expected === 'unavailable' ? /^unavailable$/ : /^(ready|partial|empty|unavailable)$/;
      await expect(home).toHaveAttribute('data-state', settledState);
      cockpitEvidence.initialHomeSettledBeforeFleet = true;
    }
    const first = page.waitForResponse(isInventory);
    await page.getByRole('navigation', { name: 'Primary' }).locator('[data-view="fleet"]').click();
    observations.push(await checkReport(await first, true));
    const beforeRefresh = responses.length;
    const refresh = page.waitForResponse(isInventory);
    await page.locator('#pve-inventory-report').getByRole('button', { name: 'Refresh inventory', exact: true }).click();
    observations.push(await checkReport(await refresh));
    expect(responses.length).toBeGreaterThan(beforeRefresh);
    const afterReload = page.waitForResponse(isInventory);
    await page.reload({ waitUntil: 'domcontentloaded' });
    expect(await verify()).toMatchObject({ status: 200, valid: true });
    await expect(page.locator('#login-overlay')).toBeHidden();
    observations.push(await checkReport(await afterReload));
    if (expectCockpit) await checkCockpitNavigation();
    if (syntheticProvider) await page.evaluate(() => {
      const label = document.createElement('p');
      label.textContent = 'SYNTHETIC PROVIDER — ORIGINAL LOCAL SERVER';
      document.body.prepend(label);
    });
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({ path: testInfo.outputPath('actual-inventory.png'), fullPage: true,
      mask: [page.locator('input[type="password"]')] });
    await page.locator('#header-user-btn').click();
    const logout = page.waitForResponse(response => new URL(response.url()).pathname === '/api/auth/logout' && response.request().method() === 'POST');
    await page.getByRole('button', { name: 'LOG OUT', exact: true }).click();
    expect((await logout).status()).toBe(200);
    await expect(page.locator('#login-overlay')).toBeVisible();
    expect(await verify()).toMatchObject({ status: 200, valid: false });
    authenticated = false;
    expect(browserErrors).toEqual([]);
    if (expectCockpit && expected === 'populated') expect(apiServerErrors, 'Positive cockpit journey has no unexpected API server errors').toEqual([]);
  } finally {
    await testInfo.attach('actual-server-inventory-observations', {
      contentType: 'application/json', body: Buffer.from(JSON.stringify({
        expectation: expected, positiveDemoRequired: expected === 'populated',
        syntheticProvider,
        inventoryResponses: responses.length, inventoryRequests, observations, mutations, browserErrors,
        filterVerification: filterEvidence,
        cockpitVerification: cockpitEvidence,
        apiServerErrors, positiveCockpitServerErrorGate: expectCockpit && expected === 'populated',
        logoutCompleted: !authenticated,
        limitation: syntheticProvider ? 'Original prestarted app with explicitly synthetic TLS provider; no route interception or live provider acceptance.' :
          'Actual prestarted server; no route interception. Target qualification is the lead responsibility. No installation/native/provider acceptance inferred.',
      }, null, 2)),
    });
    expect(mutations.filter(row => row.method !== 'POST' || !['/api/auth/login', '/api/auth/logout'].includes(row.path)), 'Only authentication mutations are permitted').toEqual([]);
  }
});

const { randomUUID } = require('node:crypto');
const { spawn } = require('node:child_process');

const SCHEMA = 'zero-state-web-v1';
const SECRETS = ['operator-password', 'bootstrap-password', 'device-password', 'service-password'];

async function responseJson(response, status) {
  const raw = await response.text();
  let body = {}; try { body = raw ? JSON.parse(raw) : {}; } catch (_) {}
  if (response.status() !== status) throw new Error(`unexpected ${response.status()} response: ${raw}`);
  return body;
}

async function startServer() {
  const child = spawn(process.env.PVE_FREQ_PYTHON || 'python3',
    ['-m', 'tests.support.hermetic_dashboard', '--profile', 'zero-state-resume', '--port', '0'],
    { cwd: process.cwd(), env: { ...process.env, PYTHONUNBUFFERED: '1' }, stdio: ['ignore', 'pipe', 'pipe'] });
  let stdout = ''; let stderr = '';
  let claimFile = ''; let claimId = '';
  const exit = new Promise(resolve => child.once('exit', (code, signal) => resolve({ code, signal })));
  const ready = new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('zero-state resume server readiness timed out')), 15_000);
    child.once('error', error => { clearTimeout(timer); reject(error); });
    let deliveryRead = false;
    child.stdout.setEncoding('utf8'); child.stderr.setEncoding('utf8');
    child.stdout.on('data', chunk => {
      stdout += chunk;
      const claim = stdout.match(/(?:^|\n)HERMETIC_FIRST_ADMIN_CLAIM_FILE (\S+) CLAIM_ID (\S+)(?:\r?\n|$)/);
      const listener = stdout.match(/(?:^|\n)HERMETIC_ZERO_STATE (https:\/\/127\.0\.0\.1:\d+)(?:\r?\n|$)/);
      if (claim) { claimFile = claim[1]; claimId = claim[2]; }
      if (listener && claimFile && !deliveryRead) {
        deliveryRead = true;
        const claimSecret = require('node:fs').readFileSync(claimFile, 'utf8');
        require('node:fs').unlinkSync(claimFile);
        clearTimeout(timer); resolve({ url: listener[1], claimSecret, claimId });
      }
    });
    child.stderr.on('data', chunk => { stderr += chunk; });
    exit.then(result => {
      if (!stdout.includes('HERMETIC_ZERO_STATE ')) {
        clearTimeout(timer); reject(new Error(`zero-state resume server exited before readiness (${result.code ?? result.signal})`));
      }
    });
  });
  try { return { child, exit, ...(await ready), output: () => ({ stdout, stderr }) }; }
  catch (error) {
    if (child.exitCode === null && child.signalCode === null) child.kill('SIGKILL');
    await exit; throw error;
  }
}

async function stopServer(server) {
  if (server.child.exitCode === null && server.child.signalCode === null) server.child.kill('SIGTERM');
  let timer;
  const result = await Promise.race([server.exit, new Promise(resolve => { timer = setTimeout(() => resolve(null), 10_000); })]);
  clearTimeout(timer);
  if (!result) { server.child.kill('SIGKILL'); await server.exit; throw new Error('zero-state resume server did not stop gracefully'); }
  const output = server.output();
  if (result.code !== 0 || result.signal !== null || !output.stdout.includes('HERMETIC_ZERO_STATE_AUDIT PASS')) {
    throw new Error(`zero-state resume child disk audit failed (code=${result.code}, signal=${result.signal}): ${output.stdout}${output.stderr}`);
  }
}

async function createFirstAdmin(context, baseURL, claimSecret) {
  return responseJson(await context.request.post(`${baseURL}/api/setup/create-admin`, { data: {
    schema: SCHEMA, username: 'admin', password: 'operator-password', claim_secret: claimSecret,
    client_request_id: randomUUID()
  }}), 200);
}

async function seedPrerequisites(context, baseURL, expect, claimSecret) {
  const create = await createFirstAdmin(context, baseURL, claimSecret);
  const csrf = create.csrf_token;
  const headers = { Origin: baseURL, 'X-Freq-CSRF': csrf };
  const discoveryStart = await responseJson(await context.request.post(`${baseURL}/api/setup/discovery/start`, { headers, data: {
    schema: SCHEMA, setup_id: create.setup_id, client_request_id: randomUUID(),
    cluster: { name: 'dc01', nodes: [{ host: '192.0.2.26', name: 'pve01' }] },
    bootstrap: { username: 'site-bootstrap', password: 'bootstrap-password' }
  }}), 202);
  const discoveryId = discoveryStart.discovery.id;
  let discovery;
  for (let attempt = 0; attempt < 8; attempt += 1) {
    discovery = await responseJson(await context.request.get(`${baseURL}/api/setup/discovery/status?id=${encodeURIComponent(discoveryId)}`), 200);
    if (discovery.discovery.state === 'succeeded') break;
    await new Promise(resolve => setTimeout(resolve, discovery.discovery.poll_after_ms || 1000));
  }
  expect(discovery.discovery.state).toBe('succeeded');
  const contract = await responseJson(await context.request.post(`${baseURL}/api/setup/contract`, { headers, data: {
    schema: SCHEMA, setup_id: create.setup_id, discovery_id: discoveryId, client_request_id: randomUUID(),
    selections: [
      { resource_id: 'pve:pve01:qemu:100', disposition: 'owned', placement: 'lab' },
      { resource_id: 'device:truenas:192.0.2.10', disposition: 'owned', placement: 'production' },
      { resource_id: 'device:unknown:192.0.2.99', disposition: 'acknowledged' }
    ]
  }}), 200);
  const contractId = contract.contract.id;
  const credentials = await responseJson(await context.request.post(`${baseURL}/api/setup/device-credentials`, { headers, data: {
    schema: SCHEMA, setup_id: create.setup_id, contract_id: contractId, client_request_id: randomUUID(),
    credentials: [{ resource_id: 'device:truenas:192.0.2.10', username: 'root', secrets: { password: 'device-password' } }]
  }}), 200);
  expect(credentials).toMatchObject({ ready: true, credentials: [{ stored_fields: ['password', 'username'], complete: true }] });
  return { create, csrf, discoveryId, contract: contract.contract };
}

async function runZeroStateFailureResume({ browser, expect, forbiddenKey }) {
  const server = await startServer();
  const context = await browser.newContext({ baseURL: server.url, ignoreHTTPSErrors: true });
  const page = await context.newPage();
  const initRequests = []; let journeyError = null;
  page.on('request', request => {
    if (request.method() !== 'POST' || new URL(request.url()).pathname !== '/api/setup/init/start') return;
    initRequests.push({ body: request.postDataJSON(), csrf: request.headers()['x-freq-csrf'] });
  });
  try {
    const seeded = await seedPrerequisites(context, server.url, expect, server.claimSecret);
    let statusFaults = 0;
    const statusFault = async route => {
      statusFaults += 1;
      const response = await route.fetch(); const real = await response.json();
      expect(real).toMatchObject({ state: 'ready', initialized: false, web_setup_complete: false });
      await route.fulfill({ response, json: { ...real, state: 'complete' } });
    };
    await page.route('**/api/setup/status', statusFault);
    await page.goto('/setup');
    await expect(page.locator('#step-progress')).toBeVisible();
    await expect(page.locator('#completion-card')).toBeHidden();
    await expect(page.locator('#form-error')).toContainText('without both durable completion markers');
    expect(statusFaults).toBe(1);
    await page.unroute('**/api/setup/status', statusFault);

    await page.reload();
    await expect(page.locator('#step-launch')).toBeVisible();
    await expect(page.locator('#contract-summary')).toContainText('Owned virtual1');
    await page.locator('#service-pass').fill('service-password');
    await page.locator('#service-pass2').fill('service-password');
    const firstStart = page.waitForResponse(response => new URL(response.url()).pathname === '/api/setup/init/start');
    await page.locator('#launch-form').evaluate(form => form.requestSubmit());
    const firstJob = await responseJson(await firstStart, 202);
    await expect(page.locator('#step-progress')).toBeVisible();
    await expect(page.locator('#retry-init')).toBeVisible();
    await expect(page.locator('#completion-card')).toBeHidden();
    await expect(page.locator('#form-error')).toContainText('freq init did not complete successfully');
    await expect(page.locator('#setup-reason')).toContainText('contract and stored credential presence remain available');

    const failedStatus = await responseJson(await context.request.get(`${server.url}/api/setup/status`), 200);
    expect(failedStatus).toMatchObject({ state: 'blocked', next: 'review_blocker', initialized: false, web_setup_complete: false,
      setup_id: seeded.create.setup_id, active_discovery_id: seeded.discoveryId,
      active_contract_id: seeded.contract.id, active_init_job_id: firstJob.job.id });
    const failedJob = await responseJson(await context.request.get(`${server.url}/api/setup/init/status?id=${encodeURIComponent(firstJob.job.id)}`), 200);
    expect(failedJob.job).toMatchObject({ state: 'failed', returncode: 0, initialized: false, web_setup_complete: false,
      error: { code: 'init_failed', retryable: true } });
    const retained = await responseJson(await context.request.get(`${server.url}/api/setup/contract`), 200);
    expect(retained.contract).toMatchObject({ id: seeded.contract.id, sha256: seeded.contract.sha256, counts: seeded.contract.counts,
      ready: true, credential_requirements: [expect.objectContaining({ stored_fields: ['password', 'username'], complete: true })] });
    for (const secret of SECRETS) expect(JSON.stringify({ failedStatus, failedJob, retained })).not.toContain(secret);
    expect(JSON.stringify({ failedJob, retained })).not.toMatch(/pve-freq-dashboard-|\/setup-init\/|\/tmp\//);

    await context.clearCookies();
    const publicStatusResponse = page.waitForResponse(response => new URL(response.url()).pathname === '/api/setup/status');
    await page.goto('/setup');
    const publicStatus = await responseJson(await publicStatusResponse, 200);
    expect(publicStatus).toMatchObject({ state: 'blocked', next: 'review_blocker', initialized: false, web_setup_complete: false,
      setup_id: null, active_discovery_id: null, active_contract_id: null, active_init_job_id: null });
    await expect(page.locator('#resume-session')).toBeVisible();
    await expect(page.locator('#completion-card')).toBeHidden();
    await expect(page.locator('#retry-init')).toBeHidden();

    const loginResponse = await context.request.post(`${server.url}/api/auth/login`, {
      headers: { Origin: server.url }, data: { username: 'admin', password: 'operator-password' }
    });
    const login = await responseJson(loginResponse, 200);
    expect(login.csrf_token).toBeTruthy(); expect(login.csrf_token).not.toBe(seeded.csrf);
    expect(loginResponse.headers()['set-cookie']).toContain('Secure');
    const stale = await context.request.post(`${server.url}/api/setup/discovery/status?id=stale-csrf`, {
      headers: { Origin: server.url, 'X-Freq-CSRF': seeded.csrf }
    });
    expect(stale.status()).toBe(403); expect((await stale.json()).error).toBe('CSRF token required');

    await page.evaluate(() => {
      window.__setupReasonHistory = [];
      new MutationObserver(() => window.__setupReasonHistory.push(document.querySelector('#setup-reason').textContent))
        .observe(document.querySelector('#setup-reason'), { childList: true, characterData: true, subtree: true });
    });
    await page.locator('#retry-session').click();
    await expect(page.locator('#step-progress')).toBeVisible();
    await expect(page.locator('#retry-init')).toBeVisible();
    const recoveryReasons = await page.evaluate(() => window.__setupReasonHistory);
    expect(recoveryReasons).not.toContain('no setup performed');
    expect(recoveryReasons.some(reason => reason.includes('Recovering the owner-bound init result'))).toBe(true);

    const retryDiscoveryRequest = page.waitForRequest(request => new URL(request.url()).pathname === '/api/setup/discovery/status');
    await page.locator('#retry-init').click();
    expect(new URL((await retryDiscoveryRequest).url()).searchParams.get('id')).toBe(seeded.discoveryId);
    await expect(page.locator('#step-launch')).toBeVisible();
    await expect(page.locator('#setup-reason')).toContainText('Retained contract and credential presence verified');
    await page.locator('#service-pass').fill('service-password');
    await page.locator('#service-pass2').fill('service-password');
    const secondStart = page.waitForResponse(response => new URL(response.url()).pathname === '/api/setup/init/start');
    await page.locator('#launch-form').evaluate(form => form.requestSubmit());
    const secondJob = await responseJson(await secondStart, 202);
    expect(secondJob.job.id).not.toBe(firstJob.job.id);
    await expect(page.locator('#completion-card')).toBeVisible();
    await expect(page.locator('#progress-state')).toHaveText('complete');
    await expect(page.locator('#phase-log')).toContainText('Phase 12 / 12 - Verification');
    await expect(page.locator('#retry-init')).toBeHidden();
    await expect(page.locator('#form-error')).toBeHidden();

    expect(initRequests).toHaveLength(2);
    expect(initRequests[0].csrf).toBe(seeded.csrf); expect(initRequests[1].csrf).toBe(login.csrf_token);
    expect(initRequests[0].body.client_request_id).not.toBe(initRequests[1].body.client_request_id);
    for (const request of initRequests) {
      expect(forbiddenKey(request.body)).toBe('');
      expect(request.body).toMatchObject({ service_account: { username: 'freq-admin', password: 'service-password' } });
    }
    const finalStatus = await responseJson(await context.request.get(`${server.url}/api/setup/status`), 200);
    expect(finalStatus).toMatchObject({ state: 'complete', initialized: true, web_setup_complete: true });
    const finalJob = await responseJson(await context.request.get(`${server.url}/api/setup/init/status?id=${encodeURIComponent(secondJob.job.id)}`), 200);
    expect(finalJob.job).toMatchObject({ state: 'succeeded', returncode: 0, initialized: true, web_setup_complete: true });
    for (const secret of SECRETS) expect(JSON.stringify({ finalStatus, finalJob })).not.toContain(secret);
    expect(JSON.stringify(finalJob)).not.toMatch(/pve-freq-dashboard-|\/setup-init\/|\/tmp\//);
  } catch (error) { journeyError = error; throw error;
  } finally {
    await context.close();
    try { await stopServer(server);
    } catch (shutdownError) {
      if (journeyError) throw new AggregateError([journeyError, shutdownError], `zero-state failure/resume journey failed: ${journeyError.message}; terminal audit: ${shutdownError.message}`);
      throw shutdownError;
    }
  }
}

module.exports = { createFirstAdmin, runZeroStateFailureResume };

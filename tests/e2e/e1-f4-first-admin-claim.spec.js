const { test, expect } = require('@playwright/test');
const { spawn } = require('node:child_process');
const { createHash } = require('node:crypto');
const fs = require('node:fs');
const { createFirstAdmin } = require('../support/zero_state_failure_resume');

const secretAuditFile = process.env.PVE_FREQ_F4_SECRET_AUDIT_FILE;
if (!secretAuditFile) throw new Error('F4 claim owner must run through the secret-safe browser runner');

test.use({ trace: 'off', screenshot: 'off', video: 'off' });

function digest(value) {
  return createHash('sha256').update(value, 'utf8').digest('hex');
}

function registerSecret(value) {
  if ((fs.statSync(secretAuditFile).mode & 0o777) !== 0o600) {
    throw new Error('F4 secret audit registry is not mode 0600');
  }
  fs.appendFileSync(secretAuditFile, `${value}\n`, { encoding: 'utf8' });
}

function containsEither(value, secrets) {
  const rendered = typeof value === 'string' ? value : JSON.stringify(value);
  return secrets.some(secret => rendered.includes(secret));
}

function assertOperatorExistsSkipsGuidance(calls) {
  expect(calls.filter(code => code === 'operator_exists')).toEqual([]);
}

function assertResumeSignInContract(link) {
  expect(link).toEqual({ id: 'resume-sign-in', href: '/', text: 'Open sign in' });
}

async function requestEvidence(request) {
  const url = new URL(request.url());
  return {
    pathname: url.pathname,
    search: url.search,
    hash: url.hash,
    headers: await request.allHeaders(),
    body: request.postDataJSON(),
  };
}

async function startClaimServer() {
  const child = spawn(process.env.PVE_FREQ_PYTHON || 'python3',
    ['-m', 'tests.support.hermetic_dashboard', '--profile', 'first-admin-claim', '--port', '0'],
    { cwd: process.cwd(), env: { ...process.env, PYTHONUNBUFFERED: '1' }, stdio: ['ignore', 'pipe', 'pipe'] });
  let stdout = ''; let stderr = ''; let claimFile = ''; let claimId = '';
  const exit = new Promise(resolve => child.once('exit', (code, signal) => resolve({ code, signal })));
  const ready = new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('first-admin claim server readiness timed out')), 15_000);
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
        const claimSecret = fs.readFileSync(claimFile, 'utf8');
        registerSecret(claimSecret);
        fs.unlinkSync(claimFile);
        clearTimeout(timer); resolve({ url: listener[1], claimSecret, claimId });
      }
    });
    child.stderr.on('data', chunk => { stderr += chunk; });
    exit.then(result => {
      if (!stdout.includes('HERMETIC_ZERO_STATE ')) {
        clearTimeout(timer);
        reject(new Error(`first-admin claim server exited before readiness (${result.code ?? result.signal})`));
      }
    });
  });
  try { return { child, exit, ...(await ready), output: () => ({ stdout, stderr }) }; }
  catch (error) {
    if (child.exitCode === null && child.signalCode === null) child.kill('SIGKILL');
    await exit; throw error;
  }
}

async function stopClaimServer(server) {
  if (server.child.exitCode === null && server.child.signalCode === null) server.child.kill('SIGTERM');
  let timer;
  const result = await Promise.race([
    server.exit,
    new Promise(resolve => { timer = setTimeout(() => resolve(null), 10_000); })
  ]);
  clearTimeout(timer);
  if (!result) {
    server.child.kill('SIGKILL'); await server.exit;
    throw new Error('first-admin claim server did not stop gracefully');
  }
  const output = server.output();
  if (result.code !== 0 || result.signal !== null ||
      !output.stdout.includes('HERMETIC_FIRST_ADMIN_CLAIM_AUDIT PASS')) {
    throw new Error(`first-admin claim disk audit failed (code=${result.code}, signal=${result.signal})`);
  }
  return output;
}

test('direct programmatic client sends the private claim without Origin and commits once', async ({ browser }) => {
  const server = await startClaimServer();
  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  let journeyError = null;
  try {
    const created = await createFirstAdmin(context, server.url, server.claimSecret);
    expect(created).toMatchObject({ ok: true, user: 'admin', role: 'admin', session_started: true });
    expect(containsEither(created, [server.claimSecret])).toBe(false);
    const replay = await context.request.post(`${server.url}/api/setup/create-admin`, { data: {
      schema: 'zero-state-web-v1', username: 'admin', password: 'operator-password',
      claim_secret: server.claimSecret, client_request_id: '12345678-1234-4123-8123-123456789abc'
    }});
    expect(replay.status()).toBe(409);
    expect(await replay.json()).toMatchObject({ error: { code: 'operator_exists' } });
  } catch (error) { journeyError = error; throw error;
  } finally {
    await context.close();
    try {
      const output = await stopClaimServer(server);
      expect(containsEither(output, [server.claimSecret])).toBe(false);
    } catch (shutdownError) {
      if (journeyError) { journeyError.cause = shutdownError; throw journeyError; }
      throw shutdownError;
    }
  }
});

test('real browser keeps the claim out of every secondary channel and clears before advance', async ({ browser }) => {
  const server = await startClaimServer();
  const wrongClaim = '  Wrong-Mixed_Case-Claim  ';
  registerSecret(wrongClaim);
  const secrets = [server.claimSecret, wrongClaim];
  const context = await browser.newContext({ baseURL: server.url, ignoreHTTPSErrors: true });
  const page = await context.newPage();
  const consoleMessages = [];
  const setupMutations = [];
  page.on('console', message => consoleMessages.push(message.text()));
  page.on('request', request => {
    const path = new URL(request.url()).pathname;
    if (request.method() === 'POST' && path.startsWith('/api/setup/')) setupMutations.push(request);
  });
  let journeyError = null;
  try {
    await page.goto('/setup');
    await expect(page.locator('#step-operator')).toBeVisible();
    expect(await page.locator('#operator-claim').getAttribute('name')).toBeNull();
    const formKeys = await page.locator('#operator-form').evaluate(form => [...new FormData(form).keys()]);
    expect(formKeys).not.toContain('claim_secret');

    await page.evaluate(registeredSecrets => {
      window.__f4TransitionEvents = [];
      window.__f4SecondaryChannelLeaks = [];
      const ids = ['operator-claim', 'operator-pass', 'operator-pass2', 'step-connect'];
      const record = label => window.__f4TransitionEvents.push(label);
      const hasSecret = value => registeredSecrets.some(secret => String(value).includes(secret));
      const valueDescriptor = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value');
      Object.defineProperty(HTMLInputElement.prototype, 'value', {
        configurable: valueDescriptor.configurable,
        enumerable: valueDescriptor.enumerable,
        get: valueDescriptor.get,
        set(value) {
          if (ids.slice(0, 3).includes(this.id) && value === '') record(`cleared:${this.id}`);
          return valueDescriptor.set.call(this, value);
        },
      });
      const storageSet = Storage.prototype.setItem;
      Storage.prototype.setItem = function(key, value) {
        if (hasSecret(key) || hasSecret(value)) window.__f4SecondaryChannelLeaks.push('storage');
        return storageSet.call(this, key, value);
      };
      const cookieDescriptor = Object.getOwnPropertyDescriptor(Document.prototype, 'cookie');
      if (cookieDescriptor && cookieDescriptor.set) {
        Object.defineProperty(document, 'cookie', {
          configurable: true,
          get: cookieDescriptor.get ? cookieDescriptor.get.bind(document) : undefined,
          set(value) {
            if (hasSecret(value)) window.__f4SecondaryChannelLeaks.push('cookie');
            return cookieDescriptor.set.call(document, value);
          },
        });
      }
      for (const method of ['pushState', 'replaceState']) {
        const original = history[method].bind(history);
        history[method] = function(...args) {
          if (hasSecret(args)) window.__f4SecondaryChannelLeaks.push(`history:${method}`);
          return original(...args);
        };
      }
      addEventListener('hashchange', () => {
        if (hasSecret(location.href)) window.__f4SecondaryChannelLeaks.push('location');
      });
      new MutationObserver(() => {
        const step = document.getElementById('step-connect');
        if (!step.hidden && getComputedStyle(step).display !== 'none') record('advanced:step-connect');
      }).observe(document.getElementById('step-connect'), { attributes: true, attributeFilter: ['class', 'hidden', 'style'] });
    }, secrets);

    await page.locator('#operator-user').fill('admin');
    await page.locator('#operator-pass').fill('operator-password');
    await page.locator('#operator-pass2').fill('operator-password');
    await page.locator('#operator-form').evaluate(form => form.requestSubmit());
    await expect(page.locator('#form-error')).toHaveAttribute('role', 'alert');
    await expect(page.locator('#form-error')).toBeVisible();
    await expect(page.locator('#form-error')).toHaveText('First-boot claim secret is required.');
    await expect(page.locator('#operator-claim')).toBeFocused();
    expect(setupMutations).toHaveLength(0);

    await page.locator('#operator-claim').fill(wrongClaim);
    const wrongResponsePromise = page.waitForResponse(response =>
      new URL(response.url()).pathname === '/api/setup/create-admin');
    await page.locator('#operator-form').evaluate(form => form.requestSubmit());
    const wrongResponse = await wrongResponsePromise;
    const wrongPayload = await wrongResponse.json();
    expect(wrongResponse.status()).toBe(403);
    expect(wrongPayload).toMatchObject({
      error: { code: 'claim_secret_invalid', field: 'claim_secret', retryable: true }
    });
    const projectedMessage = await page.locator('#form-error').textContent();
    expect(projectedMessage === wrongPayload.error.message).toBe(true);
    expect(projectedMessage.includes('newest claim for the current service')).toBe(true);
    expect(projectedMessage.includes('local first-admin claim reset procedure')).toBe(true);
    await expect(page.locator('#step-operator')).toBeVisible();
    await expect(page.locator('#operator-claim')).toBeFocused();

    const wrongEvidence = await requestEvidence(setupMutations[0]);
    expect(wrongEvidence.pathname).toBe('/api/setup/create-admin');
    expect(wrongEvidence.search).toBe(''); expect(wrongEvidence.hash).toBe('');
    expect(wrongEvidence.headers['content-type'].toLowerCase().startsWith('application/json')).toBe(true);
    expect(containsEither({ url: setupMutations[0].url(), headers: wrongEvidence.headers }, secrets)).toBe(false);
    expect(Object.keys(wrongEvidence.body).sort()).toEqual([
      'claim_secret', 'client_request_id', 'password', 'schema', 'username'
    ]);
    expect(digest(wrongEvidence.body.claim_secret)).toBe(digest(wrongClaim));
    expect(JSON.stringify(wrongEvidence.body).split('claim_secret').length - 1).toBe(1);
    await page.waitForTimeout(250);
    expect(setupMutations.map(request => new URL(request.url()).pathname)).toEqual(['/api/setup/create-admin']);
    const statusAfterWrong = await page.evaluate(async () => (await fetch('/api/setup/status')).json());
    expect(statusAfterWrong.state).toBe('needs_operator');

    await page.locator('#operator-pass').fill('operator-password');
    await page.locator('#operator-pass2').fill('operator-password');
    await page.locator('#operator-claim').fill(server.claimSecret);
    const acceptedPromise = page.waitForResponse(response =>
      new URL(response.url()).pathname === '/api/setup/create-admin');
    await page.locator('#operator-form').evaluate(form => form.requestSubmit());
    const accepted = await acceptedPromise;
    const acceptedBody = await accepted.json();
    expect(accepted.status()).toBe(200);
    expect(acceptedBody).toMatchObject({ ok: true, user: 'admin', role: 'admin', session_started: true });
    await expect(page.locator('#operator-claim')).toHaveValue('');
    await expect(page.locator('#operator-pass')).toHaveValue('');
    await expect(page.locator('#operator-pass2')).toHaveValue('');
    await expect(page.locator('#step-connect')).toBeVisible();

    const correctEvidence = await requestEvidence(setupMutations[1]);
    expect(correctEvidence.pathname).toBe('/api/setup/create-admin');
    expect(correctEvidence.search).toBe(''); expect(correctEvidence.hash).toBe('');
    expect(correctEvidence.headers['content-type'].toLowerCase().startsWith('application/json')).toBe(true);
    expect(containsEither({ url: setupMutations[1].url(), headers: correctEvidence.headers }, secrets)).toBe(false);
    expect(Object.keys(correctEvidence.body).sort()).toEqual([
      'claim_secret', 'client_request_id', 'password', 'schema', 'username'
    ]);
    expect(digest(correctEvidence.body.claim_secret)).toBe(digest(server.claimSecret));
    expect(JSON.stringify(correctEvidence.body).split('claim_secret').length - 1).toBe(1);

    const events = await page.evaluate(() => window.__f4TransitionEvents);
    const advance = events.indexOf('advanced:step-connect');
    expect(advance).toBeGreaterThan(-1);
    for (const id of ['operator-claim', 'operator-pass', 'operator-pass2']) {
      const cleared = events.indexOf(`cleared:${id}`);
      expect(cleared).toBeGreaterThan(-1);
      expect(cleared).toBeLessThan(advance);
    }
    const secondaryChannels = {
      responses: [wrongPayload, acceptedBody],
      consoleMessages,
      cookies: await context.cookies(),
      localStorage: await page.evaluate(() => ({ ...localStorage })),
      sessionStorage: await page.evaluate(() => ({ ...sessionStorage })),
      historyState: await page.evaluate(() => history.state),
      locationHref: page.url(),
      transientSecondaryWrites: await page.evaluate(() => window.__f4SecondaryChannelLeaks),
      pageHTML: await page.content(),
      pageText: await page.locator('html').textContent(),
      evidenceSummary: { requestCount: setupMutations.length, clearBeforeAdvance: true },
    };
    expect(containsEither(secondaryChannels, secrets)).toBe(false);
  } catch (error) { journeyError = error; throw error;
  } finally {
    await context.close();
    try {
      const output = await stopClaimServer(server);
      expect(containsEither(output, secrets)).toBe(false);
    } catch (shutdownError) {
      if (journeyError) { journeyError.cause = shutdownError; throw journeyError; }
      throw shutdownError;
    }
  }
});

test('claim guidance executes exhaustive focus timing, null, unknown, and operator dispositions', async ({ browser }) => {
  const server = await startClaimServer();
  const context = await browser.newContext({ baseURL: server.url, ignoreHTTPSErrors: true });
  let routeOperatorThroughGuidance = false;
  await context.addInitScript(() => { window.__f4ClaimGuidanceCalls = []; });
  await context.route('**/static/js/setup.js*', async route => {
    const response = await route.fetch();
    let source = await response.text();
    const helperAnchor = /function\s+claimFailureGuidance\s*\(\s*code\s*\)\s*\{/;
    expect(source).toMatch(helperAnchor);
    source = source.replace(helperAnchor, match => `${match}window.__f4ClaimGuidanceCalls.push(code);`);
    if (routeOperatorThroughGuidance) {
      const operatorAnchor = /if\s*\(\s*error\.code\s*===\s*['"]operator_exists['"]\s*\)\s*\{/;
      expect(source).toMatch(operatorAnchor);
      source = source.replace(operatorAnchor, match => `${match}claimFailureGuidance(error.code);`);
    }
    await route.fulfill({ response, body: source });
  });
  const page = await context.newPage();
  let responseCase;
  await context.route('**/api/setup/create-admin', async route => {
    await route.fulfill({
      status: responseCase.status,
      contentType: 'application/json',
      headers: { 'X-Request-ID': '0a1b2c3d4e5f' },
      body: JSON.stringify({
        ok: false,
        schema: 'zero-state-web-v1',
        request_id: '0a1b2c3d4e5f',
        error: {
          code: responseCase.code,
          message: responseCase.message,
          retryable: responseCase.retryable,
        },
      }),
    });
  });
  const cases = [
    { code: 'claim_secret_required', status: 400, retryable: false, focus: 'operator-claim', message: 'The first-boot claim is required.' },
    { code: 'claim_secret_invalid', status: 403, retryable: true, focus: 'operator-claim', message: 'Use the newest claim or follow the local first-admin claim reset procedure in the zero-state runbook.' },
    { code: 'claim_state_unavailable', status: 503, retryable: true, focus: 'create-operator', message: 'First-admin setup is temporarily unavailable; retry.' },
    { code: 'claim_rate_limited', status: 429, retryable: true, focus: 'create-operator', message: 'Wait for the current rate window, then retry.' },
    { code: 'claim_consumed', status: 409, retryable: false, focus: null, message: 'Follow the local first-admin claim reset procedure in the zero-state runbook.' },
    { code: 'setup_closed', status: 403, retryable: false, focus: 'resume-sign-in', message: 'First-admin setup is complete; sign in through the dashboard and resume setup.' },
    { code: 'future_ungoverned_code', status: 409, retryable: false, focus: null, message: 'Authoritative server guidance for a future condition.' },
    { code: 'operator_exists', status: 409, retryable: false, focus: 'resume-sign-in', message: 'The first operator exists; sign in through the dashboard and resume setup.' },
  ];
  let journeyError = null;
  try {
    for (const item of cases) {
      responseCase = item;
      await page.goto('/setup');
      await expect(page.locator('#step-operator')).toBeVisible();
      await page.locator('#operator-user').fill('admin');
      await page.locator('#operator-pass').fill('operator-password');
      await page.locator('#operator-pass2').fill('operator-password');
      await page.locator('#operator-claim').fill(server.claimSecret);
      const activeBefore = await page.evaluate(() => {
        window.__f4FocusCalls = [];
        const originalFocus = HTMLElement.prototype.focus;
        HTMLElement.prototype.focus = function(...args) {
          window.__f4FocusCalls.push(this.id || this.getAttribute('data-api-field') || 'anonymous');
          return originalFocus.apply(this, args);
        };
        document.getElementById('operator-pass2').focus();
        window.__f4FocusCalls = [];
        return document.activeElement && document.activeElement.id;
      });
      await page.locator('#operator-form').evaluate(form => form.requestSubmit());
      await expect(page.locator('#form-error')).toHaveAttribute('role', 'alert');
      await expect(page.locator('#form-error')).toHaveText(item.message);
      await expect(page.locator('#step-operator')).toBeVisible();

      if (item.focus === null) {
        expect(await page.evaluate(() => window.__f4FocusCalls)).toEqual([]);
        expect(await page.evaluate(() => document.activeElement && document.activeElement.id)).toBe(activeBefore);
      } else {
        await expect(page.locator(`#${item.focus}`)).toBeFocused();
        const calls = await page.evaluate(() => window.__f4FocusCalls);
        expect(calls.at(-1)).toBe(item.focus);
      }
      if (item.focus === 'create-operator') {
        await expect(page.locator('#create-operator')).toBeEnabled();
      }
      if (item.focus === 'resume-sign-in') {
        await expect(page.locator('#resume-session')).toBeVisible();
        await expect(page.locator('#resume-sign-in')).toBeVisible();
        await expect(page.locator('#resume-sign-in')).toHaveAttribute('href', '/');
        const link = await page.locator('#resume-sign-in').evaluate(element => ({
          id: element.id,
          href: element.getAttribute('href'),
          text: element.textContent.replace(/\s+/g, ' ').trim(),
        }));
        assertResumeSignInContract(link);
        expect(() => assertResumeSignInContract({ ...link, text: 'Continue to sign in' })).toThrow();
      }
      if (item.code === 'operator_exists') {
        assertOperatorExistsSkipsGuidance(await page.evaluate(() => window.__f4ClaimGuidanceCalls));
      }
      expect(await page.evaluate(() => window.__f4FocusCalls.includes('resume-session'))).toBe(false);
    }

    routeOperatorThroughGuidance = true;
    responseCase = cases.find(item => item.code === 'operator_exists');
    const mutatedPage = await context.newPage();
    await mutatedPage.goto('/setup');
    await mutatedPage.locator('#operator-user').fill('admin');
    await mutatedPage.locator('#operator-pass').fill('operator-password');
    await mutatedPage.locator('#operator-pass2').fill('operator-password');
    await mutatedPage.locator('#operator-claim').fill(server.claimSecret);
    await mutatedPage.locator('#operator-form').evaluate(form => form.requestSubmit());
    await expect(mutatedPage.locator('#form-error')).toHaveText(responseCase.message);
    const routedCalls = await mutatedPage.evaluate(() => window.__f4ClaimGuidanceCalls);
    expect(routedCalls).toContain('operator_exists');
    expect(() => assertOperatorExistsSkipsGuidance(routedCalls)).toThrow();
    await mutatedPage.close();
  } catch (error) {
    journeyError = error;
    throw error;
  } finally {
    try {
      await createFirstAdmin(context, server.url, server.claimSecret);
    } catch (cleanupError) {
      if (journeyError) journeyError.cause = cleanupError;
      else journeyError = cleanupError;
    }
    await context.close();
    try {
      const output = await stopClaimServer(server);
      expect(containsEither(output, [server.claimSecret])).toBe(false);
    } catch (shutdownError) {
      if (journeyError) { journeyError.cause = shutdownError; throw journeyError; }
      throw shutdownError;
    }
    if (journeyError) throw journeyError;
  }
});

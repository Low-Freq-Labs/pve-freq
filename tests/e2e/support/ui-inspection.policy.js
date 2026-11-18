const { test } = require('node:test');
const assert = require('node:assert/strict');
const http = require('node:http');
const { once } = require('node:events');
const { spawnSync } = require('node:child_process');
const { chromium } = require('@playwright/test');
const { allowedRequest, installInspectionPolicy } = require('./ui-inspection-policy');
const origin = 'https://example.invalid';

test('inspection refuses operational probes, writes, other origins and overrides', () => {
  for (const endpoint of ['/api/keys', '/api/log', '/api/logs/query', '/api/fleet/overview', '/api/vm/destroy', '/api/lab-tool/proxy']) {
    for (const method of ['GET', 'POST', 'PUT', 'DELETE']) assert.equal(allowedRequest(method, origin + endpoint, origin), false);
  }
  assert.equal(allowedRequest('GET', 'https://other.invalid/api/info', origin), false);
  assert.equal(allowedRequest('GET', origin + '/api/info?method=POST', origin), false);
  assert.equal(allowedRequest('POST', origin + '/api/auth/login?next=delete', origin), false);
  assert.equal(allowedRequest('GET', 'https://user:pass@example.invalid/api/info', origin), false);
  assert.equal(allowedRequest('POST', origin + '/api/auth/login', origin), true);
  assert.equal(allowedRequest('GET', origin + '/api/setup/status', origin), true);
  assert.equal(allowedRequest('GET', origin + '/static/js/app.js?v=1.0.0', origin), true);
  assert.equal(allowedRequest('GET', origin + '/static/js/app.js?method=POST', origin), false);
});

test('CLI refuses implicit live targets and operational journeys before launch', () => {
  for (const args of [
    ['--mode', 'live'], ['--url', origin],
    ['--mode', 'live', '--url', origin, '--journey', 'baseline'],
    ['--mode', 'live', '--url', 'https://user:pass@example.invalid'],
    ['--mode', 'live', '--url', 'http://example.invalid'],
    ['--port', '0']
  ]) {
    const result = spawnSync(process.execPath, ['tests/support/run_ui_check.js', ...args], { encoding: 'utf8' });
    assert.equal(result.status, 2);
    assert.match(result.stderr, /UI check refused/);
    assert.doesNotMatch(result.stdout, /Evidence:/);
  }
});

test('real Chromium guard prevents forbidden requests from reaching a server', async () => {
  const seen = [];
  const server = http.createServer((request, response) => {
    seen.push(`${request.method} ${request.url}`);
    response.setHeader('Content-Type', request.url === '/' ? 'text/html' : 'application/json');
    response.end(request.url === '/' ? '<html><body>inspection fixture</body></html>' : '{}');
  });
  server.listen(0, '127.0.0.1');
  await once(server, 'listening');
  let browser;
  try {
    const target = `http://127.0.0.1:${server.address().port}`;
    browser = await chromium.launch();
    const context = await browser.newContext({ serviceWorkers: 'block' });
    const blocked = new Set();
    await installInspectionPolicy(context, target, blocked);
    const page = await context.newPage();
    await page.goto(target);
    const statuses = await page.evaluate(async () => {
      const results = [];
      for (const [path, method] of [['/api/info', 'GET'], ['/api/keys', 'GET'], ['/api/log', 'GET'], ['/api/vm/destroy', 'POST']]) {
        results.push((await fetch(path, { method })).status);
      }
      return results;
    });
    assert.deepEqual(statuses, [200, 503, 503, 503]);
    assert.equal(seen.some(value => /keys|\/api\/log|destroy/.test(value)), false);
    assert.equal(blocked.has('GET /api/keys'), true);
    assert.equal(blocked.has('POST /api/vm/destroy'), true);
  } finally {
    if (browser) await browser.close();
    server.closeAllConnections();
    await new Promise(resolve => server.close(resolve));
  }
});

test('redirects cannot reach forbidden destinations or forward login bodies', async () => {
  const received = [];
  let targetPath = '/api/keys';
  let status = 302;
  const destination = http.createServer((request, response) => {
    received.push(`foreign ${request.method} ${request.url}`);
    request.resume(); response.end('{}');
  });
  destination.listen(0, '127.0.0.1'); await once(destination, 'listening');
  const server = http.createServer((request, response) => {
    if (request.url === '/') { response.setHeader('Content-Type', 'text/html'); response.end('<body>redirect fixture</body>'); return; }
    if (request.url === '/api/info' || request.url === '/api/auth/login') {
      request.resume(); response.writeHead(status, { Location: targetPath }); response.end(); return;
    }
    received.push(`local ${request.method} ${request.url}`);
    request.resume(); response.end('{}');
  });
  server.listen(0, '127.0.0.1'); await once(server, 'listening');
  let browser;
  try {
    browser = await chromium.launch();
    const target = `http://127.0.0.1:${server.address().port}`;
    const context = await browser.newContext({ serviceWorkers: 'block' });
    const blocked = new Set(); await installInspectionPolicy(context, target, blocked);
    const page = await context.newPage(); await page.goto(target);
    for (const redirectStatus of [301, 302, 303, 307, 308]) {
      status = redirectStatus;
      for (const destinationPath of ['/api/keys', `http://127.0.0.1:${destination.address().port}/secret-receiver`]) {
        targetPath = destinationPath;
        for (const method of ['GET', 'POST']) {
          const code = await page.evaluate(async method => (await fetch(method === 'GET' ? '/api/info' : '/api/auth/login', {
            method, ...(method === 'POST' ? { body: 'synthetic-login-body' } : {})
          })).status, method);
          assert.equal(code, 503);
        }
      }
    }
    assert.deepEqual(received, [], 'No redirect destination may receive any request, including a credential body');
    assert.equal([...blocked].some(entry => entry.startsWith('REDIRECT 307 POST')), true);
  } finally {
    if (browser) await browser.close();
    for (const listener of [server, destination]) {
      listener.closeAllConnections(); await new Promise(resolve => listener.close(resolve));
    }
  }
});

test('forced credential failures never persist the synthetic secret in runner evidence', { timeout: 90_000 }, async () => {
  const fs = require('node:fs');
  const os = require('node:os');
  const path = require('node:path');
  const https = require('node:https');
  const { randomBytes } = require('node:crypto');
  const { spawn } = require('node:child_process');
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'ui-secret-policy-'));
  const marker = randomBytes(24).toString('hex');
  const passwordFile = path.join(directory, 'password');
  fs.writeFileSync(passwordFile, marker, { mode: 0o600 });
  const certificate = path.join(directory, 'cert.pem');
  const key = path.join(directory, 'key.pem');
  const cert = spawnSync('openssl', ['req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-keyout', key, '-out', certificate,
    '-days', '1', '-subj', '/CN=localhost'], { stdio: 'ignore' });
  assert.equal(cert.status, 0);
  let scenario = 'disabled';
  const server = https.createServer({ key: fs.readFileSync(key), cert: fs.readFileSync(certificate) }, (request, response) => {
    if (request.url === '/api/auth/login') {
      request.resume(); response.writeHead(401, { 'Content-Type': 'application/json' });
      response.end(JSON.stringify({ error: 'rejected ' + marker })); return;
    }
    response.setHeader('Content-Type', 'text/html');
    response.end(`<html><body><div id="login-overlay"><form id="login-form"><input id="login-user">
      ${scenario === 'missing' ? '' : `<input type="password" id="login-pass" ${scenario === 'disabled' ? 'disabled' : ''}>`}
      <button>Login</button></form><div id="login-error"></div></div>
      <script>document.querySelector('form').onsubmit=async e=>{e.preventDefault();
      const r=await fetch('/api/auth/login',{method:'POST',body:JSON.stringify({password:document.querySelector('#login-pass').value})});
      document.querySelector('#login-error').textContent=(await r.json()).error;};</script></body></html>`);
  });
  server.listen(0, '127.0.0.1'); await once(server, 'listening');
  const outputRoot = fs.mkdtempSync(path.resolve('test-results', 'credential-failure-proof-'));
  let scanned = 0;
  try {
    for (const failure of ['disabled', 'missing', 'rejected']) {
      scenario = failure;
      const child = spawn(process.execPath, ['tests/support/run_ui_check.js', '--mode', 'live', '--url',
        `https://127.0.0.1:${server.address().port}`, '--insecure-tls', '--output-root', outputRoot], {
        env: { ...process.env, PVE_FREQ_ADMIN_USER: 'synthetic-user', PVE_FREQ_ADMIN_PASSWORD_FILE: passwordFile },
        stdio: ['ignore', 'pipe', 'pipe']
      });
      let output = ''; child.stdout.on('data', chunk => { output += chunk; }); child.stderr.on('data', chunk => { output += chunk; });
      const [exit] = await once(child, 'exit');
      assert.equal(exit, 1, `${failure} must fail the actual runner`);
      assert.equal(output.includes(marker), false, 'runner output must not contain the secret');
    }
    const inspect = dir => {
      for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
        const file = path.join(dir, entry.name);
        if (entry.isDirectory()) inspect(file);
        else {
          assert.equal(fs.readFileSync(file).includes(Buffer.from(marker)), false, 'secret found in evidence file');
          scanned += 1;
        }
      }
    };
    inspect(outputRoot);
    assert.ok(scanned >= 9, 'Scan actual JSON reports, logs and attached contexts for all failures');
    fs.writeFileSync(path.join(outputRoot, 'proof.json'), JSON.stringify({ scenarios: ['disabled', 'missing', 'rejected'],
      scannedFiles: scanned, secretOccurrences: 0, outcome: 'pass' }, null, 2));
    console.log(`Credential failure evidence: ${outputRoot}`);
  } finally {
    server.closeAllConnections(); await new Promise(resolve => server.close(resolve));
    fs.rmSync(directory, { recursive: true, force: true });
  }
});

test('guard preserves authenticated cookies across login, verification and logout', async () => {
  const seen = [];
  const server = http.createServer((request, response) => {
    request.resume();
    if (request.url === '/') {
      response.setHeader('Content-Type', 'text/html');
      response.end('<body>session fixture</body>'); return;
    }
    seen.push({ method: request.method, path: request.url, cookie: request.headers.cookie || '' });
    response.setHeader('Content-Type', 'application/json');
    if (request.url === '/api/auth/login') {
      response.setHeader('Set-Cookie', 'inspection_session=synthetic; HttpOnly; SameSite=Strict; Path=/');
      response.end('{"ok":true}'); return;
    }
    if (request.url === '/api/auth/logout') {
      response.setHeader('Set-Cookie', 'inspection_session=; Max-Age=0; HttpOnly; SameSite=Strict; Path=/');
      response.end('{"ok":true}'); return;
    }
    response.statusCode = request.headers.cookie === 'inspection_session=synthetic' ? 200 : 401;
    response.end('{}');
  });
  server.listen(0, '127.0.0.1'); await once(server, 'listening');
  let browser;
  try {
    browser = await chromium.launch();
    const context = await browser.newContext({ serviceWorkers: 'block' });
    const target = `http://127.0.0.1:${server.address().port}`;
    const blocked = new Set(); await installInspectionPolicy(context, target, blocked);
    const page = await context.newPage(); await page.goto(target);
    const statuses = await page.evaluate(async () => {
      const values = [];
      for (const [path, method] of [
        ['/api/auth/verify', 'GET'], ['/api/auth/login', 'POST'],
        ['/api/auth/verify', 'GET'], ['/api/auth/logout', 'POST'], ['/api/auth/verify', 'GET']
      ]) values.push((await fetch(path, { method })).status);
      return values;
    });
    assert.deepEqual(statuses, [401, 200, 200, 200, 401]);
    assert.equal(seen[2].cookie, 'inspection_session=synthetic');
    assert.equal(seen[3].cookie, 'inspection_session=synthetic');
    assert.equal(seen[4].cookie, '');
    assert.deepEqual(await context.cookies(), []);
    assert.equal(blocked.size, 0);
  } finally {
    if (browser) await browser.close();
    server.closeAllConnections(); await new Promise(resolve => server.close(resolve));
  }
});

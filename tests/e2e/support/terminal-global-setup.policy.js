const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');

const helper = require('./terminal-global-setup');

const ENV_KEYS = [
  'PVE_FREQ_RUN_IDRAC_TERMINAL_E2E',
  'PVE_FREQ_RUN_VM_CONTROL_E2E',
  'PVE_FREQ_ADMIN_USER',
  'PVE_FREQ_ADMIN_PASSWORD_FILE',
  'PVE_FREQ_OPERATOR_USER',
  'PVE_FREQ_OPERATOR_PASSWORD_FILE',
  'PVE_FREQ_TEST_VMID',
  'PVE_FREQ_TEST_CHANGED_VMID',
  'PVE_FREQ_TEST_VM_NAME',
  'PVE_FREQ_TEMPLATE_VMID',
  'PVE_FREQ_SANDBOX_SNAPSHOT_REF'
];

function withEnv(values, callback) {
  const previous = Object.fromEntries(ENV_KEYS.map(key => [key, process.env[key]]));
  for (const key of ENV_KEYS) delete process.env[key];
  Object.assign(process.env, values);
  try {
    return callback();
  } finally {
    for (const key of ENV_KEYS) {
      if (previous[key] === undefined) delete process.env[key];
      else process.env[key] = previous[key];
    }
  }
}

function fixtures() {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'pve-freq-terminal-policy-'));
  const oneNewline = path.join(directory, 'one-newline');
  const twoNewlines = path.join(directory, 'two-newlines');
  const invalidUtf8 = path.join(directory, 'invalid-utf8');
  fs.writeFileSync(oneNewline, 'fake-password\n');
  fs.writeFileSync(twoNewlines, 'fake-password\n\n');
  fs.writeFileSync(invalidUtf8, Buffer.from([0xff, 0xfe, 0xfd]));
  return { directory, oneNewline, twoNewlines, invalidUtf8 };
}

function response(status, body) {
  return {
    ok: status >= 200 && status < 300,
    status,
    async json() { return body; },
    async text() { return typeof body === 'string' ? body : JSON.stringify(body); }
  };
}

function fakePage(responses, calls) {
  return {
    async evaluate(callback, input) {
      const originalFetch = global.fetch;
      global.fetch = async (path, options = {}) => {
        calls.push({ path, options });
        assert.ok(responses.length > 0, `unexpected fetch for ${path}`);
        return responses.shift();
      };
      try {
        return await callback(input);
      } finally {
        global.fetch = originalFetch;
      }
    }
  };
}

test('live inputs require explicit flag and path-based admin/operator credentials', () => {
  const files = fixtures();
  try {
    withEnv({}, () => {
      assert.throws(() => helper.liveInputs(), /PVE_FREQ_RUN_IDRAC_TERMINAL_E2E=1 is required/);
    });
    withEnv({ PVE_FREQ_RUN_IDRAC_TERMINAL_E2E: '1' }, () => {
      assert.throws(() => helper.liveInputs(), /PVE_FREQ_ADMIN_USER is required/);
    });
    withEnv({
      PVE_FREQ_RUN_IDRAC_TERMINAL_E2E: '1',
      PVE_FREQ_ADMIN_USER: 'fake-admin',
      PVE_FREQ_ADMIN_PASSWORD_FILE: files.oneNewline,
      PVE_FREQ_OPERATOR_USER: 'fake-operator',
      PVE_FREQ_OPERATOR_PASSWORD_FILE: files.oneNewline
    }, () => {
      const inputs = helper.liveInputs();
      assert.equal(inputs.admin.user, 'fake-admin');
      assert.equal(inputs.operator.user, 'fake-operator');
      assert.equal(inputs.admin.password, 'fake-password');
    });
  } finally {
    fs.rmSync(files.directory, { recursive: true, force: true });
  }
});

test('password reader removes exactly one newline and rejects non-UTF-8 input', () => {
  const files = fixtures();
  try {
    withEnv({
      PVE_FREQ_ADMIN_USER: 'fake-admin',
      PVE_FREQ_ADMIN_PASSWORD_FILE: files.twoNewlines
    }, () => {
      assert.equal(helper.adminCredentials().password, 'fake-password\n');
    });
    withEnv({
      PVE_FREQ_ADMIN_USER: 'fake-admin',
      PVE_FREQ_ADMIN_PASSWORD_FILE: files.invalidUtf8
    }, () => {
      assert.throws(() => helper.adminCredentials(), /readable UTF-8 regular file/);
    });
    withEnv({
      PVE_FREQ_ADMIN_USER: 'fake-admin',
      PVE_FREQ_ADMIN_PASSWORD_FILE: files.directory
    }, () => {
      assert.throws(() => helper.adminCredentials(), /readable regular file/);
    });
  } finally {
    fs.rmSync(files.directory, { recursive: true, force: true });
  }
});

test('sandbox API requires verified CSRF and injects it into every unsafe request', async () => {
  const calls = [];
  const result = await helper.sandboxApi(
    fakePage([
      response(200, { valid: true, csrf_token: 'policy-csrf' }),
      response(200, { ok: true })
    ], calls),
    '/api/vm/clone?vmid=9000&newid=6000',
    { method: 'POST', headers: { 'x-freq-csrf': 'caller-value', Accept: 'application/json' } }
  );
  assert.deepEqual(result, { status: 200, body: { ok: true } });
  assert.deepEqual(calls[0], {
    path: '/api/auth/verify',
    options: { credentials: 'same-origin' }
  });
  assert.equal(calls[1].path, '/api/vm/clone?vmid=9000&newid=6000');
  assert.equal(calls[1].options.credentials, 'same-origin');
  assert.equal(calls[1].options.headers['X-Freq-CSRF'], 'policy-csrf');
  assert.equal(calls[1].options.headers['x-freq-csrf'], undefined);
  assert.equal(calls[1].options.headers.Accept, 'application/json');

  const missingTokenCalls = [];
  await assert.rejects(
    helper.sandboxApi(
      fakePage([response(200, { valid: true })], missingTokenCalls),
      '/api/vm/destroy?vmid=6000',
      { method: 'DELETE' }
    ),
    /requires a verified CSRF token/
  );
  assert.equal(missingTokenCalls.length, 1);
  assert.equal(missingTokenCalls[0].path, '/api/auth/verify');
});

test('sandbox safety identity is explicit and rejects ceremonial snapshot labels', () => {
  const files = fixtures();
  const valid = {
    PVE_FREQ_RUN_VM_CONTROL_E2E: '1',
    PVE_FREQ_ADMIN_USER: 'fake-admin',
    PVE_FREQ_ADMIN_PASSWORD_FILE: files.oneNewline,
    PVE_FREQ_TEST_VMID: '6000',
    PVE_FREQ_TEST_CHANGED_VMID: '6001',
    PVE_FREQ_TEST_VM_NAME: 'e2e-freq-controls-policy-proof',
    PVE_FREQ_TEMPLATE_VMID: '9000'
  };
  try {
    withEnv(valid, () => {
      const inputs = helper.sandboxInputs();
      assert.deepEqual(
        [inputs.targetVmid, inputs.changedVmid, inputs.templateVmid],
        [6000, 6001, 9000]
      );
    });
    withEnv({ ...valid, PVE_FREQ_TEST_CHANGED_VMID: '6000' }, () => {
      assert.throws(() => helper.sandboxInputs(), /must be distinct/);
    });
    withEnv({ ...valid, PVE_FREQ_TEST_VM_NAME: 'unsafe-name' }, () => {
      assert.throws(() => helper.sandboxInputs(), /e2e-freq-controls- prefix/);
    });
    withEnv({ ...valid, PVE_FREQ_TEST_VM_NAME: 'E2E-freq-controls-uppercase' }, () => {
      assert.throws(() => helper.sandboxInputs(), /e2e-freq-controls- prefix/);
    });
    withEnv({ ...valid, PVE_FREQ_TEMPLATE_VMID: '8999' }, () => {
      assert.throws(() => helper.sandboxInputs(), /9000 through 9009/);
    });
    withEnv({ ...valid, PVE_FREQ_SANDBOX_SNAPSHOT_REF: 'ceremonial-label' }, () => {
      assert.throws(() => helper.sandboxInputs(), /not an accepted safety input/);
    });
  } finally {
    fs.rmSync(files.directory, { recursive: true, force: true });
  }
});

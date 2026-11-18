const fs = require('node:fs');
const { TextDecoder } = require('node:util');

function requiredValue(name) {
  const value = process.env[name];
  if (typeof value !== 'string' || value === '') {
    throw new Error(`${name} is required`);
  }
  return value;
}

function readPasswordFile(name) {
  const file = requiredValue(name);
  let stat;
  try {
    stat = fs.statSync(file);
  } catch {
    throw new Error(`${name} must name a readable regular file`);
  }
  if (!stat.isFile()) {
    throw new Error(`${name} must name a readable regular file`);
  }

  let password;
  try {
    fs.accessSync(file, fs.constants.R_OK);
    password = new TextDecoder('utf-8', { fatal: true })
      .decode(fs.readFileSync(file))
      .replace(/(?:\r\n|\n)$/, '');
  } catch {
    throw new Error(`${name} must name a readable UTF-8 regular file`);
  }
  if (password === '') {
    throw new Error(`${name} must not be empty`);
  }
  return password;
}

function adminCredentials() {
  return {
    user: requiredValue('PVE_FREQ_ADMIN_USER'),
    password: readPasswordFile('PVE_FREQ_ADMIN_PASSWORD_FILE')
  };
}

function operatorCredentials() {
  return {
    user: requiredValue('PVE_FREQ_OPERATOR_USER'),
    password: readPasswordFile('PVE_FREQ_OPERATOR_PASSWORD_FILE')
  };
}

function integerInRange(name, minimum, maximum) {
  const raw = requiredValue(name);
  if (!/^\d+$/.test(raw)) {
    throw new Error(`${name} must be an integer from ${minimum} through ${maximum}`);
  }
  const value = Number(raw);
  if (!Number.isSafeInteger(value) || value < minimum || value > maximum) {
    throw new Error(`${name} must be an integer from ${minimum} through ${maximum}`);
  }
  return value;
}

function liveInputs() {
  if (process.env.PVE_FREQ_RUN_IDRAC_TERMINAL_E2E !== '1') {
    throw new Error('PVE_FREQ_RUN_IDRAC_TERMINAL_E2E=1 is required');
  }
  return {
    admin: adminCredentials(),
    operator: operatorCredentials()
  };
}

function sandboxInputs() {
  if (process.env.PVE_FREQ_RUN_VM_CONTROL_E2E !== '1') {
    throw new Error('PVE_FREQ_RUN_VM_CONTROL_E2E=1 is required');
  }
  if (process.env.PVE_FREQ_SANDBOX_SNAPSHOT_REF) {
    throw new Error('PVE_FREQ_SANDBOX_SNAPSHOT_REF is not an accepted safety input');
  }

  const targetVmid = integerInRange('PVE_FREQ_TEST_VMID', 6000, 6099);
  const changedVmid = integerInRange('PVE_FREQ_TEST_CHANGED_VMID', 6000, 6099);
  if (targetVmid === changedVmid) {
    throw new Error('PVE_FREQ_TEST_VMID and PVE_FREQ_TEST_CHANGED_VMID must be distinct');
  }
  const templateVmid = integerInRange('PVE_FREQ_TEMPLATE_VMID', 9000, 9009);
  const testName = requiredValue('PVE_FREQ_TEST_VM_NAME');
  if (!/^e2e-freq-controls-[a-z0-9][a-z0-9-]*$/.test(testName)) {
    throw new Error('PVE_FREQ_TEST_VM_NAME must use the e2e-freq-controls- prefix');
  }

  return {
    admin: adminCredentials(),
    targetVmid,
    changedVmid,
    templateVmid,
    testName
  };
}

async function sandboxApi(page, path, options = {}) {
  return await page.evaluate(async ({ path, options }) => {
    const requestOptions = { ...options, credentials: 'same-origin' };
    const method = String(requestOptions.method || 'GET').toUpperCase();
    if (!['GET', 'HEAD', 'OPTIONS', 'TRACE'].includes(method)) {
      const verify = await fetch('/api/auth/verify', { credentials: 'same-origin' });
      if (!verify.ok) {
        throw new Error('sandbox request could not verify its authenticated session');
      }
      const session = await verify.json().catch(() => ({}));
      if (typeof session.csrf_token !== 'string' || session.csrf_token === '') {
        throw new Error('sandbox request requires a verified CSRF token');
      }
      const headers = Object.fromEntries(
        Object.entries(requestOptions.headers || {})
          .filter(([name]) => name.toLowerCase() !== 'x-freq-csrf')
      );
      headers['X-Freq-CSRF'] = session.csrf_token;
      requestOptions.headers = headers;
    }
    const response = await fetch(path, requestOptions);
    let body = null;
    try {
      body = await response.json();
    } catch {
      body = await response.text();
    }
    return { status: response.status, body };
  }, { path, options });
}

async function terminalGlobalSetup(config) {
  const mode = config.metadata && config.metadata.terminalMode;
  if (mode === 'live') {
    liveInputs();
    return;
  }
  if (mode === 'sandbox') {
    sandboxInputs();
    return;
  }
  throw new Error('terminal E2E config must declare metadata.terminalMode');
}

module.exports = terminalGlobalSetup;
module.exports.adminCredentials = adminCredentials;
module.exports.operatorCredentials = operatorCredentials;
module.exports.liveInputs = liveInputs;
module.exports.sandboxInputs = sandboxInputs;
module.exports.sandboxApi = sandboxApi;
